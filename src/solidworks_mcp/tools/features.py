"""
Feature management tools for SolidWorks MCP.

Tools in this module:
    list_features            — List all features in the FeatureManager tree
    get_feature_info         — Details about a specific feature by name
    suppress_feature         — Suppress (hide/disable) a feature
    unsuppress_feature       — Unsuppress (restore) a feature
    get_feature_dimensions   — List all dimensions associated with a feature
    rebuild_model            — Force a full rebuild of the active document
    get_feature_error        — Check if a feature has a rebuild error

The FeatureManager tree is accessed via IModelDoc2.FirstFeature() /
IFeature.GetNextFeature().  Each IFeature exposes:
    Name, GetTypeName2(), IsSuppressed2(), SetSuppression2(),
    GetDefinition(), GetDimensions2() for parametric features.

Suppression constants (swFeatureSuppressionAction_e):
    0 = swSuppressFeature
    1 = swUnSuppressFeature
    2 = swUnSuppressDependent (unsuppress + children)

Configuration options (swInConfigurationOpts_e):
    2 = swSpecifyConfiguration (apply to named config)
    1 = swAllConfiguration
"""

import logging
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import _com_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)

M_TO_MM = 1_000.0
RAD_TO_DEG = 57.295779513


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all feature management tools with the FastMCP instance."""

    @mcp.tool()
    def list_features(
        include_suppressed: bool = True,
        feature_type_filter: str = "",
    ) -> dict:
        """
        List all features in the FeatureManager design tree.

        Use to understand part complexity, find feature names for suppression,
        or audit what operations were applied to an imported solid.

        Args:
            include_suppressed: If False, skip suppressed features.
            feature_type_filter: Optionally filter by type name substring
                (e.g. "Sketch", "Cut", "HoleWizard", "Fillet").
                Case-insensitive. Leave empty to return all features.

        Returns a dict with:
            features (list[dict]): each has name, type, is_suppressed, has_error
            count (int), total (int): total features before filter
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()

            all_features = list(bridge.iter_features(doc))
            result_features = []
            type_filter = feature_type_filter.lower()

            for feat in all_features:
                try:
                    fname = feat.Name
                    ftype = _com_call(feat, "GetTypeName2")
                    suppressed = bool(feat.IsSuppressed2(1, "Default"))  # swAllConfiguration
                    has_error = _com_call(feat, "GetErrorCode2") != 0

                    if not include_suppressed and suppressed:
                        continue
                    if type_filter and type_filter not in ftype.lower():
                        continue

                    result_features.append({
                        "name": fname,
                        "type": ftype,
                        "is_suppressed": suppressed,
                        "has_error": has_error,
                    })
                except Exception as exc:
                    logger.debug("Skipping feature: %s", exc)

            logger.info("list_features: %d/%d features", len(result_features), len(all_features))
            return {
                "features": result_features,
                "count": len(result_features),
                "total": len(all_features),
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("list_features error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_feature_info(feature_name: str) -> dict:
        """
        Get detailed information about a specific feature by name.

        Args:
            feature_name: Exact feature name as it appears in the
                          FeatureManager tree (use list_features to find names).

        Returns a dict with:
            name (str), type (str), is_suppressed (bool), has_error (bool),
            error_description (str), creation_order (int)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()

            feat = doc.FeatureByName(feature_name)
            if feat is None:
                return {
                    "error": f"Feature '{feature_name}' not found. "
                             "Use list_features to see available feature names."
                }

            suppressed = bool(feat.IsSuppressed2(1, "Default"))
            err_code = _com_call(feat, "GetErrorCode2")
            err_desc = feat.GetErrorDescription(err_code) if err_code != 0 else ""

            return {
                "name": feat.Name,
                "type": _com_call(feat, "GetTypeName2"),
                "is_suppressed": suppressed,
                "has_error": err_code != 0,
                "error_code": err_code,
                "error_description": err_desc or "",
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_feature_info error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def suppress_feature(
        feature_name: str,
        config_name: str = "",
    ) -> dict:
        """
        Suppress (disable) a feature in the FeatureManager tree.

        Suppressed features are excluded from the model geometry and mass
        properties.  Use to study variants without deleting features, or
        to isolate a specific feature's contribution to geometry.

        Args:
            feature_name: Feature name to suppress.
            config_name: Configuration to suppress in. Leave empty for
                         the active configuration only.

        Returns a dict with:
            success (bool), feature (str), configuration (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()

            feat = doc.FeatureByName(feature_name)
            if feat is None:
                return {"success": False,
                        "error": f"Feature '{feature_name}' not found"}

            if config_name:
                # swSpecifyConfiguration = 2
                ret = feat.SetSuppression2(0, 2, [config_name])
            else:
                # swThisConfiguration = 0
                ret = feat.SetSuppression2(0, 0, None)

            if not ret:
                return {"success": False,
                        "error": f"SetSuppression2 returned False for '{feature_name}'"}

            _com_call(doc, "EditRebuild3")
            logger.info("suppress_feature: suppressed '%s'", feature_name)
            return {"success": True, "feature": feature_name, "configuration": config_name or "active"}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("suppress_feature error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def unsuppress_feature(
        feature_name: str,
        config_name: str = "",
        unsuppress_children: bool = True,
    ) -> dict:
        """
        Unsuppress (restore) a previously suppressed feature.

        Args:
            feature_name: Feature name to unsuppress.
            config_name: Configuration to unsuppress in. Leave empty for
                         the active configuration.
            unsuppress_children: Also unsuppress child features (default True).

        Returns a dict with:
            success (bool), feature (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()

            feat = doc.FeatureByName(feature_name)
            if feat is None:
                return {"success": False,
                        "error": f"Feature '{feature_name}' not found"}

            # 1=unsuppress, 2=unsuppress+children
            action = 2 if unsuppress_children else 1

            if config_name:
                ret = feat.SetSuppression2(action, 2, [config_name])
            else:
                ret = feat.SetSuppression2(action, 0, None)

            if not ret:
                return {"success": False,
                        "error": f"SetSuppression2 returned False for '{feature_name}'"}

            _com_call(doc, "EditRebuild3")
            logger.info("unsuppress_feature: unsuppressed '%s'", feature_name)
            return {"success": True, "feature": feature_name}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("unsuppress_feature error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_feature_dimensions(feature_name: str) -> dict:
        """
        List all parametric dimensions associated with a named feature.

        Dimensions are the numeric values that drive the feature's geometry
        (e.g. extrude depth, hole diameter, fillet radius).  Use this to
        understand what parameters can be changed, or to read current values.

        Args:
            feature_name: Feature name (from list_features).

        Returns a dict with:
            dimensions (list[dict]): each has name, value, unit, full_name
            count (int)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()

            feat = doc.FeatureByName(feature_name)
            if feat is None:
                return {"error": f"Feature '{feature_name}' not found"}

            dims = []
            disp_dims = feat.GetDisplayDimensions()
            if disp_dims:
                for dd in disp_dims:
                    try:
                        dim = dd.GetDimension2(0)
                        if dim is None:
                            continue
                        val = dim.Value  # in document units (SI = metres/radians)
                        dtype = dim.GetType2()  # 0=linear, 1=radial, 2=angular
                        if dtype == 2:
                            unit = "deg"
                            val = round(val * RAD_TO_DEG, 4)
                        else:
                            unit = "mm"
                            val = round(val * M_TO_MM, 4)
                        dims.append({
                            "name": dim.Name,
                            "full_name": dim.FullName,
                            "value": val,
                            "unit": unit,
                        })
                    except Exception as exc:
                        logger.debug("Skipping dim: %s", exc)

            return {"feature": feature_name, "dimensions": dims, "count": len(dims)}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_feature_dimensions error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def rebuild_model(force: bool = False) -> dict:
        """
        Force a rebuild of the active document.

        Use after suppressing/unsuppressing features, changing properties,
        or when get_part_info shows stale geometry.

        Args:
            force: If True, performs a forced rebuild (Ctrl+Q equivalent)
                   that recalculates all features regardless of rebuild flag.
                   If False (default), standard rebuild (Ctrl+B equivalent).

        Returns a dict with:
            success (bool), errors (int): number of rebuild errors
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()

            if force:
                ok = doc.ForceRebuild3(False)
            else:
                ok = _com_call(doc, "EditRebuild3")

            logger.info("rebuild_model: force=%s ok=%s", force, ok)
            return {"success": bool(ok)}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("rebuild_model error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_feature_error(feature_name: str) -> dict:
        """
        Check whether a feature has a rebuild error and describe it.

        Use to diagnose why a convert_to_sheet_metal or other operation
        failed, or to inspect red items in the FeatureManager tree.

        Args:
            feature_name: Feature name to inspect.

        Returns a dict with:
            has_error (bool), error_code (int), description (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()

            feat = doc.FeatureByName(feature_name)
            if feat is None:
                return {"error": f"Feature '{feature_name}' not found"}

            err_code = _com_call(feat, "GetErrorCode2")
            err_desc = ""
            if err_code != 0:
                try:
                    err_desc = feat.GetErrorDescription(err_code) or ""
                except Exception:
                    err_desc = f"Error code {err_code}"

            return {
                "feature": feature_name,
                "has_error": err_code != 0,
                "error_code": err_code,
                "description": err_desc,
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_feature_error error")
            return {"error": f"Unexpected error: {exc}"}
