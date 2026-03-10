import os
import sys
import pytest
import numpy as np

# Add parent directory to path to import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mesher import ProfileMesher
from materials import CompositeMaterial, Layup, assign_properties_to_mesh
from solvers import SwiftCompSolver

def test_swiftcomp_integration():
    """Test generating a mesh, writing a .sc1 file, running SwiftComp, and parsing the 6x6 matrix."""
    
    # 1. Mesh
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    mesher = ProfileMesher(
        os.path.join(project_root, "meshes", "BoomSectionCRV.3dm"),
        thickness=0.25,
        num_elements_thickness=2,
        element_size_along_curve=2.0
    )
    mesh_data = mesher.generate()

    # 2. Material
    mat = CompositeMaterial(E11=140e9, E22=10e9, G12=5e9, nu12=0.3, density=1500.0, ply_thickness=0.0625)
    layup = Layup([mat, mat, mat, mat], [0, 45, -45, 90])
    vabs_props_dict = assign_properties_to_mesh(mesh_data, layup)

    # 3. SwiftComp
    sc_path = os.path.join(project_root, 'Swiftcomp', 'SwiftComp.exe')
    
    # Check if executable exists, otherwise skip
    if not os.path.exists(sc_path):
        pytest.skip(f"SwiftComp executable not found at {sc_path}")
        
    solver = SwiftCompSolver(executable_path=sc_path, working_dir=project_root)
    
    print("Writing SC1...")
    solver.write_input_file(
        mesh_data, 
        vabs_props_dict['element_properties']
    )
    
    assert os.path.exists(solver.input_filename), "SwiftComp .sc1 input file should be generated"
    
    print("Executing SwiftComp...")
    solver.execute()
    
    # Check for the stiffness matrix
    stiffness_matrix = solver.parse_results()
    
    assert stiffness_matrix is not None, "Stiffness matrix failed to parse"
    assert isinstance(stiffness_matrix, np.ndarray), "Returned stiffness matrix is not a numpy array"
    assert stiffness_matrix.shape == (6, 6), "Stiffness matrix is not 6x6"

if __name__ == "__main__":
    test_swiftcomp_integration()
