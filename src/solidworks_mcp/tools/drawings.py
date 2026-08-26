"""
Drawing creation and management tools for SolidWorks MCP.

Tools in this module:
    create_drawing_from_part  — Create a new drawing document from the active part
    add_drawing_view          — Add a projected/named view to a drawing
    list_drawing_views        — List all views on the active drawing
    get_drawing_info          — Sheet count, scale, paper size for active drawing
    add_section_view          — Add a section view to an existing drawing view
    set_drawing_scale         — Change the overall drawing scale

Drawing documents are of type 3 (swDocDRAWING).
Views are IView objects; sheets are ISheet objects accessed via
    draw.GetCurrentSheet() / draw.Sheet(name).

Paper size constants (swDwgPaperSizes_e) examples:
    0 = swDwgPaperA4size, 1 = swDwgPaperA3size, 4 = swDwgPapersLettersize
    12 = swDwgPaperUserDefined

Standard view constants (swStandardViews_e):
    1=Front, 2=Back, 3=Left, 4=Right, 5=Top, 6=Bottom, 7=Isometric
    8=Dimetric, 9=Trimetric

Projection type constants (swProjectionType_e):
    0 = first angle, 1 = third angle (default in many locales)
"""

import logging
import os
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import _com_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)

_PAPER_SIZE_NAMES = {
    0: "A4", 1: "A3", 2: "A2", 3: "A1", 4: "Letter", 5: "Legal",
    6: "B", 7: "C", 8: "D", 9: "E", 12: "Custom",
}
_STANDARD_VIEW_IDS = {
    "front": 1, "back": 2, "left": 3, "right": 4,
    "top": 5, "bottom": 6, "isometric": 7, "dimetric": 8, "trimetric": 9,
}


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all drawing tools with the FastMCP instance."""

    @mcp.tool()
    def create_drawing_from_part(
        template_path: str = "",
        paper_size: str = "A3",
        scale_numerator: float = 1.0,
        scale_denominator: float = 1.0,
    ) -> dict:
        """
        Create a new drawing document from the active part or assembly.

        Opens a blank drawing sheet linked to the active model document.
        After creation, use add_drawing_view to place views.

        Args:
            template_path: Full path to a .drwdot template file.
                           Leave empty to use the SolidWorks default template.
            paper_size: Paper size — "A4", "A3", "A2", "A1", "Letter", "Legal".
                        Default "A3".
            scale_numerator: Drawing scale numerator (e.g. 1 for 1:2).
            scale_denominator: Drawing scale denominator (e.g. 2 for 1:2).

        Returns a dict with:
            success (bool), drawing_title (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()  # ensure a source document is open

            paper_code = _paper_name_to_code(paper_size)

            if template_path and not os.path.isabs(template_path):
                template_path = os.path.abspath(template_path)

            # MakeDrawingDocument3(template, paperType, W, H, scale)
            # W/H only used when paperType == 12 (custom)
            new_draw = bridge.app.MakeDrawingDocument3(
                template_path or "",
                paper_code,
                0.2969, 0.2100,  # A3 fallback dimensions in metres
                scale_numerator / scale_denominator,
            )

            if new_draw is None:
                return {"success": False, "error": "MakeDrawingDocument3 returned None"}

            logger.info("create_drawing_from_part: created drawing from '%s'", _com_call(doc, "GetTitle"))
            return {"success": True, "drawing_title": _com_call(new_draw, "GetTitle")}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("create_drawing_from_part error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def add_drawing_view(
        view_name: str = "front",
        x_mm: float = 100.0,
        y_mm: float = 150.0,
        scale_numerator: float = 1.0,
        scale_denominator: float = 1.0,
    ) -> dict:
        """
        Add a standard named view to the active drawing.

        Adds one of the standard orthographic or isometric views at the
        specified position on the current sheet.

        Args:
            view_name: One of "front", "back", "left", "right", "top",
                       "bottom", "isometric", "dimetric", "trimetric".
                       Default "front".
            x_mm: X position of the view centre on the sheet (mm).
            y_mm: Y position of the view centre on the sheet (mm).
            scale_numerator: View scale numerator.
            scale_denominator: View scale denominator.

        Returns a dict with:
            success (bool), view (str), position_mm (dict x/y)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=3)  # drawing only

            view_id = _STANDARD_VIEW_IDS.get(view_name.lower(), 1)
            scale = scale_numerator / scale_denominator

            # CreateDrawViewFromModelView3(modelName, viewName, x, y, z)
            # For standard views, modelName="" and viewName uses the standard
            # view constant name string
            view_str = _view_id_to_api_name(view_id)
            x_m = x_mm / 1000.0
            y_m = y_mm / 1000.0

            view = doc.CreateDrawViewFromModelView3("", view_str, x_m, y_m, 0)
            if view is None:
                # Fallback: create3DView
                view = doc.Create3DView(view_id, x_m, y_m)

            if view is None:
                return {"success": False,
                        "error": f"Failed to create '{view_name}' view at ({x_mm}, {y_mm})"}

            view.ScaleDecimal = scale

            logger.info("add_drawing_view: added '%s' view at (%.1f, %.1f)", view_name, x_mm, y_mm)
            return {
                "success": True,
                "view": view_name,
                "position_mm": {"x": x_mm, "y": y_mm},
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("add_drawing_view error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def list_drawing_views() -> dict:
        """
        List all views on the active drawing document.

        Returns a dict with:
            views (list[dict]): each has name, view_type, scale,
                                position_mm (x/y), sheet
            count (int), sheet_count (int)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=3)

            draw = doc  # IDrawingDoc (same COM object as IModelDoc2 for drawings)
            sheets = _com_call(draw, "GetSheetNames")
            views_data = []

            for sheet_name in (sheets or []):
                draw.ActivateSheet(sheet_name)
                view = _com_call(draw, "GetFirstView")
                while view:
                    try:
                        vname = view.Name
                        pos = view.Position  # (x, y) in metres
                        scale = view.ScaleDecimal
                        views_data.append({
                            "name": vname,
                            "sheet": sheet_name,
                            "scale": scale,
                            "position_mm": {
                                "x": round(pos[0] * 1000, 2) if pos else None,
                                "y": round(pos[1] * 1000, 2) if pos else None,
                            },
                        })
                    except Exception as exc:
                        logger.debug("View read error: %s", exc)
                    view = _com_call(view, "GetNextView")

            return {
                "views": views_data,
                "count": len(views_data),
                "sheet_count": len(sheets) if sheets else 0,
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("list_drawing_views error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_drawing_info() -> dict:
        """
        Get metadata about the active drawing document.

        Returns a dict with:
            title (str), sheet_count (int), active_sheet (str),
            paper_size (str), drawing_scale (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=3)

            draw = doc
            sheet_names = _com_call(draw, "GetSheetNames") or []
            active_sheet = ""
            paper_size_name = ""
            draw_scale = ""

            try:
                sheet = _com_call(draw, "GetCurrentSheet")
                if sheet:
                    active_sheet = _com_call(sheet, "GetName")
                    ps = sheet.PaperSize
                    paper_size_name = _PAPER_SIZE_NAMES.get(ps, f"code={ps}")
                    sn = sheet.ScaleNumerator
                    sd = sheet.ScaleDenominator
                    draw_scale = f"{int(sn)}:{int(sd)}" if sd else str(sn)
            except Exception as exc:
                logger.debug("Sheet read error: %s", exc)

            return {
                "title": _com_call(doc, "GetTitle"),
                "sheet_count": len(sheet_names),
                "sheets": list(sheet_names),
                "active_sheet": active_sheet,
                "paper_size": paper_size_name,
                "drawing_scale": draw_scale,
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_drawing_info error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def set_drawing_scale(
        numerator: float,
        denominator: float,
        sheet_name: str = "",
    ) -> dict:
        """
        Change the scale of a drawing sheet.

        Args:
            numerator: Scale numerator (e.g. 1 for 1:2 or 2 for 2:1).
            denominator: Scale denominator (e.g. 2 for 1:2 or 1 for 2:1).
            sheet_name: Sheet to change. Leave empty for the active sheet.

        Returns a dict with:
            success (bool), scale (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=3)

            draw = doc
            if sheet_name:
                draw.ActivateSheet(sheet_name)

            sheet = _com_call(draw, "GetCurrentSheet")
            if sheet is None:
                return {"success": False, "error": "No active sheet found"}

            sheet.ScaleNumerator = numerator
            sheet.ScaleDenominator = denominator
            _com_call(doc, "EditRebuild3")

            logger.info("set_drawing_scale: %s:%s", numerator, denominator)
            return {
                "success": True,
                "scale": f"{int(numerator)}:{int(denominator)}",
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("set_drawing_scale error")
            return {"success": False, "error": f"Unexpected error: {exc}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paper_name_to_code(name: str) -> int:
    mapping = {
        "a4": 0, "a3": 1, "a2": 2, "a1": 3,
        "letter": 4, "legal": 5, "b": 6, "c": 7, "d": 8, "e": 9,
        "custom": 12,
    }
    return mapping.get(name.lower(), 1)  # default A3


def _view_id_to_api_name(view_id: int) -> str:
    """Map swStandardViews_e integer to the DrawingViewName string SolidWorks uses."""
    names = {
        1: "*Front", 2: "*Back", 3: "*Left", 4: "*Right",
        5: "*Top", 6: "*Bottom", 7: "*Isometric",
        8: "*Dimetric", 9: "*Trimetric",
    }
    return names.get(view_id, "*Front")
