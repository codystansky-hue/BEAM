import rhino3dm

def inspect_3dm(filename):
    model = rhino3dm.File3dm.Read(filename)
    b = model.Objects[0].Geometry
    print(dir(b))
    if hasattr(b, 'Edges'):
        for i in range(len(b.Edges)):
            edge = b.Edges[i]
            print(f"Edge {i}: dir={dir(edge)}, type={type(edge)}")
            try:
                curve = edge.ToNurbsCurve()
                print("  Converted to NurbsCurve!")
                print(f"  Length={curve.GetLength()}")
            except Exception as e:
                print(f"  Failed: {e}")

if __name__ == "__main__":
    inspect_3dm("../meshes/BoomSectionSRF.3dm")
