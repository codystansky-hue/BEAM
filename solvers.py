import numpy as np
import subprocess
import os
import re
import json
import logging
import sgio

log = logging.getLogger(__name__)


def _rodrigues(rv):
    """Build a 3×3 rotation matrix from a rotation vector via Rodrigues' formula.

    Parameters
    ----------
    rv : array-like, shape (3,)
        Rotation vector whose direction is the rotation axis and whose
        magnitude is the rotation angle in radians.

    Returns
    -------
    R : ndarray, shape (3, 3)
    """
    rv = np.asarray(rv, dtype=float)
    theta = np.linalg.norm(rv)
    if theta < 1e-12:
        return np.eye(3)
    k = rv / theta
    K = np.array([[0, -k[2], k[1]],
                  [k[2], 0, -k[0]],
                  [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)

class VABSSolver:
    def __init__(self, executable_path='vabs.exe', working_dir='.'):
        self.exe = os.path.abspath(executable_path) if os.path.dirname(executable_path) else executable_path
        self.wd = working_dir
        self.input_filename = os.path.join(self.wd, 'vabs_input.dat')
        self.output_filename = os.path.join(self.wd, 'vabs_input.K')
        
    def write_input_file(self, mesh_data, element_properties):
        """
        Write VABS input text format.
        mesh_data: dict with 'nodes', 'elements'
        element_properties: material definitions per element from materials.py
        """
        nodes = mesh_data['nodes']
        elements = mesh_data['elements']
        
        # 1. Boilerplate header
        # VABS format is extremely strict regarding formatting and node numbering.
        # Format typical for cross-sectional analysis
        
        num_nodes = len(nodes)
        num_elements = len(elements)
        # Material mapping will depend on how many unique layups exist, 
        # but for this generic composite shell let's define individual materials 
        # inline or collect unique ones if necessary. We assume orthotropic (type 1 or similar).
        
        with open(self.input_filename, 'w') as f:
            f.write(f"1\n") # format = 1 for VABS cross-section analysis
            f.write(f"{num_nodes} {num_elements} 1 0 0 0\n") # num_nodes, num_elems, num_materials (dummy), recovery, thermal, etc.
            
            # Nodes section
            for i, node in enumerate(nodes):
                f.write(f"{i+1} {node[0]:.6e} {node[1]:.6e}\n")
                
            # Element section (assuming 4-node quads)
            for i, elem in enumerate(elements):
                # VABS typically expects element ID, material ID, and node IDs
                # Here we mock material ID as 1 and write the 4 nodes (+1 for 1-indexing)
                f.write(f"{i+1} 1") 
                for n_idx in elem:
                    f.write(f" {n_idx+1}")
                f.write("\n")
                
            # Material/Layup sections
            # This is highly specific to VABS version and exact composite input style (e.g. 1D lamina vs 3D solid)
            # Below is a skeletal representation of mapping element properties
            f.write("1\n") # One global composite layup or list of layer properties
            
            for props in element_properties:
                # E.g. write out orientation per element
                f.write(f"Element {props['element_id']} layups:\n")
                for ply in props['layup']:
                    # Write G_12, E_11, etc. based on ply.material and ply.global_angle
                    mat = ply['material']
                    f.write(f"{mat.E11} {mat.E22} {mat.G12} {mat.nu12} {mat.density} {mat.ply_thickness} {ply['global_angle']:.2f}\n")
                    
        return self.input_filename

    def execute(self):
        """Run VABS executable with error bubbling."""
        if not os.path.exists(self.exe):
            raise FileNotFoundError(f"VABS executable not found at {self.exe}")

        log.info("VABS: launching %s", self.exe)
        try:
            env = os.environ.copy()
            cpu = str(os.cpu_count() or 4)
            env.update({'OMP_NUM_THREADS': cpu, 'NUMBER_OF_CPUS': cpu, 'JULIA_NUM_THREADS': cpu})
            result = subprocess.run([self.exe, self.input_filename],
                           cwd=self.wd,
                           check=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,
                           text=True,
                           env=env)
            log.info("VABS: finished OK")
            if result.stdout.strip():
                log.debug("VABS stdout:\n%s", result.stdout.strip())
            return True
        except subprocess.CalledProcessError as e:
            log.error("VABS failed (exit %s):\n  stdout: %s\n  stderr: %s",
                      e.returncode, e.stdout.strip(), e.stderr.strip())
            raise RuntimeError(f"VABS execution failed: {e}\\nStderr: {e.stderr}\\nStdout: {e.stdout}")

    def parse_results(self):
        """
        Parse the VABS .K file using SGIO and return a 6x6 beam stiffness matrix.
        """
        if not os.path.exists(self.output_filename):
            raise FileNotFoundError(f"VABS output file not found at {self.output_filename}")
        log.info("VABS: parsing output %s", self.output_filename)
            
        try:
            # 'vabs' format, 'BM1' = Timoshenko Beam Model
            model = sgio.readOutputModel(self.output_filename, 'vabs', 'BM1')
            K6 = np.array(model.stff)
            
            if K6.shape != (6, 6):
                # VABS might return 4x4 if its a classical run, but we expect 6x6
                if K6.shape == (4, 4):
                    # Pad to 6x6
                    Kfull = np.zeros((6, 6))
                    Kfull[0,0] = K6[0,0] # EA
                    Kfull[3,3] = K6[1,1] # GJ
                    Kfull[4,4] = K6[2,2] # EI22
                    Kfull[5,5] = K6[3,3] # EI33
                    return Kfull
                raise ValueError(f"Expected 6x6 matrix from SGIO, got {K6.shape}")
                
            return K6
            
        except Exception as e:
            raise RuntimeError(f"SGIO failed to parse VABS results: {e}")


class GXBeamSolver:
    def __init__(self, stiffness_matrix, span=13.0, executable_path='julia', working_dir='.'):
        self.stiffness_matrix = stiffness_matrix
        self.span = span
        self.exe = os.path.abspath(executable_path) if os.path.dirname(executable_path) else executable_path
        self.wd = working_dir
        self.input_filename = os.path.join(self.wd, 'gxbeam_input.json')
        self.output_filename = os.path.join(self.wd, 'gxbeam_output.json')
        self.solver_script = os.path.abspath('gxbeam_solver.jl')
        self.tip_load = [0.0, 0.0, -1000.0, 0.0, 0.0, 0.0]
        self.bc_type = "cantilever"  # cantilever, pinned-pinned, fixed-pinned, fixed-fixed
        self.distributed_moment = [0.0, 0.0, 0.0]   # [mx, my, mz] per unit length (Nm/m)
        self.distributed_force_x = 0.0                # fx per unit length (N/m)
        self.nelem = 20

    def write_input_file(self):
        """Write JSON input for the Julia GXBeam wrapper."""
        data = {
            "stiffness_matrix": self.stiffness_matrix.tolist(),
            "span": float(self.span),
            "tip_load": self.tip_load,
            "nelem": self.nelem,
            "bc_type": self.bc_type,
            "distributed_moment": self.distributed_moment,
            "distributed_force_x": self.distributed_force_x,
        }
        with open(self.input_filename, 'w') as f:
            json.dump(data, f, indent=4)

        return self.input_filename
        
    def execute(self):
        """Run Julia script silently with multi-threading."""
        julia_cwd = os.path.dirname(self.solver_script)
        log.info("GXBeam: launching Julia (multi-threaded) — %s", self.solver_script)
        try:
            cpu = str(os.cpu_count() or 4)
            env = os.environ.copy()
            env.update({
                'OMP_NUM_THREADS': cpu,
                'NUMBER_OF_CPUS': cpu,
                'JULIA_NUM_THREADS': cpu
            })
            # Use -t or --threads for Julia multi-threading
            result = subprocess.run(
                [self.exe, "--threads", cpu, self.solver_script, self.input_filename, self.output_filename],
                cwd=julia_cwd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env)
            log.info("GXBeam: finished OK")
            if result.stdout.strip():
                log.info("GXBeam stdout:\n%s", result.stdout.strip())
            if result.stderr.strip():
                log.debug("GXBeam stderr:\n%s", result.stderr.strip())
            return True
        except subprocess.CalledProcessError as e:
            stdout_msg = e.stdout.strip() if e.stdout else ""
            stderr_msg = e.stderr.strip() if e.stderr else ""
            log.error("GXBeam failed (exit %s)\nstdout: %s\nstderr: %s",
                      e.returncode, stdout_msg, stderr_msg)
            raise RuntimeError(
                f"GXBeam failed (exit {e.returncode}): {stdout_msg or stderr_msg}"
            )
        except FileNotFoundError:
            log.error("GXBeam: Julia executable not found at %s", self.exe)
            raise FileNotFoundError(f"Julia executable not found at: {self.exe}")

    def parse_results(self):
        """Extract global tip deflections and VTK path."""
        if not os.path.exists(self.output_filename):
            raise FileNotFoundError(f"GXBeam output not found at {self.output_filename}")
        log.info("GXBeam: parsing output %s", self.output_filename)
            
        with open(self.output_filename, 'r') as f:
            output_data = json.load(f)
            
        deflections = np.array([
            output_data.get("u1", 0.0),
            output_data.get("u2", 0.0),
            output_data.get("u3", 0.0),
            output_data.get("rot1", 0.0),
            output_data.get("rot2", 0.0),
            output_data.get("rot3", 0.0)
        ])
        
        vtk_path = output_data.get("vtk_path", None)
            
        return deflections, vtk_path

    def write_deformed_beam_vtk(self, mesh_data, deflections, vtk_path, gxbeam_output=None):
        """
        Write a full 3D deformed beam VTK by sweeping the 2D cross-section
        along the deflected beam axis.

        Uses per-node GXBeam displacement/rotation arrays when available
        (from ``gxbeam_output``), otherwise falls back to shape-function
        interpolation from tip values.

        Parameters
        ----------
        mesh_data      : dict with 'nodes' (N,3) and 'elements' (M,4)
        deflections    : [u1, u2, u3, rot1, rot2, rot3] at beam tip (SI)
        vtk_path       : output file path
        gxbeam_output  : dict with 'all_u' and 'all_theta' per-node arrays
        """
        nodes_2d = mesh_data['nodes'][:, :2] / 1000.0   # mm → m
        elements = mesh_data['elements']                  # 0-based
        nn2d = len(nodes_2d)
        L = float(self.span)

        # ---- Per-station displacements & rotations ----
        if gxbeam_output and "all_u" in gxbeam_output:
            all_u = np.array(gxbeam_output["all_u"])        # (n_stations, 3)
            all_theta = np.array(gxbeam_output["all_theta"])  # (n_stations, 3)
            n_stations = len(all_u)
            zs = np.linspace(0.0, L, n_stations)
        else:
            # Fallback: shape-function interpolation from tip values
            n_stations = 30
            zs = np.linspace(0.0, L, n_stations)
            u1_tip, u2_tip, u3_tip = deflections[0], deflections[1], deflections[2]
            r1_tip, r2_tip, r3_tip = deflections[3], deflections[4], deflections[5]

            def cubic(s, u_tip):
                return u_tip * (s**2 * (3*L - s)) / (2 * L**3)

            def linear(s, u_tip):
                return u_tip * s / L

            all_u = np.zeros((n_stations, 3))
            all_theta = np.zeros((n_stations, 3))
            for i, s in enumerate(zs):
                all_u[i] = [linear(s, u1_tip), cubic(s, u2_tip), cubic(s, u3_tip)]
                all_theta[i] = [linear(s, r1_tip), linear(s, r2_tip), linear(s, r3_tip)]

        # ---- Build undeformed 3D nodes ----
        all_nodes = np.zeros((n_stations * nn2d, 3))
        for kidx, s in enumerate(zs):
            base = kidx * nn2d
            all_nodes[base:base + nn2d, 0] = nodes_2d[:, 0]
            all_nodes[base:base + nn2d, 1] = nodes_2d[:, 1]
            all_nodes[base:base + nn2d, 2] = s

        # ---- Hex elements ----
        all_elems = []
        for k in range(n_stations - 1):
            lo = k * nn2d
            hi = (k + 1) * nn2d
            for e in elements:
                n1, n2, n3, n4 = e[0], e[1], e[2], e[3]
                all_elems.append([
                    lo+n1, lo+n2, lo+n3, lo+n4,
                    hi+n1, hi+n2, hi+n3, hi+n4,
                ])

        # ---- Displacement vectors (beam u + full rotation of cross-section) ----
        # Coordinate mapping  GXBeam → VTK:
        #   GXBeam x (axial)   → VTK Z
        #   GXBeam y (lateral)  → VTK X
        #   GXBeam z (vertical) → VTK Y
        # Rotation vector mapping (same permutation):
        #   GXBeam theta_x → rotation about VTK Z
        #   GXBeam theta_y → rotation about VTK X
        #   GXBeam theta_z → rotation about VTK Y
        cx = float(np.mean(nodes_2d[:, 0]))
        cy = float(np.mean(nodes_2d[:, 1]))

        disp_vec = np.zeros((len(all_nodes), 3))
        for kidx in range(n_stations):
            u_x, u_y, u_z = all_u[kidx]          # GXBeam frame
            # Map GXBeam rotation vector to VTK frame
            rv_vtk = np.array([all_theta[kidx, 1],   # GXBeam theta_y → VTK rot-X
                               all_theta[kidx, 2],   # GXBeam theta_z → VTK rot-Y
                               all_theta[kidx, 0]])   # GXBeam theta_x → VTK rot-Z
            R = _rodrigues(rv_vtk)
            R_minus_I = R - np.eye(3)
            # Beam displacement in VTK frame
            u_vtk = np.array([u_y, u_z, u_x])

            base = kidx * nn2d
            for nidx, pt in enumerate(nodes_2d):
                # Node position relative to cross-section centroid
                local = np.array([pt[0] - cx, pt[1] - cy, 0.0])
                # Rotation-induced offset + centroid translation
                disp_vec[base + nidx] = R_minus_I @ local + u_vtk

        disp_mag = np.linalg.norm(disp_vec, axis=1)

        # ---- Write VTK ----
        n_pts = len(all_nodes)
        n_elem = len(all_elems)

        with open(vtk_path, 'w') as f:
            f.write("# vtk DataFile Version 3.0\n")
            f.write("GXBeam Deformed Beam\n")
            f.write("ASCII\n")
            f.write("DATASET UNSTRUCTURED_GRID\n")
            f.write(f"POINTS {n_pts} float\n")
            for pt in all_nodes:
                f.write(f"{pt[0]:.6f} {pt[1]:.6f} {pt[2]:.6f}\n")
            f.write(f"\nCELLS {n_elem} {n_elem * 9}\n")
            for el in all_elems:
                f.write(f"8 {el[0]} {el[1]} {el[2]} {el[3]} {el[4]} {el[5]} {el[6]} {el[7]}\n")
            f.write(f"\nCELL_TYPES {n_elem}\n")
            f.write("12\n" * n_elem)
            f.write(f"\nPOINT_DATA {n_pts}\n")
            f.write("SCALARS displacement_magnitude float 1\n")
            f.write("LOOKUP_TABLE default\n")
            for v in disp_mag:
                f.write(f"{v:.6e}\n")
            f.write("VECTORS displacement float\n")
            for v in disp_vec:
                f.write(f"{v[0]:.6e} {v[1]:.6e} {v[2]:.6e}\n")

        return vtk_path



class CalculiXSolver:
    """
    Sub-modeling workflow: extrudes the 2D cross-section into a 3D Snippet block,
    ties the faces to reference nodes, and runs a linear buckling (*BUCKLE) analysis.
    """
    def __init__(self, executable_path='ccx', working_dir='.'):
        self.exe = os.path.abspath(executable_path) if os.path.dirname(executable_path) else executable_path
        self.wd = working_dir
        self.job_name = 'snippet'
        self.input_filename = os.path.join(self.wd, f'{self.job_name}.inp')
        self.output_filename = os.path.join(self.wd, f'{self.job_name}.dat')
        
    def write_input_file(self, mesh_data, element_properties, length=250.0, num_elements_z=10, compressive_load=-1000.0, temp_min_x=0.0, temp_max_x=0.0, temp_ref=0.0, nlgeom=False, root_dofs=None, tip_dofs=None, load_angle_deg=0.0):
        """
        Extrudes 2D nodes/elements to 3D and writes the CalculiX input deck.
        Length is in mm (e.g. 250mm = ~10 inches snippet).
        root_dofs: list of DOFs (1-6) to constrain at z=0
        tip_dofs: list of DOFs (1-6) to constrain at z=length
        """
        if root_dofs is None:
            root_dofs = [1, 2, 3, 4, 5, 6]  # Default: fully clamped
        if tip_dofs is None:
            tip_dofs = []  # Default: free
        nodes_2d = mesh_data['nodes']
        elements_2d = mesh_data['elements']
        
        num_nodes_2d = len(nodes_2d)
        num_elems_2d = len(elements_2d)
        
        if num_nodes_2d == 0:
            raise ValueError("Mesh generated 0 nodes. Cannot write CalculiX deck.")
        
        # 1. Create 3D nodes by stacking Z layers
        nodes_3d = []
        z_vals = np.linspace(0, length, num_elements_z + 1)
        for z in z_vals:
            layer_nodes = nodes_2d.copy()
            layer_nodes[:, 2] = z
            nodes_3d.append(layer_nodes)
        nodes_3d = np.vstack(nodes_3d)

        # 2. Create C3D8 (8-node brick) elements
        elements_3d = []
        for k in range(num_elements_z):
            layer_offset = k * num_nodes_2d
            next_layer_offset = (k + 1) * num_nodes_2d
            
            for elem_2d in elements_2d:
                n1, n2, n3, n4 = elem_2d
                # C3D8 connects bottom face (1,2,3,4) to top face (5,6,7,8)
                b1, b2, b3, b4 = n1 + layer_offset, n2 + layer_offset, n3 + layer_offset, n4 + layer_offset
                t1, t2, t3, t4 = n1 + next_layer_offset, n2 + next_layer_offset, n3 + next_layer_offset, n4 + next_layer_offset
                # 1-based indexing for CalculiX
                elements_3d.append([b1+1, b2+1, b3+1, b4+1, t1+1, t2+1, t3+1, t4+1])

        # Cache for post-run VTK generation
        self.nodes_3d = nodes_3d
        self.elements_3d = elements_3d

        # Load angle decomposition
        # The tip load is applied at load_angle_deg from the beam span axis.
        # Beam axis = snippet Z (DOF 3).  Transverse direction = cross-section Y (DOF 2).
        # F_axial  = compressive_load * cos(theta)   → DOF 3 on reference node
        # F_trans  = compressive_load * sin(theta)   → DOF 2 on reference node
        import math as _math
        _theta = _math.radians(float(load_angle_deg))
        load_axial = compressive_load * _math.cos(_theta)
        load_trans = compressive_load * _math.sin(_theta)

        # Reference node for the remote load: located at the tip face centroid.
        # All TIP_NODES are kinematically tied to this single node via *RIGID BODY,
        # which correctly distributes the angled resultant force (and any moment)
        # to the tip face without over-constraining individual nodes.
        ref_node_id = len(nodes_3d) + 1
        x_cen_tip = float(np.mean(nodes_2d[:, 0]))
        y_cen_tip = float(np.mean(nodes_2d[:, 1]))
        z_tip = float(length)

        # 3. Write .inp Deck
        with open(self.input_filename, 'w') as f:
            f.write("*HEADING\nSub-model Snippet Buckling\n")

            f.write("*NODE, NSET=ALL_NODES\n")
            for i, p in enumerate(nodes_3d):
                f.write(f"{i+1}, {p[0]:.6f}, {p[1]:.6f}, {p[2]:.6f}\n")
            # Reference node at tip centroid (remote load application point)
            f.write(f"{ref_node_id}, {x_cen_tip:.6f}, {y_cen_tip:.6f}, {z_tip:.6f}\n")

            f.write("*ELEMENT, TYPE=C3D8, ELSET=EALL\n")
            for i, e in enumerate(elements_3d):
                f.write(f"{i+1}, {e[0]}, {e[1]}, {e[2]}, {e[3]}, {e[4]}, {e[5]}, {e[6]}, {e[7]}\n")
                
            # Extract basic material from first ply properties for the solid snippet
            # (Assuming a smeared orthotropic equivalent property for now)
            # Z is fiber direction (3), X/Y is cross-section (1,2)
            mat = element_properties[0]['layup'][0]['material']
            # We map E11 (fiber) to E33 in the 3D domain, and E22 to E11/E22.
            
            f.write("*SOLID SECTION, ELSET=EALL, MATERIAL=COMPOSITE\n")
            f.write("*MATERIAL, NAME=COMPOSITE\n")
            f.write("*ELASTIC, TYPE=ENGINEERING CONSTANTS\n")
            # CCX Fortran parser strictly limits lines to 8 variables max and has token length limits
            f.write(f"{mat.E22/1e6:.8e}, {mat.E22/1e6:.8e}, {mat.E11/1e6:.8e}, {mat.nu12:.8e}, {mat.nu12:.8e}, {mat.nu12:.8e}, {mat.G12/1e6:.8e}, {mat.G12/1e6:.8e}\n")
            f.write(f"{mat.G12/1e6:.8e}\n")
            f.write(f"*EXPANSION, TYPE=ORTHO, ZERO={temp_ref}\n")
            f.write(f"{mat.cte22:.8e}, {mat.cte22:.8e}, {mat.cte11:.8e}\n")
            f.write("*DENSITY\n")
            f.write(f"{mat.density/1e9:.8e}\n")
            
            # Write Root and Tip Node Sets for Rigid Body constraints
            f.write("*NSET, NSET=ROOT_NODES\n")
            root_node_ids = np.arange(1, num_nodes_2d + 1)
            for i in range(0, len(root_node_ids), 16):
                f.write(", ".join(map(str, root_node_ids[i:i+16])) + "\n")
                
            f.write("*NSET, NSET=TIP_NODES\n")
            tip_offset = num_elements_z * num_nodes_2d
            tip_node_ids = np.arange(1, num_nodes_2d + 1) + tip_offset
            for i in range(0, len(tip_node_ids), 16):
                f.write(", ".join(map(str, tip_node_ids[i:i+16])) + "\n")

            # Kinematically tie all tip face nodes to the reference node.
            # The reference node is the remote load application point; it carries
            # the full resultant force/moment and distributes it through the rigid body
            # constraint without over-constraining individual tip node DOFs.
            f.write(f"*RIGID BODY, REF NODE={ref_node_id}, NSET=TIP_NODES\n")

            # Pre-compute per-node temperatures for the X-gradient field
            pts_x = nodes_2d[:, 0]
            x_min_c, x_max_c = np.min(pts_x), np.max(pts_x)
            has_thermal = (abs(temp_max_x - temp_ref) > 0.01 or abs(temp_min_x - temp_ref) > 0.01)
            
            if has_thermal and mat.cte11 != 0.0:
                # CalculiX requires *INITIAL CONDITIONS, TYPE=TEMPERATURE before
                # any *TEMPERATURE card can be used in a *STATIC step.
                # Initialize all nodes at the reference temperature.
                f.write("*INITIAL CONDITIONS, TYPE=TEMPERATURE\n")
                for i in range(len(nodes_3d)):
                    f.write(f"{i+1}, {temp_ref:.2f}\n")
                
            # CalculiX does NOT allow *TEMPERATURE in a *BUCKLE step.
            # Strategy: Step 1 is a *STATIC step to build thermal pre-stress,
            # Step 2 is the *BUCKLE step that inherits the pre-stressed state
            # and applies the compressive load as the live load for eigenvalue extraction.
            
            if has_thermal and mat.cte11 != 0.0:
                # STEP 1: Static — apply thermal field to build pre-stress
                if nlgeom:
                    # NLGEOM thermal can hit bifurcation; use very small
                    # steps with line search to push through instabilities.
                    f.write("*STEP, INC=10000, NLGEOM=YES\n")
                    f.write("*STATIC\n")
                    f.write("0.005, 1.0, 1.e-20, 0.01\n")
                    f.write("*CONTROLS, PARAMETERS=LINE SEARCH\n")
                    f.write("4, 0.01, 0.5, 0.85, 0.90\n")
                else:
                    # Linear thermal: single increment, direct solve
                    f.write("*STEP\n")
                    f.write("*STATIC\n")
                    f.write("1.0, 1.0\n")
                
                f.write("*BOUNDARY\n")
                for dof in sorted(root_dofs):
                    f.write(f"ROOT_NODES, {dof}, {dof}, 0.0\n")
                # Reference node (endplate) is intentionally unconstrained: it is free to
                # translate and rotate with the beam tip.  The *RIGID BODY coupling
                # transmits the applied CLOAD to the tip face; adding displacement BCs
                # here would prevent the endplate from following the buckled shape.
                f.write("*TEMPERATURE\n")
                for i, p in enumerate(nodes_3d):
                    x = p[0]
                    if x_max_c > x_min_c:
                        fraction = (x - x_min_c) / (x_max_c - x_min_c)
                        t_val = temp_min_x + fraction * (temp_max_x - temp_min_x)
                    else:
                        t_val = temp_max_x
                    f.write(f"{i+1}, {t_val:.2f}\n")
                f.write("*NODE FILE\nU, S\n")
                f.write("*END STEP\n")
            
            # STEP 2 (or 1 if no thermal): Buckle — apply angled remote load
            f.write("*STEP\n")
            f.write("*BUCKLE\n")
            f.write("1\n")  # Number of eigenvalues requested

            f.write("*BOUNDARY\n")
            for dof in sorted(root_dofs):
                f.write(f"ROOT_NODES, {dof}, {dof}, 0.0\n")
            # Endplate reference node: no displacement BCs.  Free to translate and
            # rotate with the beam tip; load is applied via CLOAD only.

            # Apply the full resultant force to the reference node only.
            # DOF 3 = beam span (axial).  DOF 2 = cross-section Y (vertical transverse).
            # The *RIGID BODY constraint distributes this to all tip face nodes.
            f.write("*CLOAD\n")
            f.write(f"{ref_node_id}, 3, {load_axial:.6f}\n")
            if abs(load_trans) > 1e-10:
                f.write(f"{ref_node_id}, 2, {load_trans:.6f}\n")
            
            f.write("*NODE FILE\nU, S\n")
            f.write("*END STEP\n")
            
        return self.input_filename
    
    def write_vtk_3d(self, nodes_3d, elements_3d, vtk_path):
        """
        Write the 3D snippet mesh to a VTK legacy ASCII file for ParaView inspection.
        nodes_3d:    numpy array (N, 3) - X, Y, Z in mm (converted to m on write)
        elements_3d: list of 8-entry lists with 1-based node indices (C3D8)
        """
        n_nodes = len(nodes_3d)
        n_elems = len(elements_3d)
        with open(vtk_path, 'w') as f:
            f.write("# vtk DataFile Version 3.0\n")
            f.write("CalculiX C3D8 Snippet Mesh\n")
            f.write("ASCII\n")
            f.write("DATASET UNSTRUCTURED_GRID\n")
            f.write(f"POINTS {n_nodes} float\n")
            for p in nodes_3d:
                # Convert mm → m to match beam VTK coordinate space
                f.write(f"{p[0]/1000.0:.6f} {p[1]/1000.0:.6f} {p[2]/1000.0:.6f}\n")
            # VTK cell list: (8, n0..n7) in 0-based indexing
            f.write(f"\nCELLS {n_elems} {n_elems * 9}\n")
            for e in elements_3d:
                nodes_0 = [idx - 1 for idx in e]
                f.write(f"8 {' '.join(map(str, nodes_0))}\n")
            # VTK_HEXAHEDRON = 12
            f.write(f"\nCELL_TYPES {n_elems}\n")
            for _ in elements_3d:
                f.write("12\n")
        return vtk_path

    def write_mode_vtk(self, nodes_3d, elements_3d, frd_path, vtk_path):
        """
        Write the 3D snippet mesh with CalculiX eigenmode displacements baked in
        as VECTORS point data for ParaView 'Warp by Vector' filter.
        Also includes stress fields from the first static step.

        nodes_3d    : (N, 3) array — undeformed coordinates
        elements_3d : list of 8-entry lists — 1-based node indices
        frd_path    : path to CalculiX .frd results file
        vtk_path    : output VTK file path
        """
        disps = self.parse_frd_displacements(frd_path)
        stresses = self.parse_frd_stresses(frd_path)
        n_nodes = len(nodes_3d)

        # disps is a numpy array of shape (max_id, 3).
        # We only need the first n_nodes, because node IDs 1..n_nodes map to the basic mesh grid.
        disps_matched = np.zeros((n_nodes, 3))
        if disps is not None:
            limit = min(n_nodes, len(disps))
            disps_matched[:limit] = disps[:limit]
        # CalculiX outputs displacements in mm — convert to m for VTK consistency
        disps = disps_matched / 1000.0

        stresses_matched = np.zeros((n_nodes, 6))
        if stresses is not None:
            limit = min(n_nodes, len(stresses))
            stresses_matched[:limit] = stresses[:limit]
        stresses = stresses_matched

        mag = np.linalg.norm(disps, axis=1)
        
        # Von Mises calculation:
        # sqrt(0.5 * ((S11-S22)^2 + (S22-S33)^2 + (S33-S11)^2 + 6*(S12^2 + S13^2 + S23^2)))
        s11, s22, s33 = stresses[:, 0], stresses[:, 1], stresses[:, 2]
        s12, s13, s23 = stresses[:, 3], stresses[:, 4], stresses[:, 5]
        vm = np.sqrt(0.5 * ((s11-s22)**2 + (s22-s33)**2 + (s33-s11)**2 + 6*(s12**2 + s13**2 + s23**2)))

        n_elems = len(elements_3d)

        with open(vtk_path, 'w') as f:
            f.write("# vtk DataFile Version 3.0\n")
            f.write("CalculiX Buckling Mode Shape\n")
            f.write("ASCII\n")
            f.write("DATASET UNSTRUCTURED_GRID\n")
            f.write(f"POINTS {n_nodes} float\n")
            for p in nodes_3d:
                # Convert mm → m to match beam VTK coordinate space
                f.write(f"{p[0]/1000.0:.6f} {p[1]/1000.0:.6f} {p[2]/1000.0:.6f}\n")
            f.write(f"\nCELLS {n_elems} {n_elems * 9}\n")
            for e in elements_3d:
                nodes_0 = [idx - 1 for idx in e]
                f.write(f"8 {' '.join(map(str, nodes_0))}\n")
            f.write(f"\nCELL_TYPES {n_elems}\n")
            for _ in elements_3d:
                f.write("12\n")

            f.write(f"\nPOINT_DATA {n_nodes}\n")
            f.write("SCALARS displacement_magnitude float 1\n")
            f.write("LOOKUP_TABLE default\n")
            for v in mag:
                f.write(f"{v:.6e}\n")
            
            f.write("SCALARS von_mises_stress float 1\n")
            f.write("LOOKUP_TABLE default\n")
            for v in vm:
                f.write(f"{v:.6e}\n")
            
            for i, name in enumerate(['S11', 'S22', 'S33', 'S12', 'S13', 'S23']):
                f.write(f"SCALARS {name} float 1\n")
                f.write("LOOKUP_TABLE default\n")
                for v in stresses[:, i]:
                    f.write(f"{v:.6e}\n")

            f.write("VECTORS displacement float\n")
            for d in disps:
                f.write(f"{d[0]:.6e} {d[1]:.6e} {d[2]:.6e}\n")

        return vtk_path


    def execute(self):
        """Run CalculiX with error bubbling and multi-threading."""
        log.info("CalculiX: launching %s -i %s", self.exe, self.job_name)
        try:
            env = os.environ.copy()
            cpu = str(os.cpu_count() or 4)
            env.update({
                'OMP_NUM_THREADS': cpu,
                'NUMBER_OF_CPUS': cpu,
                'JULIA_NUM_THREADS': cpu
            })
            # Use -nt to specify number of threads for multi-threaded versions (e.g. ccx_MT)
            result = subprocess.run([self.exe, "-nt", cpu, "-i", self.job_name],
                           cwd=self.wd,
                           check=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,
                           text=True,
                           env=env)
            log.info("CalculiX: finished OK")
            if result.stdout.strip():
                log.debug("CalculiX stdout:\n%s", result.stdout.strip())
            return True
        except subprocess.CalledProcessError as e:
            log.error("CalculiX failed (exit %s):\n  stdout: %s\n  stderr: %s",
                      e.returncode, e.stdout.strip(), e.stderr.strip())
            raise RuntimeError(f"CalculiX execution failed: {e}\\nStderr: {e.stderr}\\nStdout: {e.stdout}")
        except FileNotFoundError:
            log.error("CalculiX: executable not found at %s", self.exe)
            raise FileNotFoundError(f"CalculiX executable not found: {self.exe}")
            
    def parse_results(self):
        """Scan the .dat file for the BUCKLING FACTOR eigenvalue."""
        log.info("CalculiX: parsing results from %s", self.output_filename)
        if not os.path.exists(self.output_filename):
            log.warning("CalculiX: output file not found — %s", self.output_filename)
            return None
            
        with open(self.output_filename, 'r') as f:
            content = f.read()
            
        # CalculiX .dat output format for buckling is a table:
        #      1   0.8675451E+00
        # We look for the FACTOR header, then grab the first numeric eigenvalue line
        if 'BUCKLING' in content.upper() and 'FACTOR' in content.upper():
            # Find lines after the header
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if 'FACTOR' in line.upper():
                    # Scan subsequent lines for the eigenvalue
                    for j in range(i+1, min(i+5, len(lines))):
                        vals = lines[j].strip().split()
                        if len(vals) >= 2:
                            try:
                                factor = float(vals[-1])
                                log.info("CalculiX: buckling factor = %.6g", factor)
                                return factor
                            except ValueError:
                                continue
        log.warning("CalculiX: no BUCKLING FACTOR found in %s", self.output_filename)
        return None

    def parse_sta_file(self):
        """Parse the .sta file to get increment-by-increment progress."""
        sta_path = os.path.join(self.wd, f'{self.job_name}.sta')
        if not os.path.exists(sta_path):
            return []
            
        history = []
        try:
            with open(sta_path, 'r') as f:
                lines = f.readlines()
                # Skip header (usually 2 lines)
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 5:
                        try:
                            # STEP INC ATT ITER TIME/STEP TIME/TOTAL
                            # Indices: 0:step, 1:inc, 2:att, 3:iter, 4:dt, 5:total_t (if present)
                            history.append({
                                "step": int(parts[0]),
                                "inc": int(parts[1]),
                                "att": int(parts[2]),
                                "iter": int(parts[3]),
                                "dt": float(parts[4]),
                                "total": float(parts[6]) if len(parts) > 6 else float(parts[5])
                            })
                        except (ValueError, IndexError):
                            continue
        except Exception as e:
            log.error(f"Failed to parse .sta file: {e}")
            
        return history

    def parse_frd_displacements(self, frd_path):
        """
        Parse CalculiX .frd result file and return the first displacement block.
        Returns ndarray shape (n_nodes, 3) or None if not found.
        The .frd format uses fixed-width lines starting with codes:
          -4  DISPR  → section header
          -1  node_id  u1  u2  u3  → per-node data
          -3            → end of block
        """
        if not os.path.exists(frd_path):
            return None
        disps = {}
        in_disp = False
        import re
        # Match standard Fortran scientific drops like -1.33449E-003 or 0.00000E+000
        # Optional minus, one digit, decimal, five digits, E, sign, 2 to 3 digits
        float_pattern = re.compile(r'-?\d\.\d{5}E[+-]\d{2,3}')
        
        try:
            with open(frd_path, 'r', errors='replace') as f:
                for line in f:
                    # -4 header: check for DISP (Translation) exactly, ignore DISPR (Rotation)
                    if line.startswith(' -4'):
                        # Reset for each block so we only keep the LAST one (the buckling mode)
                        # We look for DISP but NOT DISPR
                        u_line = line.upper()
                        if ('DISP' in u_line or ' U ' in u_line) and 'DISPR' not in u_line:
                            disps = {} # CLEAR previous step results
                            in_disp = True
                        else:
                            in_disp = False
                        continue
                        
                    if in_disp:
                        if line.startswith(' -3'):
                            in_disp = False
                            continue
                        if line.startswith(' -1'):
                            try:
                                nid_str = line[3:13].strip()
                                if not nid_str: continue
                                nid = int(nid_str)
                                
                                # Extract floats using regex to bypass Fortran spacing bugs
                                # (CalculiX overflows 12-char columns to 13-chars for negative numbers)
                                matches = float_pattern.findall(line[13:])
                                if len(matches) >= 3:
                                    u1 = float(matches[0])
                                    u2 = float(matches[1])
                                    u3 = float(matches[2])
                                    disps[nid] = [u1, u2, u3]
                            except (ValueError, IndexError):
                                continue
        except Exception:
            return None
            
        if not disps:
            return None
            
        max_id = max(disps.keys())
        arr = np.zeros((max_id, 3))
        for nid, u in disps.items():
            arr[nid - 1] = u
        return arr

    def parse_frd_stresses(self, frd_path):
        """
        Parse CalculiX .frd result file and return the FIRST stress block 
        (usually the static thermal/preload step).
        Returns ndarray shape (n_nodes, 6) or None if not found.
        Columns: [S11, S22, S33, S12, S13, S23]
        """
        if not os.path.exists(frd_path):
            return None
        stresses = {}
        in_stress = False
        found_first = False
        import re
        float_pattern = re.compile(r'-?\d\.\d{5}E[+-]\d{2,3}')
        
        try:
            with open(frd_path, 'r', errors='replace') as f:
                for line in f:
                    if line.startswith(' -4'):
                        if 'STRESS' in line.upper():
                            if found_first:
                                break # Stop after first block
                            in_stress = True
                        else:
                            in_stress = False
                        continue
                        
                    if in_stress:
                        if line.startswith(' -3'):
                            in_stress = False
                            found_first = True
                            continue
                        if line.startswith(' -1'):
                            try:
                                nid_str = line[3:13].strip()
                                if not nid_str: continue
                                nid = int(nid_str)
                                matches = float_pattern.findall(line[13:])
                                if len(matches) >= 6:
                                    # S11, S22, S33, S12, S13, S23
                                    s_vals = [float(m) for m in matches[:6]]
                                    stresses[nid] = s_vals
                            except (ValueError, IndexError):
                                continue
        except Exception:
            return None
            
        if not stresses:
            return None
            
        max_id = max(stresses.keys())
        arr = np.zeros((max_id, 6))
        for nid, s in stresses.items():
            arr[nid - 1] = s
        return arr


class CLTBeamSolver:
    """Cross-section stiffness via CLT + thin-walled closed-section beam theory.

    Replaces SwiftComp for the Stage-2 beam stiffness computation.
    Produces the same 6×6 Timoshenko stiffness matrix K that SwiftComp outputs,
    in [N, N, N, N·mm, N·mm², N·mm²] units (geometry in mm).
    """

    def __init__(self, working_dir="."):
        self.wd = working_dir

    # ------------------------------------------------------------------
    # Public API (matches SwiftCompSolver interface)
    # ------------------------------------------------------------------

    def compute_stiffness(self, mesh_data, element_properties):
        """Compute and return the 6×6 beam stiffness matrix.

        Parameters
        ----------
        mesh_data : dict with 'nodes' (N×3 mm), 'elements' (M×4), 'tangents' (M×3)
        element_properties : list[dict] from assign_properties_to_mesh

        Returns
        -------
        K : ndarray (6, 6) — units consistent with mm geometry
        """
        nodes = mesh_data["nodes"]
        elements = mesh_data["elements"]

        # ── 1. Identify spine stations ──────────────────────────────────
        # The mesh has (num_spine_pts) × (num_layers+1) nodes.
        # Each spine station is a "column" of nodes across the thickness.
        # Elements along the curve share columns; we group by unique spine index.
        # The tangent per element gives the wall direction.

        # Gather per-element centroid, arc-length ds, wall angle, and ABD
        n_elem = len(elements)
        centroids = np.zeros((n_elem, 2))
        ds_list = np.zeros(n_elem)
        wall_angles = np.zeros(n_elem)

        # We only need the unique "along-curve" elements (one thickness layer).
        # But the mesh has num_layers rows per curve segment.  We compute per-
        # element and let the integration sum everything — each element is a
        # small patch with its own ABD, centroid, and ds.

        ABD_list = []  # per-element ABD (6×6) in beam-axis coords

        for i, props in enumerate(element_properties):
            el_nodes = nodes[elements[i]]
            cx = np.mean(el_nodes[:, 0])
            cy = np.mean(el_nodes[:, 1])
            centroids[i] = [cx, cy]

            # Element edge length along the curve (average of top/bottom edges)
            # edges: 0→1 (bottom) and 3→2 (top)
            e01 = np.linalg.norm(el_nodes[1, :2] - el_nodes[0, :2])
            e32 = np.linalg.norm(el_nodes[2, :2] - el_nodes[3, :2])
            ds_list[i] = 0.5 * (e01 + e32)

            # Wall angle from tangent vector
            tang = mesh_data["tangents"][i]
            wall_angles[i] = np.arctan2(tang[1], tang[0])

            # Build ABD for this element's laminate
            ABD_list.append(self._element_ABD(props))

        # ── 2. Section centroid (area-weighted) ─────────────────────────
        A11_ds = np.array([abd[0, 0] * ds for abd, ds in zip(ABD_list, ds_list)])
        total_EA_weight = np.sum(A11_ds)
        if total_EA_weight < 1e-30:
            raise ValueError("CLT solver: zero axial stiffness — check materials")

        yc = np.sum(A11_ds * centroids[:, 0]) / total_EA_weight
        zc = np.sum(A11_ds * centroids[:, 1]) / total_EA_weight

        # Shift centroids to section centroid
        dy = centroids[:, 0] - yc
        dz = centroids[:, 1] - zc

        # ── 3. Assemble beam stiffness terms ────────────────────────────
        EA = 0.0
        EIyy = 0.0  # bending about y → uses z² (vertical)
        EIzz = 0.0  # bending about z → uses y² (lateral)
        EIyz = 0.0
        ESy = 0.0   # extension-bending coupling (y)
        ESz = 0.0   # extension-bending coupling (z)

        # Torsion: Bredt–Batho for closed section
        # Shear: shear flow for closed section
        inv_A66t_ds = 0.0  # ∮ ds / (A₆₆·t) for Bredt denominator

        # Shear stiffness accumulators
        GA2_acc = 0.0  # lateral shear
        GA3_acc = 0.0  # vertical shear

        for i in range(n_elem):
            abd = ABD_list[i]
            ds = ds_list[i]
            theta = wall_angles[i]
            s2 = np.sin(theta) ** 2
            c2 = np.cos(theta) ** 2
            sc = np.sin(theta) * np.cos(theta)

            a11 = abd[0, 0]  # axial membrane stiffness (per unit width)
            a66 = abd[2, 2]  # in-plane shear stiffness
            d11 = abd[3, 3]  # wall bending stiffness

            EA += a11 * ds
            ESy += a11 * ds * dy[i]
            ESz += a11 * ds * dz[i]
            EIyy += a11 * ds * dz[i] ** 2 + d11 * ds * s2
            EIzz += a11 * ds * dy[i] ** 2 + d11 * ds * c2
            EIyz += a11 * ds * dy[i] * dz[i] + d11 * ds * sc

            # Bredt: need element "thickness" for shear — use laminate total t
            t_elem = self._laminate_thickness(element_properties[i])
            if a66 > 1e-30 and t_elem > 1e-30:
                inv_A66t_ds += ds / (a66 * t_elem)

            # Shear stiffness (projected)
            GA2_acc += a66 * ds * s2   # lateral
            GA3_acc += a66 * ds * c2   # vertical

        # ── 4. Enclosed area for Bredt torsion ──────────────────────────
        A_enc = self._enclosed_area(centroids)

        if inv_A66t_ds > 1e-30:
            GJ = 4.0 * A_enc ** 2 / inv_A66t_ds
        else:
            GJ = 0.0

        # ── 5. Assemble 6×6 K ──────────────────────────────────────────
        # Order: [F1(axial), F2(lat shear), F3(vert shear),
        #         M1(torsion), M2(bending-y), M3(bending-z)]
        K = np.zeros((6, 6))

        K[0, 0] = EA
        K[1, 1] = GA2_acc
        K[2, 2] = GA3_acc
        K[3, 3] = GJ
        K[4, 4] = EIyy
        K[5, 5] = EIzz

        # Off-diagonal coupling
        K[4, 5] = K[5, 4] = EIyz
        K[0, 4] = K[4, 0] = ESz   # axial ↔ bending-y
        K[0, 5] = K[5, 0] = ESy   # axial ↔ bending-z

        log.info(
            "CLT solver: EA=%.4e, EI22=%.4e, EI33=%.4e, GJ=%.4e, "
            "GA2=%.4e, GA3=%.4e, A_enc=%.2f mm²",
            EA, EIyy, EIzz, GJ, GA2_acc, GA3_acc, A_enc,
        )

        return K

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _Q_matrix(E11, E22, G12, nu12):
        """Reduced stiffness matrix Q for a single orthotropic ply (3×3)."""
        nu21 = nu12 * E22 / E11
        denom = 1.0 - nu12 * nu21
        Q = np.zeros((3, 3))
        Q[0, 0] = E11 / denom
        Q[1, 1] = E22 / denom
        Q[0, 1] = Q[1, 0] = nu12 * E22 / denom
        Q[2, 2] = G12
        return Q

    @staticmethod
    def _transform_Q(Q, angle_deg):
        """Transform Q into Q̄ at a given angle (degrees) using standard CLT rotation."""
        theta = np.radians(angle_deg)
        c = np.cos(theta)
        s = np.sin(theta)
        c2, s2, cs = c * c, s * s, c * s

        T_inv = np.array([
            [c2,   s2,   2 * cs],
            [s2,   c2,  -2 * cs],
            [-cs,  cs,   c2 - s2],
        ])

        # Reuter's matrix adjustment for engineering shear strain
        R = np.diag([1.0, 1.0, 2.0])
        R_inv = np.diag([1.0, 1.0, 0.5])

        Qbar = T_inv @ Q @ R @ T_inv.T @ R_inv
        return Qbar

    def _element_ABD(self, props):
        """Compute ABD matrix (6×6) for an element's laminate.

        The ABD is computed in the beam-axis coordinate system (1 = beam axis,
        2 = along wall tangent) by using each ply's global_angle which already
        includes the wall tangent rotation.
        """
        layup = props["layup"]
        n_plies = len(layup)

        # Total laminate thickness and ply z-coordinates from mid-surface
        t_total = sum(p["thickness"] for p in layup)
        z_bot = -t_total / 2.0

        A = np.zeros((3, 3))
        B = np.zeros((3, 3))
        D = np.zeros((3, 3))

        z_k = z_bot
        for ply in layup:
            mat = ply["material"]
            t_k = ply["thickness"]
            angle = ply["global_angle"]

            Q = self._Q_matrix(mat.E11, mat.E22, mat.G12, mat.nu12)
            # Material properties are in Pa; convert to N/mm² (MPa) for mm geometry
            Qbar = self._transform_Q(Q, angle) / 1e6

            z_top = z_k + t_k
            z_mid = 0.5 * (z_k + z_top)

            A += Qbar * t_k
            B += Qbar * t_k * z_mid
            D += Qbar * (t_k * z_mid ** 2 + t_k ** 3 / 12.0)

            z_k = z_top

        ABD = np.zeros((6, 6))
        ABD[:3, :3] = A
        ABD[:3, 3:] = B
        ABD[3:, :3] = B
        ABD[3:, 3:] = D
        return ABD

    @staticmethod
    def _laminate_thickness(props):
        """Total laminate thickness from element properties."""
        return sum(p["thickness"] for p in props["layup"])

    @staticmethod
    def _enclosed_area(centroids):
        """Enclosed area of the contour defined by element centroids (Shoelace).

        For a closed thin-walled section the centroids trace the mid-surface
        contour.  We sort them by angle from the geometric center, then apply
        the shoelace formula.
        """
        cx = np.mean(centroids[:, 0])
        cy = np.mean(centroids[:, 1])

        angles = np.arctan2(centroids[:, 1] - cy, centroids[:, 0] - cx)
        order = np.argsort(angles)
        pts = centroids[order]

        n = len(pts)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += pts[i, 0] * pts[j, 1] - pts[j, 0] * pts[i, 1]
        return abs(area) / 2.0


class SwiftCompSolver:
    def __init__(self, executable_path='Swiftcomp/SwiftComp.exe', working_dir='.'):
        self.exe = os.path.abspath(executable_path) if os.path.dirname(executable_path) else executable_path
        self.wd = working_dir
        self.job_name = 'beam'
        self.input_filename = os.path.join(self.wd, f'{self.job_name}.sc1')
        self.output_filename = os.path.join(self.wd, f'{self.job_name}.sc1.k')
        
    def write_input_file(self, mesh_data, element_properties):
        """
        Write a SwiftComp .sc1 file in the proven beam2D.sc1 format:
          - Header: model, curvatures, oblique, analysis flags
          - Count line: nSG nnode nelem nmate 0 0
          - Nodes, then Q8 elements (4 corners + 4 midside nodes per elem)
          - Orthotropic material: T rho / E1 E2 E3 / G12 G13 G23 / nu12 nu13 nu23
            (NO CTE lines — those crash SwiftComp for orth=1 beam analysis)
          - SG volume line (= cross-section area in mm^2) — required for orth=1
        UNITS: geometry in mm, so moduli must be in N/mm^2 = MPa.
        """
        nodes    = mesh_data['nodes']
        elements = mesh_data['elements']
        nodes_xy = nodes[:, :2]
        num_q4   = len(nodes_xy)

        # -- Build compact material table --
        mat_map  = {}
        mat_list = []
        elem_mat_ids = []
        for props in element_properties:
            mat = props['layup'][0]['material']
            key = (mat.E11, mat.E22, mat.G12, mat.nu12, mat.density)
            if key not in mat_map:
                mat_map[key] = len(mat_list) + 1
                mat_list.append(mat)
            elem_mat_ids.append(mat_map[key])
        num_materials = len(mat_list)

        # -- Upgrade Q4 → Q8 by inserting midpoint nodes on each unique edge --
        edge_to_mid = {}
        mid_coords  = []

        def get_mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in edge_to_mid:
                edge_to_mid[key] = len(mid_coords)
                mx = 0.5 * (nodes_xy[a, 0] + nodes_xy[b, 0])
                my = 0.5 * (nodes_xy[a, 1] + nodes_xy[b, 1])
                mid_coords.append((mx, my))
            return edge_to_mid[key]

        q8_elems = []  # list of (mat_id, [c1,c2,c3,c4,m12,m23,m34,m41])
        for i, elem in enumerate(elements):
            c1, c2, c3, c4 = elem[0], elem[1], elem[2], elem[3]
            m12 = get_mid(c1, c2)
            m23 = get_mid(c2, c3)
            m34 = get_mid(c3, c4)
            m41 = get_mid(c4, c1)
            q8_elems.append((elem_mat_ids[i], [c1, c2, c3, c4, m12, m23, m34, m41]))

        num_mid = len(mid_coords)
        total_nodes = num_q4 + num_mid
        total_elems = len(q8_elems)

        # -- Compute SG cross-section area via shoelace (Q4 centroids) --
        # SwiftComp requires this as the volume line for orthotropic beam SG
        sg_area = 0.0
        for elem in elements:
            pts = nodes_xy[[elem[0], elem[1], elem[2], elem[3]]]
            # shoelace for quad
            n = len(pts)
            for j in range(n):
                j2 = (j + 1) % n
                sg_area += pts[j, 0] * pts[j2, 1] - pts[j2, 0] * pts[j, 1]
        sg_area = abs(sg_area) / 2.0
        log.debug("SwiftComp: SG cross-section area = %.4f mm²", sg_area)

        with open(self.input_filename, 'w') as f:
            # Header (tab-separated to match beam2D.sc1)
            f.write('1\t!\tmodel: 0-classical, 1-shear refined\n')
            f.write('0\t0\t0\t!\tinitial curvatures\n')
            f.write('1\t0\t!\toblique parameters\n')
            f.write('\n')
            f.write('0\t0\t0\t0\t!\tanalysis elem_flag trans_flag temp_flag\n')
            f.write('\n')

            # Count line: nSG=2 (2D cross-section)
            f.write(f'2 {total_nodes:8d} {total_elems:8d} {num_materials:2d}  0   0\n')
            f.write('\n')

            # Nodes: original Q4 corners, then midside nodes
            for i in range(num_q4):
                f.write(f'{i+1:6d}  {nodes_xy[i,0]:14.6f}  {nodes_xy[i,1]:14.6f}\n')
            for j, (mx, my) in enumerate(mid_coords):
                f.write(f'{num_q4+j+1:6d}  {mx:14.6f}  {my:14.6f}\n')
            f.write('\n')

            # Q8 elements: elemID matID c1 c2 c3 c4 m12 m23 m34 m41 0
            for i, (mid_id, conn) in enumerate(q8_elems):
                c1, c2, c3, c4 = conn[0]+1, conn[1]+1, conn[2]+1, conn[3]+1
                m12 = conn[4] + num_q4 + 1
                m23 = conn[5] + num_q4 + 1
                m34 = conn[6] + num_q4 + 1
                m41 = conn[7] + num_q4 + 1
                f.write(f'{i+1:6d} {mid_id} {c1:6d} {c2:6d} {c3:6d} {c4:6d}'
                        f' {m12:6d} {m23:6d} {m34:6d} {m41:6d}  0\n')
            f.write('\n')

            # Material section — orthotropic (orth=1), 1 temperature set
            # CRITICAL: for orth=1 beam SG, SwiftComp needs EXACTLY:
            #   Line 1: matID  orth=1  ntemp=1
            #   Line 2: T(K)  density(t/mm3)   [t/mm3 = kg/m3 / 1e9]
            #   Line 3: E1  E2  E3  (MPa)
            #   Line 4: G12  G13  G23  (MPa)
            #   Line 5: nu12  nu13  nu23
            #   NO CTE lines — they cause an I/O error + NaN
            # After ALL materials: one SG volume line (area in mm2)
            for i, mat in enumerate(mat_list):
                rho_t  = mat.density / 1e9   # kg/m3 → t/mm3
                E1_mpa = mat.E11 / 1e6        # Pa → MPa
                E2_mpa = mat.E22 / 1e6
                G_mpa  = mat.G12 / 1e6
                nu     = mat.nu12
                # Single line format for 9 engineering constants
                f.write(f'{i+1} 1  1\n')
                f.write(f'0.0  {rho_t:.6e}\n')
                f.write(f'{E1_mpa:.6e} {E2_mpa:.6e} {E2_mpa:.6e} ')
                f.write(f'{G_mpa:.6e} {G_mpa:.6e} {G_mpa:.6e} ')
                f.write(f'{nu:.6f} {nu:.6f} {nu:.6f}\n')
            f.write('\n')
            # SG volume = cross-section area in mm^2 (required for orth=1)
            f.write(f'{sg_area:.6f}\n')

        return self.input_filename


    def execute(self):
        """Run SwiftComp executable with error bubbling."""
        if not os.path.exists(self.exe):
            raise FileNotFoundError(f"SwiftComp executable not found at {self.exe}")

        log.info("SwiftComp: launching %s", self.exe)
        try:
            env = os.environ.copy()
            cpu = str(os.cpu_count() or 4)
            env.update({'OMP_NUM_THREADS': cpu, 'NUMBER_OF_CPUS': cpu, 'JULIA_NUM_THREADS': cpu})
            result = subprocess.run([self.exe, self.input_filename, "1D", "H"],
                           cwd=self.wd,
                           check=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,
                           text=True,
                           env=env)
            log.info("SwiftComp: finished OK")
            if result.stdout.strip():
                log.debug("SwiftComp stdout:\n%s", result.stdout.strip())
            return True
        except subprocess.CalledProcessError as e:
            log.error("SwiftComp failed (exit %s):\n  stdout: %s\n  stderr: %s",
                      e.returncode, e.stdout.strip(), e.stderr.strip())
            raise RuntimeError(f"SwiftComp execution failed: {e}\\nStderr: {e.stderr}\\nStdout: {e.stdout}")
            
    def parse_results(self):
        """
        Parse the SwiftComp .k file using SGIO and return a 6x6 beam stiffness matrix.
        We use 'BM2' to specifically request the Timoshenko (shear-refined) model.
        """
        log.info("SwiftComp: parsing output %s", self.output_filename)
        if not os.path.exists(self.output_filename):
            raise FileNotFoundError(
                f"SwiftComp output not found: {self.output_filename}. "
                f"SwiftComp may have crashed silently."
            )

        try:
            # 'sc' = SwiftComp, 'BM2' = Timoshenko Beam Model
            model = sgio.readOutputModel(self.output_filename, 'sc', 'BM2')
            
            # SGIO stores the stiffness matrix in the .stff attribute as a list/array
            K6 = np.array(model.stff)
            
            if K6.shape != (6, 6):
                raise ValueError(f"Expected 6x6 matrix from SGIO, got {K6.shape}")
                
            return K6
            
        except Exception as e:
            raise RuntimeError(f"SGIO failed to parse results from {self.output_filename}: {e}")

    def write_ansys_macro(self, k_matrix, filename):
        """
        Export the 6x6 stiffness matrix to an ANSYS .mac file using SECCONTROL.
        Expects a 6x6 numpy array or nested list.
        """
        # ANSYS SECCONTROL for GENB (generalized beam) expects the upper triangular 
        # part of the stiffness matrix (21 entries).
        # Order: K11, K12, K13, K14, K15, K16, K22, K23, K24, K25, K26, 
        #        K33, K34, K35, K36, K44, K45, K46, K55, K56, K66
        coeffs = []
        for i in range(6):
            for j in range(i, 6):
                coeffs.append(k_matrix[i][j])

        with open(filename, 'w') as f:
            f.write("! ANSYS Generalized Beam Stiffness Matrix Macro\n")
            f.write("! Generated by BEAM-paraview\n")
            f.write("!\n")
            f.write("SECTYPE, 1, GENB, MESH\n")
            f.write("SECCONTROL, &\n")
            
            # Format nicely with line continuations
            for i in range(0, len(coeffs), 6):
                chunk = coeffs[i:i+6]
                line = ", ".join([f"{float(c):.10e}" for c in chunk])
                if i + 6 < len(coeffs):
                    f.write(f"  {line}, &\n")
                else:
                    f.write(f"  {line}\n")
            f.write("!\n")

        return filename


class SwiftCompMaterialSolver:
    """SwiftComp material SG: fiber+matrix → homogenized 3D lamina properties.

    UD fiber:  2D SG — N×N Q8 mesh, circular fiber in square matrix unit cell.
    Woven:     3D SG — simplified 2-element C3D20 layered model (warp + weft).

    Input format mirrors the bundled example files (micro2D.sc, micro3D.sc).
    Command: SwiftComp.exe <input>.sc 3D H
    Output:  <input>.sc.k  — parsed via sgio or text fallback.
    All properties in SI (Pa, kg/m³).
    """

    def __init__(self, executable_path="Swiftcomp/SwiftComp.exe", working_dir="."):
        self.exe = os.path.abspath(executable_path) if os.path.dirname(executable_path) else executable_path
        self.wd = working_dir
        self.job_name = "material_sg"
        self.input_filename = os.path.join(self.wd, f"{self.job_name}.sc")
        self.output_filename = os.path.join(self.wd, f"{self.job_name}.sc.k")

    # ------------------------------------------------------------------
    # UD fiber: 2D SG with circular fiber cross-section (Q8 mesh)
    # ------------------------------------------------------------------

    def _make_ud_mesh(self, vf: float, n: int = 10):
        """Generate N×N Q4→Q8 mesh of circular fiber in a square unit cell.

        Unit cell: [0, 1] × [0, 1] (y2–y3 plane; y1 = fiber direction).
        Fiber circle centred at (0.5, 0.5) with radius r = sqrt(Vf/π).
        Returns (nodes, q8_elems, mtypes):
          nodes     — list of (y2, y3) tuples (0-based)
          q8_elems  — list of 8-tuples of 0-based node indices
          mtypes    — list of 1 (fiber) or 2 (matrix) per element
        """
        r = np.sqrt(vf / np.pi)
        xs = np.linspace(0.0, 1.0, n + 1)

        # Corner nodes: row-major (j outer, i inner)
        q4_nodes = [(xs[i], xs[j]) for j in range(n + 1) for i in range(n + 1)]

        # Q4 elements with material tag
        q4_elems, mtypes = [], []
        for j in range(n):
            for i in range(n):
                bl = j * (n + 1) + i
                q4_elems.append((bl, bl + 1, bl + (n + 1) + 1, bl + (n + 1)))
                cx = (xs[i] + xs[i + 1]) / 2.0 - 0.5
                cy = (xs[j] + xs[j + 1]) / 2.0 - 0.5
                mtypes.append(1 if cx * cx + cy * cy <= r * r else 2)

        # Upgrade Q4 → Q8: insert midpoint nodes on unique edges
        nodes = list(q4_nodes)
        edge_mid: dict = {}
        q8_elems = []
        for n0, n1, n2, n3 in q4_elems:
            mids = []
            for a, b in [(n0, n1), (n1, n2), (n2, n3), (n3, n0)]:
                key = (min(a, b), max(a, b))
                if key not in edge_mid:
                    edge_mid[key] = len(nodes)
                    nodes.append(((nodes[a][0] + nodes[b][0]) / 2.0,
                                  (nodes[a][1] + nodes[b][1]) / 2.0))
                mids.append(edge_mid[key])
            # SwiftComp Q8 order: corner0–3, then mid(0-1), mid(1-2), mid(2-3), mid(3-0)
            q8_elems.append((n0, n1, n2, n3, mids[0], mids[1], mids[2], mids[3]))

        return nodes, q8_elems, mtypes

    def write_ud_input(self, fiber: dict, matrix: dict, vf: float, packing: str = "hexagonal"):
        """Write UD fiber 2D SG input file. Properties in Pa.

        Unit cell area = 1.0 (normalized). Fiber circle radius = sqrt(Vf/π).
        Uses 10×10 Q8 mesh (100 elements) which gives accurate Vf discretization.
        """
        nodes, q8_elems, mtypes = self._make_ud_mesh(vf)
        nnode, nelem = len(nodes), len(q8_elems)

        E1  = fiber["E11_t"]
        E2  = fiber["E22"]
        E3  = fiber.get("E3",  E2)
        G12 = fiber["G12"]
        G13 = fiber.get("G13", G12)
        nu12 = fiber["nu12"]
        nu13 = fiber.get("nu13", nu12)
        nu23 = fiber.get("nu23", nu12)
        G23  = fiber.get("G23", E2 / max(2.0 * (1.0 + nu23), 1e-10))
        rho_f = fiber.get("density", 0.0)

        E_m  = matrix["E_t"]
        nu_m = matrix["nu"]
        rho_m = matrix.get("density", 0.0)

        # Constituent CTEs (m/m/K); default to 0 if not in DB
        cte11_f = fiber.get("cte11", 0.0)
        cte22_f = fiber.get("cte22", 0.0)
        cte33_f = fiber.get("cte33", cte22_f)   # transverse isotropy assumption
        cv_f    = fiber.get("cv", 700.0)         # specific heat J/kg/K (carbon fiber default)
        cte_m   = matrix.get("cte", 0.0)
        cv_m    = matrix.get("cv", 1200.0)       # specific heat J/kg/K (epoxy default)

        # Decide whether to use thermoelastic analysis (analysis=1) based on CTE availability
        has_cte = (cte11_f != 0.0 or cte22_f != 0.0 or cte_m != 0.0)
        analysis = 1 if has_cte else 0

        with open(self.input_filename, "w") as f:
            # Control line: analysis=1 (thermoelastic) enables CTE output; 0 = elastic only
            f.write(f"{analysis} 0 0 0\n")
            # nSG=2 (2D cross-section SG), nnode, nelem, nmate=2, nslave=0
            f.write(f"2 {nnode} {nelem} 2 0 0\n\n")

            # Nodal coordinates (1-based): node_no  y2  y3
            for k, (y2, y3) in enumerate(nodes):
                f.write(f"{k + 1}  {y2:.8e}  {y3:.8e}\n")
            f.write("\n")

            # Element connectivity (1-based): elem_no  mtype  n1..n8  0
            for k, (elem, mt) in enumerate(zip(q8_elems, mtypes)):
                ns = " ".join(str(n + 1) for n in elem)
                f.write(f"{k + 1} {mt} {ns} 0\n")
            f.write("\n")

            # Material 1: fiber (orthotropic, isotropy=1)
            f.write("1 1 1\n")
            f.write(f"0.0 {rho_f:.6e}\n")
            f.write(f"{E1:.6e} {E2:.6e} {E3:.6e}\n")
            f.write(f"{G12:.6e} {G13:.6e} {G23:.6e}\n")
            f.write(f"{nu12:.6f} {nu13:.6f} {nu23:.6f}\n")
            if analysis == 1:
                # alpha11 alpha22 alpha33 cv  (isotropy=1 thermoelastic format)
                f.write(f"{cte11_f:.6e} {cte22_f:.6e} {cte33_f:.6e} {cv_f:.6e}\n")
            f.write("\n")

            # Material 2: matrix (isotropic, isotropy=0)
            f.write("2 0 1\n")
            f.write(f"0.0 {rho_m:.6e}\n")
            f.write(f"{E_m:.6e} {nu_m:.6f}\n")
            if analysis == 1:
                # alpha cv  (isotropy=0 thermoelastic format)
                f.write(f"{cte_m:.6e} {cv_m:.6e}\n")
            f.write("\n")

            # SG volume = unit cell area
            f.write("1.0\n")

    # ------------------------------------------------------------------
    # Woven fabric: 3D SG, simplified 2-element C3D20 layered model
    # Warp tow (element 1, bottom half) + weft tow (element 2, top half).
    # Topology identical to the bundled micro3D.sc example.
    # ------------------------------------------------------------------

    def write_woven_input(self, fiber: dict, matrix: dict, geometry: dict):
        """Write woven fabric 3D SG input file (simplified 2-layer model). Properties in Pa.

        fiber: fiber/yarn DB entry (keys: E11_t, E22, G12, nu12, and optional E3, G13, G23, nu13, nu23).
        Element 1 — warp tow: fiber along y1.
        Element 2 — weft tow: fiber along y2 (90° rotation of warp properties).
        Unit cell: [-1, 1]³, volume = 8.
        """
        # Translate fiber DB keys to warp yarn properties
        E1   = fiber.get("E11_t", 0.0)
        E2   = fiber.get("E22", 0.0)
        E3   = fiber.get("E3", E2)
        G12  = fiber.get("G12", 0.0)
        G13  = fiber.get("G13", G12)
        G23  = fiber.get("G23", G12)
        nu12 = fiber.get("nu12", 0.0)
        nu13 = fiber.get("nu13", nu12)
        nu23 = fiber.get("nu23", nu12)
        rho  = fiber.get("density", 0.0)

        # Weft: 90° in-plane rotation → swap y1 ↔ y2 axes
        E1w  = E2
        E2w  = E1
        E3w  = E3
        G12w = G12
        G13w = G23
        G23w = G13
        nu12w = nu12 * E2 / E1 if E1 > 0 else nu12
        nu13w = nu23
        nu23w = nu13

        # 32 nodes — same topology as bundled micro3D.sc
        nodes_3d = [
            (1, -1, -1), (1,  1, -1), (1,  1,  0), (1, -1,  0),   # 1-4
            (-1,-1, -1), (-1, 1, -1), (-1, 1,  0), (-1,-1,  0),   # 5-8
            (1, -1,  1), (1,  1,  1), (-1, 1,  1), (-1,-1,  1),   # 9-12
            (1,  0, -1), (0,  1, -1), (-1, 0, -1), (0, -1, -1),   # 13-16 (bottom face mids)
            (1,  0,  0), (0,  1,  0), (-1, 0,  0), (0, -1,  0),   # 17-20 (mid face mids)
            (1, -1,-0.5),(1,  1,-0.5),(-1, 1,-0.5),(-1,-1,-0.5),  # 21-24 (vertical mids elem1)
            (1,  0,  1), (0,  1,  1), (-1, 0,  1), (0, -1,  1),   # 25-28 (top face mids)
            (1, -1, 0.5),(1,  1, 0.5),(-1, 1, 0.5),(-1,-1, 0.5),  # 29-32 (vertical mids elem2)
        ]

        # C3D20 connectivity (1-based) — same as micro3D.sc
        # Order: 8 corners (bot then top face), then bot-face mids, top-face mids, vertical mids
        elem1 = [1, 2, 6, 5, 4, 3, 7, 8,   13,14,15,16, 17,18,19,20, 21,22,23,24]
        elem2 = [4, 3, 7, 8, 9,10,11,12,   17,18,19,20, 25,26,27,28, 29,30,31,32]

        # Constituent CTEs (m/m/K)
        cte11_f = fiber.get("cte11", 0.0)
        cte22_f = fiber.get("cte22", 0.0)
        cte33_f = fiber.get("cte33", cte22_f)
        cv_f    = fiber.get("cv", 700.0)
        cte_m   = matrix.get("cte", 0.0)
        cv_m    = matrix.get("cv", 1200.0)
        has_cte = (cte11_f != 0.0 or cte22_f != 0.0 or cte_m != 0.0)
        analysis = 1 if has_cte else 0

        # Weft CTE: 90° rotation swaps axial ↔ in-plane-transverse
        cte11_w = cte22_f   # weft "axial" = fiber transverse
        cte22_w = cte11_f   # weft in-plane transverse = fiber axial
        cte33_w = cte33_f

        with open(self.input_filename, "w") as f:
            f.write(f"{analysis} 0 0 0\n")
            f.write("3 32 2 2 0 0\n\n")

            for k, (y1, y2, y3) in enumerate(nodes_3d):
                f.write(f"{k + 1}  {y1}  {y2}  {y3}\n")
            f.write("\n")

            f.write("1 1 " + " ".join(str(n) for n in elem1) + "\n")
            f.write("2 2 " + " ".join(str(n) for n in elem2) + "\n")
            f.write("\n")

            # Material 1: warp tow (orthotropic, fiber along y1)
            f.write("1 1 1\n")
            f.write(f"0.0 {rho:.6e}\n")
            f.write(f"{E1:.6e} {E2:.6e} {E3:.6e}\n")
            f.write(f"{G12:.6e} {G13:.6e} {G23:.6e}\n")
            f.write(f"{nu12:.6f} {nu13:.6f} {nu23:.6f}\n")
            if analysis == 1:
                f.write(f"{cte11_f:.6e} {cte22_f:.6e} {cte33_f:.6e} {cv_f:.6e}\n")
            f.write("\n")

            # Material 2: weft tow (orthotropic, fiber along y2 = warp rotated 90°)
            f.write("2 1 1\n")
            f.write(f"0.0 {rho:.6e}\n")
            f.write(f"{E1w:.6e} {E2w:.6e} {E3w:.6e}\n")
            f.write(f"{G12w:.6e} {G13w:.6e} {G23w:.6e}\n")
            f.write(f"{nu12w:.6f} {nu13w:.6f} {nu23w:.6f}\n")
            if analysis == 1:
                f.write(f"{cte11_w:.6e} {cte22_w:.6e} {cte33_w:.6e} {cv_f:.6e}\n")
            f.write("\n")

            # SG volume = [-1,1]³
            f.write("8.0\n")

    # ------------------------------------------------------------------
    # Execute + parse
    # ------------------------------------------------------------------

    def execute(self):
        """Run SwiftComp 3D homogenization."""
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(os.cpu_count() or 4)
        cmd = [self.exe, self.input_filename, "3D", "H"]
        log.info("SwiftComp material SG: %s", " ".join(cmd))
        result = subprocess.run(cmd, cwd=self.wd, capture_output=True, text=True, env=env)
        if result.stdout:
            log.info("SwiftComp stdout:\n%s", result.stdout.strip())
        if result.stderr:
            log.warning("SwiftComp stderr:\n%s", result.stderr.strip())
        if result.returncode != 0:
            raise RuntimeError(
                f"SwiftComp material SG failed (rc={result.returncode}):\n"
                f"{result.stderr or result.stdout}"
            )
        if not os.path.exists(self.output_filename):
            raise RuntimeError(
                f"SwiftComp ran but produced no output file: {self.output_filename}\n"
                f"stdout: {result.stdout.strip()}"
            )

    def parse_results(self) -> dict:
        """Parse effective engineering constants from .sc.k.

        Tries sgio first; falls back to scanning the text file for
        labelled values (E1=..., E2=..., G12=..., nu12=...).
        Returns dict with keys E11, E11_t, E11_c, E22, G12, nu12, density (Pa / SI).
        """
        # --- sgio attempt ---
        for model_key in ("Lam", "eff", "MSG", "BM"):
            try:
                model = sgio.readOutputModel(self.output_filename, "sc", model_key)
                if model is None:
                    continue
                props = getattr(model, "eff", None) or getattr(model, "properties", None)
                if props and hasattr(props, "get"):
                    E1 = props.get("E1", props.get("E11", 0.0))
                    if E1 > 0:
                        return {
                            "E11":     E1,
                            "E11_t":   E1,
                            "E11_c":   E1,
                            "E22":     props.get("E2",  props.get("E22", 0.0)),
                            "G12":     props.get("G12", 0.0),
                            "nu12":    props.get("nu12", 0.0),
                            "density": props.get("density", 0.0),
                        }
            except Exception:
                pass

        log.warning("sgio could not parse %s, using text fallback", self.output_filename)
        return self._parse_text_fallback()

    def _parse_text_fallback(self) -> dict:
        """Scan .sc.k for engineering constant and thermal coefficient lines."""
        if not os.path.exists(self.output_filename):
            raise FileNotFoundError(f"SwiftComp output not found: {self.output_filename}")

        out = {"E11": 0.0, "E11_t": 0.0, "E11_c": 0.0, "E22": 0.0,
               "G12": 0.0, "nu12": 0.0, "density": 0.0,
               "cte11": None, "cte22": None}

        # Pattern: optional whitespace, label, optional whitespace, = or :, value
        pat = re.compile(
            r"(?i)\b(E1|E11|E2|E22|G12|nu12|rho|density|alpha11|alpha22)\s*[=:]\s*"
            r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
        )
        with open(self.output_filename, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()

        for m in pat.finditer(text):
            key, val_str = m.group(1).lower(), m.group(2)
            try:
                val = float(val_str)
            except ValueError:
                continue
            if key in ("e1", "e11") and out["E11"] == 0.0:
                out["E11"] = out["E11_t"] = out["E11_c"] = val
            elif key in ("e2", "e22") and out["E22"] == 0.0:
                out["E22"] = val
            elif key == "g12" and out["G12"] == 0.0:
                out["G12"] = val
            elif key == "nu12" and out["nu12"] == 0.0:
                out["nu12"] = val
            elif key in ("rho", "density") and out["density"] == 0.0:
                out["density"] = val
            elif key == "alpha11" and out["cte11"] is None:
                out["cte11"] = val
            elif key == "alpha22" and out["cte22"] is None:
                out["cte22"] = val

        # Replace None with 0.0 for any unparsed CTE (elastic-only run)
        out["cte11"] = out["cte11"] or 0.0
        out["cte22"] = out["cte22"] or 0.0

        if out["E11"] == 0.0:
            # Last resort: dump the file to the log so the user can investigate
            log.error("Could not parse engineering constants from:\n%s", text[:2000])
            raise RuntimeError(
                f"Could not parse E11 from SwiftComp output: {self.output_filename}"
            )
        return out

