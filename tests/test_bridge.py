"""
Tests for solidworks_bridge.py.

These tests mock the COM layer, so none of them need SolidWorks itself.

Most need nothing but the standard library. The exceptions are the
connect()/disconnect() tests: they patch pythoncom and win32com.client by
name, which requires those modules to be importable, and pywin32 has no
Linux wheel. Those carry @requires_pywin32 and skip elsewhere — see the
Development section of the README.
"""

import importlib.util
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
    feature_error_code,
    feature_is_suppressed,
)
from tests.com_doubles import FakeCom, feature

requires_pywin32 = pytest.mark.skipif(
    importlib.util.find_spec("pythoncom") is None,
    reason="pywin32 is Windows-only; these tests patch pythoncom/win32com by name",
)


@pytest.fixture
def bridge():
    return SolidWorksBridge()


@pytest.fixture
def connected_bridge():
    """A bridge with a mocked COM app object."""
    b = SolidWorksBridge()
    mock_app = MagicMock()
    # late-bound pywin32 auto-evaluates RevisionNumber into a str
    mock_app.RevisionNumber = "30.4.0"
    mock_app.ActiveDoc = None
    b._app = mock_app
    b._connected = True
    return b, mock_app


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


@requires_pywin32
def test_connect_raises_when_solidworks_not_running():
    b = SolidWorksBridge()
    with (
        patch("pythoncom.CoInitialize"),
        patch("win32com.client.GetActiveObject", side_effect=Exception("no SW")),
        patch("win32com.client.Dispatch", side_effect=Exception("cant launch")),
        patch(
            "solidworks_mcp.solidworks_bridge._is_solidworks_running",
            return_value=False,
        ),
    ):
        with pytest.raises(SolidWorksNotRunningError):
            b.connect()


@requires_pywin32
def test_connect_reuses_existing_instance():
    b = SolidWorksBridge()
    mock_app = MagicMock()
    # late-bound pywin32 auto-evaluates RevisionNumber into a str
    mock_app.RevisionNumber = "30.4.0"
    with (
        patch("pythoncom.CoInitialize"),
        patch("win32com.client.GetActiveObject", return_value=mock_app),
    ):
        result = b.connect()
    assert result["connected"] is True
    assert result["version"] == "30.4.0"
    assert result["is_new_instance"] is False


@requires_pywin32
def test_connect_launches_new_instance_when_none_running():
    b = SolidWorksBridge()
    mock_app = MagicMock()
    # late-bound pywin32 auto-evaluates RevisionNumber into a str
    mock_app.RevisionNumber = "30.4.0"
    with (
        patch("pythoncom.CoInitialize"),
        patch("win32com.client.GetActiveObject", side_effect=Exception("no existing")),
        patch("win32com.client.Dispatch", return_value=mock_app),
        patch(
            "solidworks_mcp.solidworks_bridge._is_solidworks_running",
            return_value=False,
        ),
    ):
        result = b.connect()
    assert result["is_new_instance"] is True


def test_is_connected_false_when_not_initialized():
    b = SolidWorksBridge()
    assert b.is_connected() is False


@requires_pywin32
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




def test_find_sheet_metal_feature_found(connected_bridge):
    b, _ = connected_bridge
    sm_feat = feature("SheetMetal", name="Sheet-Metal1")
    other_feat = feature("Extrusion", next_feature=sm_feat)

    mock_doc = MagicMock()
    mock_doc.FirstFeature = other_feat

    found = b.find_sheet_metal_feature(mock_doc)
    assert found is sm_feat


def test_find_sheet_metal_feature_not_found(connected_bridge):
    b, _ = connected_bridge
    mock_doc = MagicMock()
    mock_doc.FirstFeature = feature("Extrusion")

    found = b.find_sheet_metal_feature(mock_doc)
    assert found is None


def test_iter_features_walks_the_whole_chain(connected_bridge):
    b, _ = connected_bridge
    third = feature("Fillet")
    second = feature("Extrusion", next_feature=third)
    first = feature("RefPlane", next_feature=second)

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


# ---------------------------------------------------------------------------
# Feature state helpers
# ---------------------------------------------------------------------------


def test_feature_is_suppressed_uses_plain_bool():
    # IsSuppressed2 returns a SafeArray -> (False,), which is truthy; the
    # helper must read the no-argument IsSuppressed instead.
    assert feature_is_suppressed(FakeCom(IsSuppressed=False)) is False
    assert feature_is_suppressed(FakeCom(IsSuppressed=True)) is True


def test_feature_error_code_reads_no_arg_variant():
    assert feature_error_code(FakeCom(GetErrorCode=0)) == 0
    assert feature_error_code(FakeCom(GetErrorCode=26)) == 26
    assert feature_error_code(FakeCom(GetErrorCode=None)) == 0


# ---------------------------------------------------------------------------
# Re-attach after a stale COM reference
# ---------------------------------------------------------------------------


class _StaleApp:
    @property
    def ActiveDoc(self):
        raise Exception("RPC_E_CALL_REJECTED")


@requires_pywin32
def test_is_connected_reattaches_when_reference_goes_stale():
    b = SolidWorksBridge()
    b._app = _StaleApp()
    b._connected = True
    fresh = MagicMock()
    fresh.ActiveDoc = None
    with (
        patch("pythoncom.CoInitialize"),
        patch("win32com.client.GetActiveObject", return_value=fresh),
    ):
        assert b.is_connected() is True
    assert b._app is fresh


@requires_pywin32
def test_is_connected_false_when_reattach_fails():
    b = SolidWorksBridge()
    b._app = _StaleApp()
    b._connected = True
    with (
        patch("pythoncom.CoInitialize"),
        patch("win32com.client.GetActiveObject", side_effect=Exception("gone")),
        patch("time.sleep"),
    ):
        assert b.is_connected() is False
    assert b._connected is False
