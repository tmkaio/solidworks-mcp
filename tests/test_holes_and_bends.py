"""
Tests for hole and bend extraction.

These are the two analyses the tool actually sells: hole diameters drive
punch selection, bend angle/radius drive press brake tooling. All of it runs
against mocked COM objects, so no SolidWorks is needed.

SolidWorks reports lengths in metres and angles in radians; every assertion
below pins the conversion to mm/degrees.
"""

import math

from solidworks_mcp.tools.analysis import (
    _collect_bends,
    _collect_holes,
    _extract_bend_info,
    _extract_hole_info,
)
from tests.com_doubles import FakeCom, chain, feature, get_tool

M_TO_MM = 1000.0


def hole_feature(type_name="HoleWizard5", *, name=None, diameter_m=0.006, **definition):
    """A hole feature carrying an IHoleWzdData-ish definition."""
    fields = {"Diameter": diameter_m, **definition}
    return feature(type_name, name=name, definition=FakeCom(**fields))


# ---------------------------------------------------------------------------
# _extract_hole_info
# ---------------------------------------------------------------------------


def test_hole_diameter_converts_metres_to_mm():
    feat = hole_feature(diameter_m=0.006, name="Ø6 Hole")
    info = _extract_hole_info(feat, feat.GetDefinition, M_TO_MM)

    assert info["id"] == "Ø6 Hole"
    assert info["diameter_mm"] == 6.0


def test_through_hole_reports_through_rather_than_a_depth():
    feat = hole_feature(diameter_m=0.008, IsThrough=True, Depth=0.002)
    info = _extract_hole_info(feat, feat.GetDefinition, M_TO_MM)

    assert info["type"] == "through"
    assert info["depth_mm"] == "through"


def test_blind_hole_reports_its_depth_in_mm():
    feat = hole_feature(diameter_m=0.008, IsThrough=False, Depth=0.0125)
    info = _extract_hole_info(feat, feat.GetDefinition, M_TO_MM)

    assert info["type"] == "blind"
    assert info["depth_mm"] == 12.5


def test_hole_without_depth_is_treated_as_through():
    """No Depth and no IsThrough is how a through hole often presents."""
    feat = hole_feature(diameter_m=0.006)  # neither Depth nor IsThrough
    info = _extract_hole_info(feat, feat.GetDefinition, M_TO_MM)

    assert info["type"] == "through"


def test_hole_without_a_diameter_is_dropped():
    """A feature we cannot size is not a hole we can report on."""
    feat = feature("HoleWizard5", definition=FakeCom(Depth=0.01))
    assert _extract_hole_info(feat, feat.GetDefinition, M_TO_MM) is None


# ---------------------------------------------------------------------------
# _collect_holes
# ---------------------------------------------------------------------------


class _Bridge:
    """Minimal bridge exposing only what _collect_holes uses."""

    def __init__(self, features):
        self._features = features

    def iter_features(self, doc):
        return iter(self._features)


def test_collect_holes_ignores_non_hole_features():
    features = [
        feature("Extrusion"),
        hole_feature("HoleWizard5", diameter_m=0.006),
        feature("Fillet"),
        hole_feature("SimpleHole", diameter_m=0.010),
        feature("SheetMetal"),
    ]

    holes = _collect_holes(object(), _Bridge(features), M_TO_MM)

    assert [h["diameter_mm"] for h in holes] == [6.0, 10.0]


def test_collect_holes_skips_features_with_no_definition():
    features = [
        feature("HoleWizard5", definition=None),
        hole_feature("Hole", diameter_m=0.005),
    ]

    holes = _collect_holes(object(), _Bridge(features), M_TO_MM)

    assert [h["diameter_mm"] for h in holes] == [5.0]


# ---------------------------------------------------------------------------
# analyze_holes end to end
# ---------------------------------------------------------------------------


def test_analyze_holes_groups_by_diameter(analysis_tools):
    """The grouping that drives punch selection: 4x Ø6, 2x Ø12."""
    mcp, _bridge, doc = analysis_tools
    doc.FirstFeature = chain(
        hole_feature(name="H1", diameter_m=0.006),
        hole_feature(name="H2", diameter_m=0.006),
        feature("Extrusion"),
        hole_feature(name="H3", diameter_m=0.006),
        hole_feature(name="H4", diameter_m=0.006),
        hole_feature(name="H5", diameter_m=0.012),
        hole_feature(name="H6", diameter_m=0.012),
    )

    result = get_tool(mcp, "analyze_holes")()

    assert result["total_holes"] == 6
    assert result["by_diameter"] == {"6.0": 4, "12.0": 2}


def test_analyze_holes_on_a_part_with_none(analysis_tools):
    mcp, _bridge, doc = analysis_tools
    doc.FirstFeature = chain(feature("Extrusion"), feature("Fillet"))

    result = get_tool(mcp, "analyze_holes")()

    assert result["total_holes"] == 0
    assert result["by_diameter"] == {}


def test_analyze_holes_requires_a_connection():
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge
    from solidworks_mcp.tools.analysis import register

    mcp = FastMCP("test")
    register(mcp, SolidWorksBridge())

    assert "error" in get_tool(mcp, "analyze_holes")()


# ---------------------------------------------------------------------------
# _extract_bend_info
# ---------------------------------------------------------------------------


def bend_feature(type_name="OneBend", *, name=None, **definition):
    return feature(type_name, name=name, definition=FakeCom(**definition))


def test_bend_angle_converts_radians_to_degrees():
    feat = bend_feature(BendAngle=math.pi / 2, BendRadius=0.002)
    info = _extract_bend_info(feat, M_TO_MM)

    assert info["angle_deg"] == 90.0
    assert info["radius_mm"] == 2.0


def test_bend_reports_length_in_mm():
    feat = bend_feature(BendAngle=math.radians(45), BendRadius=0.003, Length=0.080)
    info = _extract_bend_info(feat, M_TO_MM)

    assert info["angle_deg"] == 45.0
    assert info["length_mm"] == 80.0


def test_bend_k_factor_defaults_when_solidworks_does_not_supply_one():
    feat = bend_feature(BendAngle=math.pi / 2, BendRadius=0.002)
    assert _extract_bend_info(feat, M_TO_MM)["k_factor"] == 0.44


def test_bend_k_factor_is_used_when_present():
    feat = bend_feature(BendAngle=math.pi / 2, BendRadius=0.002, KFactor=0.33)
    assert _extract_bend_info(feat, M_TO_MM)["k_factor"] == 0.33


def test_bend_with_radius_but_no_angle_still_reports():
    """A flattened bend can lose its angle; the radius still matters."""
    feat = bend_feature(BendRadius=0.0015)
    info = _extract_bend_info(feat, M_TO_MM)

    assert info["radius_mm"] == 1.5
    assert info["angle_deg"] == 0.0


def test_bend_with_neither_radius_nor_angle_is_dropped():
    feat = bend_feature(Length=0.050)
    assert _extract_bend_info(feat, M_TO_MM) is None


def test_bend_without_a_definition_is_dropped():
    assert _extract_bend_info(feature("OneBend", definition=None), M_TO_MM) is None


# ---------------------------------------------------------------------------
# _collect_bends
# ---------------------------------------------------------------------------


def test_collect_bends_finds_every_recognised_bend_type():
    doc = FakeCom(
        FirstFeature=chain(
            bend_feature("EdgeFlange", name="B1", BendAngle=math.pi / 2, BendRadius=0.002),
            feature("Extrusion"),
            bend_feature("SketchedBend", name="B2", BendAngle=math.pi / 2, BendRadius=0.002),
            bend_feature("SMMiteredFlange", name="B3", BendAngle=math.pi / 4, BendRadius=0.003),
        )
    )

    bends = _collect_bends(doc, None, M_TO_MM)

    assert [b["id"] for b in bends] == ["B1", "B2", "B3"]
    assert [b["angle_deg"] for b in bends] == [90.0, 90.0, 45.0]


def test_collect_bends_descends_into_sub_features():
    """Conversion-created bends hang off a parent feature, not the top chain."""
    nested = bend_feature("OneBend", name="Bend1", BendAngle=math.pi / 2, BendRadius=0.002)
    nested.GetNextFeature = None
    parent = feature("SheetMetal", name="Sheet-Metal1", sub_feature=nested)

    bends = _collect_bends(FakeCom(FirstFeature=chain(parent)), None, M_TO_MM)

    assert [b["id"] for b in bends] == ["Bend1"]


def test_collect_bends_dedupes_when_traversal_loops_back():
    """
    Sub-feature traversal can re-enter the top-level chain. Without the
    name-based guard the same bend is counted twice.
    """
    shared = bend_feature("OneBend", name="Bend1", BendAngle=math.pi / 2, BendRadius=0.002)
    parent = feature("SheetMetal", name="Sheet-Metal1", sub_feature=shared)
    parent.GetNextFeature = shared  # sub-feature is also the next sibling
    shared.GetNextFeature = None

    bends = _collect_bends(FakeCom(FirstFeature=parent), None, M_TO_MM)

    assert [b["id"] for b in bends] == ["Bend1"]


def test_collect_bends_on_a_part_with_none():
    doc = FakeCom(FirstFeature=chain(feature("Extrusion"), feature("Fillet")))
    assert _collect_bends(doc, None, M_TO_MM) == []


# ---------------------------------------------------------------------------
# analyze_bends end to end
# ---------------------------------------------------------------------------


def test_analyze_bends_rejects_a_part_that_is_not_sheet_metal(analysis_tools):
    mcp, _bridge, doc = analysis_tools
    doc.FirstFeature = chain(feature("Extrusion"), feature("Fillet"))

    result = get_tool(mcp, "analyze_bends")()

    assert "error" in result
    assert "convert_to_sheet_metal" in result["error"]


def test_analyze_bends_reports_each_bend(analysis_tools):
    mcp, _bridge, doc = analysis_tools
    doc.FirstFeature = chain(
        feature("SheetMetal", name="Sheet-Metal1"),
        bend_feature("OneBend", name="Bend1", BendAngle=math.pi / 2, BendRadius=0.002),
        bend_feature("OneBend", name="Bend2", BendAngle=math.radians(45), BendRadius=0.003),
    )

    result = get_tool(mcp, "analyze_bends")()

    assert result["total_bends"] == 2
    assert [b["angle_deg"] for b in result["bends"]] == [90.0, 45.0]
    assert [b["radius_mm"] for b in result["bends"]] == [2.0, 3.0]
