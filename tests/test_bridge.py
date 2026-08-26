"""
Tests for solidworks_bridge.py.

These tests mock the COM layer so they run on any machine without
SolidWorks installed.
"""

from unittest.mock import MagicMock, patch

import pytest

from solidworks_mcp.exceptions import (
    AnalysisError,
    DocumentNotOpenError,
    DocumentTypeError,
    SolidWorksConnectionError,
    SolidWorksNotRunningError,
)
from solidworks_mcp.solidworks_bridge import (
    DOC_ASSEMBLY,
    DOC_PART,
    KG_TO_G,
    M2_TO_MM2,
    M3_TO_MM3,
    M_TO_MM,
    SolidWorksBridge,
)


@pytest.fixture
def bridge():
    return SolidWorksBridge()


@pytest.fixture
def connected_bridge():
    """A bridge with a mocked COM app object."""
    b = SolidWorksBridge()
    mock_app = MagicMock()
    mock_app.RevisionNumber.return_value = "30.4.0"
    mock_app.ActiveDoc = None
    b._app = mock_app
    b._connected = True
    return b, mock_app


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


def test_connect_raises_when_solidworks_not_running():
    b = SolidWorksBridge()
    with (
        patch("pythoncom.CoInitialize"),
        patch("win32com.client.GetActiveObject", side_effect=Exception("no SW")),
        patch("win32com.client.Dispatch", side_effect=Exception("cant launch")),
    ):
        with pytest.raises(SolidWorksNotRunningError):
            b.connect()


def test_connect_reuses_existing_instance():
    b = SolidWorksBridge()
    mock_app = MagicMock()
    mock_app.RevisionNumber.return_value = "30.4.0"
    with (
        patch("pythoncom.CoInitialize"),
        patch("win32com.client.GetActiveObject", return_value=mock_app),
    ):
        result = b.connect()
    assert result["connected"] is True
    assert result["version"] == "30.4.0"
    assert result["is_new_instance"] is False


def test_connect_launches_new_instance_when_none_running():
    b = SolidWorksBridge()
    mock_app = MagicMock()
    mock_app.RevisionNumber.return_value = "30.4.0"
    with (
        patch("pythoncom.CoInitialize"),
        patch("win32com.client.GetActiveObject", side_effect=Exception("no existing")),
        patch("win32com.client.Dispatch", return_value=mock_app),
    ):
        result = b.connect()
    assert result["is_new_instance"] is True


def test_is_connected_false_when_not_initialized():
    b = SolidWorksBridge()
    assert b.is_connected() is False


def test_is_connected_false_after_disconnect(connected_bridge):
    b, mock_app = connected_bridge
    with patch("pythoncom.CoUninitialize"):
        b.disconnect()
    assert b.is_connected() is False


def test_ensure_connected_raises_when_not_connected():
    b = SolidWorksBridge()
    with pytest.raises(SolidWorksConnectionError):
        b.ensure_connected()


# ---------------------------------------------------------------------------
# Active document tests
# ---------------------------------------------------------------------------


def test_get_active_doc_raises_when_none(connected_bridge):
    b, mock_app = connected_bridge
    mock_app.ActiveDoc = None
    with pytest.raises(DocumentNotOpenError):
        b.get_active_doc()


def test_get_active_doc_returns_doc(connected_bridge):
    b, mock_app = connected_bridge
    mock_doc = MagicMock()
    mock_doc.GetType.return_value = DOC_PART
    mock_app.ActiveDoc = mock_doc
    doc = b.get_active_doc()
    assert doc is mock_doc


def test_get_active_doc_raises_wrong_type(connected_bridge):
    b, mock_app = connected_bridge
    mock_doc = MagicMock()
    mock_doc.GetType.return_value = DOC_ASSEMBLY
    mock_app.ActiveDoc = mock_doc
    with pytest.raises(DocumentTypeError):
        b.get_active_doc(require_type=DOC_PART)


# ---------------------------------------------------------------------------
# Mass properties tests
# ---------------------------------------------------------------------------


def test_get_mass_properties_raises_when_none(connected_bridge):
    b, _ = connected_bridge
    mock_doc = MagicMock()
    # Attributes are assigned directly (not via .return_value) because
    # _com_call() returns a non-method attribute as-is — a MagicMock child
    # is not a types.MethodType, so it is never invoked.
    mock_doc.Extension.CreateMassProperty = None
    with pytest.raises(AnalysisError):
        b.get_mass_properties(mock_doc)


def test_get_mass_properties_converts_units(connected_bridge):
    b, _ = connected_bridge
    mp = MagicMock()
    mp.CenterOfMass = [0.050, 0.0, 0.0]  # cx = 50 mm
    mp.Mass = 0.500                      # 500 g
    mp.Volume = 1e-5                     # 10 000 mm³
    mp.SurfaceArea = 0.01                # 10 000 mm²

    mock_doc = MagicMock()
    mock_doc.Extension.CreateMassProperty = mp
    result = b.get_mass_properties(mock_doc)

    assert abs(result["center_of_mass_mm"][0] - 50.0) < 1e-6
    assert abs(result["mass_g"] - 500.0) < 1e-6
    assert abs(result["volume_mm3"] - 10000.0) < 1e-6
    assert abs(result["surface_area_mm2"] - 10000.0) < 1e-6


def test_get_mass_properties_survives_bad_center_of_mass(connected_bridge):
    """A COM error reading CenterOfMass degrades to the origin, not a crash."""
    b, _ = connected_bridge
    mp = MagicMock()
    type(mp).CenterOfMass = property(lambda self: (_ for _ in ()).throw(Exception("COM")))
    mp.Mass = 0.100
    mp.Volume = 0.0
    mp.SurfaceArea = 0.0

    mock_doc = MagicMock()
    mock_doc.Extension.CreateMassProperty = mp
    result = b.get_mass_properties(mock_doc)

    assert result["center_of_mass_mm"] == [0.0, 0.0, 0.0]
    assert abs(result["mass_g"] - 100.0) < 1e-6


# ---------------------------------------------------------------------------
# Bounding box tests
# ---------------------------------------------------------------------------


def test_get_bounding_box_converts_units(connected_bridge):
    b, _ = connected_bridge
    mock_doc = MagicMock()
    mock_doc.GetPartBox.return_value = [0.0, 0.0, 0.0, 0.100, 0.050, 0.002]
    result = b.get_bounding_box(mock_doc)
    assert result["dimensions_mm"] == pytest.approx([100.0, 50.0, 2.0], abs=1e-4)


# ---------------------------------------------------------------------------
# Sheet metal feature detection
# ---------------------------------------------------------------------------


def _feature(type_name, next_feature=None, name=None):
    """Build a mock IFeature. Values are set as plain attributes: see the
    note in test_get_mass_properties_raises_when_none."""
    feat = MagicMock()
    feat.GetTypeName2 = type_name
    feat.GetNextFeature = next_feature
    if name is not None:
        feat.Name = name
    return feat


def test_find_sheet_metal_feature_found(connected_bridge):
    b, _ = connected_bridge
    sm_feat = _feature("SheetMetal", name="Sheet-Metal1")
    other_feat = _feature("Extrusion", next_feature=sm_feat)

    mock_doc = MagicMock()
    mock_doc.FirstFeature = other_feat

    found = b.find_sheet_metal_feature(mock_doc)
    assert found is sm_feat


def test_find_sheet_metal_feature_not_found(connected_bridge):
    b, _ = connected_bridge
    mock_doc = MagicMock()
    mock_doc.FirstFeature = _feature("Extrusion")

    found = b.find_sheet_metal_feature(mock_doc)
    assert found is None


def test_iter_features_walks_the_whole_chain(connected_bridge):
    b, _ = connected_bridge
    third = _feature("Fillet")
    second = _feature("Extrusion", next_feature=third)
    first = _feature("RefPlane", next_feature=second)

    mock_doc = MagicMock()
    mock_doc.FirstFeature = first

    assert list(b.iter_features(mock_doc)) == [first, second, third]


# ---------------------------------------------------------------------------
# Unit conversion sanity
# ---------------------------------------------------------------------------


def test_unit_conversion_constants():
    assert M_TO_MM == 1000.0
    assert M3_TO_MM3 == 1e9
    assert M2_TO_MM2 == 1e6
    assert KG_TO_G == 1000.0
