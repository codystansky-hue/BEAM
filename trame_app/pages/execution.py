"""Page 3: Execution — pipeline control and batch analysis."""

from trame.widgets import vuetify3 as v3, html

from trame_app.pages.batch_analysis import build_batch_analysis_page


def build_execution_page(server):
    """Build the Execution page UI inside the current layout context."""
    state, ctrl = server.state, server.controller

    # ---- Pipeline Control ----
    with v3.VCard(classes="mb-4", variant="outlined"):
        v3.VCardTitle("Pipeline Control")
        with v3.VCardText():
            v3.VAlert(
                v_if="!geo_file_name",
                type="warning",
                text="Please upload a geometry file in Pre-Processing first.",
                density="compact",
                classes="mb-2",
            )
            v3.VAlert(
                v_if="geo_file_name && layup_plies.length === 0",
                type="warning",
                text="Please define a layup sequence in the Layup Design tab.",
                density="compact",
                classes="mb-2",
            )

            with v3.VRow(justify="center", classes="mb-2"):
                v3.VBtn(
                    "Run All",
                    click=ctrl.run_all,
                    color="primary",
                    loading=("pipeline_running",),
                    disabled=("pipeline_running || !geo_file_name || layup_plies.length === 0",),
                    classes="mx-2",
                    prepend_icon="mdi-play",
                )
                v3.VBtn(
                    "1 \u00b7 Mesh",
                    click=ctrl.run_stage_1,
                    color="secondary",
                    variant="outlined",
                    loading=("pipeline_running",),
                    disabled=("pipeline_running || !geo_file_name || layup_plies.length === 0",),
                    classes="mx-2",
                )
                v3.VBtn(
                    "2 \u00b7 Global",
                    click=ctrl.run_stage_2,
                    color="secondary",
                    variant="outlined",
                    loading=("pipeline_running",),
                    disabled=("pipeline_running || !has_mesh",),
                    classes="mx-2",
                )
                v3.VBtn(
                    "3 \u00b7 Local",
                    click=ctrl.run_stage_3,
                    color="secondary",
                    variant="outlined",
                    loading=("pipeline_running",),
                    disabled=("pipeline_running || !has_mesh",),
                    classes="mx-2",
                )

            v3.VProgressLinear(
                v_if="pipeline_running",
                indeterminate=True,
                color="primary",
                classes="mt-2",
            )
            v3.VAlert(
                v_if="pipeline_stage && pipeline_stage !== 'Complete'",
                type="info",
                density="compact",
                text=("pipeline_stage",),
                classes="mt-2",
            )

            v3.VDivider(classes="my-4")

            html.Div("Solver Log", classes="text-caption text-medium-emphasis mb-1")
            with html.Div(
                id="pipeline-log-box",
                style=(
                    "background: #1e1e1e; color: #d4d4d4; border-radius: 4px; "
                    "padding: 8px; height: 144px; overflow-y: auto; font-family: monospace;"
                ),
            ):
                html.Pre(
                    v_text="pipeline_log_string",
                    style="margin: 0; white-space: pre-wrap; word-break: break-all; font-size: 0.75rem;",
                )

    # ---- Batch Analysis ----
    with v3.VCard(classes="mb-2", variant="outlined"):
        v3.VCardTitle("Batch Analysis")

    build_batch_analysis_page(server)
