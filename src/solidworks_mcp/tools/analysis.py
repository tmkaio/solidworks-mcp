"""
Geometric analysis tools for SolidWorks MCP.

Tools in this module:
    get_part_info           — Mass, volume, material, metadata
    get_bounding_box        — Axis-aligned bounding box
    count_features_by_type  — Feature type histogram
    analyze_holes           — Identify and classify all holes
    analyze_bends           — Identify and classify all sheet metal bends
    get_geometry_stats      — Full geometry statistics summary
    generate_part_report    — Comprehensive analysis report (JSON + Markdown)
    analyze_step_standalone — Analyze a STEP file WITHOUT SolidWorks (uses CadQuery)

Note on analyze_step_standalone:
    CadQuery/OCC reads STEP files in their authored units. A file authored
    in millimetres will have millimetre values; one authored in metres will
    have metre values. The function assumes the file was authored in mm
    (the norm for mechanical parts).
"""

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import _com_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all analysis tools with the FastMCP instance."""

    @mcp.tool()
    def get_part_info() -> dict:
        """
        Return general information about the active part in SolidWorks.

        Use this tool when the user asks about:
        - Mass, volume, density, or surface area of the part
        - What material is assigned
        - Whether the part is a sheet metal part
        - Centre of mass coordinates

        Requires: SolidWorks connected + a Part document open.
        Note: mass properties require a material to be assigned to the part.

        Returns a dict with:
            name, file_path, configuration, material, mass_g, volume_mm3,
            surface_area_mm2, density_g_cm3, center_of_mass_mm, is_sheet_metal, units
        """
        from solidworks_mcp.exceptions import (
            AnalysisError,
            DocumentNotOpenError,
            SolidWorksConnectionError,
        )

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)

            name = _com_call(doc, "GetTitle")
            file_path = _com_call(doc, "GetPathName")
            config = doc.ConfigurationManager.ActiveConfiguration.Name

            material = None
            try:
                material = str(doc.GetMaterialPropertyName2("", "")) or None
            except Exception:
                pass

            mass_props = bridge.get_mass_properties(doc)
            is_sm = bridge.find_sheet_metal_feature(doc) is not None
            units = _get_doc_units(doc)

            density = 0.0
            vol = mass_props["volume_mm3"]
            if vol > 0:
                density = round(mass_props["mass_g"] / (vol / 1000.0), 4)

            logger.info("get_part_info: '%s' mass=%.1fg", name, mass_props["mass_g"])
            return {
                "name": name,
                "file_path": file_path,
                "configuration": config,
                "material": material,
                "mass_g": round(mass_props["mass_g"], 4),
                "volume_mm3": round(mass_props["volume_mm3"], 2),
                "surface_area_mm2": round(mass_props["surface_area_mm2"], 2),
                "density_g_cm3": density,
                "center_of_mass_mm": [round(v, 4) for v in mass_props["center_of_mass_mm"]],
                "is_sheet_metal": is_sm,
                "units": units,
            }

        except (SolidWorksConnectionError, DocumentNotOpenError, AnalysisError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_part_info unexpected error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_bounding_box() -> dict:
        """
        Return the axis-aligned bounding box of the active part.

        Use this tool when the user asks about:
        - Overall dimensions (length × width × height)
        - Whether the part fits within a given envelope
        - Rough blank size estimation

        Returns a dict with:
            min_mm, max_mm, dimensions_mm ([dx, dy, dz]), diagonal_mm
        """
        from solidworks_mcp.exceptions import (
            AnalysisError,
            DocumentNotOpenError,
            SolidWorksConnectionError,
        )

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)
            return bridge.get_bounding_box(doc)
        except (SolidWorksConnectionError, DocumentNotOpenError, AnalysisError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_bounding_box unexpected error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def count_features_by_type() -> dict:
        """
        Count features in the active part grouped by their type name.

        Use this tool when the user asks about:
        - How complex the part is
        - How many holes, bends, fillets, chamfers, etc. exist
        - Whether the part has sheet metal features

        Returns a dict with:
            total_features (int), by_type (dict[str, int])
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)
            counts: dict[str, int] = {}
            for feat in bridge.iter_features(doc):
                try:
                    t = _com_call(feat, "GetTypeName2")
                    counts[t] = counts.get(t, 0) + 1
                except Exception:
                    pass
            return {
                "total_features": sum(counts.values()),
                "by_type": dict(sorted(counts.items(), key=lambda x: -x[1])),
            }
        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("count_features_by_type unexpected error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def analyze_holes() -> dict:
        """
        Identify and classify all circular holes in the active part.

        Use this tool when the user asks about:
        - How many holes the part has
        - What diameters of holes are present (for tooling selection)
        - Distribution of hole sizes (important for progressive die design)

        Returns a dict with:
            total_holes (int),
            holes (list of dicts with id, diameter_mm, depth_mm, type),
            by_diameter (dict: diameter_mm_str → count)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError
        from solidworks_mcp.solidworks_bridge import M_TO_MM

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)
            holes = _collect_holes(doc, bridge, M_TO_MM)
            by_diameter: dict[str, int] = {}
            for h in holes:
                k = str(round(h["diameter_mm"], 2))
                by_diameter[k] = by_diameter.get(k, 0) + 1
            logger.info("analyze_holes: found %d holes", len(holes))
            return {"total_holes": len(holes), "holes": holes, "by_diameter": by_diameter}
        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("analyze_holes unexpected error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def analyze_bends() -> dict:
        """
        Identify and analyse all sheet metal bends in the active part.

        Use this tool when the user asks about:
        - How many bends the part has
        - Bend angles and radii (for press brake tooling selection)
        - Bend lengths (affects blank development)
        - K-factor used in bend allowance calculations

        Requires: the active part must be a sheet metal part.
        If not sheet metal, use convert_to_sheet_metal() first.

        Returns a dict with:
            total_bends (int),
            bends (list of dicts with id, angle_deg, radius_mm, length_mm, k_factor)
        """
        from solidworks_mcp.exceptions import (
            DocumentNotOpenError,
            SheetMetalError,
            SolidWorksConnectionError,
        )
        from solidworks_mcp.solidworks_bridge import M_TO_MM

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)
            sm_feat = bridge.find_sheet_metal_feature(doc)
            if sm_feat is None:
                raise SheetMetalError(
                    "The active part is not a sheet metal part. "
                    "Use convert_to_sheet_metal() to convert it first."
                )
            bends = _collect_bends(doc, bridge, M_TO_MM)
            logger.info("analyze_bends: found %d bends", len(bends))
            return {"total_bends": len(bends), "bends": bends}
        except (SolidWorksConnectionError, DocumentNotOpenError, SheetMetalError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("analyze_bends unexpected error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_geometry_stats() -> dict:
        """
        Return a comprehensive geometry statistics summary of the active part.

        This is the "quick scan" tool — call it first to get an overview before
        diving into specific analyses. Combines bounding box, mass properties,
        feature counts, and an estimated complexity rating.

        Use this tool when the user asks for:
        - A general overview of the part
        - A quick complexity assessment
        - Manufacturing recommendations

        Returns a dict with bounding_box, mass_properties, feature_summary,
        is_sheet_metal, complexity_estimate, and manufacturing_notes.
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)

            bbox = {}
            mass = {}
            try:
                bbox = bridge.get_bounding_box(doc)
            except Exception as exc:
                bbox = {"error": str(exc)}
            try:
                mass = bridge.get_mass_properties(doc)
            except Exception as exc:
                mass = {"error": str(exc)}

            feat_counts: dict[str, int] = {}
            for feat in bridge.iter_features(doc):
                try:
                    t = _com_call(feat, "GetTypeName2")
                    feat_counts[t] = feat_counts.get(t, 0) + 1
                except Exception:
                    pass

            is_sm = bridge.find_sheet_metal_feature(doc) is not None
            complexity, notes = _estimate_complexity(feat_counts, bbox, is_sm)

            return {
                "bounding_box": bbox,
                "mass_properties": {
                    "mass_g": round(mass.get("mass_g", 0), 4),
                    "volume_mm3": round(mass.get("volume_mm3", 0), 2),
                    "surface_area_mm2": round(mass.get("surface_area_mm2", 0), 2),
                } if "error" not in mass else {"error": mass["error"]},
                "feature_summary": {
                    "total": sum(feat_counts.values()),
                    "by_type": dict(sorted(feat_counts.items(), key=lambda x: -x[1])[:20]),
                },
                "is_sheet_metal": is_sm,
                "complexity_estimate": complexity,
                "manufacturing_notes": notes,
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_geometry_stats unexpected error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def generate_part_report(output_path: str | None = None) -> dict:
        """
        Generate a comprehensive technical analysis report for the active part.

        Consolidates all available analysis data into a single structured report.
        Optionally saves to a JSON and Markdown file.

        Use this tool when the user says things like:
        - "Analyse this part completely"
        - "Give me a full report on this bracket"
        - "What do I need to know about this part for tooling?"

        Args:
            output_path: Optional directory path. If provided, saves:
                         <output_path>/report.json  and  <output_path>/report.md

        Returns the full report dict.
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError
        from solidworks_mcp.solidworks_bridge import M_TO_MM

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)
            is_sm = bridge.find_sheet_metal_feature(doc) is not None

            report: dict = {
                "metadata": {
                    "name": _com_call(doc, "GetTitle"),
                    "file_path": _com_call(doc, "GetPathName"),
                    "is_sheet_metal": is_sm,
                },
                "dimensions": {},
                "mass_properties": {},
                "features": {},
                "holes": {},
                "bends": {},
                "sheet_metal_props": {},
                "complexity_estimate": "unknown",
                "manufacturing_recommendations": [],
            }

            try:
                report["dimensions"] = bridge.get_bounding_box(doc)
            except Exception as exc:
                report["dimensions"] = {"error": str(exc)}

            try:
                report["mass_properties"] = bridge.get_mass_properties(doc)
            except Exception as exc:
                report["mass_properties"] = {"error": str(exc)}

            feat_counts: dict[str, int] = {}
            for feat in bridge.iter_features(doc):
                try:
                    t = _com_call(feat, "GetTypeName2")
                    feat_counts[t] = feat_counts.get(t, 0) + 1
                except Exception:
                    pass
            report["features"] = {
                "total": sum(feat_counts.values()),
                "by_type": dict(sorted(feat_counts.items(), key=lambda x: -x[1])),
            }

            holes = _collect_holes(doc, bridge, M_TO_MM)
            by_diam: dict[str, int] = {}
            for h in holes:
                k = str(round(h["diameter_mm"], 2))
                by_diam[k] = by_diam.get(k, 0) + 1
            report["holes"] = {"total_holes": len(holes), "holes": holes, "by_diameter": by_diam}

            if is_sm:
                bends = _collect_bends(doc, bridge, M_TO_MM)
                report["bends"] = {"total_bends": len(bends), "bends": bends}
                report["sheet_metal_props"] = _get_sm_props(doc, bridge, M_TO_MM)

            complexity, notes = _estimate_complexity(feat_counts, report["dimensions"], is_sm)
            report["complexity_estimate"] = complexity
            report["manufacturing_recommendations"] = notes

            if output_path:
                out_dir = Path(os.path.abspath(output_path))
                out_dir.mkdir(parents=True, exist_ok=True)
                json_path = out_dir / "report.json"
                md_path = out_dir / "report.md"
                json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
                md_path.write_text(_render_markdown_report(report), encoding="utf-8")
                report["saved_to"] = {"json": str(json_path), "markdown": str(md_path)}
                logger.info("generate_part_report: saved to %s", out_dir)

            logger.info("generate_part_report: completed for '%s'", report["metadata"]["name"])
            return report

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("generate_part_report unexpected error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def analyze_step_standalone(file_path: str) -> dict:
        """
        Analyse a STEP file WITHOUT opening it in SolidWorks.

        Uses CadQuery/OCC for pure-Python STEP analysis. This is the fastest
        triage tool — no COM overhead, works even when SolidWorks is closed.

        Use this tool as a FIRST STEP before deciding whether to open the file
        in SolidWorks:
        - Quick sanity check on a file received from a customer
        - Estimate part complexity before committing to full SW analysis
        - Works in offline/test environments without SW license

        Requirements: CadQuery must be installed (see INSTALL.md).
        Install via: conda install -c cadquery cadquery

        Args:
            file_path: Absolute path to the STEP file (.step or .stp).

        Returns a dict with volume_mm3, surface_area_mm2, bounding_box,
        center_of_mass_mm, face_count, face_types, estimated_thickness_mm,
        is_likely_sheet_metal.
        """
        from solidworks_mcp.exceptions import CadQueryNotAvailableError

        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            return {"error": f"File not found: {abs_path}"}

        ext = Path(abs_path).suffix.lower()
        if ext not in (".step", ".stp"):
            return {"error": f"Expected a .step or .stp file, got: {ext}"}

        try:
            import cadquery as cq
        except ImportError:
            raise CadQueryNotAvailableError(
                "CadQuery is not installed. "
                "Install it with: conda install -c cadquery cadquery\n"
                "See docs/INSTALL.md for full instructions."
            )

        try:
            file_size_kb = os.path.getsize(abs_path) / 1024.0
            logger.info("analyze_step_standalone: loading '%s' (%.1f KB)", abs_path, file_size_kb)

            wp = cq.importers.importStep(abs_path)
            shape = wp.val()

            bb = shape.BoundingBox()
            x_min, y_min, z_min = bb.xmin, bb.ymin, bb.zmin
            x_max, y_max, z_max = bb.xmax, bb.ymax, bb.zmax
            dims = [
                round(x_max - x_min, 4),
                round(y_max - y_min, 4),
                round(z_max - z_min, 4),
            ]

            volume = shape.Volume()
            area = shape.Area()
            com = shape.Center()

            faces = shape.Faces()
            face_types: dict[str, int] = {}
            for face in faces:
                try:
                    geom_type = face.geomType()
                    face_types[geom_type] = face_types.get(geom_type, 0) + 1
                except Exception:
                    face_types["Unknown"] = face_types.get("Unknown", 0) + 1

            sorted_dims = sorted(dims)
            estimated_thickness = sorted_dims[0]
            is_likely_sm = (
                estimated_thickness > 0
                and sorted_dims[1] / estimated_thickness > 5
                and sorted_dims[2] / estimated_thickness > 5
            )

            result = {
                "file_path": abs_path,
                "file_size_kb": round(file_size_kb, 2),
                "volume_mm3": round(volume, 2),
                "surface_area_mm2": round(area, 2),
                "bounding_box": {
                    "xmin_mm": round(x_min, 4), "xmax_mm": round(x_max, 4),
                    "ymin_mm": round(y_min, 4), "ymax_mm": round(y_max, 4),
                    "zmin_mm": round(z_min, 4), "zmax_mm": round(z_max, 4),
                    "dimensions_mm": dims,
                },
                "center_of_mass_mm": {
                    "x": round(com.x, 4),
                    "y": round(com.y, 4),
                    "z": round(com.z, 4),
                },
                "face_count": len(faces),
                "face_types": dict(sorted(face_types.items(), key=lambda x: -x[1])),
                "estimated_thickness_mm": round(estimated_thickness, 4),
                "is_likely_sheet_metal": is_likely_sm,
                "note": (
                    "Values assume STEP authored in millimetres. "
                    "If dimensions appear 1000x off, the file was authored in metres."
                ),
            }

            logger.info(
                "analyze_step_standalone: vol=%.1f mm³ bbox=%s sheet_metal=%s",
                volume, dims, is_likely_sm,
            )
            return result

        except CadQueryNotAvailableError:
            raise
        except Exception as exc:
            logger.exception("analyze_step_standalone failed for '%s'", abs_path)
            return {"error": f"STEP analysis failed: {exc}"}

    @mcp.tool()
    def get_moments_of_inertia() -> dict:
        """
        Return mass moments of inertia and principal axes for the active part.

        Used for dynamic analysis, flywheel design, and rotational inertia
        calculations.  Values are relative to the centre of mass.

        Requires a material assignment (same as get_part_info mass).

        Returns a dict with:
            Lxx, Lyy, Lzz (float): principal moments (g·mm²),
            Lxy, Lxz, Lyz (float): products of inertia (g·mm²),
            principal_axes (dict): unit vectors of the principal axes,
            centre_of_mass_mm (dict x/y/z)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)

            # GetMassProperties2 returns a 40-element array (SI units)
            # Indices per SolidWorks API reference:
            #   0-2: CoM (x,y,z) m
            #   3-11: inertia tensor rows (kg·m²)
            #      [3,4,5] = Ixx,Ixy,Ixz row1
            #      [6,7,8] = Iyx,Iyy,Iyz row2
            #      [9,10,11] = Izx,Izy,Izz row3
            #  15: mass (kg), 16: volume (m³)
            # Use IMassProperty (Extension.CreateMassProperty) — clean
            # property-based access to mass, inertia tensor, and CoM.
            from solidworks_mcp.solidworks_bridge import _com_call as _cc
            mp = _cc(doc.Extension, "CreateMassProperty")
            if mp is None:
                return {
                    "error": (
                        "CreateMassProperty returned None. "
                        "Assign a material to the part first (set_material tool)."
                    )
                }

            KG_MM2 = 1e6  # kg·m² → g·mm²
            M_MM = 1000.0

            def _round(v, n=4):
                return round(v, n) if v is not None else None

            com = list(mp.CenterOfMass or [0.0, 0.0, 0.0])
            # MomentOfInertia returns 9-element SafeArray: row-major
            moi = list(mp.MomentOfInertia or [0.0] * 9)
            while len(moi) < 9:
                moi.append(0.0)
            ixx = moi[0] * KG_MM2
            ixy = moi[1] * KG_MM2
            ixz = moi[2] * KG_MM2
            iyy = moi[4] * KG_MM2
            iyz = moi[5] * KG_MM2
            izz = moi[8] * KG_MM2

            result = {
                "Ixx_g_mm2": _round(ixx),
                "Iyy_g_mm2": _round(iyy),
                "Izz_g_mm2": _round(izz),
                "Ixy_g_mm2": _round(ixy),
                "Ixz_g_mm2": _round(ixz),
                "Iyz_g_mm2": _round(iyz),
                "centre_of_mass_mm": {
                    "x": _round(com[0] * M_MM),
                    "y": _round(com[1] * M_MM),
                    "z": _round(com[2] * M_MM),
                },
                "mass_g": _round(float(mp.Mass or 0.0) * 1000),
            }

            logger.info("get_moments_of_inertia: Ixx=%.2f Iyy=%.2f Izz=%.2f g·mm²",
                        ixx, iyy, izz)
            return result

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_moments_of_inertia error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def analyze_faces() -> dict:
        """
        Classify and count all faces on the active part by geometry type.

        Provides a breakdown of planar, cylindrical, conical, spherical,
        toroidal, and B-spline faces.  Use to understand part complexity,
        assess formability, or detect undercut regions.

        Returns a dict with:
            face_counts (dict[str, int]): geometry type → count,
            total_faces (int),
            total_area_mm2 (float),
            planar_area_mm2 (float),
            cylindrical_area_mm2 (float),
            largest_face_mm2 (float)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        M2_TO_MM2 = 1_000_000.0

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)

            bodies = doc.GetBodies2(0, True)  # 0 = all solid bodies
            if not bodies:
                return {"error": "No solid bodies found in the active part"}

            face_counts: dict[str, int] = {}
            type_areas: dict[str, float] = {}
            total_area = 0.0
            largest_area = 0.0

            for body in bodies:
                face = _com_call(body, "GetFirstFace")
                while face:
                    try:
                        surf = _com_call(face, "GetSurface")
                        area_mm2 = _com_call(face, "GetArea") * M2_TO_MM2

                        if surf is None:
                            ftype = "unknown"
                        elif _com_call(surf, "IsPlane"):
                            ftype = "planar"
                        elif _com_call(surf, "IsCylinder"):
                            ftype = "cylindrical"
                        elif _com_call(surf, "IsCone"):
                            ftype = "conical"
                        elif _com_call(surf, "IsSphere"):
                            ftype = "spherical"
                        elif _com_call(surf, "IsTorus"):
                            ftype = "toroidal"
                        else:
                            ftype = "spline"

                        face_counts[ftype] = face_counts.get(ftype, 0) + 1
                        type_areas[ftype] = type_areas.get(ftype, 0.0) + area_mm2
                        total_area += area_mm2
                        if area_mm2 > largest_area:
                            largest_area = area_mm2
                    except Exception as exc:
                        logger.debug("Face read error: %s", exc)
                        face_counts["error"] = face_counts.get("error", 0) + 1
                    face = _com_call(face, "GetNextFace")

            total_faces = sum(face_counts.values())
            logger.info("analyze_faces: %d faces, %.1f mm²", total_faces, total_area)

            return {
                "face_counts": dict(sorted(face_counts.items(), key=lambda x: -x[1])),
                "face_areas_mm2": {k: round(v, 2) for k, v in
                                   sorted(type_areas.items(), key=lambda x: -x[1])},
                "total_faces": total_faces,
                "total_area_mm2": round(total_area, 2),
                "planar_area_mm2": round(type_areas.get("planar", 0.0), 2),
                "cylindrical_area_mm2": round(type_areas.get("cylindrical", 0.0), 2),
                "largest_face_mm2": round(largest_area, 2),
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("analyze_faces error")
            return {"error": f"Unexpected error: {exc}"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_doc_units(doc) -> str:
    try:
        unit_code = doc.GetUnits(0)
        return {0: "mm", 1: "cm", 2: "m", 3: "in", 4: "ft", 5: "ft-in"}.get(unit_code, "mm")
    except Exception:
        return "mm"


def _extract_hole_info(feat, feat_data, m_to_mm: float) -> dict | None:
    try:
        name = feat.Name
        diameter_m = None
        depth_m = None
        is_through = False
        try:
            diameter_m = feat_data.Diameter
        except Exception:
            pass
        try:
            depth_m = feat_data.Depth
        except Exception:
            pass
        try:
            is_through = bool(feat_data.IsThrough)
        except Exception:
            is_through = depth_m is None
        if diameter_m is None:
            return None
        return {
            "id": name,
            "diameter_mm": round(diameter_m * m_to_mm, 4),
            "depth_mm": "through" if is_through else round((depth_m or 0) * m_to_mm, 4),
            "type": "through" if is_through else "blind",
        }
    except Exception:
        return None


def _extract_bend_info(feat, m_to_mm: float) -> dict | None:
    import math
    try:
        name = feat.Name
        feat_data = _com_call(feat, "GetDefinition")
        if feat_data is None:
            return None
        radius_m = None
        angle_rad = None
        length_m = None
        k_factor = 0.44
        try:
            radius_m = feat_data.BendRadius
        except Exception:
            pass
        try:
            # BendAngle is in radians for OneBend features.
            angle_rad = feat_data.BendAngle
        except Exception:
            pass
        try:
            length_m = feat_data.Length
        except Exception:
            pass
        try:
            k_factor = feat_data.KFactor
        except Exception:
            pass
        if radius_m is None and angle_rad is None:
            return None
        angle_deg = math.degrees(angle_rad) if angle_rad is not None else 0.0
        return {
            "id": name,
            "angle_deg": round(angle_deg, 2),
            "radius_mm": round((radius_m or 0) * m_to_mm, 4),
            "length_mm": round((length_m or 0) * m_to_mm, 4),
            "k_factor": k_factor,
        }
    except Exception:
        return None


def _collect_holes(doc, bridge, m_to_mm: float) -> list[dict]:
    holes = []
    for feat in bridge.iter_features(doc):
        try:
            if _com_call(feat, "GetTypeName2") not in ("HoleWizard5", "SimpleHole", "HoleWizard3", "Hole"):
                continue
            fd = _com_call(feat, "GetDefinition")
            if fd:
                info = _extract_hole_info(feat, fd, m_to_mm)
                if info:
                    holes.append(info)
        except Exception:
            pass
    return holes


_BEND_TYPE_NAMES = (
    "EdgeFlange",      # native Edge Flange
    "SketchedBend",    # native Sketched Bend
    "FlatBend",        # bent flat feature
    "Bend",            # generic bend
    "OneBend",         # bends created by SolidToSheetMetal conversion
    "UiEdgeFlange",    # UI-created edge flange
    "SMMiteredFlange", # mitered flange
)


def _collect_bends(doc, bridge, m_to_mm: float) -> list[dict]:
    bends = []
    # Dedupe by feature name — SolidWorks sub-feature traversal can
    # loop back into the top-level chain, re-visiting features.
    seen: set[str] = set()

    def _visit(feat):
        while feat is not None:
            try:
                name = feat.Name
                if name in seen:
                    return
                seen.add(name)
                tn = _com_call(feat, "GetTypeName2")
                if tn in _BEND_TYPE_NAMES:
                    info = _extract_bend_info(feat, m_to_mm)
                    if info:
                        bends.append(info)
                sub = _com_call(feat, "GetFirstSubFeature")
                if sub is not None:
                    _visit(sub)
            except Exception:
                pass
            feat = _com_call(feat, "GetNextFeature")

    try:
        _visit(_com_call(doc, "FirstFeature"))
    except Exception:
        pass
    return bends


def _get_sm_props(doc, bridge, m_to_mm: float) -> dict:
    try:
        sm_feat = bridge.find_sheet_metal_feature(doc)
        if sm_feat is None:
            return {"error": "SheetMetal feature not found"}
        fd = _com_call(sm_feat, "GetDefinition")
        return {
            "thickness_mm": round(fd.Thickness * m_to_mm, 4),
            "default_bend_radius_mm": round(fd.BendRadius * m_to_mm, 4),
            "k_factor": fd.KFactor,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _estimate_complexity(
    feat_counts: dict,
    bbox: dict,
    is_sm: bool,
) -> tuple[str, list[str]]:
    total = sum(feat_counts.values())
    holes = sum(v for k, v in feat_counts.items() if "hole" in k.lower() or "Hole" in k)
    bends = sum(v for k, v in feat_counts.items() if "bend" in k.lower() or "flange" in k.lower())
    notes: list[str] = []

    if total < 10:
        complexity = "simple"
    elif total < 50:
        complexity = "medium"
    else:
        complexity = "complex"

    if is_sm:
        notes.append("Sheet metal part — suitable for progressive die stamping.")
        if bends > 6:
            notes.append(f"{bends} bends detected — consider split tooling or a transfer die.")
        if holes > 20:
            notes.append(f"{holes} holes — verify minimum edge-to-hole distances.")
    else:
        notes.append(
            "Not a sheet metal part. "
            "Use convert_to_sheet_metal() if this should be a stamped part."
        )

    dims = bbox.get("dimensions_mm")
    if dims:
        min_dim = min((d for d in dims if d > 0), default=0)
        if 0 < min_dim < 3:
            notes.append(f"Thin wall detected (~{min_dim:.2f} mm) — verify formability.")

    return complexity, notes


def _render_markdown_report(report: dict) -> str:
    meta = report.get("metadata", {})
    dims = report.get("dimensions", {})
    mass = report.get("mass_properties", {})
    features = report.get("features", {})
    holes = report.get("holes", {})
    bends = report.get("bends", {})
    sm = report.get("sheet_metal_props", {})

    lines = [
        f"# Part Analysis Report: {meta.get('name', 'Unknown')}",
        "",
        f"**File:** `{meta.get('file_path', '')}`  ",
        f"**Sheet Metal:** {'Yes' if meta.get('is_sheet_metal') else 'No'}  ",
        f"**Complexity:** {report.get('complexity_estimate', '')}",
        "",
        "## Dimensions (mm)", "",
    ]

    if "dimensions_mm" in dims:
        d = dims["dimensions_mm"]
        lines += [
            "| Axis | Min | Max | Span |",
            "|------|-----|-----|------|",
            f"| X | {dims['min_mm'][0]:.2f} | {dims['max_mm'][0]:.2f} | {d[0]:.2f} |",
            f"| Y | {dims['min_mm'][1]:.2f} | {dims['max_mm'][1]:.2f} | {d[1]:.2f} |",
            f"| Z | {dims['min_mm'][2]:.2f} | {dims['max_mm'][2]:.2f} | {d[2]:.2f} |",
            "",
        ]

    lines += ["## Mass Properties", ""]
    if "mass_g" in mass:
        lines += [
            f"- **Mass:** {mass['mass_g']:.2f} g",
            f"- **Volume:** {mass['volume_mm3']:.2f} mm³",
            f"- **Surface Area:** {mass['surface_area_mm2']:.2f} mm²",
            "",
        ]

    lines += ["## Features", "", f"Total features: **{features.get('total', 0)}**", ""]
    by_type = features.get("by_type", {})
    if by_type:
        lines += ["| Feature Type | Count |", "|---|---|"]
        for ft, cnt in list(by_type.items())[:20]:
            lines.append(f"| {ft} | {cnt} |")
        lines.append("")

    lines += [
        f"## Holes (Total: {holes.get('total_holes', 0)})", "",
        "| Diameter (mm) | Count |", "|---|---|",
    ]
    for diam, cnt in holes.get("by_diameter", {}).items():
        lines.append(f"| {diam} | {cnt} |")
    lines.append("")

    if meta.get("is_sheet_metal"):
        lines += [f"## Bends (Total: {bends.get('total_bends', 0)})", ""]
        for b in bends.get("bends", []):
            lines.append(
                f"- **{b['id']}**: {b['angle_deg']}° × R{b['radius_mm']} mm, L={b['length_mm']} mm"
            )
        lines += [
            "",
            "## Sheet Metal Properties", "",
            f"- Thickness: {sm.get('thickness_mm', 'N/A')} mm",
            f"- Default Bend Radius: {sm.get('default_bend_radius_mm', 'N/A')} mm",
            f"- K-Factor: {sm.get('k_factor', 'N/A')}",
            "",
        ]

    if report.get("manufacturing_recommendations"):
        lines += ["## Manufacturing Recommendations", ""]
        for note in report["manufacturing_recommendations"]:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)
