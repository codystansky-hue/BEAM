"""State management: defaults, DB load/save, initialization."""

import os
import json
import logging

log = logging.getLogger(__name__)

DB_DIR = "db"
FIBERS_DB = os.path.join(DB_DIR, "fibers.json")
RESINS_DB = os.path.join(DB_DIR, "resins.json")
LAMINAE_DB = os.path.join(DB_DIR, "laminae.json")
LAYUPS_DB = os.path.join(DB_DIR, "layups.json")
LAST_SESSION_DB = os.path.join(DB_DIR, "last_session.json")
LAST_GEO_FILE = os.path.join("meshes", "last_uploaded.3dm")
DEFAULT_CAD_PATH = r"G:\My Drive\Reflect Orbital\CAD\BoomSectionCRV.3dm"

def load_db(path):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Error loading DB {path}: {e}")
    return []

def save_db(path, data):
    os.makedirs(DB_DIR, exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        log.error(f"Error saving DB {path}: {e}")

DEFAULTS = {
    # Geometry / mesh
    "geo_file_name": None,
    "geo_upload_path": None,
    "geo_file_input": None,
    "span_length": 13.0,
    "elem_size": 2.0,
    "num_elem_thick": 2,
    # Cross-section solver
    "xs_solver": "CLT (Built-in)",
    # Solver paths
    "swiftcomp_path": "Swiftcomp/SwiftComp.exe",
    "gxbeam_path": "julia",
    "ccx_path": "../VABS-preprocessor/CalculiX-Windows/bin/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe",
    # Boundary conditions
    "bc_type": "Fixed-Free (Cantilever)",
    "ccx_root_dofs": [1, 2, 3, 4, 5, 6],
    "ccx_tip_dofs": [],
    # Snippet / CalculiX
    "snippet_length": 250.0,
    "snippet_elems_z": 25,
    "snippet_compressive_load": -1000.0,
    # Angle of the tip load vector from the beam axis (degrees).
    # 0 = purely axial; 30 = 30° toward the cross-section vertical (yz-plane bending).
    # Applies to both GXBeam (tip_load Fx/Fz) and CalculiX (CLOAD DOF3/DOF2 on ref node).
    "load_angle_deg": 0.0,
    "gxbeam_nelem": 20,
    # Thermal
    "include_thermal": True,
    "nlgeom_thermal": False,
    "temp_max_x": 102.51,
    "temp_min_x": -31.85,
    "temp_ref": 20.0,
    "load_diagram_svg": "",   # computed SVG for tip-load direction diagram
    # Pipeline
    "pipeline_log": [],
    "pipeline_log_string": "",
    "pipeline_running": False,
    "pipeline_stage": "",
    # Results (Staged Execution Architecture)
    "has_mesh": False,
    "result_k_mm": None,        # list 6x6 — mm units
    "result_k_SI": None,        # ndarray 6x6 — SI units
    "result_deflections": None,  # ndarray 6 — GXBeam tip displacements
    "result_P_cr_22": None,     # float N — Euler lateral buckling load
    "result_P_cr_33": None,     # float N — Euler vertical buckling load
    "result_ccx_factor": None,  # float — CalculiX eigenvalue multiplier
    "result_runs_dir": None,    # str — path to runs/ directory
    "ccx_history": [],          # list of dicts from .sta file
    "ccx_convergence_img": "",  # base64 PNG updated live during Stage 3
    # ---- Constituent / lamina edit dialogs ----
    "edit_fiber_open": False, "edit_fiber_idx": -1,
    "edit_fiber_name": "", "edit_fiber_e11_t": 0.0, "edit_fiber_e11_c": 0.0,
    "edit_fiber_e22": 0.0, "edit_fiber_g12": 0.0, "edit_fiber_nu12": 0.0,
    "edit_fiber_density": 0.0, "edit_fiber_xt": 0.0, "edit_fiber_xc": 0.0,
    "edit_fiber_cte11": 0.0, "edit_fiber_cte22": 0.0,
    "edit_resin_open": False, "edit_resin_idx": -1,
    "edit_resin_name": "", "edit_resin_e_t": 0.0, "edit_resin_e_c": 0.0,
    "edit_resin_nu": 0.0, "edit_resin_density": 0.0,
    "edit_resin_s": 0.0, "edit_resin_cte": 0.0,
    "edit_resin_xt": 0.0, "edit_resin_xc": 0.0,
    "edit_lamina_open": False, "edit_lamina_idx": -1,
    "edit_lamina_name": "", "edit_lamina_thickness": 0.0,
    "edit_lamina_cte11": 0.0, "edit_lamina_cte22": 0.0,
    # New-item input fields (CTE + Xt/Xc missing from current forms)
    "new_fiber_cte11": 0.0, "new_fiber_cte22": 0.0,
    "new_resin_cte": 0.0, "new_resin_xt": 0.0, "new_resin_xc": 0.0,
    "new_lamina_cte11": 0.0, "new_lamina_cte22": 0.0,
    # Clipboard TSV strings
    "fiber_tsv": "", "resin_tsv": "", "lamina_tsv": "",
    # Save confirmation snackbar
    "save_snackbar_open": False, "save_snackbar_text": "",
    # Selected item indices for edit/delete selects
    "sel_fiber_idx": None, "sel_resin_idx": None, "sel_lamina_idx": None,
    # PDF datasheet import
    "fiber_pdf_input": None, "pdf_fiber_summary": "",
    "resin_pdf_input": None, "pdf_resin_summary": "",
    # Ply inline angle editing
    "edit_ply_idx": -1, "edit_ply_angle_val": 0.0,
    # Legacy keys (keeping for compatibility during transition if needed)
    "k_matrix": None,
    "deflections": None,
    "buckling_factor": None,
    # VTK view
    "active_vtk": "none",
    "active_page": 0,
    "mesh_vtk_path": None,
    "snippet_vtk_path": None,
    "beam_vtk_path": None,
    "buckling_vtk_path": None,
    "warp_factor_beam": 1.0,
    "warp_factor_buckling": 1.0,
    "buckling_scalar": "displacement_magnitude",
    "show_edges": False,
    "show_undeformed": True,
    # Export
    "export_trigger": 0,
    "export_content": "",
    "export_filename": "",
    # Clipboard (server→client copy via execCommand fallback)
    "clipboard_text": "",
    "clipboard_trigger": 0,
    # Material editing helpers
    "layup_plies": [],
    "restore_status": "",
    # Tow count estimator
    "lamina_tow_k": 3,
    "lamina_filament_dia_um": 7.0,
    "lamina_tow_width_mm": 3.0,
    "lamina_est_faw_text": "",
    # Lamina generator — type and SwiftComp material SG parameters
    "lamina_type": "ud",               # "ud" or "woven"
    "lamina_packing": "hexagonal",     # UD packing: "hexagonal" or "square"
    "woven_yarn_spacing": 1.0,
    "woven_yarn_width": 0.5,
    "woven_yarn_thickness": 0.2,
    "woven_pattern": "plain",          # "plain", "twill", "satin"
    "woven_vf": 0.60,
    "lamina_homog_method": "Micromechanics (Built-in)",
    "lamina_sg_preview": "",           # e.g. "E11=138 GPa  E22=9.0 GPa ..."
    "lamina_sg_running": False,
    "lamina_sg_props": None,           # computed props dict, held until Save
}

def initialize_state(server):
    """Load DB files and set all state defaults on the trame server."""
    state = server.state

    # Load databases
    state.fibers = load_db(FIBERS_DB)
    state.resins = load_db(RESINS_DB)
    state.laminae = load_db(LAMINAE_DB)
    state.layups = load_db(LAYUPS_DB)

    # Apply defaults
    for key, value in DEFAULTS.items():
        state[key] = value

    # Restore session or load default file
    if os.path.exists(LAST_GEO_FILE):
        session_data = load_db(LAST_SESSION_DB)
        if session_data:
            state.geo_file_name = session_data.get("geo_file_name")
            state.layup_plies = session_data.get("layup_plies", [])
            state.restore_status = f"Restored last session: {state.geo_file_name} · {len(state.layup_plies)} plies"
            log.info(state.restore_status)
    elif os.path.exists(DEFAULT_CAD_PATH):
        import shutil
        os.makedirs("meshes", exist_ok=True)
        try:
            shutil.copy(DEFAULT_CAD_PATH, LAST_GEO_FILE)
            state.geo_file_name = os.path.basename(DEFAULT_CAD_PATH)
            state.restore_status = f"Loaded default CAD: {state.geo_file_name}"
            log.info(state.restore_status)
        except Exception as e:
            log.error(f"Failed to copy default CAD: {e}")
