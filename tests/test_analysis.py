"""
Tests for analysis tools.

analyze_step_standalone() is tested with the real CadQuery library.
If CadQuery is not installed, those tests are automatically skipped.

All SolidWorks-dependent tests use mocked COM objects and run on any platform.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

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

    tool_fn = _get_tool(mcp, "analyze_step_standalone")
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

    tool_fn = _get_tool(mcp, "analyze_step_standalone")
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

    tool_fn = _get_tool(mcp, "get_part_info")
    result = tool_fn()
    assert "error" in result


def test_get_bounding_box_not_connected():
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge
    from solidworks_mcp.tools.analysis import register

    mcp = FastMCP("test")
    bridge = SolidWorksBridge()
    register(mcp, bridge)

    tool_fn = _get_tool(mcp, "get_bounding_box")
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

    features = [
        _make_feature("Extrusion"),
        _make_feature("Extrusion"),
        _make_feature("HoleWizard5"),
        _make_feature("SheetMetal"),
        _make_feature("EdgeFlange"),
    ]
    for i, f in enumerate(features[:-1]):
        f.GetNextFeature = features[i + 1]
    features[-1].GetNextFeature = None
    mock_doc.FirstFeature = features[0]

    bridge._app = MagicMock()
    bridge._app.ActiveDoc = mock_doc
    bridge._connected = True

    register(mcp, bridge)
    tool_fn = _get_tool(mcp, "count_features_by_type")
    result = tool_fn()

    assert result["total_features"] == 5
    assert result["by_type"]["Extrusion"] == 2
    assert result["by_type"]["HoleWizard5"] == 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_tool(mcp_instance, name: str):
    """Retrieve a registered tool function from a FastMCP instance by name."""
    tools_dict = getattr(mcp_instance, "_tools", None)
    if tools_dict and name in tools_dict:
        fn = tools_dict[name]
        return fn.fn if hasattr(fn, "fn") else fn

    tool_manager = getattr(mcp_instance, "_tool_manager", None)
    if tool_manager:
        mgr_tools = getattr(tool_manager, "_tools", {})
        if name in mgr_tools:
            fn = mgr_tools[name]
            return fn.fn if hasattr(fn, "fn") else fn

    raise KeyError(f"Tool '{name}' not found in FastMCP instance")


def _make_feature(type_name: str) -> MagicMock:
    feat = MagicMock()
    feat.GetTypeName2 = type_name
    feat.Name = type_name + "1"
    return feat
