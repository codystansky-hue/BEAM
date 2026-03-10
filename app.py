import streamlit as st
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import os
import tempfile
import json
import logging
import sys

from mesher import ProfileMesher
from materials import CompositeMaterial, Layup, assign_properties_to_mesh
from solvers import GXBeamSolver, CalculiXSolver, SwiftCompSolver
from pdf_parser import extract_properties_from_pdf
from micromechanics import calculate_lamina_properties

# Configure terminal logging once per process.
# force=True replaces any handlers set by previous Streamlit reruns.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
    force=True,
)
logger = logging.getLogger("BEAM")

# --- Database Helpers ---

DB_DIR = "db"
FIBERS_DB = os.path.join(DB_DIR, "fibers.json")
RESINS_DB = os.path.join(DB_DIR, "resins.json")
LAMINAE_DB = os.path.join(DB_DIR, "laminae.json")
LAYUPS_DB = os.path.join(DB_DIR, "layups.json")

def load_db(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return []

def save_db(path, data):
    os.makedirs(DB_DIR, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=4)

if 'fibers' not in st.session_state:
    st.session_state.fibers = load_db(FIBERS_DB)
if 'resins' not in st.session_state:
    st.session_state.resins = load_db(RESINS_DB)
if 'laminae' not in st.session_state:
    st.session_state.laminae = load_db(LAMINAE_DB)
if 'layups' not in st.session_state:
    st.session_state.layups = load_db(LAYUPS_DB)
if 'layup_plies' not in st.session_state:
    st.session_state.layup_plies = []

st.title("BEAM – Composite Section Analyzer")
st.markdown("A local engineering tool to analyze a thin-walled composite omega section using SwiftComp, GXBeam, and CalculiX.")

# --- SIDEBAR (Global Configs & Geometric Inputs) ---


st.set_page_config(layout="wide", page_title="BEAM Composite Analyzer")

# --- SESSION STATE INITIALIZATION FOR ANSYS WORKFLOW ---
from datetime import datetime
import pandas as pd

defaults = {
    'geo_file_name': None,
    'span_length': 13.0,
    'elem_size': 2.0,
    'num_elem_thick': 2,
    'swiftcomp_path': "Swiftcomp/SwiftComp.exe",
    'gxbeam_path': "julia",
    'ccx_path': "CalculiX-Windows/bin/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe",
    'bc_type': "Fixed-Free (Cantilever)",
    'ccx_root_dofs': [1,2,3,4,5,6],
    'ccx_tip_dofs': [],
    'snippet_length': 250.0,
    'snippet_elems_z': 25,
    'snippet_compressive_load': -1000.0,
    'include_thermal': True,
    'nlgeom_thermal': False,
    'temp_max_x': 102.51,
    'temp_min_x': -31.85,
    'temp_ref': 20.0,
    'analysis_lock': False,
    'last_run_time': None
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# --- PROJECT OUTLINE (ANSYS-STYLE SIDEBAR TREE) ---
st.sidebar.title("Model Outline")
pages = [
    "📐 1. Pre-Processing",
    "⚙️ 2. Solution Setup",
    "📊 3. Results Dashboard"
]

nav_selection = st.sidebar.radio("Navigation", pages, label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.info("The workflow has been consolidated. Configure your model in Pre-Processing, run it in Solution Setup, and view outputs in the Results Dashboard.")

def cln(v):
    return float(v) if v is not None else 0.0

# ==========================================
# PAGE 1: PRE-PROCESSING (Geo, Mesh, Mats, Layup)
# ==========================================
if nav_selection == pages[0]:
    st.header("📐 Pre-Processing: Geometry, Materials, & Layup")
    
    st.markdown("### Part 1: Geometry & Mesh Options")
    col1, col2 = st.columns(2)
    with col1:
        uploaded_file = st.file_uploader("Upload 2D Spine Curve (.3dm)", type=["3dm"], key="geo_upl")
        if uploaded_file is not None:
            os.makedirs("meshes", exist_ok=True)
            with open("meshes/last_uploaded.3dm", "wb") as f:
                f.write(uploaded_file.getvalue())
            st.session_state.geo_file_name = uploaded_file.name
            st.success(f"Successfully loaded {uploaded_file.name}")
        elif st.session_state.geo_file_name and os.path.exists("meshes/last_uploaded.3dm"):
            st.success(f"Using previously uploaded file: {st.session_state.geo_file_name}")
        else:
            st.warning("Please upload a .3dm file.")
        
        st.session_state.span_length = st.number_input("Global Beam Span Length (m)", value=st.session_state.span_length, step=0.1)

    with col2:
        st.session_state.elem_size = st.number_input("Element Size Along Curve (mm)", value=st.session_state.elem_size, step=0.5)
        st.session_state.num_elem_thick = st.number_input("Elements Through Thickness", min_value=1, max_value=10, value=st.session_state.num_elem_thick)

    # --- MESH PREVIEW ---
    if os.path.exists("meshes/last_uploaded.3dm"):
        st.markdown("#### Mesh Preview")
        # Resolve thickness: use current layup total if defined, else 2 mm placeholder
        _preview_thickness = 2.0
        if st.session_state.layup_plies:
            _th = sum(
                next((x for x in st.session_state.laminae if x['name'] == p['lamina_name']), {}).get('thickness_mm', 0.0)
                for p in st.session_state.layup_plies
            )
            if _th > 0:
                _preview_thickness = _th
        st.caption(f"Preview uses current mesh settings — thickness: {_preview_thickness:.3f} mm")
        with st.spinner("Generating mesh preview..."):
            try:
                logger.info(
                    "Mesh preview: elem_size=%.1f mm, n_thick=%d, thickness=%.3f mm",
                    st.session_state.elem_size, st.session_state.num_elem_thick, _preview_thickness,
                )
                _prev_mesher = ProfileMesher(
                    "meshes/last_uploaded.3dm",
                    thickness=_preview_thickness,
                    num_elements_thickness=st.session_state.num_elem_thick,
                    element_size_along_curve=st.session_state.elem_size
                )
                _prev_md = _prev_mesher.generate()
                _prev_nodes = _prev_md['nodes']
                _prev_elems = _prev_md['elements']
                logger.info("Mesh preview: %d nodes, %d elements", len(_prev_nodes), len(_prev_elems))

                _pts2d = _prev_nodes[:, :2]
                _xall, _yall = _pts2d[:, 0], _pts2d[:, 1]
                _xmin, _xmax = _xall.min(), _xall.max()
                _ymin, _ymax = _yall.min(), _yall.max()
                _xrng = _xmax - _xmin
                _yrng = _ymax - _ymin
                _ycen = 0.5 * (_ymin + _ymax)

                # Zoom window: left 38% of X, full Y with padding
                _zx0 = _xmin - 0.02 * _xrng
                _zx1 = _xmin + 0.38 * _xrng
                _zy0 = _ycen - 0.60 * _yrng
                _zy1 = _ycen + 0.60 * _yrng

                fig_prev, (ax_zoom, ax_full) = plt.subplots(1, 2, figsize=(13, 4))

                def _draw_prev(ax, xlim=None, ylim=None):
                    for _el in _prev_elems:
                        _ep = _pts2d[_el]
                        _ep = np.vstack((_ep, _ep[0]))
                        ax.plot(_ep[:, 0], _ep[:, 1], 'k-', lw=0.5, alpha=0.75)
                    ax.set_aspect('equal', 'box')
                    ax.grid(True, linestyle='--', alpha=0.35, color='gray')
                    ax.tick_params(labelsize=8)
                    ax.set_xlabel("X (mm)", fontsize=8)
                    ax.set_ylabel("Y (mm)", fontsize=8)
                    if xlim is not None:
                        ax.set_xlim(xlim)
                    if ylim is not None:
                        ax.set_ylim(ylim)

                # Full view with red zoom-region indicator
                _draw_prev(ax_full)
                ax_full.set_title(f"Overall  ({len(_prev_nodes)} nodes, {len(_prev_elems)} elements)", fontsize=9)
                from matplotlib.patches import Rectangle
                _rect = Rectangle((_zx0, _zy0), _zx1 - _zx0, _zy1 - _zy0,
                                   linewidth=1.4, edgecolor='#e84545',
                                   facecolor='#e8454518', zorder=5)
                ax_full.add_patch(_rect)

                # Zoomed view: middle-left region
                _draw_prev(ax_zoom, xlim=[_zx0, _zx1], ylim=[_zy0, _zy1])
                ax_zoom.set_title("Zoom: Middle-Left", fontsize=9)

                fig_prev.tight_layout()
                st.pyplot(fig_prev)
                plt.close(fig_prev)

            except Exception as _prev_err:
                logger.error("Mesh preview failed: %s", _prev_err, exc_info=True)
                st.warning(f"Mesh preview unavailable: {_prev_err}")

    st.divider()

    st.markdown("### Part 2: Material Library")
    t1, t2, t3 = st.tabs(["Constituents (Fibers/Resins)", "Lamina Generator", "Layup Designer"])
    
    with t1:
        c_fib, c_res = st.columns(2)
        with c_fib:
            st.subheader("Fibers")
            with st.expander("Manage Saved Fibers", expanded=bool(st.session_state.fibers)):
                if st.session_state.fibers:
                    df_fib = pd.DataFrame(st.session_state.fibers)
                    for c in ['E11_t', 'E11_c', 'E22', 'G12']:
                        if c in df_fib.columns: df_fib[c] /= 1e9
                    for c in ['Xt', 'Xc']:
                        if c in df_fib.columns: df_fib[c] /= 1e6
                    edit_df = st.data_editor(df_fib, num_rows="dynamic", key="fib_editor")
                    if st.button("Save Database Edits", key="save_fib_edits"):
                        new_f = edit_df.to_dict('records')
                        for row in new_f:
                            for c in ['E11_t', 'E11_c', 'E22', 'G12']:
                                if c in row: row[c] = cln(row[c]) * 1e9
                            for c in ['Xt', 'Xc']:
                                if c in row: row[c] = cln(row[c]) * 1e6
                        st.session_state.fibers = new_f
                        save_db(FIBERS_DB, st.session_state.fibers)
                        st.success("Fiber database updated!")
                        st.rerun()
                    st.markdown("---")
                    _del_f_names = [f['name'] for f in st.session_state.fibers]
                    _del_f_sel = st.selectbox("Select fiber to delete", _del_f_names, key="del_fib_sel")
                    if st.button("Delete Fiber", key="del_fib_btn", type="secondary"):
                        st.session_state.fibers.pop(_del_f_names.index(_del_f_sel))
                        save_db(FIBERS_DB, st.session_state.fibers)
                        st.rerun()
                else:
                    st.caption("No fibers saved yet.")
            f_pdf = st.file_uploader("Upload Fiber PDF", type=["pdf"])
            f_parsed = {}
            if f_pdf:
                with st.spinner("Parsing PDF..."):
                    import tempfile
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(f_pdf.getvalue())
                        tmp_pdf = tmp.name
                    from pdf_parser import extract_properties_from_pdf
                    f_parsed = extract_properties_from_pdf(tmp_pdf)
                    os.unlink(tmp_pdf)
            f_name = st.text_input("Fiber Name", value=f_pdf.name.replace(".pdf","") if f_pdf else "Carbon T700")
            f_e11_t = st.number_input("E11 Tension (GPa)", value=f_parsed.get('tensile_modulus_gpa', None), key="f_e11_t")
            f_e11_c = st.number_input("E11 Comp. (GPa)", value=f_parsed.get('compressive_modulus_gpa', None), key="f_e11_c")
            f_e22 = st.number_input("E22 (GPa)", value=None, key="f_e22")
            f_g12 = st.number_input("G12 (GPa)", value=None, key="f_g12")
            f_xt = st.number_input("Tensile Strength Xt (MPa)", value=f_parsed.get('tensile_strength_mpa', None), key="f_xt")
            f_xc = st.number_input("Comp. Strength Xc (MPa)", value=f_parsed.get('compressive_strength_mpa', None), key="f_xc")
            f_nu = st.number_input("nu12", value=f_parsed.get('poissons_ratio', None), key="f_nu")
            f_rho = st.number_input("Density (kg/m3)", value=f_parsed.get('density_kg_m3', None), key="f_rho")
            if st.button("Save Fiber"):
                st.session_state.fibers.append({'name': f_name, 'E11_t': cln(f_e11_t)*1e9, 'E11_c': cln(f_e11_c)*1e9, 'E22': cln(f_e22)*1e9, 'G12': cln(f_g12)*1e9, 'nu12': cln(f_nu), 'density': cln(f_rho), 'Xt': cln(f_xt)*1e6, 'Xc': cln(f_xc)*1e6})
                save_db(FIBERS_DB, st.session_state.fibers)
                st.success("Saved!")
                st.rerun()

        with c_res:
            st.subheader("Resins")
            with st.expander("Manage Saved Resins", expanded=bool(st.session_state.resins)):
                if st.session_state.resins:
                    df_res = pd.DataFrame(st.session_state.resins)
                    for c in ['E_t', 'E_c', 'E']:
                        if c in df_res.columns: df_res[c] /= 1e9
                    for c in ['Xt', 'Xc', 'S']:
                        if c in df_res.columns: df_res[c] /= 1e6
                    edit_r_df = st.data_editor(df_res, num_rows="dynamic", key="res_editor")
                    if st.button("Save Database Edits", key="save_res_edits"):
                        new_r = edit_r_df.to_dict('records')
                        for row in new_r:
                            for c in ['E_t', 'E_c', 'E']:
                                if c in row: row[c] = cln(row[c]) * 1e9
                            for c in ['Xt', 'Xc', 'S']:
                                if c in row: row[c] = cln(row[c]) * 1e6
                        st.session_state.resins = new_r
                        save_db(RESINS_DB, st.session_state.resins)
                        st.success("Resin database updated!")
                        st.rerun()
                    st.markdown("---")
                    _del_r_names = [r['name'] for r in st.session_state.resins]
                    _del_r_sel = st.selectbox("Select resin to delete", _del_r_names, key="del_res_sel")
                    if st.button("Delete Resin", key="del_res_btn", type="secondary"):
                        st.session_state.resins.pop(_del_r_names.index(_del_r_sel))
                        save_db(RESINS_DB, st.session_state.resins)
                        st.rerun()
                else:
                    st.caption("No resins saved yet.")
            r_pdf = st.file_uploader("Upload Resin PDF", type=["pdf"])
            r_parsed = {}
            if r_pdf:
                with st.spinner("Parsing PDF..."):
                    import tempfile
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(r_pdf.getvalue())
                        tmp_pdf = tmp.name
                    from pdf_parser import extract_properties_from_pdf
                    r_parsed = extract_properties_from_pdf(tmp_pdf)
                    os.unlink(tmp_pdf)
            r_name = st.text_input("Resin Name", value=r_pdf.name.replace(".pdf","") if r_pdf else "Epoxy 3501")
            r_e_t = st.number_input("Tensile Modulus (GPa)", value=r_parsed.get('tensile_modulus_gpa', None), key="r_e_t")
            r_e_c = st.number_input("Compressive Modulus (GPa)", value=r_parsed.get('compressive_modulus_gpa', None), key="r_e_c")
            r_sc = st.number_input("Shear Strength (MPa)", value=None, key="r_sc")
            r_nu = st.number_input("Isotropic nu", value=r_parsed.get('poissons_ratio', None), key="r_nu")
            r_rho = st.number_input("Density (kg/m3)", value=r_parsed.get('density_kg_m3', None), key="r_rho")
            if st.button("Save Resin"):
                st.session_state.resins.append({'name': r_name, 'E_t': cln(r_e_t)*1e9, 'E_c': cln(r_e_c)*1e9, 'nu': cln(r_nu), 'density': cln(r_rho), 'S': cln(r_sc)*1e6})
                save_db(RESINS_DB, st.session_state.resins)
                st.success("Saved!")
                st.rerun()

    with t2:
        with st.expander("Saved Laminae", expanded=bool(st.session_state.laminae)):
            if st.session_state.laminae:
                df_lam = pd.DataFrame(st.session_state.laminae)
                for c in ['E11_t', 'E11_c', 'E11', 'E22', 'G12']:
                    if c in df_lam.columns: df_lam[c] /= 1e9
                for c in ['Xt', 'Xc', 'Yt', 'Yc', 'S12']:
                    if c in df_lam.columns: df_lam[c] /= 1e6
                edit_lam_df = st.data_editor(df_lam, num_rows="dynamic", key="lam_editor")
                if st.button("Save Database Edits", key="save_lam_edits"):
                    new_l = edit_lam_df.to_dict('records')
                    for row in new_l:
                        for c in ['E11_t', 'E11_c', 'E11', 'E22', 'G12']:
                            if c in row: row[c] = cln(row[c]) * 1e9
                        for c in ['Xt', 'Xc', 'Yt', 'Yc', 'S12']:
                            if c in row: row[c] = cln(row[c]) * 1e6
                    st.session_state.laminae = new_l
                    save_db(LAMINAE_DB, st.session_state.laminae)
                    st.success("Laminae updated!")
                    st.rerun()
                st.markdown("---")
                _del_l_names = [l['name'] for l in st.session_state.laminae]
                _del_l_sel = st.selectbox("Select lamina to delete", _del_l_names, key="del_lam_sel")
                if st.button("Delete Lamina", key="del_lam_btn", type="secondary"):
                    st.session_state.laminae.pop(_del_l_names.index(_del_l_sel))
                    save_db(LAMINAE_DB, st.session_state.laminae)
                    st.rerun()
            else:
                st.caption("No laminae saved yet.")
        if not st.session_state.fibers or not st.session_state.resins:
            st.warning("Save a fiber and resin first.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                sel_f = st.selectbox("Fiber", range(len(st.session_state.fibers)), format_func=lambda i: st.session_state.fibers[i]['name'])
                sel_r = st.selectbox("Resin", range(len(st.session_state.resins)), format_func=lambda i: st.session_state.resins[i]['name'])
                vf = st.slider("Fiber Volume Fraction (Vf)", 0.1, 0.9, 0.6)
            with c2:
                l_name = st.text_input("Lamina Name", value=f"{st.session_state.fibers[sel_f]['name']} Lamina")
                faw = st.number_input("Fiber Areal Weight (FAW, g/m2)", value=150.0)
                f_dens = st.session_state.fibers[sel_f].get('density', 1800.0)
                thick_mm = 0.0
                if f_dens > 0 and vf > 0:
                    thick_mm = ((faw / 1000.0) / (f_dens * vf)) * 1000.0
                st.info(f"Cured Thickness: {thick_mm:.4f} mm")
                if st.button("Save Lamina"):
                    lam_props = calculate_lamina_properties(st.session_state.fibers[sel_f], st.session_state.resins[sel_r], vf)
                    lam_props['name'] = l_name
                    lam_props['thickness_mm'] = thick_mm
                    st.session_state.laminae.append(lam_props)
                    save_db(LAMINAE_DB, st.session_state.laminae)
                    st.success("Saved!")
                    st.rerun()

    with t3:
        with st.expander("Saved Layups", expanded=bool(st.session_state.layups)):
            if st.session_state.layups:
                for _li, _ly in enumerate(st.session_state.layups):
                    _lc1, _lc2, _lc3 = st.columns([4, 1, 1])
                    _lc1.write(f"**{_ly['name']}** — {len(_ly['plies'])} plies")
                    if _lc2.button("Load", key=f"load_ly_{_li}"):
                        st.session_state.layup_plies = list(_ly['plies'])
                        st.rerun()
                    if _lc3.button("Delete", key=f"del_ly_{_li}", type="secondary"):
                        st.session_state.layups.pop(_li)
                        save_db(LAYUPS_DB, st.session_state.layups)
                        st.rerun()
            else:
                st.caption("No layups saved yet.")
        st.subheader("Current Layup Stack")
        c1, c2 = st.columns(2)
        with c1:
            if not st.session_state.laminae:
                st.warning("Needs laminae first.")
            else:
                sc_lam = st.selectbox("Lamina", range(len(st.session_state.laminae)), format_func=lambda i: st.session_state.laminae[i]['name'])
                sc_ang = st.number_input("Angle (deg)", value=0.0, step=15.0)
                if st.button("Add Ply"):
                    st.session_state.layup_plies.append({'lamina_name': st.session_state.laminae[sc_lam]['name'], 'angle': sc_ang})
                    st.rerun()
                if st.button("Clear Plies"):
                    st.session_state.layup_plies = []
                    st.rerun()
                st.divider()
                l_save_name = st.text_input("Layup Name", value="Quasi-Isotropic 8-ply")
                if st.button("💾 Save Layup") and st.session_state.layup_plies:
                    st.session_state.layups.append({'name': l_save_name, 'plies': list(st.session_state.layup_plies)})
                    save_db(LAYUPS_DB, st.session_state.layups)
                    st.success(f"Saved {l_save_name}")
        with c2:
            if st.session_state.layup_plies:
                stack_df = []
                tt = 0.0
                for i, p in enumerate(st.session_state.layup_plies):
                    lam = next((x for x in st.session_state.laminae if x['name'] == p['lamina_name']), None)
                    t = lam['thickness_mm'] if lam else 0.0
                    stack_df.append({'Ply #': i+1, 'Material': lam['name'] if lam else "MISSING", 'Orientation': p['angle'], 'Thick(mm)': t})
                    tt += t
                st.table(pd.DataFrame(stack_df).set_index('Ply #'))
                st.info(f"Total Thickness: {tt:.3f} mm")
                idx_to_remove = st.selectbox("Select Ply to Remove:", range(len(st.session_state.layup_plies)))
                if st.button("🗑️ Remove Ply"):
                    st.session_state.layup_plies.pop(idx_to_remove)
                    st.rerun()
            else:
                st.caption("No plies in current stack.")
    

# ==========================================
# PAGE 2: SOLUTION SETUP
# ==========================================
elif nav_selection == pages[1]:
    st.header("⚙️ Solution Setup: Constraints, Sub-Modeling, & Execution")
    
    st.markdown("### Part 1: Boundary Conditions")
    c1, c2 = st.columns(2)
    with c1:
        st.session_state.bc_type = st.selectbox("Global Beam Constraint (Affects Euler)", 
            ["Fixed-Free (Cantilever)", "Pinned-Pinned", "Fixed-Pinned", "Fixed-Fixed"],
            index=["Fixed-Free (Cantilever)", "Pinned-Pinned", "Fixed-Pinned", "Fixed-Fixed"].index(st.session_state.bc_type))

    with c2:
        dof_labels = {1:"UX", 2:"UY", 3:"UZ", 4:"RX", 5:"RY", 6:"RZ"}
        with st.expander("Override CCX 3D DOF Constraints"):
            st.session_state.ccx_root_dofs = st.multiselect("CCX Root Nodes", [1,2,3,4,5,6], default=st.session_state.ccx_root_dofs, format_func=lambda x: dof_labels[x])
            st.session_state.ccx_tip_dofs = st.multiselect("CCX Tip Nodes", [1,2,3,4,5,6], default=st.session_state.ccx_tip_dofs, format_func=lambda x: dof_labels[x])

    st.divider()
    
    st.markdown("### Part 2: Thermal & CCX Snippet Settings")
    c3, c4 = st.columns(2)
    with c3:
        st.session_state.include_thermal = st.checkbox("Include Static Thermal Pre-Stress", value=st.session_state.include_thermal)
        if st.session_state.include_thermal:
            st.session_state.nlgeom_thermal = st.checkbox("Use NLGEOM for Thermal Step", value=st.session_state.nlgeom_thermal)
            st.session_state.temp_max_x = st.number_input("Temp Max +X", value=st.session_state.temp_max_x)
            st.session_state.temp_min_x = st.number_input("Temp Min -X", value=st.session_state.temp_min_x)
            st.session_state.temp_ref = st.number_input("Ref Temp", value=st.session_state.temp_ref)
    with c4:
        st.session_state.snippet_length = st.number_input("Snippet Length (mm)", value=st.session_state.snippet_length, step=10.0)
        st.session_state.snippet_elems_z = st.number_input("Elements along Z", value=st.session_state.snippet_elems_z)
        st.session_state.snippet_compressive_load = st.number_input("Compressive Tip Load (N)", value=st.session_state.snippet_compressive_load)

# ==========================================
# PAGE 3: RESULTS DASHBOARD
# ==========================================
elif nav_selection == pages[2]:
    st.header("📊 Results & Execution Dashboard")
    
    target_thickness = 0.25 # default fallback
    if st.session_state.layup_plies:
        tt = 0.0
        for p in st.session_state.layup_plies:
            lam = next((x for x in st.session_state.laminae if x['name'] == p.get('lamina_name')), None)
            if lam:
                tt += lam['thickness_mm']
        target_thickness = tt

    if not st.session_state.geo_file_name:
        st.warning("⚠ Please complete the Geometry upload in Pre-Processing first.")
    elif not st.session_state.layup_plies:
        st.warning("⚠ Please define a layup sequence in the Layup Design tab.")
    else:
        run_btn = st.button("▶️ Run Total Engine Analysis", type="primary", use_container_width=True)
        if run_btn:
            with st.spinner("Executing processing pipeline..."):
                from datetime import datetime
                _ui_log = []
                def _log(msg, level=logging.INFO):
                    ts = datetime.now().strftime("%H:%M:%S")
                    line = f"[BEAM {ts}] {msg}"
                    _ui_log.append(line)
                    logger.log(level, msg)
                
                _log("=== Pipeline START ===")
                _log(f"  Geometry  : {st.session_state.geo_file_name}")
                _log(f"  Plies     : {len(st.session_state.layup_plies)}")
                _log(f"  Span      : {st.session_state.span_length} m  |  Snippet length: {st.session_state.snippet_length} mm")

                runs_dir = os.path.join(os.getcwd(), 'runs')
                os.makedirs(runs_dir, exist_ok=True)
                
                # Build Layup Object from Session State
                mats = []
                angs = []
                from materials import CompositeMaterial, Layup, assign_properties_to_mesh
                for p in st.session_state.layup_plies:
                    lam = next((x for x in st.session_state.laminae if x['name'] == p['lamina_name']), None)
                    if not lam: continue
                    cm = CompositeMaterial(
                        E11=lam['E11'], E22=lam['E22'], G12=lam['G12'], nu12=lam['nu12'],
                        density=lam['density'], ply_thickness=lam['thickness_mm'],
                        cte11=lam.get('cte11', 0.0), cte22=lam.get('cte22', 0.0)
                    )
                    mats.append(cm)
                    angs.append(p['angle'])
                    _log(f"  Ply       : {lam['name']}  @ {p['angle']}°")
                    
                layup = Layup(mats, angs)
                tmp_filename = 'meshes/last_uploaded.3dm'
                    
                try:
                    # 1. MESHING
                    st.subheader("1. Profile Mesher Output")
                    vtk_out_path = os.path.join(runs_dir, st.session_state.geo_file_name.replace(".3dm", ".vtk"))
                    from mesher import ProfileMesher
                    mesher = ProfileMesher(
                        tmp_filename, 
                        thickness=target_thickness, 
                        num_elements_thickness=st.session_state.num_elem_thick, 
                        element_size_along_curve=st.session_state.elem_size,
                        vtk_out_path=vtk_out_path
                    )
                    
                    try:
                        mesh_data = mesher.generate()
                        nodes = mesh_data['nodes']
                        elements = mesh_data['elements']
                        _log(f"  Mesh OK   : {len(nodes)} nodes, {len(elements)} elements")
                        st.success(f"Generated structured Transfinite mesh with {len(nodes)} nodes and {len(elements)} elements.")
                        
                        if os.path.exists(vtk_out_path):
                            with open(vtk_out_path, "rb") as f:
                                st.download_button(
                                    label="Download Paraview Mesh (.vtk)",
                                    data=f,
                                    file_name=os.path.basename(vtk_out_path),
                                    mime="application/octet-stream"
                                )
                        
                        fig, ax = plt.subplots(figsize=(10, 5))
                        for elem in elements:
                            pts = nodes[elem][:, :2]
                            pts = np.vstack((pts, pts[0]))
                            ax.plot(pts[:, 0], pts[:, 1], 'k-', lw=0.6, alpha=0.8)
                        ax.set_aspect('equal', 'box')
                        ax.grid(True, linestyle='--', alpha=0.5)
                        st.pyplot(fig)
                        
                    except Exception as e:
                        _log(f"  Mesh FAIL : {e}", logging.ERROR)
                        st.error(f"Meshing failed: {e}")
                        st.stop()
                        
                    # 2. MATERIAL MAPPING
                    st.subheader("2. Material & Property Mapping")
                    try:
                        vabs_props_dict = assign_properties_to_mesh(mesh_data, layup)
                        st.success(f"Successfully mapped {len(layup.materials)} plies to {vabs_props_dict['num_elements']} elements.")
                    except Exception as e:
                        st.error(f"Property assignment failed: {e}")
                        st.stop()

                    # 3. SWIFTCOMP CROSS-SECTION
                    st.subheader("3. SwiftComp Cross-sectional Analysis")
                    try:
                        from solvers import SwiftCompSolver
                        solver = SwiftCompSolver(executable_path=st.session_state.swiftcomp_path, working_dir=runs_dir)
                        solver.write_input_file(mesh_data, vabs_props_dict['element_properties'])
                        solver.execute()
                        k_matrix = solver.parse_results()
                        
                        st.write(f"**Cross-sectional 6x6 Stiffness Matrix (K)**")
                        labels = ["Axial (F1)", "Lateral (F2)", "Vertical (F3)", "Torsion (M1)", "Bending (M2)", "Bending (M3)"]
                        df_k = pd.DataFrame(k_matrix, columns=["E1", "E2", "E3", "K1", "K2", "K3"], index=labels)
                        st.dataframe(df_k.style.format("{:.3e}"))
                    except Exception as e:
                        _log(f"  SwiftComp FAIL : {e}", logging.ERROR)
                        logger.exception("SwiftComp traceback:")
                        st.error(f"SwiftComp execution failed / skipped.")
                        st.code(str(e), language="text")
                        k_matrix = np.eye(6)
                        st.warning("⚠️ SwiftComp failed — falling back to identity K-matrix.")

                    # 4. GXBeam
                    st.subheader("4. GXBeam 1D Global Beam Analysis")
                    try:
                        from solvers import GXBeamSolver
                        k_SI = k_matrix.copy()
                        bending_idx = [3, 4, 5]
                        for r in range(6):
                            for c in range(6):
                                if r in bending_idx and c in bending_idx:
                                    k_SI[r, c] /= 1e6
                                elif r in bending_idx or c in bending_idx:
                                    k_SI[r, c] /= 1e3

                        pts = nodes[:, :2]
                        x_min_sec, x_max_sec = np.min(pts[:, 0]), np.max(pts[:, 0])
                        total_A, x_cen, y_cen = 0.0, 0.0, 0.0
                        for elem in elements:
                            ep = pts[elem]
                            xc_e, yc_e = np.mean(ep[:, 0]), np.mean(ep[:, 1])
                            x0,y0 = ep[0]; x1,y1 = ep[1]; x2,y2 = ep[2]; x3,y3 = ep[3]
                            Ae = 0.5*abs((x0*y1-x1*y0)+(x1*y2-x2*y1)+(x2*y3-x3*y2)+(x3*y0-x0*y3))
                            total_A += Ae
                            x_cen  += Ae * xc_e
                            y_cen  += Ae * yc_e
                        x_cen /= (total_A + 1e-30)
                        y_cen /= (total_A + 1e-30)

                        F_th = 0.0; M2_th = 0.0; M3_th = 0.0
                        for i, elem in enumerate(elements):
                            ep = pts[elem]
                            xc, yc = np.mean(ep[:, 0]), np.mean(ep[:, 1])
                            x0,y0 = ep[0]; x1,y1 = ep[1]; x2,y2 = ep[2]; x3,y3 = ep[3]
                            A_e_mm2 = 0.5*abs((x0*y1-x1*y0)+(x1*y2-x2*y1)+(x2*y3-x3*y2)+(x3*y0-x0*y3))
                            A_e_m2  = A_e_mm2 * 1e-6

                            if x_max_sec > x_min_sec:
                                frac = (xc - x_min_sec) / (x_max_sec - x_min_sec)
                                T_c = st.session_state.temp_min_x + frac * (st.session_state.temp_max_x - st.session_state.temp_min_x)
                            else:
                                T_c = 0.5 * (st.session_state.temp_max_x + st.session_state.temp_min_x)

                            dT_total = T_c - st.session_state.temp_ref
                            T_mean   = 0.5*(st.session_state.temp_max_x + st.session_state.temp_min_x)
                            dT_mean  = T_mean - st.session_state.temp_ref
                            dT_grad  = dT_total - dT_mean

                            prop = vabs_props_dict['element_properties'][i]
                            avg_E11   = np.mean([p['material'].E11   for p in prop['layup']])
                            avg_cte11 = np.mean([p['material'].cte11 for p in prop['layup']])

                            dF_axial = avg_E11 * avg_cte11 * dT_mean * A_e_m2
                            dF_bend  = avg_E11 * avg_cte11 * dT_grad * A_e_m2

                            F_th  += dF_axial
                            M3_th += dF_bend * (xc - x_cen) * 1e-3
                            M2_th += dF_bend * (yc - y_cen) * 1e-3

                        # Clamp thermal loads
                        EA_SI = k_SI[0, 0]
                        P_euler = (np.pi**2 * k_SI[5, 5] / (st.session_state.span_length**2)) if k_SI[5, 5] > 0 else 1e9
                        max_f = min(0.001 * EA_SI, 10.0 * P_euler)
                        if abs(F_th) > max_f:
                            scale = max_f / abs(F_th)
                            st.warning(f"Thermal loads are extreme ({F_th:.2e} N). Clamping to {max_f:.2f} N for solver stability.")
                            F_th *= scale; M2_th *= scale; M3_th *= scale

                        gxbeam = GXBeamSolver(stiffness_matrix=k_SI, span=st.session_state.span_length,
                                              executable_path=st.session_state.gxbeam_path, working_dir=runs_dir)
                        gxbeam.tip_load = [F_th, 0.0, 0.0, 0.0, M2_th, M3_th]
                        gxbeam_bc_map = {"Fixed-Free (Cantilever)": "cantilever", "Pinned-Pinned": "pinned-pinned", 
                                         "Fixed-Pinned": "fixed-pinned", "Fixed-Fixed": "fixed-fixed"}
                        gxbeam.bc_type = gxbeam_bc_map[st.session_state.bc_type]
                        gxbeam.write_input_file()
                        gxbeam.execute()
                        deflections, gxbeam_vtk_path = gxbeam.parse_results()
                        st.write(f"**Tip Deflections at Span = {st.session_state.span_length}m ({st.session_state.bc_type})**")
                        
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Axial Disp (u1)", f"{deflections[0]:.4e} m")
                        c2.metric("Lateral Disp (u2)", f"{deflections[1]:.4e} m")
                        c3.metric("Vertical Disp (u3)", f"{deflections[2]:.4e} m")
                        
                        c4, c5, c6 = st.columns(3)
                        c4.metric("Twist (rot1)", f"{deflections[3]:.4e} rad")
                        c5.metric("Bending (rot2)", f"{deflections[4]:.4e} rad")
                        c6.metric("Bending (rot3)", f"{deflections[5]:.4e} rad")

                        beam_vtk_path = os.path.join(runs_dir, "deformed_beam.vtk")
                        gxbeam.write_deformed_beam_vtk(mesh_data, deflections, beam_vtk_path)
                        st.info("💡 ParaView: Color by `displacement_magnitude`, or apply Warp by Vector (`displacement`) to exaggerate deflection.")
                        
                        g1, g2 = st.columns(2)
                        with open(beam_vtk_path, "rb") as vf:
                            g1.download_button(label="⬇️ Download Deformed Beam 3D (.vtk)", data=vf, file_name="deformed_beam.vtk", mime="application/octet-stream", key="dl_gxbeam_vtk")
                        
                        if g2.button("👁️ Open in ParaView", key="open_pv_gxbeam"):
                            import subprocess
                            try:
                                subprocess.Popen(["paraview", beam_vtk_path], shell=True)
                            except Exception as pe:
                                st.error(f"Failed to launch ParaView: {pe}")

                    except Exception as e:
                        st.error(f"GXBeam execution failed.")
                        st.code(str(e), language="text")

                    # 5. EULER
                    st.subheader("5. Global Euler Buckling Estimation")
                    euler_K = {"Fixed-Free (Cantilever)": 2.0, "Pinned-Pinned": 1.0, "Fixed-Pinned": 0.7, "Fixed-Fixed": 0.5}[st.session_state.bc_type]
                    EI_22, EI_33 = k_SI[4, 4], k_SI[5, 5]
                    KL_sq = (euler_K * st.session_state.span_length)**2 if st.session_state.span_length > 0 else 1.0
                    P_cr_22 = (np.pi**2 * EI_22) / KL_sq
                    P_cr_33 = (np.pi**2 * EI_33) / KL_sq
                    
                    b1, b2, b3 = st.columns(3)
                    b1.metric("Critical Load (Lateral Bending)", f"{P_cr_22 / 1000:.2f} kN")
                    b2.metric("Critical Load (Vertical Bending)", f"{P_cr_33 / 1000:.2f} kN")
                    min_load = min(P_cr_22, P_cr_33)
                    b3.metric("Limit Buckling Load", f"{min_load / 1000:.2f} kN" if min_load > 0 else "-")
                            
                    # 6. CALCULIX
                    st.subheader("6. Local Buckling (CalculiX Snippet)")
                    st.write(f"Generating explicit 3D C3D8 sub-model shell of {st.session_state.snippet_length}mm length...")
                    try:
                        from solvers import CalculiXSolver
                        ccx_solver = CalculiXSolver(executable_path=st.session_state.ccx_path, working_dir=runs_dir)
                        inp_file = ccx_solver.write_input_file(
                            mesh_data, vabs_props_dict['element_properties'],
                            length=st.session_state.snippet_length,
                            num_elements_z=st.session_state.snippet_elems_z,
                            compressive_load=st.session_state.snippet_compressive_load,
                            temp_min_x=st.session_state.temp_min_x if st.session_state.include_thermal else st.session_state.temp_ref,
                            temp_max_x=st.session_state.temp_max_x if st.session_state.include_thermal else st.session_state.temp_ref,
                            temp_ref=st.session_state.temp_ref,
                            nlgeom=st.session_state.nlgeom_thermal,
                            root_dofs=st.session_state.ccx_root_dofs,
                            tip_dofs=st.session_state.ccx_tip_dofs
                        )
                        st.info(f"Generated sub-model deck: `{os.path.basename(inp_file)}`")
                        
                        _nodes_2d = mesh_data['nodes']
                        _elems_2d = mesh_data['elements']
                        _nn2d = len(_nodes_2d)
                        _z_vals = np.linspace(0, st.session_state.snippet_length, st.session_state.snippet_elems_z + 1)
                        _nodes_3d_list = []
                        for _z in _z_vals:
                            _layer = _nodes_2d.copy()
                            _layer[:, 2] = _z
                            _nodes_3d_list.append(_layer)
                        _nodes_3d = np.vstack(_nodes_3d_list)
                        _elems_3d = []
                        for _k in range(st.session_state.snippet_elems_z):
                            _lo, _hi = _k * _nn2d, (_k + 1) * _nn2d
                            for _e in _elems_2d:
                                n1,n2,n3,n4 = _e
                                _elems_3d.append([n1+_lo+1, n2+_lo+1, n3+_lo+1, n4+_lo+1,
                                                  n1+_hi+1, n2+_hi+1, n3+_hi+1, n4+_hi+1])
                        
                        ccx_success = ccx_solver.execute()
                        if ccx_success:
                            multiplier = ccx_solver.parse_results()
                            if multiplier is not None:
                                if multiplier > 1.0: st.success(f"**Buckling Factor:** {multiplier:.5f} (Safe)")
                                else: st.error(f"**Buckling Factor:** {multiplier:.5f} (Buckles!)")
                                st.write(f"**Critical Local Load:** {abs(st.session_state.snippet_compressive_load * multiplier):.2f} N")
                            else:
                                st.warning("CalculiX finished, but no 'BUCKLING FACTOR' was found in the .dat file.")

                        frd_path = os.path.join(runs_dir, 'snippet.frd')
                        if os.path.exists(frd_path):
                            _vtk_path = os.path.join(runs_dir, "snippet_mode.vtk")
                            ccx_solver.write_mode_vtk(_nodes_3d, _elems_3d, frd_path, _vtk_path)
                            st.info("💡 ParaView: open snippet_mode.vtk -> Filters -> Warp by Vector -> select `displacement`, scale as needed.")
                            
                            cd1, cd2, cd3 = st.columns(3)
                            with open(frd_path, "rb") as frd_f:
                                cd1.download_button(label="⬇️ Download (.frd)", data=frd_f, file_name="snippet.frd", mime="application/octet-stream", key="dl_ccx_frd")
                            with open(_vtk_path, "rb") as _vf:
                                cd2.download_button(label="⬇️ Download (.vtk)", data=_vf, file_name="snippet_mode.vtk", mime="application/octet-stream", key="dl_ccx_vtk")
                            if cd3.button("👁️ Open in ParaView", key="open_pv_ccx"):
                                import subprocess
                                try:
                                    subprocess.Popen(["paraview", _vtk_path], shell=True)
                                except Exception as pe:
                                    st.error(f"Failed to launch ParaView: {pe}")
                            
                            try:
                                disps = ccx_solver.parse_frd_displacements(frd_path)
                                if disps is not None and len(disps) > 0:
                                    mag = np.linalg.norm(disps, axis=1)
                                    scale = 0.1 * st.session_state.snippet_length / (np.max(mag) + 1e-12)
                                    mid_layer = st.session_state.snippet_elems_z // 2
                                    offset = mid_layer * _nn2d
                                    base_pts = mesh_data['nodes'][:, :2]
                                    d_slice = disps[offset:offset + _nn2d, :2] * scale
                                    deformed = base_pts + d_slice
                                    mag_slice = mag[offset:offset + _nn2d]
                                    
                                    fig2, ax2 = plt.subplots(figsize=(10, 4))
                                    for elem in mesh_data['elements']:
                                        p0 = base_pts[elem]; p0 = np.vstack((p0, p0[0]))
                                        p1 = deformed[elem]; p1 = np.vstack((p1, p1[0]))
                                        ax2.plot(p0[:, 0], p0[:, 1], 'k--', lw=0.4, alpha=0.4)
                                        ax2.plot(p1[:, 0], p1[:, 1], 'b-', lw=0.7)
                                    sc2 = ax2.scatter(deformed[:, 0], deformed[:, 1], c=mag_slice, cmap='plasma', s=8, zorder=3)
                                    plt.colorbar(sc2, ax=ax2, label='Displacement (scaled)')
                                    ax2.set_title('Buckling Mode Shape — Mid-span Cross-section (dashed=undeformed)')
                                    ax2.set_aspect('equal', 'box')
                                    st.pyplot(fig2)
                            except Exception as _fe:
                                st.caption(f'_(Mode shape render skipped: {_fe})_')
                                
                    except Exception as e:
                        _log(f"  CCX FAIL : {e}")
                        st.error("CalculiX snippet workflow failed.")
                        st.code(str(e), language="text")

                except Exception as e:
                    _log(f"  Unhandled Pipeline Exception: {e}", logging.ERROR)
                    logger.exception("Pipeline traceback:")
                    st.error(f"Pipeline crashed entirely: {e}")
                
                _log("=== Pipeline COMPLETE ===")
                try:
                    os.unlink(tmp_filename)
                except:
                    pass
                
                with st.expander("📝 Pipeline Execution Log", expanded=False):
                    st.code("\n".join(_ui_log), language="text")
                st.balloons()

