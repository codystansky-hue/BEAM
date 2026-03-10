import numpy as np
import os
from mesher import ProfileMesher
from materials import CompositeMaterial, Layup, assign_properties_to_mesh
from solvers import SwiftCompSolver, GXBeamSolver, CalculiXSolver

def main():
    filename = "../meshes/BoomSectionSRF.3dm"
    if not os.path.exists(filename):
        print(f"{filename} not found. Cannot run test.")
        return
        
    print("--- 1. Meshing ---")
    mesher = ProfileMesher(filename, thickness=0.5, num_elements_thickness=2, element_size_along_curve=5.0)
    mesh_data = mesher.generate()
    nodes = mesh_data['nodes']
    elements = mesh_data['elements']
    
    print("--- 2. Materials ---")
    cm = CompositeMaterial(E11=150e9, E22=10e9, G12=5e9, nu12=0.3, density=1600.0, ply_thickness=0.25, cte11=-0.5e-6, cte22=30e-6)
    layup = Layup([cm, cm], [0.0, 90.0])
    vabs_props_dict = assign_properties_to_mesh(mesh_data, layup)
    
    print("--- 3. SwiftComp Homogenization ---")
    sc = SwiftCompSolver(executable_path='Swiftcomp/SwiftComp.exe')
    sc.write_input_file(mesh_data, vabs_props_dict['element_properties'])
    try:
        sc.execute()
        k_matrix = sc.parse_results()
        print(f"K Matrix: {k_matrix[0,0]}")
    except Exception as e:
        print(f"SwiftComp failed, using Identity Matrix as fallback. Error: {e}")
        k_matrix = np.eye(6)
    
    temp_max_x = 102.51
    temp_min_x = -31.85
    temp_ref = 20.0
    pts = nodes[:, :2]
    x_min, x_max = np.min(pts[:, 0]), np.max(pts[:, 0])
    
    F_th = 0.0
    M2_th = 0.0 
    M3_th = 0.0 
    
    for i, elem in enumerate(elements):
        elem_pts = pts[elem]
        xc, yc = np.mean(elem_pts[:, 0]), np.mean(elem_pts[:, 1])
        if x_max > x_min:
            fraction = (xc - x_min) / (x_max - x_min)
            T_c = temp_min_x + fraction * (temp_max_x - temp_min_x)
        else:
            T_c = temp_max_x
        dT = T_c - temp_ref
        
        x0, y0 = elem_pts[0]
        x1, y1 = elem_pts[1]
        x2, y2 = elem_pts[2]
        x3, y3 = elem_pts[3]
        A_e = 0.5 * abs((x0*y1 - x1*y0) + (x1*y2 - x2*y1) + (x2*y3 - x3*y2) + (x3*y0 - x0*y3))
        
        prop = vabs_props_dict['element_properties'][i]
        avg_E11 = np.mean([p['material'].E11 for p in prop['layup']])
        avg_cte11 = np.mean([p['material'].cte11 for p in prop['layup']])
        
        A_e_m2 = A_e * 1e-6
        dF = avg_E11 * avg_cte11 * dT * A_e_m2
        F_th += dF
        M2_th += dF * (yc * 1e-3)
        M3_th += dF * (xc * 1e-3)
        
    print(f"Thermal Loads computed -> Fx={F_th:.2f} M2={M2_th:.2f} M3={M3_th:.2f}")
    
    print("--- 4. GXBeam ---")
    gxb = GXBeamSolver(stiffness_matrix=k_matrix)
    gxb.tip_load = [F_th, 0.0, 0.0, 0.0, M2_th, M3_th]
    gxb.write_input_file()
    gxb.execute()
    defs, _ = gxb.parse_results()
    print(f"GXBeam Deflections -> U3={defs[2]}")
    
    print("--- 5. CalculiX Snippet ---")
    ccx = CalculiXSolver(executable_path='CalculiX-Windows/bin/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe')
    ccx.write_input_file(mesh_data, vabs_props_dict['element_properties'], temp_min_x=temp_min_x, temp_max_x=temp_max_x, temp_ref=temp_ref, num_elements_z=2)
    ccx.execute()
    eig = ccx.parse_results()
    print(f"Buckling eigenvalue -> {eig}")
    print("DONE YAY")

if __name__ == '__main__':
    main()
