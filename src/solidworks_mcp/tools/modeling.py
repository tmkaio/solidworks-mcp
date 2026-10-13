"""
Part modeling tools for SolidWorks MCP — the tools that BUILD geometry.

Tools in this module:
    new_part            — Create a new part from the default part template
    start_sketch        — Open a sketch on the Front / Top / Right plane
    sketch_line         — Add a line to the active sketch
    sketch_rectangle    — Add a corner rectangle to the active sketch
    sketch_circle       — Add a circle to the active sketch
    sketch_polygon      — Add a closed polyline (e.g. a blank outline)
    finish_sketch       — Close the active sketch and return its name
    extrude             — Boss-extrude a sketch (blind or mid-plane)
    cut_extrude         — Cut-extrude a sketch (through all, or blind)
    rename_feature      — Rename a feature (label process steps)
    delete_feature      — Delete a feature by name (undo a modeling step)

Coordinates are millimetres in the SKETCH's own 2D frame:
    Front plane → sketch (x, y) = model (X, Y);   extrudes along +Z
    Top plane   → sketch (x, y) = model (X, -Z);  extrudes along +Y
    Right plane → sketch (x, y) = model (-Z, Y);  extrudes along +X

Sketch entities are created with SketchManager.AddToDB = True so that
SolidWorks does not snap them to nearby points or grid or add automatic
relations — the geometry lands exactly at the coordinates given.

Validated live against SOLIDWORKS 2025 SP5: rectangle + 2 mm extrude +
two Ø8 through-all cuts gives 3398.9 mm³, the analytic volume exactly.
"""

import logging
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import DOC_PART, _com_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)

MM_TO_M = 0.001

# swEndConditions_e
END_BLIND = 0
END_THROUGH_ALL = 1
END_MID_PLANE = 6

_PLANE_INDEX = {"front": 0, "top": 1, "right": 2}

_NO_SKETCH = (
    "No sketch is open. Call start_sketch(plane) first, add entities, "
    "then finish_sketch()."
)


# ----------------------------------------------------------------------
# Helpers (module level so they can be unit-tested with COM doubles)
# ----------------------------------------------------------------------

def features_of_type(doc, type_name: str) -> list:
    """All top-level features whose GetTypeName2 equals type_name, in tree order."""
    found = []
    feat = _com_call(doc, "FirstFeature")
    while feat is not None:
        try:
            if _com_call(feat, "GetTypeName2") == type_name:
                found.append(feat)
        except Exception:
            pass
        feat = _com_call(feat, "GetNextFeature")
    return found


def default_plane(doc, plane: str):
    """
    The default Front / Top / Right reference plane.

    Picked by position (the first three RefPlane features), not by name,
    so it works on non-English installs where they are called e.g.
    "Plano frontal".
    """
    key = plane.strip().lower()
    if key not in _PLANE_INDEX:
        raise ValueError(f"plane must be one of front/top/right, got {plane!r}")
    planes = features_of_type(doc, "RefPlane")
    if len(planes) < 3:
        raise ValueError("Could not find the three default reference planes")
    return planes[_PLANE_INDEX[key]]


def resolve_sketch(doc, sketch_name: str):
    """The named sketch, or the last sketch in the tree when name is empty."""
    sketches = features_of_type(doc, "ProfileFeature")
    if not sketches:
        return None
    if not sketch_name:
        return sketches[-1]
    for sk in sketches:
        if sk.Name == sketch_name:
            return sk
    return None


def clean_polygon(points, tol_mm: float = 1e-4) -> list[tuple[float, float]]:
    """
    Drop consecutive duplicate points (and a repeated closing point).

    SolidWorks refuses a zero-length line; polygons coming out of geometry
    libraries (e.g. Shapely ring buffers) often repeat a vertex.
    """
    out: list[tuple[float, float]] = []
    for p in points:
        q = (float(p[0]), float(p[1]))
        if out and abs(q[0] - out[-1][0]) < tol_mm and abs(q[1] - out[-1][1]) < tol_mm:
            continue
        out.append(q)
    while len(out) > 1 and abs(out[0][0] - out[-1][0]) < tol_mm \
            and abs(out[0][1] - out[-1][1]) < tol_mm:
        out.pop()
    return out


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all modeling tools with the FastMCP instance."""

    def _part():
        bridge.ensure_connected()
        return bridge.get_active_doc(require_type=DOC_PART)

    def _active_sketch_manager():
        doc = _part()
        skm = doc.SketchManager
        if _com_call(skm, "ActiveSketch") is None:
            raise RuntimeError(_NO_SKETCH)
        return doc, skm

    def _add_entities(build) -> dict:
        """Run build(skm) with snapping/auto-relations disabled."""
        try:
            doc, skm = _active_sketch_manager()
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}
        skm.AddToDB = True
        try:
            created = build(skm)
        finally:
            skm.AddToDB = False
        _com_call(doc, "GraphicsRedraw2")
        if not created:
            return {"success": False,
                    "error": "SolidWorks did not create the sketch entity."}
        return {"success": True}

    # ------------------------------------------------------------------

    @mcp.tool()
    def new_part() -> dict:
        """
        Create a new, empty part from the default part template and make it active.

        Use this tool when starting to model something from scratch, e.g.
        building a progressive-die strip station by station.

        Returns a dict with:
            success (bool), title (str): e.g. "Part3"
        """
        try:
            bridge.ensure_connected()
            template = bridge.app.GetUserPreferenceStringValue(8)  # swDefaultTemplatePart
            if not template:
                return {"success": False,
                        "error": "No default part template is configured "
                                 "(Tools > Options > Default Templates)."}
            doc = bridge.app.NewDocument(template, 0, 0, 0)
            if doc is None:
                return {"success": False,
                        "error": f"NewDocument failed with template {template}"}
            title = _com_call(bridge.app.ActiveDoc, "GetTitle")
            logger.info("new_part: created %s", title)
            return {"success": True, "title": title}
        except Exception as exc:
            logger.exception("new_part error")
            return {"success": False, "error": str(exc)}

    @mcp.tool()
    def start_sketch(plane: str = "front") -> dict:
        """
        Open a new sketch on one of the default planes of the active part.

        Args:
            plane: "front" (sketch XY = model XY), "top" (sketch XY = model X,-Z)
                   or "right" (sketch XY = model -Z,Y).

        After this, add entities with sketch_line / sketch_rectangle /
        sketch_circle / sketch_polygon, then call finish_sketch().

        Returns a dict with: success (bool), plane (str)
        """
        try:
            doc = _part()
            skm = doc.SketchManager
            if _com_call(skm, "ActiveSketch") is not None:
                return {"success": False,
                        "error": "A sketch is already open. Call finish_sketch() first."}
            ref = default_plane(doc, plane)
            doc.ClearSelection2(True)
            if not ref.Select2(False, 0):
                return {"success": False, "error": f"Could not select the {plane} plane"}
            skm.InsertSketch(True)
            return {"success": True, "plane": plane.lower()}
        except Exception as exc:
            logger.exception("start_sketch error")
            return {"success": False, "error": str(exc)}

    @mcp.tool()
    def sketch_line(x1: float, y1: float, x2: float, y2: float) -> dict:
        """
        Add a straight line to the open sketch. Coordinates in mm (sketch frame).

        Note: a cut or extrude needs CLOSED contours — use sketch_polygon or
        sketch_rectangle for profiles; plain lines are for construction.

        Returns a dict with: success (bool)
        """
        return _add_entities(lambda skm: skm.CreateLine(
            x1 * MM_TO_M, y1 * MM_TO_M, 0, x2 * MM_TO_M, y2 * MM_TO_M, 0))

    @mcp.tool()
    def sketch_rectangle(x1: float, y1: float, x2: float, y2: float) -> dict:
        """
        Add an axis-aligned rectangle with opposite corners (x1,y1) and (x2,y2), in mm.

        Returns a dict with: success (bool)
        """
        return _add_entities(lambda skm: skm.CreateCornerRectangle(
            x1 * MM_TO_M, y1 * MM_TO_M, 0, x2 * MM_TO_M, y2 * MM_TO_M, 0))

    @mcp.tool()
    def sketch_circle(cx: float, cy: float, diameter: float) -> dict:
        """
        Add a circle with centre (cx, cy) and the given DIAMETER, all in mm.

        Returns a dict with: success (bool)
        """
        if diameter <= 0:
            return {"success": False, "error": "diameter must be > 0"}
        return _add_entities(lambda skm: skm.CreateCircleByRadius(
            cx * MM_TO_M, cy * MM_TO_M, 0, diameter / 2 * MM_TO_M))

    @mcp.tool()
    def sketch_polygon(points: list[list[float]]) -> dict:
        """
        Add a CLOSED polyline through the given points (mm, sketch frame).

        The last point connects back to the first automatically — do not
        repeat the first point at the end. Use it for blank outlines, notch
        punches and carrier profiles.

        Args:
            points: [[x, y], [x, y], ...] with at least 3 points.

        Returns a dict with: success (bool), segments (int)
        """
        pts = clean_polygon(points)
        if len(pts) < 3:
            return {"success": False, "error": "need at least 3 distinct points"}

        failed: list[int] = []

        def build(skm):
            for i, ((ax, ay), (bx, by)) in enumerate(zip(pts, pts[1:] + pts[:1])):
                seg = skm.CreateLine(ax * MM_TO_M, ay * MM_TO_M, 0,
                                     bx * MM_TO_M, by * MM_TO_M, 0)
                if seg is None:
                    failed.append(i)
            return not failed

        result = _add_entities(build)
        if result.get("success"):
            result["segments"] = len(pts)
        elif failed:
            result["error"] = (f"SolidWorks rejected {len(failed)} of {len(pts)} "
                               f"segments (indices {failed[:10]}).")
        return result

    @mcp.tool()
    def finish_sketch() -> dict:
        """
        Close the open sketch.

        Returns a dict with:
            success (bool), sketch_name (str): the name to pass to extrude /
            cut_extrude, e.g. "Sketch3"
        """
        try:
            doc, skm = _active_sketch_manager()
            # the open sketch is already in the tree (as the newest sketch);
            # remember its name and check it survives closing
            open_sk = resolve_sketch(doc, "")
            name = open_sk.Name if open_sk is not None else None
            skm.InsertSketch(True)
            if name is None or doc.FeatureByName(name) is None:
                # SolidWorks silently discards a sketch with no entities
                return {"success": True, "sketch_name": None,
                        "note": "The sketch was empty and SolidWorks discarded it."}
            return {"success": True, "sketch_name": name}
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("finish_sketch error")
            return {"success": False, "error": str(exc)}

    @mcp.tool()
    def extrude(depth: float, sketch_name: str = "", reverse: bool = False,
                mid_plane: bool = False) -> dict:
        """
        Boss-extrude a closed sketch to create or add material.

        Args:
            depth: extrusion depth in mm (e.g. sheet thickness 1.5).
            sketch_name: sketch to extrude; empty = the most recent sketch.
            reverse: extrude to the opposite side of the sketch plane.
            mid_plane: extrude symmetrically, depth/2 to each side.

        Returns a dict with: success (bool), feature (str) e.g. "Boss-Extrude1"
        """
        try:
            doc = _part()
            if depth <= 0:
                return {"success": False, "error": "depth must be > 0"}
            sk = resolve_sketch(doc, sketch_name)
            if sk is None:
                return {"success": False,
                        "error": f"Sketch {sketch_name or '(last)'} not found"}
            doc.ClearSelection2(True)
            sk.Select2(False, 0)
            end = END_MID_PLANE if mid_plane else END_BLIND
            feat = doc.FeatureManager.FeatureExtrusion3(
                True, bool(reverse), False, end, 0, depth * MM_TO_M, 0,
                False, False, False, False, 0, 0, False, False, False, False,
                True, False, True, 0, 0, False)
            if feat is None:
                return {"success": False,
                        "error": "Extrusion failed — the sketch is probably not a "
                                 "closed contour, or contours overlap."}
            return {"success": True, "feature": feat.Name}
        except Exception as exc:
            logger.exception("extrude error")
            return {"success": False, "error": str(exc)}

    @mcp.tool()
    def cut_extrude(sketch_name: str = "", depth: float = 0.0,
                    reverse: bool = False) -> dict:
        """
        Cut material with a closed sketch (holes, notches, punches).

        Args:
            sketch_name: sketch to cut with; empty = the most recent sketch.
            depth: 0 (default) = THROUGH ALL in both directions from the
                   sketch plane — the right choice for punching sheet metal.
                   > 0 = blind cut of that depth in mm.
            reverse: flip the direction of a blind cut.

        Returns a dict with: success (bool), feature (str) e.g. "Cut-Extrude1"
        """
        try:
            doc = _part()
            sk = resolve_sketch(doc, sketch_name)
            if sk is None:
                return {"success": False,
                        "error": f"Sketch {sketch_name or '(last)'} not found"}
            doc.ClearSelection2(True)
            sk.Select2(False, 0)
            if depth and depth > 0:
                single, t1, t2, d1 = True, END_BLIND, END_BLIND, depth * MM_TO_M
            else:
                # one-directional through-all can point away from the material
                # and silently cut nothing — cut both ways instead
                single, t1, t2, d1 = False, END_THROUGH_ALL, END_THROUGH_ALL, 0
            feat = doc.FeatureManager.FeatureCut4(
                single, bool(reverse), False, t1, t2, d1, 0,
                False, False, False, False, 0, 0, False, False, False, False,
                False, False, True, True, False, False, 0, 0, False, False)
            if feat is None:
                return {"success": False,
                        "error": "Cut failed — the sketch is probably not closed, "
                                 "or it does not intersect any material."}
            return {"success": True, "feature": feat.Name}
        except Exception as exc:
            logger.exception("cut_extrude error")
            return {"success": False, "error": str(exc)}

    @mcp.tool()
    def rename_feature(feature_name: str, new_name: str) -> dict:
        """
        Rename a feature in the FeatureManager tree.

        Use to label modeling steps meaningfully, e.g. "St2 - Pierce holes",
        so the tree reads like the engineer's process sheet.

        Returns a dict with: success (bool), name (str): the name now in the tree
        """
        try:
            doc = _part()
            new_name = new_name.strip()
            if not new_name:
                return {"success": False, "error": "new_name is empty"}
            if doc.FeatureByName(new_name) is not None:
                return {"success": False,
                        "error": f"A feature named '{new_name}' already exists"}
            feat = doc.FeatureByName(feature_name)
            if feat is None:
                return {"success": False, "error": f"Feature '{feature_name}' not found"}
            feat.Name = new_name
            return {"success": True, "name": feat.Name}
        except Exception as exc:
            logger.exception("rename_feature error")
            return {"success": False, "error": str(exc)}

    @mcp.tool()
    def delete_feature(feature_name: str) -> dict:
        """
        Delete a feature (and its absorbed sketch) from the active part.

        Use to back out a modeling step that came out wrong — the way an
        engineer deletes a feature and redoes it.

        Returns a dict with: success (bool), deleted (str)
        """
        try:
            doc = _part()
            feat = doc.FeatureByName(feature_name)
            if feat is None:
                return {"success": False, "error": f"Feature '{feature_name}' not found"}
            doc.ClearSelection2(True)
            feat.Select2(False, 0)
            # swDeleteSelectionOptions_e: 1 = also absorbed features (the
            # sketch of a cut); a bare sketch has none, so retry plainly
            ok = doc.Extension.DeleteSelection2(1)
            if not ok and doc.FeatureByName(feature_name) is not None:
                doc.ClearSelection2(True)
                feat.Select2(False, 0)
                ok = doc.Extension.DeleteSelection2(0)
            if not ok:
                return {"success": False, "error": "SolidWorks refused the delete"}
            return {"success": True, "deleted": feature_name}
        except Exception as exc:
            logger.exception("delete_feature error")
            return {"success": False, "error": str(exc)}
