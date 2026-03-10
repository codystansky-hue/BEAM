import os
import io
import base64
import json
import logging
import asyncio
import time
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from materials import CompositeMaterial, Layup, assign_properties_to_mesh
from mesher import ProfileMesher
from solvers import CLTBeamSolver, SwiftCompSolver, SwiftCompMaterialSolver, GXBeamSolver, CalculiXSolver
from trame_app.vtk_views import invalidate_mesh_cache

log = logging.getLogger(__name__)

# Internal cache for non-serializable data (NumPy arrays, etc.)
_INTERNAL_CACHE = {
    "mesh": None,
    "props": None,
}

GXBEAM_BC_MAP = {
    "Fixed-Free (Cantilever)": "cantilever",
    "Pinned-Pinned": "pinned-pinned",
    "Fixed-Pinned": "fixed-pinned",
    "Fixed-Fixed": "fixed-fixed",
}

EULER_K_MAP = {
    "Fixed-Free (Cantilever)": 2.0,
    "Pinned-Pinned": 1.0,
    "Fixed-Pinned": 0.7,
    "Fixed-Fixed": 0.5,
}

def generate_snippet_preview(snap):
    """Generate a 3D snippet mesh VTK preview from cached 2D mesh data.

    Returns vtk_path on success, None on failure.
    """
    mesh_data = _INTERNAL_CACHE["mesh"]
    if mesh_data is None:
        return None

    nodes_2d = mesh_data["nodes"]
    elements_2d = mesh_data["elements"]
    length = float(snap.get("snippet_length", 250.0))
    num_elements_z = int(snap.get("snippet_elems_z", 25))
    num_nodes_2d = len(nodes_2d)

    # Stack 2D cross-section along Z
    z_vals = np.linspace(0, length, num_elements_z + 1)
    nodes_3d = []
    for z in z_vals:
        layer = nodes_2d.copy()
        layer[:, 2] = z
        nodes_3d.append(layer)
    nodes_3d = np.vstack(nodes_3d)

    # Create C3D8 hex elements (1-based for write_vtk_3d compatibility)
    elements_3d = []
    for k in range(num_elements_z):
        bot = k * num_nodes_2d
        top = (k + 1) * num_nodes_2d
        for elem_2d in elements_2d:
            n1, n2, n3, n4 = elem_2d
            elements_3d.append([
                n1 + bot + 1, n2 + bot + 1, n3 + bot + 1, n4 + bot + 1,
                n1 + top + 1, n2 + top + 1, n3 + top + 1, n4 + top + 1,
            ])

    runs_dir = os.path.join(os.getcwd(), "runs")
    os.makedirs(runs_dir, exist_ok=True)
    vtk_path = os.path.join(runs_dir, "snippet_preview.vtk")

    ccx = CalculiXSolver(working_dir=runs_dir)
    ccx.write_vtk_3d(nodes_3d, elements_3d, vtk_path)
    return vtk_path


def _snapshot_state(state):
    """Copy all needed state values into a plain dict to avoid race conditions."""
    keys = [
        "geo_file_name", "geo_upload_path", "span_length", "elem_size", "num_elem_thick",
        "xs_solver", "swiftcomp_path", "gxbeam_path", "ccx_path",
        "bc_type", "ccx_root_dofs", "ccx_tip_dofs",
        "snippet_length", "snippet_elems_z", "snippet_compressive_load", "load_angle_deg", "gxbeam_nelem",
        "include_thermal", "nlgeom_thermal",
        "temp_max_x", "temp_min_x", "temp_ref",
        "layup_plies", "laminae",
        # Material SG
        "sel_fiber_idx", "sel_resin_idx", "fibers", "resins",
        "lamina_homog_method", "lamina_type", "lamina_vf", "lamina_packing",
        "woven_pattern", "woven_yarn_spacing", "woven_yarn_width", "woven_yarn_thickness", "woven_vf",
    ]
    snap = {}
    for k in keys:
        try:
            v = state[k]
            if isinstance(v, list):
                v = list(v)
            elif isinstance(v, dict):
                v = dict(v)
            snap[k] = v
        except KeyError:
            snap[k] = None
    return snap


def _build_layup(snap):
    """Build Layup object from snapshot plies and laminae."""
    mats = []
    angs = []
    for p in snap["layup_plies"]:
        lam = next((x for x in snap["laminae"] if x["name"] == p["lamina_name"]), None)
        if not lam: continue
        cm = CompositeMaterial(
            E11=lam["E11"], E22=lam["E22"], G12=lam["G12"], nu12=lam["nu12"],
            density=lam["density"], ply_thickness=lam["thickness_mm"],
            cte11=lam.get("cte11", 0.0), cte22=lam.get("cte22", 0.0),
        )
        mats.append(cm)
        angs.append(p["angle"])
    return Layup(mats, angs)

def _compute_target_thickness(snap):
    tt = 0.0
    for p in snap["layup_plies"]:
        lam = next((x for x in snap["laminae"] if x["name"] == p.get("lamina_name")), None)
        if lam: tt += lam["thickness_mm"]
    return tt if tt > 0 else 0.25


# ---------------------------------------------------------------------------
# Stage functions: PURE — no state mutation, only logging + return results
# ---------------------------------------------------------------------------

def _run_stage_1(snap, log_cb=None):
    """Stage 1: Meshing + Material Mapping. Returns (ok, results_dict, log_lines)."""
    logs = []
    def _log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        logs.append(line)
        log.info(msg)
        if log_cb:
            log_cb(line)

    results = {}
    t0 = time.perf_counter()
    _log("=== Stage 1: Meshing ===")

    runs_dir = os.path.join(os.getcwd(), "runs")
    os.makedirs(runs_dir, exist_ok=True)
    results["result_runs_dir"] = runs_dir
    _log(f"  Output dir: {runs_dir}")

    tmp_filename = snap.get("geo_upload_path") or "meshes/last_uploaded.3dm"
    if not os.path.exists(tmp_filename):
        _log(f"  FAIL: No uploaded mesh found at {tmp_filename}")
        return False, results, logs

    fsize = os.path.getsize(tmp_filename)
    _log(f"  Geometry: {snap['geo_file_name'] or 'unknown'} ({fsize/1024:.1f} KB)")

    target_thickness = _compute_target_thickness(snap)
    layup = _build_layup(snap)
    n_plies = len(layup.materials)

    _log(f"  Layup: {n_plies} plies, total thickness = {target_thickness:.3f} mm")
    _log(f"  Mesh params: elem_size={snap['elem_size']}mm, elem_thick={snap['num_elem_thick']}")

    geo_name = snap["geo_file_name"] or "model"
    vtk_name = os.path.splitext(geo_name)[0] + ".vtk"
    vtk_out_path = os.path.join(runs_dir, vtk_name)

    try:
        _log("  Initializing mesher...")
        mesher = ProfileMesher(
            tmp_filename,
            thickness=target_thickness,
            num_elements_thickness=int(snap["num_elem_thick"]),
            element_size_along_curve=float(snap["elem_size"]),
            vtk_out_path=vtk_out_path,
        )

        _log("  Generating mesh...")
        mesh_data = mesher.generate()
        _log("  Meshing complete.")

        n_nodes = len(mesh_data['nodes'])
        n_elems = len(mesh_data['elements'])
        bounds = mesh_data['nodes'].min(axis=0), mesh_data['nodes'].max(axis=0)
        _log(f"  Mesh OK: {n_nodes} nodes, {n_elems} Q4 elements")
        _log(f"  Bounds: X=[{bounds[0][0]:.2f}, {bounds[1][0]:.2f}]  Y=[{bounds[0][1]:.2f}, {bounds[1][1]:.2f}] mm")

        _log("  Assigning material properties...")
        props_dict = assign_properties_to_mesh(mesh_data, layup)
        _log(f"  Materials mapped: {n_plies} plies -> {n_elems} elements")

        # Store in internal cache
        _INTERNAL_CACHE["mesh"] = mesh_data
        _INTERNAL_CACHE["props"] = props_dict["element_properties"]

        results["has_mesh"] = True
        results["mesh_vtk_path"] = vtk_out_path

        # Generate snippet 3D mesh preview
        try:
            snippet_vtk = generate_snippet_preview(snap)
            if snippet_vtk:
                results["snippet_vtk_path"] = snippet_vtk
                _log(f"  Snippet preview: {int(snap['snippet_elems_z'])} Z-layers, {float(snap['snippet_length']):.0f} mm")
        except Exception as e:
            _log(f"  Snippet preview skipped: {e}")

        elapsed = time.perf_counter() - t0
        _log(f"  Stage 1 complete ({elapsed:.2f}s)")
        return True, results, logs
    except Exception as e:
        _log(f"  FAIL: {e}")
        import traceback
        _log(f"  Traceback: {traceback.format_exc()}")
        return False, results, logs


def _run_stage_2(snap, log_cb=None):
    """Stage 2: SwiftComp + GXBeam + Euler. Returns (ok, results_dict, log_lines)."""
    logs = []
    def _log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        logs.append(line)
        log.info(msg)
        if log_cb:
            log_cb(line)

    results = {}
    t0 = time.perf_counter()
    mesh_data = _INTERNAL_CACHE["mesh"]
    element_props = _INTERNAL_CACHE["props"]

    if not mesh_data:
        _log("  FAIL: Run Stage 1 (Mesh) first")
        return False, results, logs

    _log("=== Stage 2: Global Analysis ===")
    runs_dir = os.path.join(os.getcwd(), "runs")

    try:
        # Cross-section solver dispatch
        solver_choice = snap.get("xs_solver", "CLT (Built-in)")
        _log(f"  Cross-section solver: {solver_choice}")

        if solver_choice == "CLT (Built-in)":
            _log("  Computing ABD + Bredt closed-section stiffness...")
            t_sc = time.perf_counter()
            clt = CLTBeamSolver(working_dir=runs_dir)
            k_mm = clt.compute_stiffness(mesh_data, element_props)
            _log(f"  CLT solver finished ({time.perf_counter()-t_sc:.2f}s)")
        else:
            # SwiftComp (or VABS — same interface)
            sc_exe = os.path.abspath(snap["swiftcomp_path"])
            _log(f"  SwiftComp exe: {sc_exe}")
            sc = SwiftCompSolver(executable_path=snap["swiftcomp_path"], working_dir=runs_dir)

            _log("  Writing SwiftComp input deck...")
            sc.write_input_file(mesh_data, element_props)

            _log("  Running SwiftComp...")
            t_sc = time.perf_counter()
            sc.execute()
            _log(f"  SwiftComp finished ({time.perf_counter()-t_sc:.2f}s)")

            _log("  Parsing stiffness matrix...")
            k_mm = sc.parse_results()

        results["result_k_mm"] = k_mm.tolist()
        _log(f"  K(1,1) = {k_mm[0,0]:.4e}")

        # Convert to SI
        k_SI = k_mm.copy()
        bending_idx = [3, 4, 5]
        for r in range(6):
            for c in range(6):
                if r in bending_idx and c in bending_idx: k_SI[r, c] /= 1e6
                elif r in bending_idx or c in bending_idx: k_SI[r, c] /= 1e3
        results["result_k_SI"] = k_SI.tolist()

        # Euler Buckling
        euler_K = EULER_K_MAP.get(snap["bc_type"], 2.0)
        KL_sq = (euler_K * float(snap["span_length"]))**2
        p_cr_22 = (np.pi**2 * k_SI[4, 4]) / KL_sq if KL_sq > 0 else 0.0
        p_cr_33 = (np.pi**2 * k_SI[5, 5]) / KL_sq if KL_sq > 0 else 0.0
        results["result_P_cr_22"] = float(p_cr_22)
        results["result_P_cr_33"] = float(p_cr_33)
        _log(f"  EI_22={k_SI[4,4]:.4f} N·m², EI_33={k_SI[5,5]:.4f} N·m²")
        _log(f"  Euler (K={euler_K}, L={float(snap['span_length'])}m): P_cr_22={p_cr_22:.3f} N, P_cr_33={p_cr_33:.3f} N")

        # GXBeam — compute thermal bending moments from temperature gradient
        gx_exe = snap["gxbeam_path"]
        _log(f"  GXBeam: julia exe = {gx_exe}")
        bc_key = GXBEAM_BC_MAP.get(snap["bc_type"], "cantilever")
        gx = GXBeamSolver(stiffness_matrix=k_SI, span=float(snap["span_length"]),
                          executable_path=gx_exe, working_dir=runs_dir)
        gx.bc_type = bc_key
        gx.nelem = int(snap.get("gxbeam_nelem", 20) or 20)

        # Decompose the tip load into axial and transverse components.
        # load_angle_deg is the angle from the beam axis toward the cross-section
        # vertical (yz-plane).  0° = purely axial; 30° = 30° off-axis.
        F_total = float(snap["snippet_compressive_load"] or -1000.0)
        _theta = np.radians(float(snap.get("load_angle_deg", 0.0)))
        axial_load  = F_total * np.cos(_theta)   # component along beam axis
        trans_load  = F_total * np.sin(_theta)   # component in cross-section Y (vertical)
        F_th, M2_th, M3_th = 0.0, 0.0, 0.0

        if snap["include_thermal"]:
            _log("  Computing thermal loads from temperature gradient...")
            pts = mesh_data['nodes']
            elements_2d = mesh_data['elements']
            x_min_sec = np.min(pts[:, 0])
            x_max_sec = np.max(pts[:, 0])
            temp_min = float(snap["temp_min_x"])
            temp_max = float(snap["temp_max_x"])
            temp_ref = float(snap["temp_ref"])

            # Compute cross-section centroid
            total_A, x_cen, y_cen = 0.0, 0.0, 0.0
            for elem in elements_2d:
                ep = pts[elem]
                xc_e, yc_e = np.mean(ep[:, 0]), np.mean(ep[:, 1])
                x0, y0 = ep[0, 0], ep[0, 1]
                x1, y1 = ep[1, 0], ep[1, 1]
                x2, y2 = ep[2, 0], ep[2, 1]
                x3, y3 = ep[3, 0], ep[3, 1]
                Ae = 0.5 * abs((x0*y1-x1*y0)+(x1*y2-x2*y1)+(x2*y3-x3*y2)+(x3*y0-x0*y3))
                total_A += Ae
                x_cen += Ae * xc_e
                y_cen += Ae * yc_e
            x_cen /= (total_A + 1e-30)
            y_cen /= (total_A + 1e-30)

            T_mean = 0.5 * (temp_max + temp_min)
            dT_mean = T_mean - temp_ref

            for i, elem in enumerate(elements_2d):
                ep = pts[elem]
                xc, yc = np.mean(ep[:, 0]), np.mean(ep[:, 1])
                x0, y0 = ep[0, 0], ep[0, 1]
                x1, y1 = ep[1, 0], ep[1, 1]
                x2, y2 = ep[2, 0], ep[2, 1]
                x3, y3 = ep[3, 0], ep[3, 1]
                A_e_mm2 = 0.5 * abs((x0*y1-x1*y0)+(x1*y2-x2*y1)+(x2*y3-x3*y2)+(x3*y0-x0*y3))
                A_e_m2 = A_e_mm2 * 1e-6

                if x_max_sec > x_min_sec:
                    frac = (xc - x_min_sec) / (x_max_sec - x_min_sec)
                    T_c = temp_min + frac * (temp_max - temp_min)
                else:
                    T_c = T_mean

                dT_total = T_c - temp_ref
                dT_grad = dT_total - dT_mean

                prop = element_props[i]
                # Use angle-transformed axial CTE: cte_axial = cte11·cos²θ + cte22·sin²θ
                # where θ = ply angle relative to beam axis (global_angle in radians).
                ply_E11s, ply_cte_axials = [], []
                for p in prop['layup']:
                    theta = np.radians(p['global_angle'])
                    c2, s2 = np.cos(theta)**2, np.sin(theta)**2
                    ply_E11s.append(p['material'].E11)
                    ply_cte_axials.append(p['material'].cte11 * c2 + p['material'].cte22 * s2)
                avg_E11 = np.mean(ply_E11s)
                avg_cte11 = np.mean(ply_cte_axials)

                dF_axial = avg_E11 * avg_cte11 * dT_mean * A_e_m2
                dF_bend = avg_E11 * avg_cte11 * dT_grad * A_e_m2

                F_th += dF_axial
                M3_th += dF_bend * (xc - x_cen) * 1e-3   # mm → m moment arm
                M2_th += dF_bend * (yc - y_cen) * 1e-3

            # Clamp thermal loads for solver stability
            EA_SI = k_SI[0, 0]
            P_euler = (np.pi**2 * k_SI[5, 5] / (float(snap["span_length"])**2)) if k_SI[5, 5] > 0 else 1e9
            max_f = min(0.001 * EA_SI, 10.0 * P_euler)
            if abs(F_th) > max_f:
                scale = max_f / abs(F_th)
                _log(f"  WARNING: Thermal loads extreme ({F_th:.2e} N). Clamping to {max_f:.2f} N")
                F_th *= scale
                M2_th *= scale
                M3_th *= scale

            _log(f"  Thermal loads: F={F_th:.2f} N, M2={M2_th:.4f} Nm, M3={M3_th:.4f} Nm")

        # Compressive load at tip; thermal loads as distributed (per unit length)
        span_m = float(snap["span_length"])

        # Cap only the axial component against the Euler buckling load.
        # GXBeam's geometrically-exact solver diverges if Fx exceeds P_cr.
        # Scale the transverse component proportionally if the axial is capped.
        p_cr_gx = min(p_cr_22, p_cr_33) if p_cr_22 > 0 and p_cr_33 > 0 else 1e9
        axial_limit = 0.9 * p_cr_gx
        if abs(axial_load) > axial_limit:
            cap_scale = axial_limit / abs(axial_load)
            axial_load_gx = -axial_limit * np.sign(axial_load)
            trans_load_gx = trans_load * cap_scale
            _log(f"  WARNING: |axial_load| {abs(axial_load):.1f} N > 90% P_cr ({p_cr_gx:.2f} N). "
                 f"Capping to {axial_load_gx:.2f} N axial, {trans_load_gx:.2f} N transverse "
                 f"(use CalculiX result for buckling)")
        else:
            axial_load_gx = axial_load
            trans_load_gx = trans_load

        # GXBeam tip_load = [Fx, Fy, Fz, Mx, My, Mz]
        # Fx = along beam axis (x1).  Fz = cross-section vertical (x3 = CCX DOF2).
        gx.tip_load = [axial_load_gx, 0.0, trans_load_gx, 0.0, 0.0, 0.0]
        gx.distributed_moment = [0.0, M2_th / span_m, M3_th / span_m]
        gx.distributed_force_x = F_th / span_m
        _log(f"  GXBeam tip load: Fx={axial_load_gx:.3f} N, Fz={trans_load_gx:.3f} N "
             f"(angle={np.degrees(_theta):.1f}° from beam axis)")
        if snap["include_thermal"]:
            _log(f"  GXBeam distributed: fx={gx.distributed_force_x:.4f} N/m, my={gx.distributed_moment[1]:.6f} Nm/m, mz={gx.distributed_moment[2]:.6f} Nm/m")

        _log("  Writing GXBeam input...")
        gx.write_input_file()

        _log("  Running GXBeam (Julia)...")
        t_gx = time.perf_counter()
        gx.execute()
        _log(f"  GXBeam finished ({time.perf_counter()-t_gx:.2f}s)")

        _log("  Parsing deflections...")
        defl, _ = gx.parse_results()
        results["result_deflections"] = defl.tolist()

        # Read full per-node GXBeam output for VTK
        gx_output = None
        if os.path.exists(gx.output_filename):
            with open(gx.output_filename, 'r') as f:
                gx_output = json.load(f)

        beam_vtk = os.path.join(runs_dir, "deformed_beam.vtk")
        gx.write_deformed_beam_vtk(mesh_data, defl, beam_vtk, gxbeam_output=gx_output)
        invalidate_mesh_cache(beam_vtk)
        results["beam_vtk_path"] = beam_vtk

        elapsed = time.perf_counter() - t0
        _log(f"  Stage 2 complete ({elapsed:.2f}s)")
        return True, results, logs
    except Exception as e:
        _log(f"  FAIL: {e}")
        import traceback
        _log(f"  Traceback: {traceback.format_exc()}")
        return False, results, logs


def _run_stage_3(snap, log_cb=None):
    """Stage 3: Local Buckling (CalculiX). Returns (ok, results_dict, log_lines)."""
    logs = []
    def _log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        logs.append(line)
        log.info(msg)
        if log_cb:
            log_cb(line)

    results = {}
    t0 = time.perf_counter()
    mesh_data = _INTERNAL_CACHE["mesh"]
    element_props = _INTERNAL_CACHE["props"]

    if not mesh_data:
        _log("  FAIL: Run Stage 1 (Mesh) first")
        return False, results, logs

    _log("=== Stage 3: Local Buckling (CalculiX) ===")
    runs_dir = os.path.join(os.getcwd(), "runs")

    try:
        ccx = CalculiXSolver(executable_path=snap["ccx_path"], working_dir=runs_dir)
        _log("  Writing CalculiX input deck...")
        ccx.write_input_file(
            mesh_data, element_props,
            length=float(snap["snippet_length"]),
            num_elements_z=int(snap["snippet_elems_z"]),
            compressive_load=float(snap["snippet_compressive_load"]),
            temp_min_x=float(snap["temp_min_x"]) if snap["include_thermal"] else float(snap["temp_ref"]),
            temp_max_x=float(snap["temp_max_x"]) if snap["include_thermal"] else float(snap["temp_ref"]),
            temp_ref=float(snap["temp_ref"]), nlgeom=snap["nlgeom_thermal"],
            root_dofs=snap["ccx_root_dofs"], tip_dofs=snap["ccx_tip_dofs"],
            load_angle_deg=float(snap.get("load_angle_deg", 0.0)),
        )
        _log("  Running CalculiX...")
        t_ccx = time.perf_counter()
        ccx.execute()
        _log(f"  CalculiX finished ({time.perf_counter()-t_ccx:.2f}s)")

        # Capture solver history
        history = ccx.parse_sta_file()
        results["ccx_history"] = history

        _log("  Parsing buckling results...")
        factor = ccx.parse_results()
        if factor is not None:
            results["result_ccx_factor"] = float(factor)
            _log(f"  Buckling factor = {factor:.5f}")
        else:
            results["result_ccx_factor"] = None
            # Check .dat file for clues
            dat_path = os.path.join(runs_dir, "snippet.dat")
            dat_size = os.path.getsize(dat_path) if os.path.exists(dat_path) else -1
            _log(f"  WARNING: No buckling factor found (.dat size={dat_size} bytes)")
            _log("  Likely cause: thermal preload step failed to converge")
            _log("  Try: disable thermal loading, or reduce temperature range")

        frd_path = os.path.join(runs_dir, "snippet.frd")
        if os.path.exists(frd_path):
            vtk_path = os.path.join(runs_dir, "snippet_mode.vtk")
            try:
                ccx.write_mode_vtk(ccx.nodes_3d, ccx.elements_3d, frd_path, vtk_path)
                invalidate_mesh_cache(vtk_path)
                results["buckling_vtk_path"] = vtk_path
                _log("  Buckling mode VTK written.")
            except Exception as e:
                _log(f"  WARNING: Could not write buckling VTK: {e}")

        elapsed = time.perf_counter() - t0
        _log(f"  Stage 3 complete ({elapsed:.2f}s)")
        return True, results, logs
    except Exception as e:
        _log(f"  FAIL: {e}")
        import traceback
        _log(f"  Traceback: {traceback.format_exc()}")
        return False, results, logs


# ---------------------------------------------------------------------------
# Convergence monitor helpers
# ---------------------------------------------------------------------------

def _render_convergence_plot(history) -> str:
    """Render a dark-themed convergence plot and return a base64 PNG data URI."""
    idxs = list(range(len(history)))
    iters = [h["iter"] for h in history]
    dts   = [h["dt"]   for h in history]

    bar_colors = [
        "#4caf50" if it <= 4 else "#ff9800" if it <= 8 else "#f44336"
        for it in iters
    ]

    bg   = "#1e1e1e"
    axes_bg = "#2a2a2a"
    text_c  = "#cccccc"
    grid_c  = "#444444"

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 3.5))
    fig.patch.set_facecolor(bg)

    # -- Top: iterations per increment --
    ax1.set_facecolor(axes_bg)
    ax1.bar(idxs, iters, color=bar_colors, width=0.7)
    ax1.set_ylabel("Iterations", color=text_c, fontsize=8)
    ax1.tick_params(colors=text_c, labelsize=7)
    ax1.set_xticks([])
    ax1.grid(axis="y", color=grid_c, linewidth=0.5)
    ax1.spines[:].set_color(grid_c)
    ax1.set_title("CalculiX Convergence", color=text_c, fontsize=9, pad=4)

    # -- Bottom: time-step size --
    ax2.set_facecolor(axes_bg)
    ax2.plot(idxs, dts, color="#42a5f5", linewidth=1.2, marker="o", markersize=3)
    ax2.set_ylabel("dt", color=text_c, fontsize=8)
    ax2.set_xlabel("Increment index", color=text_c, fontsize=8)
    ax2.tick_params(colors=text_c, labelsize=7)
    ax2.grid(color=grid_c, linewidth=0.5)
    ax2.spines[:].set_color(grid_c)

    plt.tight_layout(pad=0.8)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=bg)
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    return f"data:image/png;base64,{b64}"


async def _poll_ccx_convergence(state, runs_dir):
    """Poll snippet.sta every 0.5 s and push convergence chart to trame state."""
    ccx_poll = CalculiXSolver(working_dir=runs_dir)
    while True:
        await asyncio.sleep(0.5)
        history = ccx_poll.parse_sta_file()
        if history:
            state.ccx_history = history
            state.ccx_convergence_img = _render_convergence_plot(history)
            state.flush()


# ---------------------------------------------------------------------------
# Async wrappers — all state mutation happens here, on the event loop
# ---------------------------------------------------------------------------

def _apply_results(state, results, log_lines=None):
    """Apply results dict and optional log lines to trame state (event-loop safe)."""
    # Append log lines (only used when real-time streaming is NOT active)
    if log_lines:
        current_log = list(state.pipeline_log or [])
        current_log.extend(log_lines)
        state.pipeline_log = current_log
        state.pipeline_log_string = "\n".join(current_log)
    # Apply result keys
    for k, v in results.items():
        state[k] = v
    state.flush()


def _make_log_streamer(state, loop):
    """Create a thread-safe callback that pushes each log line to the client immediately."""
    def _stream(line):
        def _update():
            current = list(state.pipeline_log or [])
            current.append(line)
            state.pipeline_log = current
            state.pipeline_log_string = "\n".join(current)
            state.flush()
        loop.call_soon_threadsafe(_update)
    return _stream


async def run_all_stages(state):
    state.pipeline_running = True
    state.pipeline_log = []
    state.pipeline_log_string = ""
    state.pipeline_stage = "Starting..."
    state.flush()

    snap = _snapshot_state(state)
    t_total = time.perf_counter()
    loop = asyncio.get_event_loop()
    log_cb = _make_log_streamer(state, loop)

    ts = datetime.now().strftime("%H:%M:%S")
    log.info("========== Pipeline Start ==========")
    state.pipeline_log = [f"[{ts}] ========== Pipeline Start =========="]
    state.pipeline_log_string = state.pipeline_log[0]
    state.flush()

    # --- Stage 1 ---
    state.pipeline_stage = "Stage 1: Meshing"
    state.flush()
    ok1, res1, _logs1 = await asyncio.to_thread(_run_stage_1, snap, log_cb)
    _apply_results(state, res1)
    if ok1:
        state.pipeline_stage = "Stage 1 Complete"
        # Invalidate downstream
        state.result_k_mm = None
        state.result_k_SI = None
        state.result_deflections = None
        state.result_ccx_factor = None
    state.flush()

    # --- Stage 2 ---
    if ok1:
        state.pipeline_stage = "Stage 2: Global Analysis"
        state.flush()
        ok2, res2, _logs2 = await asyncio.to_thread(_run_stage_2, snap, log_cb)
        _apply_results(state, res2)
        if ok2:
            state.pipeline_stage = "Stage 2 Complete"
        state.flush()
    else:
        ok2 = False
        ts = datetime.now().strftime("%H:%M:%S")
        log_cb(f"[{ts}] Pipeline stopped: Stage 1 failed")

    # --- Stage 3 ---
    if ok1 and ok2:
        state.pipeline_stage = "Stage 3: Local Buckling"
        state.ccx_convergence_img = ""
        state.flush()
        runs_dir = os.path.join(os.getcwd(), "runs")
        poll_task = asyncio.create_task(_poll_ccx_convergence(state, runs_dir))
        try:
            ok3, res3, _logs3 = await asyncio.to_thread(_run_stage_3, snap, log_cb)
        finally:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
        _apply_results(state, res3)
        if state.ccx_history:
            state.ccx_convergence_img = _render_convergence_plot(state.ccx_history)
        if ok3:
            state.pipeline_stage = "Stage 3 Complete"
        state.flush()
    elif ok1 and not ok2:
        ts = datetime.now().strftime("%H:%M:%S")
        log_cb(f"[{ts}] Pipeline stopped: Stage 2 failed")

    elapsed = time.perf_counter() - t_total
    ts = datetime.now().strftime("%H:%M:%S")
    log.info(f"========== Pipeline Done ({elapsed:.2f}s) ==========")
    log_cb(f"[{ts}] ========== Pipeline Done ({elapsed:.2f}s) ==========")
    state.pipeline_stage = "Complete"
    state.pipeline_running = False
    state.flush()


# ---------------------------------------------------------------------------
# Individual stage runners (called from trame_app.py buttons)
# ---------------------------------------------------------------------------

async def run_stage_1_async(state):
    state.pipeline_running = True
    state.pipeline_log = []
    state.pipeline_log_string = ""
    state.pipeline_stage = "Stage 1: Meshing"
    state.flush()
    snap = _snapshot_state(state)
    loop = asyncio.get_event_loop()
    log_cb = _make_log_streamer(state, loop)
    ok, results, _logs = await asyncio.to_thread(_run_stage_1, snap, log_cb)
    _apply_results(state, results)
    state.pipeline_stage = "Stage 1 Complete" if ok else "Stage 1 Failed"
    state.pipeline_running = False
    state.flush()

async def run_stage_2_async(state):
    state.pipeline_running = True
    state.pipeline_log = []
    state.pipeline_log_string = ""
    state.pipeline_stage = "Stage 2: Global Analysis"
    state.flush()
    snap = _snapshot_state(state)
    loop = asyncio.get_event_loop()
    log_cb = _make_log_streamer(state, loop)
    ok, results, _logs = await asyncio.to_thread(_run_stage_2, snap, log_cb)
    _apply_results(state, results)
    state.pipeline_stage = "Stage 2 Complete" if ok else "Stage 2 Failed"
    state.pipeline_running = False
    state.flush()

async def run_stage_3_async(state):
    state.pipeline_running = True
    state.pipeline_log = []
    state.pipeline_log_string = ""
    state.pipeline_stage = "Stage 3: Local Buckling"
    state.ccx_convergence_img = ""
    state.flush()

    snap = _snapshot_state(state)
    runs_dir = os.path.join(os.getcwd(), "runs")
    loop = asyncio.get_event_loop()
    log_cb = _make_log_streamer(state, loop)

    poll_task = asyncio.create_task(_poll_ccx_convergence(state, runs_dir))
    try:
        ok, results, _logs = await asyncio.to_thread(_run_stage_3, snap, log_cb)
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass

    _apply_results(state, results)

    # Render final chart from completed history
    if state.ccx_history:
        state.ccx_convergence_img = _render_convergence_plot(state.ccx_history)

    state.pipeline_stage = "Stage 3 Complete" if ok else "Stage 3 Failed"
    state.pipeline_running = False
    state.flush()


# ---------------------------------------------------------------------------
# Material SG (Step 1 replacement): fiber/matrix → lamina properties
# ---------------------------------------------------------------------------

def _run_material_sg(snap: dict) -> dict:
    """Sync: compute homogenised lamina properties. Returns props dict (SI).

    Dispatches between built-in micromechanics (ROM/Chamis/Schapery) and
    SwiftComp material SG based on ``lamina_homog_method``.
    """
    fibers = snap.get("fibers") or []
    resins = snap.get("resins") or []
    idx_f = int(snap.get("sel_fiber_idx") or 0)
    idx_r = int(snap.get("sel_resin_idx") or 0)

    if not fibers or idx_f >= len(fibers):
        raise ValueError("No fiber selected")
    if not resins or idx_r >= len(resins):
        raise ValueError("No resin selected")

    fiber = fibers[idx_f]
    matrix = resins[idx_r]

    lamina_type = snap.get("lamina_type", "ud")
    method = snap.get("lamina_homog_method", "Micromechanics (Built-in)")

    # ── Built-in micromechanics (UD only) ───────────────────────────────
    if method == "Micromechanics (Built-in)" and lamina_type == "ud":
        from micromechanics import calculate_lamina_properties

        vf = float(snap.get("lamina_vf") or 0.6)
        props = calculate_lamina_properties(fiber, matrix, vf)
        return props

    # ── SwiftComp Material SG ───────────────────────────────────────────
    runs_dir = os.path.join(os.getcwd(), "runs", "material_sg")
    os.makedirs(runs_dir, exist_ok=True)

    sc = SwiftCompMaterialSolver(
        executable_path=snap.get("swiftcomp_path", "Swiftcomp/SwiftComp.exe"),
        working_dir=runs_dir,
    )

    if lamina_type == "ud":
        vf = float(snap.get("lamina_vf") or 0.6)
        packing = snap.get("lamina_packing", "hexagonal")
        sc.write_ud_input(fiber, matrix, vf, packing)
    else:
        vf = float(snap.get("woven_vf") or 0.6)
        geometry = {
            "weave_pattern": snap.get("woven_pattern", "plain"),
            "yarn_spacing":  float(snap.get("woven_yarn_spacing") or 1.0),
            "yarn_width":    float(snap.get("woven_yarn_width") or 0.5),
            "yarn_thickness": float(snap.get("woven_yarn_thickness") or 0.2),
            "vf":            vf,
        }
        sc.write_woven_input(fiber, matrix, geometry)

    sc.execute()
    props = sc.parse_results()

    # SwiftComp skips density when temp_flag=0; compute via ROM as fallback
    if not props.get("density"):
        rho_f = fiber.get("density", 0.0)
        rho_m = matrix.get("density", 0.0)
        props["density"] = vf * rho_f + (1.0 - vf) * rho_m

    return props


async def run_material_sg_async(state):
    """Async wrapper: run SwiftComp material SG and update state."""
    state.lamina_sg_running = True
    method = state.lamina_homog_method or "Micromechanics (Built-in)"
    state.lamina_sg_preview = f"Running {method}..."
    state.lamina_sg_props = None
    state.flush()
    try:
        snap = _snapshot_state(state)
        props = await asyncio.to_thread(_run_material_sg, snap)
        state.lamina_sg_props = props
        cte11_um = props.get("cte11", 0.0) * 1e6
        cte22_um = props.get("cte22", 0.0) * 1e6
        preview = (
            f"E11={props['E11']/1e9:.1f} GPa  "
            f"E22={props['E22']/1e9:.1f} GPa  "
            f"G12={props['G12']/1e9:.1f} GPa  "
            f"\u03bd12={props['nu12']:.3f}"
        )
        if cte11_um != 0.0 or cte22_um != 0.0:
            preview += f"  \u03b111={cte11_um:.3f} \u03b122={cte22_um:.3f} \u00b5m/m/K"
        state.lamina_sg_preview = preview
        # Auto-populate CTE fields so user doesn't need to enter them manually
        if props.get("cte11") is not None:
            state.new_lamina_cte11 = round(cte11_um, 4)
        if props.get("cte22") is not None:
            state.new_lamina_cte22 = round(cte22_um, 4)
        log.info("Material SG complete: %s", state.lamina_sg_preview)
    except Exception as e:
        state.lamina_sg_preview = f"ERROR: {e}"
        log.error("Material SG failed: %s", e)
    finally:
        state.lamina_sg_running = False
        state.flush()
