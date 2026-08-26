"""
SolidWorks COM Bridge — manages the application connection lifecycle.

All SolidWorks COM interaction flows through this module.
Tools receive a SolidWorksBridge instance and call its methods;
they never import win32com or pythoncom directly.

SolidWorks is a Single-Threaded Apartment (STA) COM server.
pythoncom.CoInitialize() is called once during connect(); because
FastMCP runs synchronous tools in the calling thread (not a thread pool),
this is sufficient. If async/threaded execution is introduced later,
each thread will need its own CoInitialize() call.

Unit conventions (SolidWorks API internal units):
    Lengths  → metres     → multiply by M_TO_MM = 1000.0 for mm
    Area     → m²         → multiply by M2_TO_MM2 = 1e6 for mm²
    Volume   → m³         → multiply by M3_TO_MM3 = 1e9 for mm³
    Mass     → kg         → multiply by KG_TO_G   = 1000.0 for g

GetMassProperties2 return array layout (indices):
    0,1,2   → Centre of mass X, Y, Z  (metres)
    3,4,5   → Principal inertia axes Px, Py, Pz  (unit vectors)
    6..14   → Inertia tensor Lxx, Lxy, Lxz, Lyx, Lyy, Lyz, Lzx, Lzy, Lzz
    15      → Mass  (kg)
    16      → Volume (m³)
    17      → Surface area (m²)

Document type constants:
    1 → Part
    2 → Assembly
    3 → Drawing
"""

import logging

from .exceptions import (
    AnalysisError,
    DocumentNotOpenError,
    DocumentTypeError,
    SolidWorksConnectionError,
    SolidWorksNotRunningError,
)

logger = logging.getLogger(__name__)

# Unit conversion factors
M_TO_MM: float = 1_000.0
M2_TO_MM2: float = 1e6
M3_TO_MM3: float = 1e9
KG_TO_G: float = 1_000.0

# SolidWorks document type codes
DOC_PART: int = 1
DOC_ASSEMBLY: int = 2
DOC_DRAWING: int = 3
DOC_TYPE_NAMES = {DOC_PART: "part", DOC_ASSEMBLY: "assembly", DOC_DRAWING: "drawing"}


class SolidWorksBridge:
    """
    Singleton-style wrapper around the SolidWorks COM application object.

    Instantiate once at server startup; pass to every tool module.
    Connection is lazy: COM is not touched until connect() is called.
    """

    def __init__(self) -> None:
        self._app = None
        self._connected = False

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, allow_launch: bool = True) -> dict:
        """
        Connect to a running SolidWorks instance.

        Tries GetActiveObject first (reuse existing). If that fails:
          * If a SldWorks.exe process is already running, raises
            SolidWorksConnectionError with an elevation-mismatch hint —
            Windows COM's Running Object Table is per-integrity-level, so
            a process at a different privilege level cannot attach and
            silently spawning a second instance would just cause confusion.
          * Otherwise, if allow_launch is True, launches a new instance
            via Dispatch.

        Args:
            allow_launch: If False, never launch a new SolidWorks instance.

        Returns:
            dict with 'connected' (bool), 'version' (str),
            'is_new_instance' (bool), 'elevated' (bool).
        """
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise SolidWorksConnectionError(
                "pywin32 is not installed. Run: pip install pywin32"
            ) from exc

        pythoncom.CoInitialize()
        is_new = False
        elevated = _is_process_elevated()

        try:
            self._app = win32com.client.GetActiveObject("SldWorks.Application")
            logger.info(
                "Connected to existing SolidWorks instance (elevated=%s)",
                elevated,
            )
        except Exception:
            sw_running = _is_solidworks_running()
            if sw_running:
                raise SolidWorksConnectionError(
                    "A SolidWorks process is already running but cannot be "
                    "attached via COM. This almost always means an elevation "
                    "mismatch: the running SolidWorks and this MCP server are "
                    "at different integrity levels (one is Admin, the other is "
                    "not). Windows COM's Running Object Table is isolated per "
                    f"integrity level. (This process elevated={elevated}"
                    ".) Fix: close SolidWorks and relaunch it at the same "
                    "elevation as Claude Desktop — or close it entirely and "
                    "let solidworks_connect launch a fresh instance."
                )

            if not allow_launch:
                raise SolidWorksNotRunningError(
                    "SolidWorks is not running and allow_launch=False."
                )

            logger.info("No running SolidWorks found; launching new instance …")
            try:
                self._app = win32com.client.Dispatch("SldWorks.Application")
                self._app.Visible = True
                is_new = True
                logger.info("New SolidWorks instance started")
            except Exception as exc:
                raise SolidWorksNotRunningError(
                    f"Could not connect to or launch SolidWorks: {exc}"
                ) from exc

        self._connected = True
        version = self._safe_get_version()
        return {
            "connected": True,
            "version": version,
            "is_new_instance": is_new,
            "elevated": elevated,
        }

    def disconnect(self) -> None:
        """Release COM references (does not close SolidWorks)."""
        if self._app is not None:
            try:
                import pythoncom

                del self._app
                self._app = None
                pythoncom.CoUninitialize()
            except Exception as exc:
                logger.warning("Error during COM disconnect: %s", exc)
        self._connected = False
        logger.info("Disconnected from SolidWorks COM")

    def is_connected(self) -> bool:
        """Return True if an app reference is held and still responsive."""
        if not self._connected or self._app is None:
            return False
        try:
            _ = self._app.ActiveDoc
            return True
        except Exception:
            self._connected = False
            return False

    def ensure_connected(self) -> None:
        """Raise SolidWorksConnectionError if not connected."""
        if not self.is_connected():
            raise SolidWorksConnectionError(
                "Not connected to SolidWorks. Call solidworks_connect() first."
            )

    # ------------------------------------------------------------------
    # Application-level accessors
    # ------------------------------------------------------------------

    @property
    def app(self):
        """Raw COM application object. Raises if not connected."""
        if self._app is None or not self._connected:
            raise SolidWorksConnectionError(
                "Not connected. Call solidworks_connect() first."
            )
        return self._app

    def get_version(self) -> str:
        """Return SolidWorks revision string, e.g. '30.4.0' for SW2022 SP4."""
        return self._safe_get_version()

    def get_open_documents(self) -> list[str]:
        """Return list of file paths for all documents currently open."""
        self.ensure_connected()
        paths = []
        try:
            doc = _com_call(self.app, "GetFirstDocument")
            while doc is not None:
                path = _com_call(doc, "GetPathName")
                if path:
                    paths.append(path)
                doc = _com_call(doc, "GetNext")
        except Exception as exc:
            logger.warning("Error enumerating open documents: %s", exc)
        return paths

    # ------------------------------------------------------------------
    # Document access
    # ------------------------------------------------------------------

    def get_active_doc(self, require_type: int | None = None):
        """
        Return the active document COM object.

        Args:
            require_type: If given (DOC_PART/DOC_ASSEMBLY/DOC_DRAWING),
                          raises DocumentTypeError when active doc type
                          does not match.

        Raises:
            DocumentNotOpenError: no document is active.
            DocumentTypeError: active document is the wrong type.
        """
        self.ensure_connected()
        doc = self.app.ActiveDoc
        if doc is None:
            raise DocumentNotOpenError(
                "No document is currently open in SolidWorks. "
                "Open a file first using open_file()."
            )

        if require_type is not None:
            actual = _com_call(doc, "GetType")
            if actual != require_type:
                expected_name = DOC_TYPE_NAMES.get(require_type, str(require_type))
                actual_name = DOC_TYPE_NAMES.get(actual, str(actual))
                raise DocumentTypeError(
                    f"This operation requires a {expected_name} document, "
                    f"but the active document is a {actual_name}."
                )

        return doc

    def get_active_doc_type(self) -> int | None:
        """Return the active document's type code, or None if none open."""
        self.ensure_connected()
        doc = self.app.ActiveDoc
        if doc is None:
            return None
        return _com_call(doc, "GetType")

    # ------------------------------------------------------------------
    # Geometry and mass properties
    # ------------------------------------------------------------------

    def get_mass_properties(self, doc) -> dict:
        """
        Return mass/volume/surface-area properties for a part.

        Args:
            doc: IModelDoc2 COM object (must be a Part).

        Returns:
            dict with mass_g, volume_mm3, surface_area_mm2, center_of_mass_mm.

        Raises:
            AnalysisError: if properties cannot be retrieved (e.g. no material).
        """
        # Use IMassProperty (created via Extension.CreateMassProperty).
        # This exposes Mass, Volume, SurfaceArea, CenterOfMass as
        # properties — no fragile array-index unpacking.
        ext = doc.Extension
        mp = _com_call(ext, "CreateMassProperty")
        if mp is None:
            raise AnalysisError(
                "CreateMassProperty returned None. "
                "The SolidWorks session may not support mass calculations."
            )
        try:
            com = mp.CenterOfMass  # SafeArray[3] in meters
            com_list = list(com) if com else [0.0, 0.0, 0.0]
        except Exception:
            com_list = [0.0, 0.0, 0.0]
        mass = float(getattr(mp, "Mass", 0.0) or 0.0)
        volume = float(getattr(mp, "Volume", 0.0) or 0.0)
        surface = float(getattr(mp, "SurfaceArea", 0.0) or 0.0)
        return {
            "center_of_mass_mm": [
                com_list[0] * M_TO_MM,
                com_list[1] * M_TO_MM,
                com_list[2] * M_TO_MM,
            ],
            "mass_g": mass * KG_TO_G,
            "volume_mm3": volume * M3_TO_MM3,
            "surface_area_mm2": surface * M2_TO_MM2,
        }

    def get_bounding_box(self, doc) -> dict:
        """
        Return the axis-aligned bounding box of the active part.

        Returns:
            dict with min_mm, max_mm, dimensions_mm (each a 3-element list).
        """
        try:
            # GetPartBox is the part-level API; Extension.GetBox is the
            # fallback for documents where it returns nothing.
            box = doc.GetPartBox(True)
            if box is None:
                box = doc.Extension.GetBox(0)
            if box is None:
                raise AnalysisError("Could not retrieve bounding box from SolidWorks.")
            box = list(box)
            x_min, y_min, z_min = box[0] * M_TO_MM, box[1] * M_TO_MM, box[2] * M_TO_MM
            x_max, y_max, z_max = box[3] * M_TO_MM, box[4] * M_TO_MM, box[5] * M_TO_MM
            dims = [x_max - x_min, y_max - y_min, z_max - z_min]
            diagonal = (dims[0] ** 2 + dims[1] ** 2 + dims[2] ** 2) ** 0.5
            return {
                "min_mm": [x_min, y_min, z_min],
                "max_mm": [x_max, y_max, z_max],
                "dimensions_mm": dims,
                "diagonal_mm": round(diagonal, 4),
            }
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError(f"Bounding box retrieval failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Feature tree traversal
    # ------------------------------------------------------------------

    def find_sheet_metal_feature(self, doc):
        """
        Traverse the feature tree and return the SheetMetal feature, or None.

        Uses GetTypeName2() (API name, language-independent) rather than
        GetTypeName() (which returns localized names on non-English installs).
        """
        try:
            feat = _com_call(doc, "FirstFeature")
            while feat is not None:
                try:
                    if _com_call(feat, "GetTypeName2") == "SheetMetal":
                        return feat
                except Exception:
                    pass
                feat = _com_call(feat, "GetNextFeature")
        except Exception as exc:
            logger.warning("Error traversing feature tree: %s", exc)
        return None

    def iter_features(self, doc):
        """
        Generator that yields each IFeature in the top-level tree.
        Stops after MAX_FEATURES to avoid blocking indefinitely on complex parts.
        """
        MAX_FEATURES = 5000
        count = 0
        try:
            feat = _com_call(doc, "FirstFeature")
            while feat is not None and count < MAX_FEATURES:
                yield feat
                count += 1
                feat = _com_call(feat, "GetNextFeature")
        except Exception as exc:
            logger.warning("Feature traversal interrupted: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _safe_get_version(self) -> str:
        if self._app is None:
            return "unknown"
        try:
            return str(self._app.RevisionNumber())
        except Exception:
            return "unknown"


# ----------------------------------------------------------------------
# Module-level Windows helpers (only used at connect time)
# ----------------------------------------------------------------------

def _com_call(obj, method_name: str, *args):
    """
    Invoke a COM method robustly against pywin32 late-binding quirks.

    With SolidWorks' IDispatch (no automatic typelib discovery), pywin32 may
    auto-evaluate a zero-argument method on first attribute access, caching
    the return value on the CDispatch. Later calling that cached value then
    fails — 'int object is not callable' for methods returning ints, or the
    wrong default-member invocation if it happens to be a CDispatch.

    Strategy:
      * If the attribute is a bound Python method or builtin function,
        invoke it with args.
      * Otherwise the attribute IS the result of an auto-evaluated property
        getter. Return it directly.

    This rule must NOT use plain `callable()` because win32com CDispatch
    instances are themselves callable (they forward to the default member),
    which would cause infinite re-dispatch.
    """
    import types

    attr = getattr(obj, method_name)
    if isinstance(attr, (types.MethodType, types.BuiltinFunctionType,
                         types.FunctionType, types.MethodWrapperType)):
        return attr(*args)
    if args:
        raise TypeError(
            f"{method_name!r} resolved to a non-method value "
            f"({type(attr).__name__}) but {len(args)} argument(s) were "
            "supplied. Use the property-style value directly."
        )
    return attr


def _is_process_elevated() -> bool:
    """Return True if this Python process is running elevated (Administrator)."""
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _is_solidworks_running() -> bool:
    """
    Return True if any SLDWORKS.exe process is currently running.

    Uses the Win32 ToolHelp snapshot API via ctypes so there's no dependency
    on psutil. Returns False on any error — this is a diagnostic helper, not
    a correctness gate.
    """
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 2
        INVALID_HANDLE_VALUE = -1

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE:
            return False
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return False
            while True:
                if entry.szExeFile.lower() == "sldworks.exe":
                    return True
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    return False
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception as exc:
        logger.debug("_is_solidworks_running probe failed: %s", exc)
        return False
