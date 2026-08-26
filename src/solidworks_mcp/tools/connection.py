"""
Connection and status tools for SolidWorks MCP.

Tools in this module:
    solidworks_connect     — Connect to a running SolidWorks instance
    solidworks_status      — Query connection state and active document
    solidworks_disconnect  — Release COM references (does not close SW)
"""

import logging
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import _com_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all connection tools with the FastMCP instance."""

    @mcp.tool()
    def solidworks_connect() -> dict:
        """
        Connect to a running SolidWorks instance (or start a new one).

        Call this before using any other SolidWorks tool.
        If SolidWorks is already open, this reuses the existing session.
        If not open, it launches a new SolidWorks process.

        Use this tool when:
        - Starting a new session
        - Connection was lost and tools are returning "not connected" errors

        Returns a dict with:
            connected (bool): whether connection succeeded
            version (str): SolidWorks revision string, e.g. "30.4.0" for 2022 SP4
            is_new_instance (bool): True if SolidWorks was launched fresh
            error (str): present only on failure
        """
        try:
            result = bridge.connect()
            logger.info("solidworks_connect: connected, version=%s", result["version"])
            return {
                "connected": True,
                "version": result["version"],
                "is_new_instance": result["is_new_instance"],
            }
        except Exception as exc:
            logger.error("solidworks_connect failed: %s", exc)
            return {"connected": False, "error": str(exc)}

    @mcp.tool()
    def solidworks_status() -> dict:
        """
        Return the current state of the SolidWorks connection and active document.

        Use this tool when:
        - Checking whether SolidWorks is connected before starting analysis
        - Verifying which file is currently open
        - Confirming document type (part / assembly / drawing)
        - Checking if the active part is a sheet metal part

        Returns a dict with:
            connected (bool)
            version (str): SolidWorks revision (if connected)
            active_document (str | null): full path of active document
            document_type (str | null): "part", "assembly", "drawing", or null
            is_sheet_metal (bool | null): true if active part is sheet metal
            documents_open (list[str]): paths of all open documents
        """
        if not bridge.is_connected():
            return {
                "connected": False,
                "version": None,
                "active_document": None,
                "document_type": None,
                "is_sheet_metal": None,
                "documents_open": [],
            }

        try:
            from solidworks_mcp.solidworks_bridge import DOC_TYPE_NAMES

            version = bridge.get_version()
            docs_open = bridge.get_open_documents()

            active_path: str | None = None
            doc_type_name: str | None = None
            is_sm: bool | None = None

            try:
                doc = bridge.app.ActiveDoc
                if doc is not None:
                    active_path = _com_call(doc, "GetPathName") or None
                    doc_type = _com_call(doc, "GetType")
                    doc_type_name = DOC_TYPE_NAMES.get(doc_type)
                    if doc_type == 1:  # Part
                        is_sm = bridge.find_sheet_metal_feature(doc) is not None
            except Exception as exc:
                logger.warning("Could not read active document info: %s", exc)

            return {
                "connected": True,
                "version": version,
                "active_document": active_path,
                "document_type": doc_type_name,
                "is_sheet_metal": is_sm,
                "documents_open": docs_open,
            }
        except Exception as exc:
            logger.error("solidworks_status error: %s", exc)
            return {"connected": True, "error": str(exc)}

    @mcp.tool()
    def solidworks_disconnect() -> dict:
        """
        Release COM references to SolidWorks without closing the application.

        Use this tool when you are done with all analysis tasks and want to
        free COM resources. SolidWorks itself remains open.

        Returns a dict with:
            disconnected (bool): always True on success
        """
        try:
            bridge.disconnect()
            logger.info("solidworks_disconnect: released COM references")
            return {"disconnected": True}
        except Exception as exc:
            logger.error("solidworks_disconnect error: %s", exc)
            return {"disconnected": False, "error": str(exc)}
