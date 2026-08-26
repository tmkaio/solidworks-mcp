"""
Tests for analysis tools.

analyze_step_standalone() is tested with the real CadQuery library.
If CadQuery is not installed, those tests are automatically skipped.

All SolidWorks-dependent tests use mocked COM objects and run on any platform.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.com_doubles import chain, feature, get_tool

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_STEP = FIXTURES_DIR / "sample_part.step"

cadquery = pytest.importorskip("cadquery", reason="CadQuery not installed — skipping STEP tests")


def test_analyze_step_standalone_file_not_found():
    """Returns error dict for missing files."""
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge
    from solidworks_mcp.tools.analysis import register

    mcp = FastMCP("test")
    bridge = SolidWorksBridge()
    register(mcp, bridge)

    tool_fn = get_tool(mcp, "analyze_step_standalone")
    result = tool_fn(file_path="C:\\nonexistent\\phantom.step")
    assert "error" in result
    assert "not found" in result["error"].lower()


@pytest.mark.skipif(not SAMPLE_STEP.exists(), reason="Sample STEP fixture not present")
def test_analyze_step_standalone_real_file():
    """Full integration test against the sample STEP fixture."""
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge
    from solidworks_mcp.tools.analysis import register

    mcp = FastMCP("test")
    bridge = SolidWorksBridge()
    register(mcp, bridge)

    tool_fn = get_tool(mcp, "analyze_step_standalone")
    result = tool_fn(file_path=str(SAMPLE_STEP))

    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    assert result["volume_mm3"] > 0
    assert result["surface_area_mm2"] > 0
    assert "dimensions_mm" in result["bounding_box"]
    assert len(result["bounding_box"]["dimensions_mm"]) == 3
    assert result["face_count"] > 0
    assert isinstance(result["is_likely_sheet_metal"], bool)


def test_get_part_info_not_connected():
    """get_part_info returns error dict when bridge is not connected."""
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge
    from solidworks_mcp.tools.analysis import register

    mcp = FastMCP("test")
    bridge = SolidWorksBridge()
    register(mcp, bridge)

    tool_fn = get_tool(mcp, "get_part_info")
    result = tool_fn()
    assert "error" in result


def test_get_bounding_box_not_connected():
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge
    from solidworks_mcp.tools.analysis import register

    mcp = FastMCP("test")
    bridge = SolidWorksBridge()
    register(mcp, bridge)

    tool_fn = get_tool(mcp, "get_bounding_box")
    result = tool_fn()
    assert "error" in result


def test_count_features_by_type_mocked():
    """count_features_by_type correctly groups feature types."""
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import DOC_PART, SolidWorksBridge
    from solidworks_mcp.tools.analysis import register

    mcp = FastMCP("test")
    bridge = SolidWorksBridge()

    mock_doc = MagicMock()
    # Plain attributes, not .return_value: _com_call() hands back any
    # attribute that is not a real method without invoking it.
    mock_doc.GetType = DOC_PART

    mock_doc.FirstFeature = chain(
        feature("Extrusion"),
        feature("Extrusion"),
        feature("HoleWizard5"),
        feature("SheetMetal"),
        feature("EdgeFlange"),
    )

    bridge._app = MagicMock()
    bridge._app.ActiveDoc = mock_doc
    bridge._connected = True

    register(mcp, bridge)
    tool_fn = get_tool(mcp, "count_features_by_type")
    result = tool_fn()

    assert result["total_features"] == 5
    assert result["by_type"]["Extrusion"] == 2
    assert result["by_type"]["HoleWizard5"] == 1
