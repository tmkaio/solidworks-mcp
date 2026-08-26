"""
Measurement tools for SolidWorks MCP.

Tools in this module:
    measure_distance         — Distance between two selected entities
    measure_entity           — Properties of a single entity (edge/face/vertex)
    get_face_properties      — Area, normal vector, centroid of a face
    measure_minimum_distance — Minimum gap between two bodies or faces
    get_section_properties   — Cross-section area, centroid, moments of a face loop

SolidWorks measurement is done through IMeasureManager / IModelMeasure
(app.GetMeasureManager()).  Entity selection uses IModelDocExtension.SelectByID2.

Selection type strings (partial list):
    "EDGE"      — linear edge
    "FACE"      — face
    "VERTEX"    — point / vertex
    "COMPONENT" — assembly component

Units: all SolidWorks API values are in metres.  Results are converted to mm.
"""

import logging
from typing import TYPE_CHECKING

from solidworks_mcp.solidworks_bridge import _com_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from solidworks_mcp.solidworks_bridge import SolidWorksBridge

logger = logging.getLogger(__name__)

M_TO_MM = 1_000.0
M2_TO_MM2 = 1_000_000.0
M3_TO_MM3 = 1_000_000_000.0


def register(mcp: "FastMCP", bridge: "SolidWorksBridge") -> None:
    """Register all measurement tools with the FastMCP instance."""

    @mcp.tool()
    def measure_distance(
        entity1_name: str,
        entity1_type: str,
        entity2_name: str,
        entity2_type: str,
    ) -> dict:
        """
        Measure the distance between two entities in the active document.

        Use when the user asks "how far is X from Y", "what is the gap
        between these faces", or "distance between two holes".

        Entity name format: "FeatureName@PartName" (e.g. "Boss-Extrude1@Part1")
        For faces/edges the name is as shown in the SolidWorks status bar.
        Use "FACE", "EDGE", or "VERTEX" for entity_type.

        Args:
            entity1_name: Selection name of first entity.
            entity1_type: Selection type: "FACE", "EDGE", "VERTEX", etc.
            entity2_name: Selection name of second entity.
            entity2_type: Selection type for second entity.

        Returns a dict with:
            distance_mm (float): minimum distance between entities
            delta_x_mm, delta_y_mm, delta_z_mm (float): component distances
            success (bool)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            ext = doc.Extension

            # Clear selection
            doc.ClearSelection2(True)

            # Select first entity
            ok1 = ext.SelectByID2(entity1_name, entity1_type.upper(),
                                   0, 0, 0, False, 1, None, 0)
            ok2 = ext.SelectByID2(entity2_name, entity2_type.upper(),
                                   0, 0, 0, True, 2, None, 0)  # True = add to selection

            if not ok1 or not ok2:
                return {
                    "success": False,
                    "error": (
                        f"Could not select entities. "
                        f"Entity1 '{entity1_name}' ({ok1}), "
                        f"Entity2 '{entity2_name}' ({ok2}). "
                        "Verify the entity names using the SolidWorks status bar."
                    ),
                }

            measure = bridge.app.GetMeasureManager()
            if measure is None:
                return {"success": False, "error": "MeasureManager not available"}

            measure.ArcOption = 0  # minimum distance
            dist = measure.Distance
            dx = measure.DeltaX
            dy = measure.DeltaY
            dz = measure.DeltaZ

            doc.ClearSelection2(True)
            return {
                "success": True,
                "distance_mm": round(dist * M_TO_MM, 4) if dist is not None else None,
                "delta_x_mm": round(dx * M_TO_MM, 4) if dx is not None else None,
                "delta_y_mm": round(dy * M_TO_MM, 4) if dy is not None else None,
                "delta_z_mm": round(dz * M_TO_MM, 4) if dz is not None else None,
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("measure_distance error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def measure_entity(entity_name: str, entity_type: str) -> dict:
        """
        Measure properties of a single entity (edge, face, or vertex).

        Use to get the length of an edge, area of a face, or coordinates
        of a vertex without needing a second selection.

        Args:
            entity_name: Selection name (as shown in SolidWorks status bar).
            entity_type: "FACE", "EDGE", or "VERTEX".

        Returns a dict with (depending on type):
            For EDGE:  length_mm (float)
            For FACE:  area_mm2 (float), perimeter_mm (float)
            For VERTEX: x_mm, y_mm, z_mm (float)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            ext = doc.Extension

            doc.ClearSelection2(True)
            ok = ext.SelectByID2(entity_name, entity_type.upper(),
                                  0, 0, 0, False, 0, None, 0)
            if not ok:
                return {"success": False,
                        "error": f"Could not select '{entity_name}' as {entity_type}"}

            measure = bridge.app.GetMeasureManager()
            if measure is None:
                return {"success": False, "error": "MeasureManager not available"}

            result: dict = {"success": True, "entity_type": entity_type.upper()}
            et = entity_type.upper()

            if et == "EDGE":
                result["length_mm"] = round(measure.Length * M_TO_MM, 4)
            elif et == "FACE":
                result["area_mm2"] = round(measure.Area * M2_TO_MM2, 4)
                result["perimeter_mm"] = round(measure.Perimeter * M_TO_MM, 4)
            elif et == "VERTEX":
                result["x_mm"] = round(measure.X * M_TO_MM, 4)
                result["y_mm"] = round(measure.Y * M_TO_MM, 4)
                result["z_mm"] = round(measure.Z * M_TO_MM, 4)

            doc.ClearSelection2(True)
            return result

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("measure_entity error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_face_properties(face_index: int = 0) -> dict:
        """
        Get geometric properties of a face on the active part by index.

        Iterates over all faces of the first solid body and returns properties
        of the face at the given index.  Use analyze_holes for hole-specific
        geometry; use this for planar, cylindrical, or freeform faces.

        Args:
            face_index: 0-based index into the face list of the first body.

        Returns a dict with:
            index (int), face_type (str), area_mm2 (float),
            normal (dict with x, y, z): unit normal vector for planar faces,
            centroid_mm (dict with x, y, z)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)

            bodies = doc.GetBodies2(0, True)  # 0 = all solid bodies
            if not bodies:
                return {"error": "No solid bodies found"}

            body = bodies[0]
            faces = []
            face = _com_call(body, "GetFirstFace")
            while face:
                faces.append(face)
                face = _com_call(face, "GetNextFace")

            if face_index >= len(faces) or face_index < 0:
                return {"error": f"face_index {face_index} out of range (0–{len(faces)-1})"}

            f = faces[face_index]
            surf = _com_call(f, "GetSurface")
            face_type = "unknown"
            normal_data = None

            if surf:
                if _com_call(surf, "IsPlane"):
                    face_type = "plane"
                    params = surf.PlaneParams()
                    if params:
                        normal_data = {
                            "x": round(params[0], 6),
                            "y": round(params[1], 6),
                            "z": round(params[2], 6),
                        }
                elif _com_call(surf, "IsCylinder"):
                    face_type = "cylinder"
                elif _com_call(surf, "IsCone"):
                    face_type = "cone"
                elif _com_call(surf, "IsSphere"):
                    face_type = "sphere"
                elif _com_call(surf, "IsTorus"):
                    face_type = "torus"
                else:
                    face_type = "spline/other"

            area = _com_call(f, "GetArea") * M2_TO_MM2
            # Centroid via face params
            props = f.GetMassProperties()  # returns [area, cx, cy, cz, ...]
            centroid = None
            if props and len(props) >= 4:
                centroid = {
                    "x_mm": round(props[1] * M_TO_MM, 4),
                    "y_mm": round(props[2] * M_TO_MM, 4),
                    "z_mm": round(props[3] * M_TO_MM, 4),
                }

            return {
                "index": face_index,
                "face_type": face_type,
                "area_mm2": round(area, 4),
                "normal": normal_data,
                "centroid_mm": centroid,
                "total_faces": len(faces),
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_face_properties error")
            return {"error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def measure_minimum_distance(
        entity1_name: str,
        entity1_type: str,
        entity2_name: str,
        entity2_type: str,
    ) -> dict:
        """
        Measure the minimum distance between two bodies, faces, or components.

        Similar to measure_distance but uses the minimum-distance mode of
        IMeasureManager.  Most useful for checking clearances in assemblies
        (e.g. "what is the minimum gap between the bracket and the housing?").

        Args:
            entity1_name: Selection name of first entity.
            entity1_type: Selection type string.
            entity2_name: Selection name of second entity.
            entity2_type: Selection type string.

        Returns a dict with:
            minimum_distance_mm (float),
            point1_mm (dict x/y/z): closest point on entity 1,
            point2_mm (dict x/y/z): closest point on entity 2
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc()
            ext = doc.Extension

            doc.ClearSelection2(True)
            ok1 = ext.SelectByID2(entity1_name, entity1_type.upper(),
                                   0, 0, 0, False, 1, None, 0)
            ok2 = ext.SelectByID2(entity2_name, entity2_type.upper(),
                                   0, 0, 0, True, 2, None, 0)

            if not ok1 or not ok2:
                return {
                    "success": False,
                    "error": f"Selection failed: e1={ok1}, e2={ok2}",
                }

            measure = bridge.app.GetMeasureManager()
            if measure is None:
                return {"success": False, "error": "MeasureManager not available"}

            measure.ArcOption = 1  # minimum distance mode

            dist = measure.Distance
            # Closest points
            px1 = getattr(measure, "PointOnEntity1X", None)
            py1 = getattr(measure, "PointOnEntity1Y", None)
            pz1 = getattr(measure, "PointOnEntity1Z", None)
            px2 = getattr(measure, "PointOnEntity2X", None)
            py2 = getattr(measure, "PointOnEntity2Y", None)
            pz2 = getattr(measure, "PointOnEntity2Z", None)

            doc.ClearSelection2(True)
            result: dict = {
                "success": True,
                "minimum_distance_mm": round(dist * M_TO_MM, 4) if dist is not None else None,
            }
            if px1 is not None:
                result["point1_mm"] = {
                    "x": round(px1 * M_TO_MM, 4),
                    "y": round(py1 * M_TO_MM, 4),
                    "z": round(pz1 * M_TO_MM, 4),
                }
            if px2 is not None:
                result["point2_mm"] = {
                    "x": round(px2 * M_TO_MM, 4),
                    "y": round(py2 * M_TO_MM, 4),
                    "z": round(pz2 * M_TO_MM, 4),
                }
            return result

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("measure_minimum_distance error")
            return {"success": False, "error": f"Unexpected error: {exc}"}

    @mcp.tool()
    def get_section_properties(face_name: str = "") -> dict:
        """
        Get cross-section area, centroid, and second moments of area for a face.

        Useful for structural analysis — gives the section modulus inputs
        needed for beam bending or column buckling checks.

        Args:
            face_name: Selection name of the face to use as the cross-section.
                       Leave empty to use the first planar face found on the part.

        Returns a dict with:
            area_mm2 (float),
            centroid_mm (dict x/y/z),
            Ixx_mm4, Iyy_mm4, Ixy_mm4 (float): second moments of area,
            perimeter_mm (float)
        """
        from solidworks_mcp.exceptions import DocumentNotOpenError, SolidWorksConnectionError

        try:
            bridge.ensure_connected()
            doc = bridge.get_active_doc(require_type=1)
            ext = doc.Extension

            if face_name:
                doc.ClearSelection2(True)
                ok = ext.SelectByID2(face_name, "FACE", 0, 0, 0, False, 0, None, 0)
                if not ok:
                    return {"error": f"Could not select face '{face_name}'"}

            # Use SectionPropertyManager if available
            sec_mgr = getattr(doc, "SectionPropertyManager", None)
            if sec_mgr is None:
                return {"error": "SectionPropertyManager not available on this document type"}

            sec = sec_mgr.GetSectionProperties()
            if sec is None:
                return {"error": "GetSectionProperties returned None — select a planar face first"}

            return {
                "area_mm2": round(sec.Area * M2_TO_MM2, 4),
                "perimeter_mm": round(sec.Perimeter * M_TO_MM, 4),
                "centroid_mm": {
                    "x": round(sec.CentroidX * M_TO_MM, 4),
                    "y": round(sec.CentroidY * M_TO_MM, 4),
                    "z": round(sec.CentroidZ * M_TO_MM, 4),
                },
                "Ixx_mm4": round(sec.Ixx * (M_TO_MM ** 4), 4),
                "Iyy_mm4": round(sec.Iyy * (M_TO_MM ** 4), 4),
                "Ixy_mm4": round(sec.Ixy * (M_TO_MM ** 4), 4),
            }

        except (SolidWorksConnectionError, DocumentNotOpenError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("get_section_properties error")
            return {"error": f"Unexpected error: {exc}"}
