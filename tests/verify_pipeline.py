import os, sys
sys.path.insert(0, '.')
from mesher import ProfileMesher
from materials import CompositeMaterial, Layup, assign_properties_to_mesh
from solvers import SwiftCompSolver
import sgio, numpy as np

# Mesh
mesher = ProfileMesher('../meshes/BoomSectionCRV.3dm', thickness=0.25, num_elements_thickness=2, element_size_along_curve=2.0)
mesh_data = mesher.generate()
nodes = mesh_data['nodes']
print(f"Mesh X range: {nodes[:,0].min():.2f} to {nodes[:,0].max():.2f} mm (width={nodes[:,0].max()-nodes[:,0].min():.2f})")
print(f"Mesh Y range: {nodes[:,1].min():.2f} to {nodes[:,1].max():.2f} mm (height={nodes[:,1].max()-nodes[:,1].min():.2f})")
num_nodes = len(nodes)
num_elems = len(mesh_data['elements'])
print(f"Nodes: {num_nodes}, Elements: {num_elems}")

# Material
mat = CompositeMaterial(E11=140e9, E22=10e9, G12=5e9, nu12=0.3, density=1500.0, ply_thickness=0.125)
layup = Layup([mat, mat, mat, mat], [0, 45, -45, 90])
vabs_props = assign_properties_to_mesh(mesh_data, layup)

# SwiftComp
sc_path = os.path.join(os.getcwd(), 'Swiftcomp', 'SwiftComp.exe')
solver = SwiftCompSolver(executable_path=sc_path, working_dir=os.getcwd())
solver.write_input_file(mesh_data, vabs_props['element_properties'])
solver.execute()

# Parse
K = solver.parse_results()
EA = K[0,0]
EI22 = K[4,4]
EI33 = K[5,5]
print(f"\nEA = {EA:.4e} N")
print(f"EI22 = {EI22:.4e} N.mm^2 = {EI22/1e6:.4e} N.m^2")
print(f"EI33 = {EI33:.4e} N.mm^2 = {EI33/1e6:.4e} N.m^2")

L_m = 13.0
P22 = (np.pi**2 * (EI22/1e6)) / (4 * L_m**2)
P33 = (np.pi**2 * (EI33/1e6)) / (4 * L_m**2)
print(f"\nEuler (13m cantilever):")
print(f"  P_cr_22 = {P22:.1f} N = {P22/1000:.4f} kN")
print(f"  P_cr_33 = {P33:.1f} N = {P33/1000:.4f} kN")
print(f"  Limit   = {min(P22,P33)/1000:.4f} kN")
