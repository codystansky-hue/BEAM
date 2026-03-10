import rhino3dm

def inspect_edges(filename):
    model = rhino3dm.File3dm.Read(filename)
    if not model:
        print(f"Could not read {filename}")
        return
        
    for obj_idx, obj in enumerate(model.Objects):
        if obj.Geometry.ObjectType == rhino3dm.ObjectType.Brep:
            brep = obj.Geometry
            if hasattr(brep, 'Edges'):
                print(f"Brep {obj_idx} has {len(brep.Edges)} edges:")
                for i in range(len(brep.Edges)):
                    try:
                        edge = brep.Edges[i]
                        edge_curve = edge.ToNurbsCurve()
                        bbox = edge_curve.GetBoundingBox()
                        diag = 0
                        if bbox.IsValid:
                            diag = bbox.Max.DistanceTo(bbox.Min)
                        
                        # Print properties
                        is_linear = edge_curve.IsLinear()
                        is_planar = edge_curve.IsPlanar()
                        degree = edge_curve.Degree
                        points = len(edge_curve.Points)
                        print(f"  Edge {i}: diag={diag:.4f}, linear={is_linear}, planar={is_planar}, degree={degree}, points={points}")
                    except Exception as e:
                        print(f"  Edge {i}: Failed to analyze - {e}")

if __name__ == "__main__":
    inspect_edges("../meshes/BoomSectionSRF.3dm")
