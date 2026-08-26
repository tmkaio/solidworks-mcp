"""
Custom properties and material tools for SolidWorks MCP.

Tools in this module:
    get_custom_properties   — Read all custom/configuration properties
    get_custom_property     — Read a single property value
    set_custom_property     — Write or create a property
    delete_custom_property  — Remove a property
    set_material            — Assign a material from the SolidWorks library
    get_material_databases  — List available material libraries

SolidWorks custom properties are stored on IModelDoc2 via
ICustomPropertyManager (doc.Extension.CustomPropertyManager).

Configuration-specific properties shadow document-level ones.
Pass config_name="" (empty string) for document-level properties,
or pass a configuration name for config-specific values.

Property type constants (swCustomInfoType_e):
    0 = swCustomInfoUnknown
    1 = swCustomInfoText
    2 = swCustomInfoDate
    3 = swCustomInfoNumber
    4 = swCustomInfoYesOrNo
"""

import logging
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import _com_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)

# swCustomInfoType_e
_PROP_TYPE_TEXT = 1
_PROP_TYPE_DATE = 2
_PROP_TYPE_NUMBER = 3
_PROP_TYPE_YES_NO = 4


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all property tools with the FastMCP instance."""

    @mcp.tool()
    def get_custom_properties(config_name: str = "") -> dict:
        """
        Read all custom properties from the active document.

        SolidWorks parts/assemblies/drawings can carry metadata as custom
        properties — part number, revision, material grade, heat treatment,
        surface finish, customer, drawing number, etc.

        Use this tool when the user asks about:
        - Part number, revision, or drawing number stored on the file
        - Material specification beyond the SolidWorks material database
        - Any custom metadata on the document

        Args:
            config_name: Configuration name for config-specific properties.
                         Pass "" (empty string, default) for document-level
                         properties that apply to all configurations.

        Returns a dict with:
            properties (dict[str, dict]): property name → {value, type, resolved_value}
            config (str): which config was queried ("" = document level)
            count (int)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            mgr = doc.Extension.CustomPropertyManager(config_name)

            props = {}
            names = mgr.GetNames()
            if names:
                for name in names:
                    try:
                        # GetProperty3: returns (retval, value_str, resolved_value, was_linked)
                        ret = mgr.GetProperty3(name, False)
                        val = ret[0] if ret else ""
                        resolved = ret[1] if ret and len(ret) > 1 else val
                        prop_type = mgr.GetType2(name)
                        props[name] = {
                            "value": str(val),
                            "resolved_value": str(resolved),
                            "type": _prop_type_name(prop_type),
                        }
                    except Exception as exc:
                        logger.debug("Could not read property '%s': %s", name, exc)
                        props[name] = {"value": "(unreadable)", "type": "unknown"}

            logger.info("get_custom_properties: %d properties on '%s'", len(props), _com_call(doc, "GetTitle"))
            return {"properties": props, "config": config_name, "count": len(props)}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_custom_properties error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_custom_property(name: str, config_name: str = "") -> dict:
        """
        Read a single custom property value from the active document.

        Use this tool when you know exactly which property you need
        (faster than get_custom_properties for a single lookup).

        Args:
            name: Property name (e.g. "PartNumber", "Revision", "Material")
            config_name: Configuration name, or "" for document-level.

        Returns a dict with:
            name (str), value (str), resolved_value (str), type (str), found (bool)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            mgr = doc.Extension.CustomPropertyManager(config_name)
            ret = mgr.GetProperty3(name, False)
            if ret is None:
                return {"name": name, "found": False, "value": None}
            val = str(ret[0]) if ret else ""
            resolved = str(ret[1]) if ret and len(ret) > 1 else val
            prop_type = mgr.GetType2(name)
            return {
                "name": name,
                "found": True,
                "value": val,
                "resolved_value": resolved,
                "type": _prop_type_name(prop_type),
            }
        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_custom_property error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def set_custom_property(
        name: str,
        value: str,
        config_name: str = "",
        prop_type: str = "text",
    ) -> dict:
        """
        Set (create or update) a custom property on the active document.

        Use this tool when the user wants to:
        - Tag a part with its part number or revision
        - Record material specification, heat treatment, or surface finish
        - Add any metadata that should travel with the file

        Args:
            name: Property name (e.g. "PartNumber", "Revision", "Finish")
            value: Property value string
            config_name: Configuration name, or "" for document-level.
            prop_type: One of "text" (default), "number", "date", "yes_no"

        Returns a dict with:
            success (bool), name (str), value (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        type_codes = {"text": _PROP_TYPE_TEXT, "number": _PROP_TYPE_NUMBER,
                      "date": _PROP_TYPE_DATE, "yes_no": _PROP_TYPE_YES_NO}
        type_code = type_codes.get(prop_type.lower(), _PROP_TYPE_TEXT)

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            mgr = doc.Extension.CustomPropertyManager(config_name)
            # Add2: returns 0=success, other=error
            ret = mgr.Add3(name, type_code, value, 0)  # 0 = swCustomPropertyReplaceValue
            if ret not in (0, None):
                return {"success": False, "error": f"Add3 returned error code {ret}"}
            logger.info("set_custom_property: set '%s'='%s' on '%s'", name, value, _com_call(doc, "GetTitle"))
            return {"success": True, "name": name, "value": value}
        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("set_custom_property error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def delete_custom_property(name: str, config_name: str = "") -> dict:
        """
        Delete a custom property from the active document.

        Args:
            name: Property name to delete.
            config_name: Configuration name, or "" for document-level.

        Returns a dict with:
            success (bool), deleted (str): property that was removed
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            mgr = doc.Extension.CustomPropertyManager(config_name)
            ret = mgr.Delete2(name)
            if ret not in (0, None, True):
                return {"success": False, "error": f"Delete2 returned {ret}"}
            logger.info("delete_custom_property: deleted '%s' from '%s'", name, _com_call(doc, "GetTitle"))
            return {"success": True, "deleted": name}
        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("delete_custom_property error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def set_material(material_name: str, library_name: str = "") -> dict:
        """
        Assign a material to the active part from the SolidWorks material database.

        This is required for mass properties (get_part_info returns mass/density
        only when a material is assigned).

        Common material names:
        - "AISI 1020 Steel"
        - "AISI 304 Stainless Steel (SS)"
        - "Aluminum 1060 Alloy"
        - "Galvanized Steel"
        - "Plain Carbon Steel"

        Use this tool when:
        - The user specifies a material for mass calculations
        - get_part_info returned null for mass (no material assigned)
        - You need to verify weight before quoting tooling cost

        Args:
            material_name: Exact SolidWorks material name (case-sensitive).
            library_name: Material database filename without extension
                          (e.g. "solidworks materials", "custom materials").
                          Leave empty to search all installed databases.

        Returns a dict with:
            success (bool), material (str), database (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)  # Part only
            doc.SetMaterialPropertyName2("", library_name, material_name)
            # Verify assignment
            assigned = doc.GetMaterialPropertyName2("", "")
            if not assigned:
                return {
                    "success": False,
                    "error": (
                        f"Material '{material_name}' was not found in library '{library_name}'. "
                        "Check the exact name — it is case-sensitive. "
                        "Use get_material_databases() to browse available libraries."
                    ),
                }
            _com_call(doc, "EditRebuild3")
            logger.info("set_material: assigned '%s' to '%s'", material_name, _com_call(doc, "GetTitle"))
            return {"success": True, "material": assigned, "database": library_name or "default"}
        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("set_material error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_material_databases() -> dict:
        """
        List available SolidWorks material database files.

        Use this tool when set_material fails and you need to discover
        the correct library name, or when the user asks what materials
        are available.

        Returns a dict with:
            databases (list[str]): available .sldmat database names
        """
        from solidworks_mcp.exceptions import SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            # SolidWorks stores material databases in the lang directory
            import glob
            import os

            sw_dir = ""
            try:
                sw_dir = bridge.app.GetExecutablePath()
                sw_dir = os.path.dirname(sw_dir)
            except Exception:
                pass

            databases = []
            search_dirs = [
                os.path.join(sw_dir, "lang", "english"),
                os.path.join(sw_dir, "lang"),
                r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english",
                r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang",
            ]
            for d in search_dirs:
                if os.path.isdir(d):
                    for f in glob.glob(os.path.join(d, "*.sldmat")):
                        name = os.path.splitext(os.path.basename(f))[0]
                        if name not in databases:
                            databases.append(name)

            return {"databases": databases or ["solidworks materials"]}
        except (SolidWorksConnectionError,) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_material_databases error")
            return {"error": f"Unexpected error: {exc}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prop_type_name(code) -> str:
    return {1: "text", 2: "date", 3: "number", 4: "yes_no"}.get(code, "unknown")
