"""Page 4: Visualization — 3D VTK viewport with toolbars."""

from trame.widgets import vuetify3 as v3, html
from trame_vtk.widgets.vtk import VtkLocalView


SCALAR_OPTIONS = [
    {"title": "Displacement Mag", "value": "displacement_magnitude"},
    {"title": "Von Mises Stress", "value": "von_mises_stress"},
    {"title": "S11 (Axial)", "value": "S11"},
    {"title": "S22 (Hoop)", "value": "S22"},
    {"title": "S33 (Through-thick)", "value": "S33"},
    {"title": "S12 (Shear)", "value": "S12"},
    {"title": "S13 (Shear)", "value": "S13"},
    {"title": "S23 (Shear)", "value": "S23"},
]

INTERACTOR_SETTINGS_3D = [
    {"button": 1, "action": "Rotate"},
    {"button": 2, "action": "Pan"},
    {"button": 3, "action": "Zoom", "scrollEnabled": True},
    {"button": 1, "action": "Pan", "shift": True},
    {"button": 1, "action": "Zoom", "control": True},
    {"button": 1, "action": "Roll", "alt": True, "shift": True},
]

INTERACTOR_SETTINGS_2D = [
    {"button": 1, "action": "Pan"},
    {"button": 2, "action": "Pan"},
    {"button": 3, "action": "Zoom", "scrollEnabled": True},
    {"button": 1, "action": "Zoom", "control": True},
]


def _build_warp_row(fullscreen=False):
    """Warp slider + number input, shown for beam/buckling views."""
    with v3.VSheet(
        v_if="active_vtk === 'beam' || active_vtk === 'buckling'",
        color="grey-darken-3",
        theme="dark",
        style="position: sticky; top: 48px; z-index: 9;" if not fullscreen else "",
        classes="px-4 py-1 d-flex align-center",
    ):
        # Beam warp controls
        with html.Div(v_if="active_vtk === 'beam'", classes="d-flex align-center flex-grow-1"):
            html.Span("Warp ×", classes="text-caption mr-2 flex-shrink-0")
            v3.VSlider(
                v_model=("warp_factor_beam",),
                min=0.1, max=5, step=0.1,
                density="compact",
                hide_details=True,
                classes="flex-grow-1",
            )
            v3.VTextField(
                v_model=("warp_factor_beam",),
                type="number",
                density="compact",
                hide_details=True,
                style="max-width: 90px;",
                classes="ml-3 flex-shrink-0",
                **{"@keyup.enter": "$event.target.blur()"},
            )

        # Buckling warp controls
        with html.Div(v_if="active_vtk === 'buckling'", classes="d-flex align-center flex-grow-1"):
            html.Span("Warp ×", classes="text-caption mr-2 flex-shrink-0")
            v3.VSlider(
                v_model=("warp_factor_buckling",),
                min=0.1, max=100, step=0.1,
                density="compact",
                hide_details=True,
                classes="flex-grow-1",
            )
            v3.VTextField(
                v_model=("warp_factor_buckling",),
                type="number",
                density="compact",
                hide_details=True,
                style="max-width: 90px;",
                classes="ml-3 flex-shrink-0",
            )


def _build_toolbar(ctrl, fullscreen=False):
    """Main controls toolbar. sticky in inline mode."""
    toolbar_style = "position: sticky; top: 0; z-index: 10;" if not fullscreen else ""
    with v3.VToolbar(
        density="compact",
        color="grey-darken-4",
        theme="dark",
        style=toolbar_style,
    ):
        with v3.VBtnToggle(
            v_model=("active_vtk",),
            mandatory=True,
            color="primary",
            density="compact",
            classes="mr-2",
        ):
            v3.VBtn("Cross-Section", value="mesh", disabled=("!mesh_vtk_path",))
            v3.VBtn("Snippet", value="snippet", disabled=("!snippet_vtk_path",))
            v3.VBtn("Deformed Beam", value="beam", disabled=("!beam_vtk_path",))
            v3.VBtn("Buckling Mode", value="buckling", disabled=("!buckling_vtk_path",))

        v3.VDivider(vertical=True, classes="mx-1")

        v3.VBtn(
            icon="mdi-fit-to-screen-outline",
            title="Zoom to Object",
            click=ctrl.reset_camera,
            variant="text",
            density="compact",
        )
        v3.VBtn(
            icon="mdi-arrow-expand-vertical",
            title="Autoscale Data Range",
            click=ctrl.autoscale_data,
            variant="text",
            density="compact",
            disabled=("active_vtk === 'mesh'",),
        )
        v3.VBtn(
            icon="mdi-refresh",
            title="Reset View",
            click=ctrl.reset_view,
            variant="text",
            density="compact",
        )

        v3.VDivider(vertical=True, classes="mx-1")

        with v3.VBtnToggle(density="compact", color="secondary", variant="text", classes="mr-1"):
            v3.VBtn("+X", click=(ctrl.snap_view, "['px']"), density="compact", size="small")
            v3.VBtn("+Y", click=(ctrl.snap_view, "['py']"), density="compact", size="small")
            v3.VBtn("+Z", click=(ctrl.snap_view, "['pz']"), density="compact", size="small")
            v3.VBtn("-X", click=(ctrl.snap_view, "['nx']"), density="compact", size="small")
            v3.VBtn("-Y", click=(ctrl.snap_view, "['ny']"), density="compact", size="small")
            v3.VBtn("-Z", click=(ctrl.snap_view, "['nz']"), density="compact", size="small")

        v3.VDivider(vertical=True, classes="mx-1")

        v3.VBtn(
            icon=("show_edges ? 'mdi-grid' : 'mdi-texture'",),
            title=("show_edges ? 'Surface only' : 'Show edges'",),
            click="show_edges = !show_edges",
            variant=("show_edges ? 'tonal' : 'text'",),
            color=("show_edges ? 'secondary' : ''",),
            density="compact",
        )
        v3.VBtn(
            v_if="active_vtk === 'beam' || active_vtk === 'buckling'",
            icon=("show_undeformed ? 'mdi-ghost' : 'mdi-ghost-off'",),
            title=("show_undeformed ? 'Hide undeformed' : 'Show undeformed'",),
            click="show_undeformed = !show_undeformed",
            variant=("show_undeformed ? 'tonal' : 'text'",),
            color=("show_undeformed ? 'secondary' : ''",),
            density="compact",
        )

        v3.VSpacer()

        v3.VSelect(
            v_if="active_vtk === 'buckling'",
            label="Scalar",
            v_model=("buckling_scalar",),
            items=("scalar_options", SCALAR_OPTIONS),
            density="compact",
            hide_details=True,
            style="max-width: 200px;",
            classes="mr-2",
        )

        if not fullscreen:
            v3.VBtn(
                icon="mdi-fullscreen",
                title="Full Screen",
                click="show_full_screen = true",
                variant="text",
                density="compact",
            )
        else:
            v3.VBtn(
                icon="mdi-close",
                click="show_full_screen = false",
                variant="text",
                density="compact",
            )


def build_visualization_page(server, plotter):
    """Build the 3D visualization page UI inside the current layout context."""
    state, ctrl = server.state, server.controller

    state.interactor_settings = INTERACTOR_SETTINGS_3D

    @state.change("active_vtk")
    def _on_vtk_type_change(active_vtk, **kwargs):
        if active_vtk == "mesh":
            state.interactor_settings = INTERACTOR_SETTINGS_2D
        else:
            state.interactor_settings = INTERACTOR_SETTINGS_3D

    # ---- Sticky toolbar + warp bar ----
    _build_toolbar(ctrl, fullscreen=False)
    _build_warp_row(fullscreen=False)

    # ---- VTK Viewport ----
    # Height accounts for toolbar (48px) + warp bar (~44px when visible)
    with v3.VSheet(
        v_if="!show_full_screen",
        style="height: calc(100vh - 140px); min-height: 400px; border: 1px solid #555;",
        classes="d-flex align-center justify-center",
    ):
        view = VtkLocalView(plotter.ren_win, interactor_settings=("interactor_settings",))
        ctrl.view_update = view.update
        ctrl.view_reset_camera = view.reset_camera
        ctrl.view_push_camera = view.push_camera

    # ---- Full Screen Dialog ----
    with v3.VDialog(v_model=("show_full_screen", False), fullscreen=True):
        with v3.VCard(theme="dark", classes="d-flex flex-column fill-height"):
            _build_toolbar(ctrl, fullscreen=True)
            _build_warp_row(fullscreen=True)

            with v3.VSheet(v_if="show_full_screen", classes="flex-grow-1", color="#1e1e1e", style="min-height: 0;"):
                view_fs = VtkLocalView(plotter.ren_win, interactor_settings=("interactor_settings",))
                ctrl.view_update_fs = view_fs.update
                ctrl.view_reset_camera_fs = view_fs.reset_camera
                ctrl.view_push_camera_fs = view_fs.push_camera

    # ---- Callbacks ----
    @ctrl.add("reset_camera")
    def _reset_camera():
        if state.active_vtk == "mesh":
            plotter.view_xy()
        plotter.reset_camera()
        ctrl.view_update()
        ctrl.view_push_camera()
        ctrl.view_reset_camera()
        try:
            ctrl.view_update_fs()
            ctrl.view_push_camera_fs()
            ctrl.view_reset_camera_fs()
        except Exception:
            pass

    @state.change("mesh_vtk_path")
    def _on_mesh_path_change(mesh_vtk_path, **kwargs):
        if mesh_vtk_path and state.active_vtk == "none":
            state.active_vtk = "mesh"
