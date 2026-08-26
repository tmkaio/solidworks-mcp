"""
Sheet metal operation tools for SolidWorks MCP.

Tools in this module:
    is_sheet_metal              — Check if active part is sheet metal
    get_sheet_metal_properties  — Thickness, bend radius, K-factor
    convert_to_sheet_metal      — Convert imported solid to sheet metal
    flatten_part                — Activate flat pattern (unfold)
    unflatten_part              — Return to folded state

Important state note:
    flatten_part changes document state (flat vs. folded). This is a reversible
    change — call unflatten_part() to restore the folded state. The document is
    NOT automatically saved after flattening.
"""

import logging
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import _com_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all sheet metal tools with the FastMCP instance."""

    @mcp.tool()
    def is_sheet_metal() -> dict:
        """
        Check if the active part is a sheet metal part.

        Use this tool before any sheet metal-specific operation (flatten,
        get_sheet_metal_properties, analyze_bends) to confirm the part type.

        Returns a dict with:
            is_sheet_metal (bool): True if a SheetMetal feature exists
            feature_name (str | null): name of the SheetMetal feature if found
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)
            feat = bridge.find_sheet_metal_feature(doc)
            if feat:
                return {"is_sheet_metal": True, "feature_name": feat.Name}
            return {"is_sheet_metal": False, "feature_name": None}
        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("is_sheet_metal error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_sheet_metal_properties() -> dict:
        """
        Return the sheet metal parameters of the active part.

        Use this tool when the user asks about:
        - Material thickness (crucial for press brake tooling selection)
        - Default bend radius
        - K-factor used for bend allowance calculations

        Requires: active part must be a sheet metal part.

        Returns a dict with:
            thickness_mm (float): sheet thickness in mm
            default_bend_radius_mm (float): default inner bend radius in mm
            k_factor (float): K-factor for bend allowance (typically 0.33–0.5)
            feature_name (str): name of the SheetMetal feature
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
                    "The active part has no SheetMetal feature. "
                    "Use convert_to_sheet_metal() to convert it, "
                    "or open a native sheet metal part."
                )

            fd = _com_call(sm_feat, "GetDefinition")
            if fd is None:
                raise SheetMetalError(
                    "Could not retrieve SheetMetal feature definition."
                )

            thickness_mm = round(fd.Thickness * M_TO_MM, 4)
            bend_radius_mm = round(fd.BendRadius * M_TO_MM, 4)
            k_factor = fd.KFactor

            logger.info(
                "get_sheet_metal_properties: t=%.3f mm, R=%.3f mm, K=%.3f",
                thickness_mm, bend_radius_mm, k_factor,
            )

            return {
                "thickness_mm": thickness_mm,
                "default_bend_radius_mm": bend_radius_mm,
                "k_factor": k_factor,
                "feature_name": sm_feat.Name,
            }

        except (SolidWorksConnectionError, DocumentNotOpenError, SheetMetalError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_sheet_metal_properties error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def convert_to_sheet_metal(
        thickness: float,
        k_factor: float = 0.44,
        bend_radius: float = 1.0,
    ) -> dict:
        """
        Convert the active solid part to a sheet metal part.

        Use this tool after opening a STEP file that represents a sheet metal
        part. STEP files import as "dumb" solids without sheet metal features;
        this conversion adds the SheetMetal feature tree so flatten, bend
        analysis, and DXF export become available.

        SolidWorks requires selecting a fixed face before conversion. This tool
        automatically selects the largest planar face as the fixed face, which
        works for most flat-based sheet metal parts.

        Args:
            thickness: Sheet thickness in mm (e.g. 1.5, 2.0, 3.0)
            k_factor: Bend allowance K-factor (0.33–0.5, default 0.44)
            bend_radius: Default inner bend radius in mm (default 1.0)

        Returns a dict with:
            success (bool)
            thickness_mm (float): applied thickness
            k_factor (float): applied K-factor
            bend_radius_mm (float): applied bend radius
            warning (str): present if SolidWorks issued warnings
            error (str): present only on failure
        """
        from solidworks_mcp.exceptions import (
            DocumentNotOpenError,
            SheetMetalError,
            SolidWorksConnectionError,
        )
        from solidworks_mcp.solidworks_bridge import M_TO_MM

        if thickness <= 0:
            return {"error": "thickness must be a positive number in mm"}
        if not (0.1 <= k_factor <= 0.9):
            return {"error": "k_factor must be between 0.1 and 0.9"}
        if bend_radius <= 0:
            return {"error": "bend_radius must be a positive number in mm"}

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)

            if bridge.find_sheet_metal_feature(doc) is not None:
                return {
                    "success": True,
                    "warning": "Part is already a sheet metal part — no conversion needed.",
                    "thickness_mm": thickness,
                    "k_factor": k_factor,
                    "bend_radius_mm": bend_radius,
                }

            fixed_face = _select_largest_planar_face(doc)
            if fixed_face is None:
                raise SheetMetalError(
                    "Could not find a planar face to use as the fixed face. "
                    "The part may not be suitable for sheet metal conversion."
                )

            thickness_m = thickness / M_TO_MM
            bend_radius_m = bend_radius / M_TO_MM

            feat_mgr = doc.FeatureManager
            # Actual gen_py signature (SolidWorks 2025):
            #   InsertConvertToSheetMetal2(Thickness, ReverseThickDir, FindBends,
            #       Radius, Gap, ReliefType, ReliefRatio, OverlapType,
            #       OverlapRatio, KeepBody) -> bool
            # K-factor is NOT a parameter here — it's set on the SheetMetal
            # feature definition afterwards.
            result = feat_mgr.InsertConvertToSheetMetal2(
                thickness_m,
                False,           # ReverseThickDir
                True,            # FindBends (auto-detect bend edges)
                bend_radius_m,
                0.0005,          # Gap (rip gap in meters — 0.5 mm default)
                0,               # ReliefType: 0 = Rectangular
                0.5,             # ReliefRatio
                0,               # OverlapType: 0 = No overlap
                1.0,             # OverlapRatio
                True,            # KeepBody
            )

            # Note: InsertConvertToSheetMetal2 may return False even when
            # conversion succeeded (e.g. with multi-body parts). The
            # authoritative success signal is whether a SheetMetal feature
            # was created in the tree.
            _com_call(doc, "EditRebuild3")

            sm_feat = bridge.find_sheet_metal_feature(doc)
            if sm_feat is None:
                raise SheetMetalError(
                    f"Conversion failed (return={result}). "
                    "SheetMetal feature was not created. "
                    "Check that the part is a single solid body and a planar "
                    "fixed face was selected."
                )

            # Apply K-factor to the SheetMetal feature definition.
            try:
                fd = _com_call(sm_feat, "GetDefinition")
                if fd is not None:
                    fd.KFactor = k_factor
                    sm_feat.ModifyDefinition(fd, doc, None)
            except Exception as exc:
                logger.warning("Could not set K-factor on SheetMetal feature: %s", exc)

            logger.info(
                "convert_to_sheet_metal: success t=%.3f mm K=%.3f R=%.3f mm",
                thickness, k_factor, bend_radius,
            )

            return {
                "success": True,
                "thickness_mm": thickness,
                "k_factor": k_factor,
                "bend_radius_mm": bend_radius,
            }

        except (SolidWorksConnectionError, DocumentNotOpenError, SheetMetalError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("convert_to_sheet_metal error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def flatten_part() -> dict:
        """
        Activate the flat pattern (unfold) of the active sheet metal part.

        This changes the document state from 3D folded to 2D flat.
        Call unflatten_part() to return to the folded state.

        Use this tool when you need to:
        - See the flat (unfolded) shape for blank size calculation
        - Export a DXF of the flat pattern (call export_dxf() after this)
        - Measure the overall flat dimensions

        Requires: active part must be a sheet metal part.

        Returns a dict with:
            success (bool)
            flat_area_mm2 (float): area of the flat pattern
            flat_dimensions_mm (list[float]): [length, width] of the flat bounding box
        """
        from solidworks_mcp.exceptions import (
            DocumentNotOpenError,
            SheetMetalError,
            SolidWorksConnectionError,
        )

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)

            if bridge.find_sheet_metal_feature(doc) is None:
                raise SheetMetalError(
                    "The active part is not a sheet metal part. "
                    "Cannot flatten. Use convert_to_sheet_metal() first."
                )

            flat_feat = _find_flat_pattern_feature(doc)
            if flat_feat is None:
                raise SheetMetalError(
                    "FlatPattern feature not found in the feature tree. "
                    "The part may need to be rebuilt first."
                )

            flat_feat.SetSuppression2(0, 2, None)  # 0 = unsuppress, 2 = all configs
            _com_call(doc, "EditRebuild3")

            try:
                bbox = bridge.get_bounding_box(doc)
                dims = bbox.get("dimensions_mm", [0, 0, 0])
                sorted_dims = sorted(dims, reverse=True)
                flat_dims = sorted_dims[:2]
                flat_area = flat_dims[0] * flat_dims[1]
            except Exception:
                flat_dims = [0.0, 0.0]
                flat_area = 0.0

            logger.info("flatten_part: flat area=%.1f mm²", flat_area)
            return {
                "success": True,
                "flat_area_mm2": round(flat_area, 2),
                "flat_dimensions_mm": [round(d, 4) for d in flat_dims],
            }

        except (SolidWorksConnectionError, DocumentNotOpenError, SheetMetalError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("flatten_part error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def unflatten_part() -> dict:
        """
        Return the flat pattern to the folded (3D) state.

        Call this after export_dxf() or after measuring the flat pattern,
        to return the part to its normal 3D folded shape.

        Returns a dict with:
            success (bool)
            error (str): present only on failure
        """
        from solidworks_mcp.exceptions import (
            DocumentNotOpenError,
            SolidWorksConnectionError,
        )

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)

            flat_feat = _find_flat_pattern_feature(doc)
            if flat_feat is None:
                return {
                    "success": True,
                    "note": "FlatPattern feature not found — part may already be in folded state.",
                }

            flat_feat.SetSuppression2(1, 2, None)  # 1 = suppress
            _com_call(doc, "EditRebuild3")
            logger.info("unflatten_part: part returned to folded state")
            return {"success": True}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("unflatten_part error")
            return {"success": False, "error": f"Unexpected error: {exc}"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _select_largest_planar_face(doc) -> object | None:
    """Select the largest planar face in the part and return it."""
    try:
        bodies = doc.GetBodies2(0, True)  # 0 = swSolidBody
        if not bodies:
            return None

        best_face = None
        best_area = 0.0

        for body in bodies:
            face = _com_call(body, "GetFirstFace")
            while face is not None:
                try:
                    surface = _com_call(face, "GetSurface")
                    if surface and _com_call(surface, "IsPlane"):
                        area = _com_call(face, "GetArea")
                        if area > best_area:
                            best_area = area
                            best_face = face
                except Exception:
                    pass
                face = _com_call(face, "GetNextFace")

        if best_face:
            doc.ClearSelection2(True)
            best_face.Select2(False, 0)

        return best_face
    except Exception as exc:
        logger.warning("_select_largest_planar_face failed: %s", exc)
        return None


def _find_flat_pattern_feature(doc) -> object | None:
    """Search the feature tree for the FlatPattern feature."""
    try:
        feat = _com_call(doc, "FirstFeature")
        while feat is not None:
            try:
                type_name = _com_call(feat, "GetTypeName2")
                if type_name in ("FlatPattern", "FlatPatternFolder"):
                    return feat
            except Exception:
                pass
            feat = _com_call(feat, "GetNextFeature")
    except Exception:
        pass
    return None
