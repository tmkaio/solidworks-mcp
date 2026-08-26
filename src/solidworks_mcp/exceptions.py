"""
Custom exception hierarchy for SolidWorks MCP server.

All domain exceptions inherit from SolidWorksMCPError.
Tool handlers catch these and return structured error dicts to the MCP layer.
"""


class SolidWorksMCPError(Exception):
    """Base exception for all SolidWorks MCP errors."""
    pass


class SolidWorksNotRunningError(SolidWorksMCPError):
    """SolidWorks application is not running or cannot be found."""
    pass


class SolidWorksConnectionError(SolidWorksMCPError):
    """Failed to connect to SolidWorks COM interface."""
    pass


class DocumentNotOpenError(SolidWorksMCPError):
    """No document is currently open in SolidWorks."""
    pass


class DocumentTypeError(SolidWorksMCPError):
    """Operation requires a different document type (part/assembly/drawing)."""
    pass


class ExportError(SolidWorksMCPError):
    """Failed to export file."""
    pass


class SheetMetalError(SolidWorksMCPError):
    """Operation requires a sheet metal part, or sheet metal operation failed."""
    pass


class AnalysisError(SolidWorksMCPError):
    """Failed to analyze part geometry or properties."""
    pass


class FileOperationError(SolidWorksMCPError):
    """Failed to open, close, or save a file."""
    pass


class FeatureError(SolidWorksMCPError):
    """Error accessing or traversing features in the feature tree."""
    pass


class CadQueryNotAvailableError(SolidWorksMCPError):
    """CadQuery/OCC is not installed; standalone STEP analysis unavailable."""
    pass
