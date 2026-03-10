from mesher import ProfileMesher

def main():
    filename = "meshes/BoomSectionSRF.3dm"
    print(f"Loading geometry from {filename}...")
    
    try:
        mesher = ProfileMesher(filename, thickness=0.25, num_elements_thickness=2)
        mesh_data = mesher.generate()
        
        nodes = mesh_data['nodes']
        elements = mesh_data['elements']
        tangents = mesh_data['tangents']
        
        print("\\n--- Mesher Results ---")
        print(f"Number of nodes generated: {len(nodes)}")
        print(f"Number of elements generated: {len(elements)}")
        print(f"Number of computed tangents: {len(tangents)}")
        
        import numpy as np
        print(f"X bounds: [{np.min(nodes[:,0]):.4f}, {np.max(nodes[:,0]):.4f}]")
        print(f"Y bounds: [{np.min(nodes[:,1]):.4f}, {np.max(nodes[:,1]):.4f}]")
        print(f"Z bounds: [{np.min(nodes[:,2]):.4f}, {np.max(nodes[:,2]):.4f}]")
        print("Success!")
        
    except Exception as e:
        print(f"Failed to mesh the provided geometry: {e}")

if __name__ == "__main__":
    main()
