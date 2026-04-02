"""Batch Analysis sub-page — select layups, run batch, view results."""

import logging

from trame.widgets import vuetify3 as v3, html

log = logging.getLogger(__name__)

BATCH_TABLE_HEADERS = [
    {"title": "Layup", "key": "name"},
    {"title": "EA (MN)", "key": "EA"},
    {"title": "EI22 (N m²)", "key": "EI22"},
    {"title": "EI33 (N m²)", "key": "EI33"},
    {"title": "GJ (N m²)", "key": "GJ"},
    {"title": "Mass (kg/m)", "key": "mass"},
]


def build_batch_analysis_page(server):
    """Build the batch analysis UI inside the current layout context."""
    state, ctrl = server.state, server.controller

    with v3.VCardText():
        # Layup selection
        v3.VSelect(
            v_model=("batch_selected_layups", []),
            items=("(layups || []).map(l => l.name)",),
            label="Select layups to compare",
            multiple=True,
            chips=True,
            closable_chips=True,
            density="compact",
            classes="mb-2",
        )

        with v3.VRow(classes="mb-2"):
            v3.VBtn(
                "Run Batch",
                click=ctrl.run_batch,
                color="primary",
                loading=("batch_running",),
                disabled=("batch_running || (batch_selected_layups || []).length === 0",),
                prepend_icon="mdi-play-box-multiple",
                classes="mx-2",
            )
            v3.VBtn(
                "Export PDF",
                click=ctrl.export_batch_pdf,
                variant="outlined",
                disabled=("!batch_results || batch_results.length === 0",),
                prepend_icon="mdi-file-pdf-box",
                classes="mx-2",
            )
            v3.VBtn(
                "Export Excel",
                click=ctrl.export_batch_excel,
                variant="outlined",
                disabled=("!batch_results || batch_results.length === 0",),
                prepend_icon="mdi-microsoft-excel",
                classes="mx-2",
            )

        # Progress
        v3.VProgressLinear(
            v_if="batch_running",
            model_value=("batch_progress", 0),
            color="primary",
            classes="mb-2",
        )

        # Batch log
        with html.Div(
            v_if="batch_log_string",
            style=(
                "background: #1e1e1e; color: #d4d4d4; border-radius: 4px; "
                "padding: 8px; max-height: 120px; overflow-y: auto; font-family: monospace; "
                "display: flex; flex-direction: column-reverse;"
            ),
            classes="mb-2",
        ):
            html.Pre(
                v_text="batch_log_string",
                style="margin: 0; white-space: pre-wrap; word-break: break-all; font-size: 0.75rem;",
            )

        # Results table
        v3.VDataTable(
            v_if="batch_table_rows && batch_table_rows.length > 0",
            headers=("batch_table_headers", BATCH_TABLE_HEADERS),
            items=("batch_table_rows", []),
            density="compact",
            classes="mb-2",
        )

        # Chart
        with html.Div(v_if="batch_chart_b64"):
            html.Img(
                src=("'data:image/png;base64,' + batch_chart_b64",),
                style="max-width: 100%; border-radius: 4px;",
            )
