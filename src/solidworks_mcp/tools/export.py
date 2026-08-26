"""
Export tools for SolidWorks MCP.

Tools in this module:
    export_dxf       — Export flat pattern as DXF (sheet metal parts)
    export_step      — Export active document as STEP
    export_stl       — Export active document as STL
    export_pdf       — Export active document as PDF
    take_screenshot  — Capture viewport screenshot as PNG

Export format type codes (swExportDataFileType_e):
    1  = DXF/DWG
    6  = PDF
    20 = STEP
    22 = STL
"""

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import _com_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)

_EXPORT_DXF = 1
_EXPORT_PDF = 6
_EXPORT_STEP = 20
_EXPORT_STL = 22


def _save_as3(doc, abs_out: str, export_data=None) -> bool:
    """
    Invoke ModelDocExtension::SaveAs3 via raw InvokeTypes.

    With typed gen_py wrappers, passing Python None for the ExportData or
    AdvancedSaveAsOptions IDispatch params triggers "Type mismatch". This
    helper substitutes empty VARIANTs and calls InvokeTypes directly.

    Signature (DISPID 315):
        SaveAs3(Name, Version, Options, ExportData, AdvancedSaveAsOptions,
                Errors[byref], Warnings[byref]) -> bool
    """
    ext_obj = doc.Extension
    raw_ext = ext_obj._oleobj_ if hasattr(ext_obj, "_oleobj_") else ext_obj

    # For the IDispatch params, we need the raw _oleobj_ of any wrapped
    # export_data, and None is acceptable at the raw InvokeTypes layer
    # (unlike _ApplyTypes_ in the generated wrapper which rejects None).
    ed_raw = export_data
    if ed_raw is not None and hasattr(ed_raw, "_oleobj_"):
        ed_raw = ed_raw._oleobj_

    result = raw_ext.InvokeTypes(
        315, 0, 1, (11, 0),
        ((8, 1), (3, 1), (3, 1), (9, 1), (9, 1), (16387, 3), (16387, 3)),
        abs_out, 0, 0, ed_raw, None, 0, 0,
    )
    logger.debug("SaveAs3(%s) -> %r", abs_out, result)
    # Result shape: either bool, or tuple (bool, errors, warnings)
    if isinstance(result, tuple):
        return bool(result[0])
    return bool(result)


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all export tools with the FastMCP instance."""

    @mcp.tool()
    def export_dxf(
        output_path: str,
        include_bend_lines: bool = True,
    ) -> dict:
        """
        Export the flat pattern of the active sheet metal part as a DXF file.

        This is the primary output for laser cutting and press-brake programming.
        Call flatten_part() before this tool, or the tool will attempt to flatten
        automatically.

        Use this tool when the user asks:
        - "Export the flat pattern as DXF"
        - "Give me the DXF for laser cutting"
        - "Export for Almacam / JETCAM / nesting software"

        Args:
            output_path: Absolute path for the output file (e.g. C:\\output\\bracket.dxf)
            include_bend_lines: Include bend lines as a separate layer.
                                Recommended True for press brake programming.

        Returns a dict with:
            success (bool)
            output_path (str): path where the DXF was saved
            file_size_kb (float)
            warnings (list[str])
            error (str): present only on failure
        """
        from solidworks_mcp.exceptions import (
            DocumentNotOpenError,
            ExportError,
            SheetMetalError,
            SolidWorksConnectionError,
        )

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)

            if bridge.find_sheet_metal_feature(doc) is None:
                raise SheetMetalError(
                    "DXF flat pattern export requires a sheet metal part. "
                    "Use convert_to_sheet_metal() first."
                )

            abs_out = os.path.abspath(output_path)
            Path(abs_out).parent.mkdir(parents=True, exist_ok=True)

            # ExportToDWG2 requires the part to have a saved path. For
            # STEP-imported parts (which have no path until saved), save
            # as SLDPRT alongside the DXF first.
            current_path = _com_call(doc, "GetPathName") or ""
            if not current_path:
                sldprt_path = str(Path(abs_out).with_suffix(".SLDPRT"))
                _save_as3(doc, sldprt_path)
                logger.info("export_dxf: auto-saved part to %s", sldprt_path)
                current_path = _com_call(doc, "GetPathName") or sldprt_path

            # Use IPartDoc::ExportToDWG2 — this is the correct API for
            # flat-pattern DXF export. SaveAs3 on a sheet metal part
            # doesn't trigger flat-pattern export; it just saves the 3D
            # model as a (blank) DXF.
            # SheetMetalOptions bitmask (swExportToDWGOptions_e):
            #   0x01 = ExportBendLines
            #   0x02 = ExportGeometry
            #   0x04 = ExportFormedFeatures
            #   0x10 = ExportBendDirectionNotes
            sm_options = 0x02  # geometry always
            if include_bend_lines:
                sm_options |= 0x01 | 0x10
            # Action=1 = sheet metal flat pattern export
            ok = doc.ExportToDWG2(
                abs_out,
                current_path,
                1,        # Action: 1 = sheet metal flat pattern
                True,     # ExportToSingleFile
                None,     # Alignment (VT_VARIANT — None = default)
                False,    # IsXDirFlipped
                False,    # IsYDirFlipped
                sm_options,
                None,     # Views
            )
            logger.debug("ExportToDWG2 returned: %r", ok)

            if not os.path.isfile(abs_out):
                raise ExportError(
                    f"SaveAs3 did not create the file at '{abs_out}'. "
                    "Check SolidWorks for error dialogs."
                )

            file_size_kb = os.path.getsize(abs_out) / 1024.0
            logger.info("export_dxf: wrote '%s' (%.1f KB)", abs_out, file_size_kb)
            return {
                "success": True,
                "output_path": abs_out,
                "file_size_kb": round(file_size_kb, 2),
                "warnings": [],
            }

        except (SolidWorksConnectionError, DocumentNotOpenError, SheetMetalError, ExportError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("export_dxf error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def export_step(output_path: str) -> dict:
        """
        Export the active document as a STEP (AP214) file.

        Use this tool when the user wants to:
        - Save the converted/modified part back to STEP for sharing
        - Export for use in other CAD systems

        Args:
            output_path: Absolute path for the output .step file.

        Returns a dict with:
            success (bool), output_path (str), file_size_kb (float)
        """
        from solidworks_mcp.exceptions import (
            DocumentNotOpenError,
            ExportError,
            SolidWorksConnectionError,
        )

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            abs_out = os.path.abspath(output_path)
            Path(abs_out).parent.mkdir(parents=True, exist_ok=True)
            _save_as3(doc, abs_out)
            if not os.path.isfile(abs_out):
                raise ExportError(f"STEP export failed — file not created at '{abs_out}'.")
            file_size_kb = os.path.getsize(abs_out) / 1024.0
            logger.info("export_step: wrote '%s' (%.1f KB)", abs_out, file_size_kb)
            return {"success": True, "output_path": abs_out, "file_size_kb": round(file_size_kb, 2)}
        except (SolidWorksConnectionError, DocumentNotOpenError, ExportError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("export_step error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def export_stl(output_path: str, quality: str = "fine") -> dict:
        """
        Export the active part or assembly as an STL file.

        Use this tool when the user wants to:
        - Send the part to a 3D printing service
        - Create a mesh representation for simulation

        Args:
            output_path: Absolute path for the output .stl file.
            quality: Mesh quality — "coarse", "fine", or "custom".

        Returns a dict with:
            success (bool), output_path (str), file_size_kb (float), quality (str)
        """
        from solidworks_mcp.exceptions import (
            DocumentNotOpenError,
            ExportError,
            SolidWorksConnectionError,
        )

        quality_map = {"coarse": 0, "fine": 1, "custom": 2}
        quality_code = quality_map.get(quality.lower(), 1)

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            abs_out = os.path.abspath(output_path)
            Path(abs_out).parent.mkdir(parents=True, exist_ok=True)

            try:
                bridge.app.SetUserPreferenceIntegerValue(71, quality_code)
            except Exception as exc:
                logger.warning("Could not set STL quality: %s", exc)

            _save_as3(doc, abs_out)
            if not os.path.isfile(abs_out):
                raise ExportError(f"STL export failed — file not created at '{abs_out}'.")
            file_size_kb = os.path.getsize(abs_out) / 1024.0
            logger.info("export_stl: wrote '%s' (%.1f KB)", abs_out, file_size_kb)
            return {
                "success": True,
                "output_path": abs_out,
                "file_size_kb": round(file_size_kb, 2),
                "quality": quality,
            }
        except (SolidWorksConnectionError, DocumentNotOpenError, ExportError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("export_stl error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def export_pdf(output_path: str) -> dict:
        """
        Export the active document as a PDF file.

        For Drawing documents: exports all sheets as a multi-page PDF.
        For Part/Assembly documents: exports a rendered image of the current view.

        Args:
            output_path: Absolute path for the output .pdf file.

        Returns a dict with:
            success (bool), output_path (str), file_size_kb (float)
        """
        from solidworks_mcp.exceptions import (
            DocumentNotOpenError,
            ExportError,
            SolidWorksConnectionError,
        )

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            abs_out = os.path.abspath(output_path)
            Path(abs_out).parent.mkdir(parents=True, exist_ok=True)

            export_data = None
            try:
                export_data = bridge.app.GetExportFileData(_EXPORT_PDF)
            except Exception as exc:
                logger.warning("Could not create PDF export data: %s", exc)

            _save_as3(doc, abs_out, export_data)
            if not os.path.isfile(abs_out):
                raise ExportError(f"PDF export failed — file not created at '{abs_out}'.")
            file_size_kb = os.path.getsize(abs_out) / 1024.0
            logger.info("export_pdf: wrote '%s' (%.1f KB)", abs_out, file_size_kb)
            return {"success": True, "output_path": abs_out, "file_size_kb": round(file_size_kb, 2)}
        except (SolidWorksConnectionError, DocumentNotOpenError, ExportError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("export_pdf error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def take_screenshot(output_path: str, view: str = "isometric") -> dict:
        """
        Capture a screenshot of the active SolidWorks viewport and save as PNG.

        Use this tool when the user asks to:
        - See what the part looks like
        - Include a render/image in a report

        Args:
            output_path: Absolute path for the output .png file.
            view: Camera preset — "isometric", "front", "back", "top",
                  "bottom", "left", "right". Default is "isometric".

        Returns a dict with:
            success (bool), output_path (str), file_size_kb (float), view (str)
        """
        from solidworks_mcp.exceptions import (
            DocumentNotOpenError,
            ExportError,
            SolidWorksConnectionError,
        )

        view_codes = {
            "front": 1, "back": 2, "left": 3, "right": 4,
            "top": 5, "bottom": 6, "isometric": 7,
            "trimetric": 8, "dimetric": 9,
        }
        view_code = view_codes.get(view.lower(), 7)

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            abs_out = os.path.abspath(output_path)
            Path(abs_out).parent.mkdir(parents=True, exist_ok=True)

            try:
                doc.ShowNamedView2("", view_code)
                doc.ViewZoomtofit2()
            except Exception as exc:
                logger.warning("Could not set view '%s': %s", view, exc)

            _save_as3(doc, abs_out)
            if not os.path.isfile(abs_out):
                raise ExportError(f"Screenshot failed — file not created at '{abs_out}'.")
            file_size_kb = os.path.getsize(abs_out) / 1024.0
            logger.info("take_screenshot: wrote '%s' (%.1f KB)", abs_out, file_size_kb)
            return {
                "success": True,
                "output_path": abs_out,
                "file_size_kb": round(file_size_kb, 2),
                "view": view,
            }
        except (SolidWorksConnectionError, DocumentNotOpenError, ExportError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("take_screenshot error")
            return {"success": False, "error": f"Unexpected error: {exc}"}
