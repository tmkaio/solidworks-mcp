"""
Assembly analysis tools for SolidWorks MCP.

Tools in this module:
    get_assembly_components   — List all top-level components with suppression state
    get_component_count       — Quick count of components (recursive or top-level)
    get_assembly_bom          — Bill of materials — quantity, part number, description
    list_assembly_mates       — List mates that constrain the assembly
    get_component_info        — Mass, path, configuration for a single component
    get_assembly_mass         — Total mass and CoM for the whole assembly

IAssemblyDoc is accessed as the same COM object as IModelDoc2 for assemblies.
Top-level components: doc.GetComponents(False) — False = top-level only.
All components (recursive): doc.GetComponents(True).

IComponent2 interface key methods:
    GetTitle(), GetPathName(), ReferencedConfiguration,
    IsSuppressed(), IsLightweight(), GetBodies2(),
    GetMassProperties()
"""

import logging
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import _com_call, feature_is_suppressed

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)

M_TO_MM = 1_000.0
KG_TO_G = 1_000.0


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all assembly tools with the FastMCP instance."""

    @mcp.tool()
    def get_assembly_components(recursive: bool = False) -> dict:
        """
        List all components in the active assembly.

        Args:
            recursive: If True, list all components at every level of nesting.
                       If False (default), only top-level components.

        Returns a dict with:
            components (list[dict]): each has name, path, configuration,
                                     is_suppressed, is_lightweight, is_virtual
            count (int), level (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=2)  # Assembly only

            comps = doc.GetComponents(recursive) or []
            result = []
            for comp in comps:
                try:
                    result.append({
                        "name": comp.Name2,
                        "path": _com_call(comp, "GetPathName"),
                        "configuration": comp.ReferencedConfiguration,
                        "is_suppressed": bool(comp.IsSuppressed()),
                        "is_lightweight": bool(comp.IsLightweight()),
                        "is_virtual": bool(comp.IsVirtual),
                    })
                except Exception as exc:
                    logger.debug("Component read error: %s", exc)
                    result.append({"name": "(unreadable)", "error": str(exc)})

            logger.info("get_assembly_components: %d components (recursive=%s)", len(result), recursive)
            return {
                "components": result,
                "count": len(result),
                "level": "all" if recursive else "top-level",
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_assembly_components error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_component_count(recursive: bool = True) -> dict:
        """
        Get the total count of components in the active assembly.

        Args:
            recursive: Count all nested components (default True).

        Returns a dict with:
            count (int), unique_parts (int), sub_assemblies (int)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=2)

            comps = doc.GetComponents(recursive) or []
            parts = 0
            sub_assemblies = 0

            for comp in comps:
                try:
                    path = _com_call(comp, "GetPathName") or ""
                    if path.lower().endswith(".sldasm"):
                        sub_assemblies += 1
                    else:
                        parts += 1
                except Exception:
                    parts += 1

            # Unique part paths
            paths = set()
            for comp in comps:
                try:
                    p = _com_call(comp, "GetPathName")
                    if p:
                        paths.add(p.lower())
                except Exception:
                    pass

            return {
                "count": len(comps),
                "unique_parts": len(paths),
                "sub_assemblies": sub_assemblies,
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_component_count error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_assembly_bom(recursive: bool = False) -> dict:
        """
        Generate a Bill of Materials (BOM) for the active assembly.

        Reads part number, description, and quantity from each component.
        Part number and description are read from the component's custom
        properties ("PartNumber" and "Description" fields).

        Args:
            recursive: Include sub-assembly components in the BOM.

        Returns a dict with:
            bom (list[dict]): each has item_no, part_number, description,
                              quantity, file_name, configuration
            count (int)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=2)

            comps = doc.GetComponents(recursive) or []

            # Group by path to aggregate quantities
            groups: dict = {}
            for comp in comps:
                try:
                    if comp.IsSuppressed():
                        continue
                    path = _com_call(comp, "GetPathName") or comp.Name2
                    cfg = comp.ReferencedConfiguration or ""
                    key = (path.lower(), cfg.lower())

                    if key not in groups:
                        # Read custom properties from comp model
                        part_number = _read_comp_property(comp, "PartNumber") or ""
                        description = _read_comp_property(comp, "Description") or ""
                        if not part_number:
                            part_number = _read_comp_property(comp, "Part Number") or ""
                        groups[key] = {
                            "part_number": part_number,
                            "description": description,
                            "file_name": _basename(path),
                            "configuration": cfg,
                            "quantity": 0,
                        }
                    groups[key]["quantity"] += 1
                except Exception as exc:
                    logger.debug("BOM component error: %s", exc)

            bom = []
            for i, (key, data) in enumerate(sorted(groups.items(), key=lambda x: x[1]["file_name"]), 1):
                bom.append({"item_no": i, **data})

            logger.info("get_assembly_bom: %d unique items", len(bom))
            return {"bom": bom, "count": len(bom)}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_assembly_bom error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def list_assembly_mates() -> dict:
        """
        List all mates (constraints) in the active assembly.

        Mates define geometric relationships between components
        (coincident, parallel, concentric, distance, angle, etc.).
        Use to understand how components are constrained to each other.

        Returns a dict with:
            mates (list[dict]): each has name, type, is_suppressed, entities
            count (int)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=2)

            from solidworks_mcp.solidworks_bridge import _com_call as _cc
            mates_data = []
            feat = _cc(doc, "FirstFeature")
            while feat:
                try:
                    ftype = _cc(feat, "GetTypeName2")
                    # Mate features have type names like "MateCoincident",
                    # "MateConcentric", "MateParallel", etc.
                    if ftype.startswith("Mate"):
                        mate_def = _cc(feat, "GetDefinition")
                        entities = []
                        if mate_def:
                            try:
                                n = mate_def.EntitiesToMate.Count
                                entities = [f"entity_{i}" for i in range(n)]
                            except Exception:
                                pass

                        mates_data.append({
                            "name": feat.Name,
                            "type": ftype.replace("Mate", "", 1),
                            "is_suppressed": feature_is_suppressed(feat),
                            "entity_count": len(entities),
                        })
                except Exception as exc:
                    logger.debug("Mate read error: %s", exc)

                feat = _cc(feat, "GetNextFeature")

            logger.info("list_assembly_mates: %d mates", len(mates_data))
            return {"mates": mates_data, "count": len(mates_data)}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("list_assembly_mates error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_component_info(component_name: str) -> dict:
        """
        Get detailed information about a specific component in the active assembly.

        Args:
            component_name: Component name as returned by get_assembly_components
                            (e.g. "Bracket-1").

        Returns a dict with:
            name (str), path (str), configuration (str),
            mass_g (float), volume_mm3 (float),
            is_suppressed (bool), is_lightweight (bool),
            bounding_box_mm (dict)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=2)

            comps = doc.GetComponents(True) or []
            target = None
            for comp in comps:
                try:
                    if comp.Name2 == component_name:
                        target = comp
                        break
                except Exception:
                    pass

            if target is None:
                return {
                    "error": f"Component '{component_name}' not found. "
                             "Use get_assembly_components to list available names."
                }

            result: dict = {
                "name": target.Name2,
                "path": _com_call(target, "GetPathName"),
                "configuration": target.ReferencedConfiguration,
                "is_suppressed": bool(target.IsSuppressed()),
                "is_lightweight": bool(target.IsLightweight()),
            }

            # Mass properties
            try:
                mass_props = target.GetMassProperties(1)  # 1 = use assigned material
                if mass_props:
                    result["mass_g"] = round(mass_props[5] * KG_TO_G, 4)
                    result["volume_mm3"] = round(mass_props[4] * (M_TO_MM ** 3), 4)
            except Exception as exc:
                logger.debug("Mass properties error for '%s': %s", component_name, exc)

            # Bounding box via model doc
            try:
                comp_doc = _com_call(target, "GetModelDoc2")
                if comp_doc:
                    bb = comp_doc.GetPartBox(True)
                    if bb and len(bb) >= 6:
                        result["bounding_box_mm"] = {
                            "x": round((bb[3] - bb[0]) * M_TO_MM, 4),
                            "y": round((bb[4] - bb[1]) * M_TO_MM, 4),
                            "z": round((bb[5] - bb[2]) * M_TO_MM, 4),
                        }
            except Exception as exc:
                logger.debug("Bounding box error for '%s': %s", component_name, exc)

            return result

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_component_info error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_assembly_mass() -> dict:
        """
        Get total mass and centre of mass for the active assembly.

        Sums all non-suppressed components.  Each component must have a
        material assigned for its contribution to be included.

        Returns a dict with:
            total_mass_g (float),
            centre_of_mass_mm (dict x/y/z),
            volume_mm3 (float)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=2)

            # Assembly-level mass properties
            mass_props = bridge.get_mass_properties(doc)
            return mass_props

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_assembly_mass error")
            return {"error": f"Unexpected error: {exc}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_comp_property(comp, prop_name: str) -> str:
    """Read a custom property from a component's referenced model doc."""
    try:
        model_doc = _com_call(comp, "GetModelDoc2")
        if model_doc is None:
            return ""
        mgr = model_doc.Extension.CustomPropertyManager("")
        ret = mgr.GetProperty3(prop_name, False)
        return str(ret[0]) if ret and ret[0] else ""
    except Exception:
        return ""


def _basename(path: str) -> str:
    return path.split("\\")[-1].split("/")[-1] if path else ""
