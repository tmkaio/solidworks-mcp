"""
SolidWorks MCP Server — entry point.

Architecture:
    server.py                ← this file: wires everything together
    solidworks_bridge        ← owns the COM lifecycle singleton
    tools/connection         ← connect/status/disconnect tools
    tools/file_ops           ← open/close/save/list tools
    tools/analysis           ← geometry analysis + standalone STEP analysis
    tools/sheet_metal        ← sheet metal tools (flatten, convert, properties)
    tools/export             ← DXF, STEP, STL, PDF, screenshot export
    tools/properties         ← custom properties + material assignment
    tools/configurations     ← configuration management (add/switch/delete/list)
    tools/measurements       ← distance, entity, face, section properties
    tools/features           ← feature tree management (suppress/unsuppress/list)
    tools/drawings           ← drawing creation and view management
    tools/assemblies         ← assembly BOM, components, mates, mass

Transport: STDIO (required by Claude Desktop MCP protocol).
CRITICAL: Nothing in this file (or any import chain) may write to stdout.
All logging goes to stderr via logging_config.configure_logging().
"""

import os
import sys

# ------------------------------------------------------------------
# Configure logging FIRST — before any other import that might log.
# This ensures nothing touches stdout before MCP protocol starts.
# ------------------------------------------------------------------
from solidworks_mcp.logging_config import configure_logging

configure_logging()

import logging

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Imports (after logging is configured)
# ------------------------------------------------------------------
from mcp.server.fastmcp import FastMCP

from solidworks_mcp.solidworks_bridge import SolidWorksBridge
from solidworks_mcp.tools import (
    analysis,
    assemblies,
    configurations,
    connection,
    drawings,
    export,
    features,
    file_ops,
    measurements,
    properties,
    sheet_metal,
)

# ------------------------------------------------------------------
# Server and bridge setup
# ------------------------------------------------------------------

mcp = FastMCP("solidworks-mcp")

# Single bridge instance shared across all tool modules
bridge = SolidWorksBridge()

# ------------------------------------------------------------------
# Register tool modules
# ------------------------------------------------------------------
connection.register(mcp, bridge)
file_ops.register(mcp, bridge)
analysis.register(mcp, bridge)
sheet_metal.register(mcp, bridge)
export.register(mcp, bridge)
properties.register(mcp, bridge)
configurations.register(mcp, bridge)
measurements.register(mcp, bridge)
features.register(mcp, bridge)
drawings.register(mcp, bridge)
assemblies.register(mcp, bridge)

logger.info(
    "SolidWorks MCP server initialized (PID %d, Python %s)",
    os.getpid(),
    sys.version.split()[0],
)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main() -> None:
    """Run the MCP server on STDIO transport."""
    logger.info("Starting SolidWorks MCP server on stdio transport")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
