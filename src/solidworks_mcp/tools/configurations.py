"""
Configuration management tools for SolidWorks MCP.

Tools in this module:
    list_configurations          — List all configurations in the document
    get_active_configuration     — Get name and properties of the active config
    switch_configuration         — Activate a different configuration
    add_configuration            — Create a new configuration
    delete_configuration         — Remove an existing configuration
    get_configuration_properties — Read config-specific custom properties

SolidWorks configurations are managed via IModelDoc2.ConfigurationManager
(doc.ConfigurationManager).  Each IConfiguration object exposes:
    Name, Comment, IsSuppressed, IsRootMotionEnvelope, SuppressionState, etc.

Design-table-driven configurations are read-only here — edits need the
embedded Excel sheet.  This module handles manually-created configurations.

Suppression state constants (swSuppressionState_e):
    0 = swSuppressed
    1 = swFullyResolved
    2 = swLightweight (assemblies)
"""

import logging
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import _com_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all configuration tools with the FastMCP instance."""

    @mcp.tool()
    def list_configurations() -> dict:
        """
        List all configurations in the active document.

        Parts and assemblies can have multiple configurations representing
        design variants (e.g. different hole patterns, lengths, or suppressed
        features).  Use this to discover which configurations exist before
        switching or querying config-specific properties.

        Returns a dict with:
            configurations (list[dict]): each has name, is_active, description,
                                         suppression_state
            count (int)
            active (str): name of the currently active configuration
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            cfg_mgr = doc.ConfigurationManager
            active_name = cfg_mgr.ActiveConfiguration.Name if cfg_mgr.ActiveConfiguration else ""
            config_names = _com_call(doc, "GetConfigurationNames")
            configs = []
            if config_names:
                for cname in config_names:
                    try:
                        cfg = doc.GetConfigurationByName(cname)
                        configs.append({
                            "name": cname,
                            "is_active": cname == active_name,
                            "description": cfg.Comment if cfg else "",
                            "suppression_state": _suppression_name(
                                cfg.SuppressionState if cfg else -1
                            ),
                        })
                    except Exception as exc:
                        logger.debug("Could not read config '%s': %s", cname, exc)
                        configs.append({"name": cname, "is_active": cname == active_name})

            logger.info("list_configurations: %d configs in '%s'", len(configs), _com_call(doc, "GetTitle"))
            return {"configurations": configs, "count": len(configs), "active": active_name}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("list_configurations error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_active_configuration() -> dict:
        """
        Get detailed information about the currently active configuration.

        Returns a dict with:
            name (str), description (str), suppression_state (str),
            is_design_table (bool): True if controlled by a design table
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            cfg_mgr = doc.ConfigurationManager
            cfg = cfg_mgr.ActiveConfiguration
            if cfg is None:
                return {"error": "No active configuration found"}

            return {
                "name": cfg.Name,
                "description": cfg.Comment or "",
                "suppression_state": _suppression_name(cfg.SuppressionState),
                "is_design_table": bool(cfg_mgr.ActiveConfiguration and
                                        _com_call(doc, "GetConfigurationNames") and
                                        _has_design_table(doc)),
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_active_configuration error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def switch_configuration(config_name: str) -> dict:
        """
        Activate a different configuration in the active document.

        Use when the user wants to analyse or export a specific variant
        (e.g. "switch to the 2mm thickness configuration").

        Args:
            config_name: Exact configuration name (case-sensitive).
                         Use list_configurations to see available names.

        Returns a dict with:
            success (bool), previous (str), active (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            cfg_mgr = doc.ConfigurationManager
            previous = cfg_mgr.ActiveConfiguration.Name if cfg_mgr.ActiveConfiguration else ""

            # ShowConfiguration2 activates a configuration
            ok = doc.ShowConfiguration2(config_name)
            if not ok:
                return {
                    "success": False,
                    "error": (
                        f"Could not activate configuration '{config_name}'. "
                        "Check the exact name with list_configurations."
                    ),
                }
            _com_call(doc, "EditRebuild3")
            logger.info("switch_configuration: '%s' → '%s'", previous, config_name)
            return {"success": True, "previous": previous, "active": config_name}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("switch_configuration error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def add_configuration(
        config_name: str,
        description: str = "",
        copy_from: str = "",
    ) -> dict:
        """
        Create a new configuration in the active document.

        Creates a copy of an existing configuration (or the active one) and
        gives it a new name.  The new configuration starts as an exact copy;
        use SolidWorks to suppress/unsuppress features as needed.

        Args:
            config_name: Name for the new configuration.
            description: Optional description / comment.
            copy_from: Name of the source configuration to copy.
                       Leave empty to copy the currently active configuration.

        Returns a dict with:
            success (bool), name (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()

            # Switch to source config first if specified
            if copy_from:
                ok = doc.ShowConfiguration2(copy_from)
                if not ok:
                    return {"success": False,
                            "error": f"Source configuration '{copy_from}' not found."}

            # AddConfiguration3(name, comment, altName, options)
            # options: 0 = default
            new_cfg = doc.ConfigurationManager.AddConfiguration3(
                config_name, description, "", 0
            )
            if new_cfg is None:
                return {"success": False,
                        "error": f"AddConfiguration3 failed for '{config_name}'."}

            logger.info("add_configuration: created '%s'", config_name)
            return {"success": True, "name": config_name}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("add_configuration error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def delete_configuration(config_name: str) -> dict:
        """
        Delete a configuration from the active document.

        Cannot delete the active configuration or the last remaining one.
        Switch to a different configuration first if needed.

        Args:
            config_name: Name of the configuration to delete.

        Returns a dict with:
            success (bool), deleted (str)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            cfg_mgr = doc.ConfigurationManager

            active_name = cfg_mgr.ActiveConfiguration.Name if cfg_mgr.ActiveConfiguration else ""
            if config_name == active_name:
                return {
                    "success": False,
                    "error": (
                        f"Cannot delete the active configuration '{config_name}'. "
                        "Switch to a different configuration first."
                    ),
                }

            ok = cfg_mgr.DeleteConfiguration(config_name)
            if not ok:
                return {"success": False,
                        "error": f"DeleteConfiguration failed for '{config_name}'."}

            logger.info("delete_configuration: deleted '%s'", config_name)
            return {"success": True, "deleted": config_name}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("delete_configuration error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_configuration_properties(config_name: str = "") -> dict:
        """
        Read custom properties specific to a named configuration.

        Configuration-specific properties shadow (override) document-level ones
        for that configuration.  This is how design variants carry different
        part numbers, revisions, or material specs.

        Args:
            config_name: Configuration to query. Leave empty for the active
                         configuration's specific properties.

        Returns a dict with:
            properties (dict[str, dict]): name → {value, resolved_value, type}
            config (str), count (int)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()

            # Resolve empty string to active config name
            if not config_name:
                cfg_mgr = doc.ConfigurationManager
                config_name = (
                    cfg_mgr.ActiveConfiguration.Name
                    if cfg_mgr.ActiveConfiguration else ""
                )

            mgr = doc.Extension.CustomPropertyManager(config_name)
            props = {}
            names = mgr.GetNames()
            if names:
                for name in names:
                    try:
                        ret = mgr.GetProperty3(name, False)
                        val = ret[0] if ret else ""
                        resolved = ret[1] if ret and len(ret) > 1 else val
                        prop_type = mgr.GetType2(name)
                        props[name] = {
                            "value": str(val),
                            "resolved_value": str(resolved),
                            "type": {1: "text", 2: "date", 3: "number", 4: "yes_no"}.get(
                                prop_type, "unknown"
                            ),
                        }
                    except Exception as exc:
                        logger.debug("Could not read prop '%s': %s", name, exc)
                        props[name] = {"value": "(unreadable)", "type": "unknown"}

            return {"properties": props, "config": config_name, "count": len(props)}

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_configuration_properties error")
            return {"error": f"Unexpected error: {exc}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _suppression_name(code) -> str:
    return {0: "suppressed", 1: "resolved", 2: "lightweight"}.get(code, "unknown")


def _has_design_table(doc) -> bool:
    """Return True if the document has a design table feature."""
    try:
        feat = _com_call(doc, "FirstFeature")
        while feat:
            name = _com_call(feat, "GetTypeName2")
            if name == "DriveWorksTable":
                return True
            # Look for embedded Excel design table
            if "DesignTable" in name or "Design Table" in name:
                return True
            feat = _com_call(feat, "GetNextFeature")
    except Exception:
        pass
    return False
