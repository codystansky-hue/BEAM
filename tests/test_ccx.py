import os
from mesher import ProfileMesher
from materials import CompositeMaterial, Layup, assign_properties_to_mesh
from solvers import CalculiXSolver

def test_ccx():
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

    # 3. CalculiX
    ccx_path = os.path.join(project_root, 'CalculiX-Windows', 'bin', 'CalculiX-2.23.0-win-x64', 'bin', 'ccx_MT.exe')

    solver = CalculiXSolver(executable_path=ccx_path, working_dir=project_root)
    
    print("Writing INP...")
    solver.write_input_file(
        mesh_data, 
        vabs_props_dict['element_properties'],
        length=250.0,
        num_elements_z=10,
        compressive_load=-1000.0
    )
    
    print("Executing CCX...")
    solver.execute()
    factor = solver.parse_results()
    print(f"Buckling factor: {factor}")

if __name__ == "__main__":
    test_ccx()
