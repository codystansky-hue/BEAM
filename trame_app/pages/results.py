"""Page 2: Results — results display and 3D visualization."""

import logging

from trame.widgets import vuetify3 as v3, html, client

log = logging.getLogger(__name__)

K_LABELS = ["Axial (F1)", "Lateral (F2)", "Vertical (F3)", "Torsion (M1)", "Bending (M2)", "Bending (M3)"]
K_COL_HEADERS = [
    {"title": "", "key": "label", "sortable": False},
    {"title": "E1", "key": "c0"},
    {"title": "E2", "key": "c1"},
    {"title": "E3", "key": "c2"},
    {"title": "K1", "key": "c3"},
    {"title": "K2", "key": "c4"},
    {"title": "K3", "key": "c5"},
]


_COPY_BTN = dict(
    prepend_icon="mdi-content-copy",
    density="compact",
    variant="tonal",
    size="small",
    classes="ml-2",
)


def _copy_js(text_expr):
    """Return a trame.trigger call that sends text to the server for clipboard copy."""
    return f"trame.trigger('_do_copy', [{text_expr}])"


def build_results_page(server, plotter):
    """Build the results page UI inside the current layout context."""
    from trame_app.pages.visualization import build_visualization_page
    state, ctrl = server.state, server.controller

    # Shared "Copied!" snackbar
    v3.VSnackbar(
        v_model=("copy_snack", False),
        timeout=1800,
        color="success",
        location="bottom right",
        text="Copied to clipboard",
    )

    # Server-side clipboard handler: receives text from client JS,
    # stores it in state, then triggers client-side execCommand fallback.
    @ctrl.trigger("_do_copy")
    def _do_copy(text="", **_):
        state.clipboard_text = text
        state.clipboard_trigger = int(state.clipboard_trigger or 0) + 1
        state.copy_snack = True

    # Client-side watcher that performs the actual copy when trigger fires
    client.ClientStateChange(
        value="clipboard_trigger",
        change=(
            "if (clipboard_text) {"
            " var a = document.createElement('textarea');"
            " a.value = clipboard_text;"
            " a.style.position = 'fixed'; a.style.left = '-9999px';"
            " document.body.appendChild(a); a.select();"
            " document.execCommand('copy');"
            " document.body.removeChild(a);"
            "}"
        ),
        style="display:none",
    )

    # File download watcher — triggers Blob download when export_trigger changes
    client.ClientStateChange(
        value="export_trigger",
        change="""
            if (export_content && export_filename) {
                const bin = atob(export_content);
                const bytes = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
                const blob = new Blob([bytes], {type: 'application/octet-stream'});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url; a.download = export_filename;
                document.body.appendChild(a); a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }
        """,
        style="display:none",
    )

    # ---- Beam Mass Estimate ----
    with v3.VCard(
        v_if="result_beam_mass_kg !== null",
        classes="mb-4",
        variant="outlined",
    ):
        with v3.VCardTitle(classes="d-flex align-center"):
            html.Span("Beam Mass Estimate")
            v3.VSpacer()
            v3.VBtn(
                "Copy",
                click=_copy_js(
                    "'Mass (g)\\t' + (result_beam_mass_kg * 1000).toFixed(1) + '\\n'"
                    "+ 'Mass (kg)\\t' + result_beam_mass_kg.toFixed(4)"
                ),
                **_COPY_BTN,
            )
        with v3.VCardText():
            with v3.VRow():
                with v3.VCol(cols=4):
                    with v3.VCard(variant="outlined", border=True):
                        v3.VCardSubtitle("Mass")
                        with v3.VCardText(classes="text-h6 font-weight-bold text-primary"):
                            html.Span(
                                v_text="result_beam_mass_kg >= 1 ? result_beam_mass_kg.toFixed(3) + ' kg' : (result_beam_mass_kg * 1000).toFixed(1) + ' g'"
                            )
                with v3.VCol(cols=8):
                    v3.VAlert(
                        text=("'Full-length beam (' + span_length + ' m span) — cross-section area × layup density integrated over all elements'",),
                        type="info",
                        density="compact",
                        variant="tonal",
                    )

    # ---- Save to Library dialog ----
    with v3.VDialog(v_model=("save_k_dialog_open", False), max_width=440):
        with v3.VCard():
            v3.VCardTitle("Save to Section Library")
            with v3.VCardText():
                v3.VTextField(
                    label="Name",
                    v_model=("save_k_name", ""),
                    placeholder="e.g. CFRP boom — quasi-isotropic 0.74 mm",
                    density="compact",
                    autofocus=True,
                )
                v3.VAlert(
                    text="Saves the K matrix together with geometry, layup, solver, and boundary condition context.",
                    type="info",
                    density="compact",
                    variant="tonal",
                    classes="mt-2",
                )
            with v3.VCardActions():
                v3.VSpacer()
                v3.VBtn("Cancel", variant="text", click="save_k_dialog_open = false")
                v3.VBtn(
                    "Save",
                    color="primary",
                    variant="tonal",
                    disabled=("!save_k_name || save_k_name.trim() === ''",),
                    click=ctrl.save_k_to_library,
                )

    # ---- K Matrix ----
    with v3.VCard(
        v_if="result_k_mm",
        classes="mb-4",
        variant="outlined",
    ):
        with v3.VCardTitle(classes="d-flex align-center"):
            html.Span("6x6 Cross-Section Stiffness Matrix (K) [N/mm]")
            v3.VSpacer()
            v3.VBtn(
                "Copy TSV",
                click=_copy_js(
                    "['\\t','E1','E2','E3','K1','K2','K3'].join('\\t') + '\\n' + "
                    "k_matrix_rows.map(r => [r.label,r.c0,r.c1,r.c2,r.c3,r.c4,r.c5].join('\\t')).join('\\n')"
                ),
                **_COPY_BTN,
            )
            v3.VBtn(
                "Export to ANSYS (.mac)",
                prepend_icon="mdi-download",
                color="secondary",
                variant="tonal",
                density="compact",
                classes="ml-2",
                click=ctrl.export_ansys,
            )
            v3.VBtn(
                "Save to Library",
                prepend_icon="mdi-database-plus-outline",
                color="primary",
                variant="tonal",
                density="compact",
                classes="ml-2",
                click="save_k_dialog_open = true",
            )
        
        with v3.VCardText():
            v3.VDataTable(
                headers=("k_col_headers", K_COL_HEADERS),
                items=("k_matrix_rows", []),
                density="compact",
                hover=True,
                items_per_page=-1,
                hide_default_footer=True,
            )

    # ---- Deflections ----
    # Translations stored in m → display in mm (×1000)
    # Rotations stored in rad → display in deg (×180/π)
    DEFL_ITEMS = [
        ("Axial (u1)",    0, "mm",  "* 1000",           "text-primary"),
        ("Lateral (u2)",  1, "mm",  "* 1000",           "text-primary"),
        ("Vertical (u3)", 2, "mm",  "* 1000",           "text-primary"),
        ("Twist (rot1)",  3, "deg", "* (180 / Math.PI)", "text-secondary"),
        ("Bending (rot2)",4, "deg", "* (180 / Math.PI)", "text-secondary"),
        ("Bending (rot3)",5, "deg", "* (180 / Math.PI)", "text-secondary"),
    ]
    with v3.VCard(v_if="result_deflections", classes="mb-4", variant="outlined"):
        with v3.VCardTitle(classes="d-flex align-center"):
            html.Span("GXBeam Tip Deflections")
            v3.VSpacer()
            v3.VBtn(
                "Copy",
                click=_copy_js(
                    "'Component\\tValue\\tUnit\\n'"
                    "+ 'Axial (u1)\\t'     + (result_deflections[0]*1000).toFixed(4) + '\\tmm\\n'"
                    "+ 'Lateral (u2)\\t'   + (result_deflections[1]*1000).toFixed(4) + '\\tmm\\n'"
                    "+ 'Vertical (u3)\\t'  + (result_deflections[2]*1000).toFixed(4) + '\\tmm\\n'"
                    "+ 'Twist (rot1)\\t'   + (result_deflections[3]*(180/Math.PI)).toFixed(4) + '\\tdeg\\n'"
                    "+ 'Bending (rot2)\\t' + (result_deflections[4]*(180/Math.PI)).toFixed(4) + '\\tdeg\\n'"
                    "+ 'Bending (rot3)\\t' + (result_deflections[5]*(180/Math.PI)).toFixed(4) + '\\tdeg'"
                ),
                **_COPY_BTN,
            )
        with v3.VCardText():
            with v3.VRow():
                for label, idx, unit, scale, color in DEFL_ITEMS[:3]:
                    with v3.VCol(cols=4):
                        with v3.VCard(variant="outlined", border=True):
                            v3.VCardSubtitle(label)
                            with v3.VCardText(classes=f"text-h6 font-weight-bold {color}"):
                                html.Span(
                                    v_text=f"(result_deflections[{idx}] {scale}).toFixed(4) + ' {unit}'"
                                )
            with v3.VRow(classes="mt-2"):
                for label, idx, unit, scale, color in DEFL_ITEMS[3:]:
                    with v3.VCol(cols=4):
                        with v3.VCard(variant="outlined", border=True):
                            v3.VCardSubtitle(label)
                            with v3.VCardText(classes=f"text-h6 font-weight-bold {color}"):
                                html.Span(
                                    v_text=f"(result_deflections[{idx}] {scale}).toFixed(4) + ' {unit}'"
                                )

    # ---- Euler Buckling ----
    with v3.VCard(v_if="result_P_cr_22 !== null", classes="mb-4", variant="outlined"):
        with v3.VCardTitle(classes="d-flex align-center"):
            html.Span("Euler Buckling (axial compression)")
            v3.VSpacer()
            v3.VBtn(
                "Copy",
                click=_copy_js(
                    "'Metric\\tValue\\n'"
                    "+ 'P_cr (EI22 — bends about X)\\t' + result_P_cr_22.toFixed(3) + ' N\\n'"
                    "+ 'P_cr (EI33 — bends about Y)\\t' + result_P_cr_33.toFixed(3) + ' N\\n'"
                    "+ 'Limit Load\\t' + Math.min(result_P_cr_22, result_P_cr_33).toFixed(3) + ' N'"
                ),
                **_COPY_BTN,
            )
        with v3.VCardText():
            with v3.VRow():
                with v3.VCol(cols=4):
                    with v3.VCard(variant="outlined", border=True):
                        v3.VCardSubtitle("P_cr (EI\u2082\u2082 — bends about section X)")
                        with v3.VCardText(classes="text-h6 font-weight-bold text-orange-darken-3"):
                            html.Span(v_text="result_P_cr_22 >= 1000 ? (result_P_cr_22 / 1000).toFixed(2) + ' kN' : result_P_cr_22.toFixed(3) + ' N'")
                with v3.VCol(cols=4):
                    with v3.VCard(variant="outlined", border=True):
                        v3.VCardSubtitle("P_cr (EI\u2083\u2083 — bends about section Y)")
                        with v3.VCardText(classes="text-h6 font-weight-bold text-orange-darken-3"):
                            html.Span(v_text="result_P_cr_33 >= 1000 ? (result_P_cr_33 / 1000).toFixed(2) + ' kN' : result_P_cr_33.toFixed(3) + ' N'")
                with v3.VCol(cols=4):
                    with v3.VCard(variant="outlined", border=True):
                        v3.VCardSubtitle("Limit Load")
                        with v3.VCardText(classes="text-h6 font-weight-bold text-error"):
                            html.Span(v_text="Math.min(result_P_cr_22, result_P_cr_33) >= 1000 ? (Math.min(result_P_cr_22, result_P_cr_33) / 1000).toFixed(2) + ' kN' : Math.min(result_P_cr_22, result_P_cr_33).toFixed(3) + ' N'")

    # ---- CalculiX Convergence Monitor ----
    with v3.VCard(
        v_if="ccx_convergence_img || (pipeline_running && pipeline_stage.includes('Stage 3'))",
        classes="mb-4",
        variant="outlined",
    ):
        with v3.VCardTitle(classes="d-flex align-center"):
            html.Span("CalculiX Convergence Monitor")
            v3.VSpacer()
            v3.VBtn(
                "Copy Increments",
                v_if="ccx_history.length > 0 && !pipeline_running",
                click=_copy_js(
                    "['Step','Inc','Att','Iter','dt','Total'].join('\\t') + '\\n' + "
                    "ccx_history.map(r => [r.step,r.inc,r.att,r.iter,r.dt,r.total].join('\\t')).join('\\n')"
                ),
                **_COPY_BTN,
            )
        with v3.VCardText():
            # Live plot image — updates every ~0.5 s while solving
            html.Img(
                v_if="ccx_convergence_img",
                src=("ccx_convergence_img",),
                style="width:100%; border-radius:4px;",
            )
            # Spinner shown before first .sta data arrives
            with v3.VRow(
                v_if="!ccx_convergence_img && pipeline_running",
                justify="center",
                classes="py-4",
            ):
                v3.VProgressCircular(indeterminate=True, color="primary")
                html.Span("Waiting for CalculiX...", classes="ml-3 text-grey")
            # Collapsible increment table (shown only after solve finishes)
            with v3.VExpansionPanels(
                v_if="ccx_history.length > 0 && !pipeline_running",
                classes="mt-2",
            ):
                with v3.VExpansionPanel(title="Increment Details"):
                    with v3.VExpansionPanelText():
                        v3.VDataTable(
                            headers=[
                                {"title": "Step",  "key": "step"},
                                {"title": "Inc",   "key": "inc"},
                                {"title": "Att",   "key": "att"},
                                {"title": "Iter",  "key": "iter"},
                                {"title": "dt",    "key": "dt"},
                                {"title": "Total", "key": "total"},
                            ],
                            items=("ccx_history", []),
                            density="compact",
                            items_per_page=10,
                            class_="elevation-0",
                        )

    # ---- Buckling Factor ----
    with v3.VCard(v_if="result_ccx_factor !== null", classes="mb-4", variant="outlined"):
        with v3.VCardTitle(classes="d-flex align-center"):
            html.Span("Local Buckling (CalculiX)")
            v3.VSpacer()
            v3.VBtn(
                "Copy",
                click=_copy_js(
                    "'Metric\\tValue\\n'"
                    "+ 'Buckling Factor\\t' + result_ccx_factor.toFixed(5) + '\\n'"
                    "+ 'Critical Load\\t' + (Math.abs(snippet_compressive_load) * result_ccx_factor / 1000).toFixed(2) + ' kN'"
                ),
                **_COPY_BTN,
            )
        with v3.VCardText():
            with v3.VRow():
                with v3.VCol(cols=6):
                    with v3.VAlert(
                        v_if="result_ccx_factor > 1.0",
                        type="success",
                        variant="tonal",
                        density="comfortable",
                        classes="text-h6 font-weight-bold",
                    ):
                        html.Span(v_text="'Buckling Factor: ' + result_ccx_factor.toFixed(5) + ' (Safe)'")
                    with v3.VAlert(
                        v_if="result_ccx_factor <= 1.0",
                        type="error",
                        variant="elevated",
                        density="comfortable",
                        classes="text-h6 font-weight-bold",
                    ):
                        html.Span(v_text="'Buckling Factor: ' + result_ccx_factor.toFixed(5) + ' (Buckles!)'")
                with v3.VCol(cols=6):
                    with v3.VCard(variant="outlined", border=True):
                        v3.VCardSubtitle("Critical Load (kN)")
                        with v3.VCardText(classes="text-h4 font-weight-black text-deep-orange-darken-4"):
                            html.Span(v_text="(Math.abs(snippet_compressive_load) * result_ccx_factor / 1000).toFixed(2) + ' kN'")

    # ---- Output Files ----
    with v3.VCard(
        v_if="mesh_vtk_path || beam_vtk_path || buckling_vtk_path || snippet_vtk_path",
        classes="mb-4",
        variant="outlined",
    ):
        with v3.VCardTitle(classes="d-flex align-center"):
            html.Span("Output Files")
            v3.VSpacer()
            v3.VBtn(
                "Copy Paths",
                click=_copy_js(
                    "['Output\\tFile Path']"
                    ".concat(result_runs_dir   ? ['Run Directory\\t'  + result_runs_dir]   : [])"
                    ".concat(mesh_vtk_path     ? ['Cross-Section Mesh\\t' + mesh_vtk_path] : [])"
                    ".concat(snippet_vtk_path  ? ['Snippet Preview\\t' + snippet_vtk_path] : [])"
                    ".concat(beam_vtk_path     ? ['Deformed Beam\\t'   + beam_vtk_path]    : [])"
                    ".concat(buckling_vtk_path ? ['Buckling Mode\\t'   + buckling_vtk_path]: [])"
                    ".join('\\n')"
                ),
                **_COPY_BTN,
            )
        with v3.VCardText():
            with v3.VTable(density="compact"):
                with html.Thead():
                    with html.Tr():
                        html.Th("Output")
                        html.Th("File Path")
                with html.Tbody():
                    with html.Tr(v_if="result_runs_dir"):
                        html.Td("Run Directory", classes="font-weight-bold")
                        html.Td(v_text="result_runs_dir", style="word-break: break-all; font-family: monospace;")
                    with html.Tr(v_if="mesh_vtk_path"):
                        html.Td("Cross-Section Mesh")
                        html.Td(v_text="mesh_vtk_path", style="word-break: break-all; font-family: monospace;")
                    with html.Tr(v_if="snippet_vtk_path"):
                        html.Td("Snippet Preview")
                        html.Td(v_text="snippet_vtk_path", style="word-break: break-all; font-family: monospace;")
                    with html.Tr(v_if="beam_vtk_path"):
                        html.Td("Deformed Beam")
                        html.Td(v_text="beam_vtk_path", style="word-break: break-all; font-family: monospace;")
                    with html.Tr(v_if="buckling_vtk_path"):
                        html.Td("Buckling Mode")
                        html.Td(v_text="buckling_vtk_path", style="word-break: break-all; font-family: monospace;")
    # ---- Callbacks ----
    @state.change("result_k_mm")
    def _on_k_matrix_change(result_k_mm, **kwargs):
        if result_k_mm:
            rows = []
            for i, label in enumerate(K_LABELS):
                row = {"label": label}
                for j in range(6):
                    row[f"c{j}"] = f"{result_k_mm[i][j]:.3e}"
                rows.append(row)
            state.k_matrix_rows = rows

    # ---- Visualization ----
    v3.VDivider(classes="my-4")
    html.Div(
        "3D Visualization",
        classes="text-h6 font-weight-medium mb-3",
    )
    build_visualization_page(server, plotter)
