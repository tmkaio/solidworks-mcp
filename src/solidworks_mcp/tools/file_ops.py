"""
File operation tools for SolidWorks MCP.

Tools in this module:
    open_file          — Open a STEP, SLDPRT, IGES, or other CAD file
    close_file         — Close the active document
    save_file          — Save the active document (optionally to a new path)
    list_open_documents — List all documents currently open in SolidWorks

Critical note on OpenDoc6 VARIANT parameters:
    SolidWorks OpenDoc6 has by-reference output parameters (errors, warnings)
    that must be passed as win32com VARIANT objects, not plain Python ints.
    Getting this wrong is the #1 source of runtime crashes in pywin32/SW integrations.
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

# SolidWorks document type codes by file extension (for native OpenDoc6)
_EXTENSION_TO_DOC_TYPE: dict[str, int] = {
    ".sldprt": 1,
    ".sldasm": 2,
    ".slddrw": 3,
    ".prt": 1,
    ".asm": 2,
    ".drw": 3,
}

# Foreign/import formats that must go through LoadFile4 + GetImportFileData,
# not OpenDoc6. OpenDoc6 is strictly for native SolidWorks documents; calling
# it on a STEP/IGES/X_T/SAT/STL returns null with a non-standard error bit
# (commonly 0x00200000) even when the file is perfectly valid.
_IMPORT_EXTENSIONS: set[str] = {
    ".step", ".stp",
    ".iges", ".igs",
    ".x_t", ".x_b",
    ".sat",
    ".stl",
}


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all file operation tools with the FastMCP instance."""

    @mcp.tool()
    def open_file(file_path: str, read_only: bool = False) -> dict:
        """
        Open a CAD file in SolidWorks.

        Supported formats: SLDPRT, SLDASM, STEP, STP, IGES, IGS, X_T, SAT, STL.

        IMPORTANT: For STEP files, the part imports as a "dumb" solid (no parametric
        features). This is normal. Sheet metal analysis requires converting the
        imported solid using convert_to_sheet_metal() afterward.

        Use this tool when:
        - The user wants to analyze a specific file
        - Opening a STEP file received from a customer

        Args:
            file_path: Absolute path to the file (e.g. C:\\parts\\bracket.step)
            read_only: If True, open in read-only mode (safer for analysis)

        Returns a dict with:
            success (bool)
            document_path (str): canonical path of the opened document
            document_type (str): "part", "assembly", or "drawing"
            is_sheet_metal (bool): whether the part has a SheetMetal feature
            errors (list[str]): any error messages from SolidWorks
            warnings (list[str]): any warning messages from SolidWorks
            error (str): present only if the overall operation failed
        """
        from solidworks_mcp.exceptions import SolidWorksConnectionError
        from solidworks_mcp.solidworks_bridge import DOC_TYPE_NAMES

        try:
            bridge.ensure_connected()
        except SolidWorksConnectionError as exc:
            return {"success": False, "error": str(exc)}

        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            return {
                "success": False,
                "error": f"File not found: {abs_path}",
            }

        ext = Path(abs_path).suffix.lower()
        is_import = ext in _IMPORT_EXTENSIONS

        try:
            import pythoncom
            import win32com.client

            # CRITICAL: errors/warnings are by-reference COM output parameters
            # and MUST be VARIANT objects, not plain Python ints.
            errors = win32com.client.VARIANT(
                pythoncom.VT_BYREF | pythoncom.VT_I4, 0
            )
            warnings = win32com.client.VARIANT(
                pythoncom.VT_BYREF | pythoncom.VT_I4, 0
            )

            if is_import:
                # Route foreign formats through the import pipeline.
                # GetImportFileData returns a translator-specific IImport*Data
                # object (or None if the STEP/IGES translator add-in is missing).
                import_data = bridge.app.GetImportFileData(abs_path)
                if import_data is None:
                    return {
                        "success": False,
                        "error": (
                            f"SolidWorks could not create import data for '{abs_path}'. "
                            "The translator for this format is not installed or not "
                            "licensed. Check Tools → Add-Ins for the relevant "
                            "translator (e.g. 'STEP/IGES/ACIS Translators')."
                        ),
                    }

                arg_string = "r" if read_only else ""
                # LoadFile4 gen_py signature: Errors is (16387, 3) =
                # VT_BYREF|VT_I4 in/out. With typed wrappers, bypass the
                # generated method and invoke the raw oleobj directly,
                # which handles by-ref ints cleanly.
                try:
                    raw_app = bridge.app._oleobj_
                except AttributeError:
                    raw_app = bridge.app
                # DISPID 227 is LoadFile4 (from gen_py wrapper).
                result = raw_app.InvokeTypes(
                    227, 0, 1, (9, 0),
                    ((8, 1), (8, 1), (9, 1), (16387, 3)),
                    abs_path, arg_string, import_data, 0,
                )
                # Result is (dispatch_or_none, errors_out)
                if isinstance(result, tuple):
                    loaded, errors_out = result[0], result[1]
                else:
                    loaded, errors_out = result, 0
                errors.value = int(errors_out) if errors_out else 0
                # Use ActiveDoc for further work — this is the canonical
                # route to the loaded document and is properly typed.
                doc = bridge.app.ActiveDoc if loaded is not None else None
            else:
                doc_type = _EXTENSION_TO_DOC_TYPE.get(ext, 1)
                options = 1 if read_only else 0  # swOpenDocOptions_ReadOnly
                doc = bridge.app.OpenDoc6(
                    abs_path,
                    doc_type,
                    options,
                    "",   # configuration name (empty = default)
                    errors,
                    warnings,
                )

            if doc is None:
                err_code = int(errors.value) if errors.value else 0
                err_msgs = _decode_open_errors(err_code)
                hint = (
                    " (Import format — ensure the STEP/IGES/ACIS translator "
                    "add-in is enabled in Tools → Add-Ins.)"
                    if is_import else ""
                )
                return {
                    "success": False,
                    "error": (
                        f"SolidWorks returned null document "
                        f"(error code: {err_code:#010x})."
                        f"{hint}"
                    ),
                    "errors": err_msgs,
                    "error_code": err_code,
                }


            doc_type_actual = _com_call(doc, "GetType")
            doc_type_name = DOC_TYPE_NAMES.get(doc_type_actual, "unknown")
            doc_path = _com_call(doc, "GetPathName")

            is_sm = False
            if doc_type_actual == 1:  # Part
                is_sm = bridge.find_sheet_metal_feature(doc) is not None

            err_msgs = _decode_open_errors(int(errors.value) if errors.value else 0)
            warn_msgs = _decode_open_warnings(int(warnings.value) if warnings.value else 0)

            logger.info(
                "open_file: opened '%s' as %s (sheet_metal=%s)",
                doc_path,
                doc_type_name,
                is_sm,
            )

            return {
                "success": True,
                "document_path": doc_path,
                "document_type": doc_type_name,
                "is_sheet_metal": is_sm,
                "errors": err_msgs,
                "warnings": warn_msgs,
            }

        except Exception as exc:
            logger.exception("open_file failed for '%s'", abs_path)
            return {"success": False, "error": str(exc)}

    @mcp.tool()
    def close_file(save: bool = False) -> dict:
        """
        Close the currently active document in SolidWorks.

        Use this tool after finishing analysis to free resources,
        or before opening a different file.

        Args:
            save: If True, save the document before closing.
                  Use False (default) for analysis-only workflows.

        Returns a dict with:
            success (bool)
            closed_document (str): path of the document that was closed
            error (str): present only on failure
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            doc_path = _com_call(doc, "GetPathName")

            if save:
                doc.Save3(1, 0, 0)
                logger.info("close_file: saved '%s'", doc_path)

            bridge.app.CloseDoc(doc_path)
            logger.info("close_file: closed '%s'", doc_path)
            return {"success": True, "closed_document": doc_path}

        except DocumentNotOpenError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("close_file error")
            return {"success": False, "error": str(exc)}

    @mcp.tool()
    def save_file(output_path: str | None = None) -> dict:
        """
        Save the active document.

        If output_path is None, saves in-place (overwrites the original file).
        If output_path is given, performs a Save As to the specified path.
        Supported Save As formats: SLDPRT, STEP, STL, DXF, PDF (by extension).

        Args:
            output_path: Optional absolute path for Save As.
                         Leave null to save in place.

        Returns a dict with:
            success (bool)
            saved_path (str): the path where the file was saved
            error (str): present only on failure
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()

            if output_path is None:
                doc.Save3(1, 0, 0)
                saved = _com_call(doc, "GetPathName")
            else:
                abs_out = os.path.abspath(output_path)
                Path(abs_out).parent.mkdir(parents=True, exist_ok=True)
                doc.Extension.SaveAs3(abs_out, 0, 1, None, None, 0, 0)
                saved = abs_out

            logger.info("save_file: saved to '%s'", saved)
            return {"success": True, "saved_path": saved}

        except DocumentNotOpenError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("save_file error")
            return {"success": False, "error": str(exc)}

    @mcp.tool()
    def list_open_documents() -> dict:
        """
        List all documents currently open in SolidWorks.

        Use this tool when:
        - Checking which files are loaded before opening another
        - Finding the path of a file that is already open

        Returns a dict with:
            documents (list[dict]): each item has 'path' and 'type'
            count (int): total number of open documents
            error (str): present only on failure
        """
        from solidworks_mcp.exceptions import SolidWorksConnectionError
        from solidworks_mcp.solidworks_bridge import DOC_TYPE_NAMES

        try:
            bridge.ensure_connected()
        except SolidWorksConnectionError as exc:
            return {"documents": [], "count": 0, "error": str(exc)}

        try:
            result = []
            doc = bridge.app.GetFirstDocument()
            while doc is not None:
                path = _com_call(doc, "GetPathName")
                doc_type = _com_call(doc, "GetType")
                result.append({
                    "path": path,
                    "type": DOC_TYPE_NAMES.get(doc_type, "unknown"),
                })
                doc = _com_call(doc, "GetNext")

            return {"documents": result, "count": len(result)}

        except Exception as exc:
            logger.error("list_open_documents error: %s", exc)
            return {"documents": [], "count": 0, "error": str(exc)}


def _decode_open_errors(code: int) -> list[str]:
    """
    Translate a SolidWorks swFileLoadError_e bitmask to human-readable strings.

    Values are taken from the SolidWorks API reference; unknown bits are
    still reported so we don't silently drop diagnostic info.
    """
    if code == 0:
        return []
    # Known swFileLoadError_e bits.
    flags = {
        1: "Generic error",
        2: "File not found",
        4: "ID match error",
        8: "Bad parameter error",
        16: "Already open with another name",
        32: "Future version — newer than this SolidWorks installation",
        64: "Cannot convert (import/translator failure)",
        128: "Sheet metal conversion failed during import",
        0x10000: "File with same title already open",
        0x20000: "Low-resource error",
        0x40000: "Application busy",
        0x80000: "Liquid machine file error",
        0x100000: "Critical data repair",
        0x200000: "Critical data repair required, or invalid file type for this open path",
        0x400000: "File requires repair tool",
    }
    messages = [msg for bit, msg in flags.items() if code & bit]
    # Surface any leftover bits so unexpected errors are still visible.
    known_mask = 0
    for bit in flags:
        known_mask |= bit
    leftover = code & ~known_mask
    if leftover:
        messages.append(f"Unknown error bits: {leftover:#010x}")
    if not messages:
        messages.append(f"Unrecognised error code: {code:#010x}")
    return messages


def _decode_open_warnings(code: int) -> list[str]:
    """Translate SolidWorks OpenDoc warning bitmask to human-readable strings."""
    messages = []
    flags = {
        1: "File was converted from an older version",
        2: "Referenced components not found (assembly)",
        4: "Some features suppressed during open",
        8: "File geometry imported with some loss",
        16: "Lightweight components loaded (assembly)",
    }
    for bit, msg in flags.items():
        if code & bit:
            messages.append(msg)
    return messages
