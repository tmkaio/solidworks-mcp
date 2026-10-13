"""Unit tests for the modeling helpers (no SolidWorks needed)."""

import pytest

from solidworks_mcp.tools.modeling import default_plane, features_of_type, resolve_sketch
from tests.com_doubles import FakeCom, chain, feature


def _doc(*features):
    return FakeCom(FirstFeature=chain(*features))


def _tree():
    return _doc(
        feature("CommentsFolder", name="Comments"),
        feature("RefPlane", name="Plano frontal"),
        feature("RefPlane", name="Plano superior"),
        feature("RefPlane", name="Plano direito"),
        feature("ProfileFeature", name="Sketch1"),
        feature("Extrusion", name="Boss-Extrude1"),
        feature("ProfileFeature", name="Sketch2"),
    )


def test_features_of_type_keeps_tree_order():
    names = [f.Name for f in features_of_type(_tree(), "ProfileFeature")]
    assert names == ["Sketch1", "Sketch2"]


def test_features_of_type_empty_tree():
    assert features_of_type(FakeCom(FirstFeature=None), "RefPlane") == []


@pytest.mark.parametrize("plane,expected", [
    ("front", "Plano frontal"),
    ("Top", "Plano superior"),
    (" right ", "Plano direito"),
])
def test_default_plane_by_position_not_name(plane, expected):
    # localized names: selection must not depend on "Front Plane" text
    assert default_plane(_tree(), plane).Name == expected


def test_default_plane_rejects_unknown_plane():
    with pytest.raises(ValueError):
        default_plane(_tree(), "isometric")


def test_default_plane_requires_three_planes():
    with pytest.raises(ValueError):
        default_plane(_doc(feature("RefPlane"), feature("RefPlane")), "front")


def test_resolve_sketch_last_named_and_missing():
    doc = _tree()
    assert resolve_sketch(doc, "").Name == "Sketch2"
    assert resolve_sketch(doc, "Sketch1").Name == "Sketch1"
    assert resolve_sketch(doc, "Sketch9") is None
    assert resolve_sketch(FakeCom(FirstFeature=None), "") is None
