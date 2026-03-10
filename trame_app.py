"""BEAM Composite Section Analyzer — Trame Application Entry Point."""

import asyncio
import base64
import logging
import os

# Configure terminal logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

from trame.app import get_server
from trame.widgets import vuetify3 as v3, vtk as vtk_widgets
from trame.ui.vuetify3 import SinglePageWithDrawerLayout

from trame_app.state import initialize_state, save_db, LAST_SESSION_DB
from trame_app.vtk_views import (
    create_plotter,
    show_mesh_preview,
    show_snippet_preview,
    show_deformed_beam,
    show_buckling_mode,
    autoscale_data_range,
    clear_serializer_cache,
)
from trame_app.pages.preprocessing import build_preprocessing_page
from trame_app.pages.solution_setup import build_solution_setup_page
from trame_app.pages.results import build_results_page
from trame_app.pages.visualization import build_visualization_page
from trame_app.engine import (
    run_all_stages,
    run_stage_1_async,
    run_stage_2_async,
    run_stage_3_async,
    run_material_sg_async,
    generate_snippet_preview,
    _snapshot_state,
)
from solvers import SwiftCompSolver

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------
server = get_server(client_type="vue3")
state, ctrl = server.state, server.controller

initialize_state(server)

# ---------------------------------------------------------------------------
# PyVista plotter
# ---------------------------------------------------------------------------
plotter = create_plotter()

# ---------------------------------------------------------------------------
# VTK view switching
# ---------------------------------------------------------------------------
def _push_view(reset_camera=True):
    """Push scene to client-side vtk.js views.

    Args:
        reset_camera: If True, also reset camera framing. False for
                      in-place updates like warp factor changes.
    """
    # Clear the trame-vtk serializer property cache so the next view.update()
    # sends complete (not delta) property data.  Without this, scalar ranges
    # from previously-deleted actors leak through the delta mechanism and
    # vtk.js receives mismatched scalarRange / valueRange pairs.
    clear_serializer_cache()
    ctrl.view_update(orientation_axis=1)
    if reset_camera:
        ctrl.view_push_camera()
        ctrl.view_reset_camera()
    try:
        ctrl.view_update_fs(orientation_axis=1)
        if reset_camera:
            ctrl.view_push_camera_fs()
            ctrl.view_reset_camera_fs()
    except AttributeError:
        pass  # Fullscreen view not available in this trame configuration
    except Exception as e:
        log.warning("Fullscreen view update failed: %s", e)


def _refresh_active_view(reset_camera=True):
    """Re-render the current active VTK view with current state settings."""
    edges = state.show_edges
    undeformed = state.show_undeformed
    active = state.active_vtk
    if active == "mesh" and state.mesh_vtk_path:
        show_mesh_preview(plotter, state.mesh_vtk_path, show_edges=edges)
    elif active == "snippet" and state.snippet_vtk_path:
        show_snippet_preview(plotter, state.snippet_vtk_path, show_edges=edges)
    elif active == "beam" and state.beam_vtk_path:
        show_deformed_beam(plotter, state.beam_vtk_path, state.warp_factor_beam,
                           show_edges=edges, show_undeformed=undeformed)
    elif active == "buckling" and state.buckling_vtk_path:
        show_buckling_mode(
            plotter, state.buckling_vtk_path, state.warp_factor_buckling,
            state.buckling_scalar, show_edges=edges, show_undeformed=undeformed,
        )
    else:
        plotter.clear()
        plotter.reset_camera()
    _push_view(reset_camera=reset_camera)


@state.change("active_vtk", "buckling_scalar")
def _on_active_vtk_change(active_vtk, buckling_scalar, **kwargs):
    _refresh_active_view(reset_camera=True)


@state.change("snippet_length", "snippet_elems_z")
def _on_snippet_params_change(snippet_length, snippet_elems_z, **kwargs):
    """Regenerate snippet preview when snippet parameters change."""
    if not state.has_mesh:
        return
    snap = _snapshot_state(state)
    try:
        vtk_path = generate_snippet_preview(snap)
        if vtk_path:
            state.snippet_vtk_path = vtk_path
            if state.active_vtk == "snippet":
                show_snippet_preview(plotter, vtk_path, show_edges=state.show_edges)
                state.flush()
                _push_view()
    except Exception:
        pass


@state.change("warp_factor_beam")
def _on_warp_beam_change(warp_factor_beam, **kwargs):
    if state.active_vtk == "beam" and state.beam_vtk_path:
        show_deformed_beam(plotter, state.beam_vtk_path, warp_factor_beam,
                           show_edges=state.show_edges, show_undeformed=state.show_undeformed,
                           reset_camera=False)
        _push_view(reset_camera=False)


@state.change("warp_factor_buckling")
def _on_warp_buckling_change(warp_factor_buckling, **kwargs):
    if state.active_vtk == "buckling" and state.buckling_vtk_path:
        show_buckling_mode(plotter, state.buckling_vtk_path, warp_factor_buckling,
                           show_edges=state.show_edges, show_undeformed=state.show_undeformed,
                           reset_camera=False)
        _push_view(reset_camera=False)


@state.change("show_edges")
def _on_show_edges_change(show_edges, **kwargs):
    _refresh_active_view(reset_camera=False)


@state.change("show_undeformed")
def _on_show_undeformed_change(show_undeformed, **kwargs):
    _refresh_active_view(reset_camera=False)


@ctrl.add("autoscale_data")
def on_autoscale_data():
    # Walk existing mappers and set scalar range from actual data in-place.
    # Avoids a full scene rebuild (plotter.clear → add_mesh) which causes vtk.js
    # to re-receive geometry and may override the server-set range on arrival.
    autoscale_data_range(plotter)
    _push_view(reset_camera=False)


@ctrl.add("snap_view")
def on_snap_view(axis):
    view_map = {
        "px": plotter.view_yz,
        "nx": lambda: plotter.view_yz(negative=True),
        "py": plotter.view_xz,
        "ny": lambda: plotter.view_xz(negative=True),
        "pz": plotter.view_xy,
        "nz": lambda: plotter.view_xy(negative=True),
    }
    fn = view_map.get(axis)
    if fn:
        fn()
    plotter.reset_camera()
    _push_view()


@ctrl.add("reset_view")
def on_reset_view():
    """Re-render the current view from scratch with default warp and camera."""
    if state.active_vtk == "beam":
        state.warp_factor_beam = 1.0
    elif state.active_vtk == "buckling":
        state.warp_factor_buckling = 1.0
    state.flush()
    _refresh_active_view(reset_camera=True)


# ---------------------------------------------------------------------------
# Execution Controllers
# ---------------------------------------------------------------------------
@ctrl.add("run_all")
def on_run_all():
    asyncio.ensure_future(_run_all_async())

async def _run_all_async():
    await run_all_stages(state)

@ctrl.add("run_stage_1")
def on_run_stage_1():
    asyncio.ensure_future(run_stage_1_async(state))

@ctrl.add("run_stage_2")
def on_run_stage_2():
    asyncio.ensure_future(run_stage_2_async(state))

@ctrl.add("run_stage_3")
def on_run_stage_3():
    asyncio.ensure_future(run_stage_3_async(state))

@ctrl.add("run_material_sg")
def on_run_material_sg():
    asyncio.ensure_future(run_material_sg_async(state))


# ---------------------------------------------------------------------------
# Session Persistence
# ---------------------------------------------------------------------------
@state.change("geo_file_name", "layup_plies")
def save_session(**kwargs):
    save_db(LAST_SESSION_DB, {
        "geo_file_name": state.geo_file_name,
        "layup_plies": state.layup_plies,
    })

@ctrl.add("export_ansys")
def export_ansys():
    if not state.result_k_mm:
        return

    runs_dir = state.result_runs_dir or "runs"
    os.makedirs(runs_dir, exist_ok=True)

    mac_path = os.path.join(runs_dir, "beam_properties.mac")
    sc = SwiftCompSolver()
    sc.write_ansys_macro(state.result_k_mm, mac_path)

    # Send base64 content + filename; client-side JS does the Blob download
    with open(mac_path, "r") as f:
        text = f.read()
    state.export_content = base64.b64encode(text.encode()).decode()
    state.export_filename = "beam_properties.mac"
    state.export_trigger += 1

# ---------------------------------------------------------------------------
# UI Layout
# ---------------------------------------------------------------------------
NAV_ITEMS = [
    {"title": "Pre-Processing", "icon": "mdi-cog-outline", "page": 0},
    {"title": "Solution Setup", "icon": "mdi-tune", "page": 1},
    {"title": "Results", "icon": "mdi-chart-box-outline", "page": 2},
    {"title": "Visualization", "icon": "mdi-cube-scan", "page": 3},
]

with SinglePageWithDrawerLayout(server, full_height=True) as layout:
    layout.title.set_text("BEAM — Composite Section Analyzer")


    # --- Drawer: Navigation + Solver Paths ---
    with layout.drawer as drawer:
        drawer.width = 300

        with v3.VList(nav=True, density="compact"):
            for item in NAV_ITEMS:
                v3.VListItem(
                    title=item["title"],
                    prepend_icon=item["icon"],
                    click=f"active_page = {item['page']}",
                    active=f"active_page === {item['page']}",
                )

        v3.VDivider(classes="my-2")

        with v3.VExpansionPanels(variant="accordion"):
            with v3.VExpansionPanel(title="Solver Paths"):
                with v3.VExpansionPanelText():
                    v3.VTextField(
                        label="SwiftComp",
                        v_model=("swiftcomp_path",),
                        density="compact",
                        hide_details=True,
                        classes="mb-2",
                    )
                    v3.VTextField(
                        label="Julia (GXBeam)",
                        v_model=("gxbeam_path",),
                        density="compact",
                        hide_details=True,
                        classes="mb-2",
                    )
                    v3.VTextField(
                        label="CalculiX",
                        v_model=("ccx_path",),
                        density="compact",
                        hide_details=True,
                    )

    # --- Main Content ---
    with layout.content:
        with v3.VContainer(fluid=True, classes="fill-height"):
            # Page 0: Pre-Processing
            with v3.VRow(v_show="active_page === 0"):
                with v3.VCol(cols=12):
                    build_preprocessing_page(server)

            # Page 1: Solution Setup
            with v3.VRow(v_show="active_page === 1"):
                with v3.VCol(cols=12):
                    build_solution_setup_page(server)

            # Page 2: Results
            with v3.VRow(v_show="active_page === 2"):
                with v3.VCol(cols=12):
                    build_results_page(server)

            # Page 3: Visualization
            with v3.VRow(v_show="active_page === 3"):
                with v3.VCol(cols=12):
                    build_visualization_page(server, plotter)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    server.start(port=8502)
