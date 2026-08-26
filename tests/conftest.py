"""
Shared pytest fixtures.

COM test doubles live in tests/com_doubles.py — see the module docstring
there for why a MagicMock is the wrong shape for a _com_call target.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def bridge_with_part():
    """
    A connected bridge whose active document is a part.

    Returns (bridge, doc). Attach a feature chain with:
        doc.FirstFeature = chain(feature(...), feature(...))
    """
    from solidworks_mcp.solidworks_bridge import DOC_PART, SolidWorksBridge

    doc = MagicMock()
    doc.GetType = DOC_PART
    doc.FirstFeature = None

    b = SolidWorksBridge()
    b._app = MagicMock()
    b._app.ActiveDoc = doc
    b._connected = True
    return b, doc


@pytest.fixture
def analysis_tools(bridge_with_part):
    """Register the analysis tool module against bridge_with_part."""
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.tools.analysis import register

    b, doc = bridge_with_part
    mcp = FastMCP("test")
    register(mcp, b)
    return mcp, b, doc
