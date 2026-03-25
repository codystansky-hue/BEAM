"""Page 4: Stiffness Library — browse, view, and delete saved K-matrix entries."""

import logging

from trame.widgets import vuetify3 as v3, html

log = logging.getLogger(__name__)

LIB_HEADERS = [
    {"title": "#", "key": "index", "sortable": False, "width": "40px"},
    {"title": "Name / Laminate", "key": "name", "width": "240px"},
    {"title": "K Matrix [N/mm]", "key": "k_matrix", "sortable": False},
    {"title": "Solver", "key": "xs_solver", "width": "100px"},
    {"title": "BC", "key": "bc_type", "width": "120px"},
    {"title": "t (mm)", "key": "thickness", "width": "70px"},
    {"title": "", "key": "actions", "sortable": False, "width": "110px"},
]

K_COL_LABELS = ["E1", "E2", "E3", "K1", "K2", "K3"]


def build_stiffness_library_page(server):
    """Build the stiffness library page UI inside the current layout context."""
    state, ctrl = server.state, server.controller

    with v3.VCard(classes="pa-4"):
        v3.VCardTitle("Section Stiffness Library")
        v3.VCardSubtitle("Saved cross-section stiffness matrices")

        with v3.VDataTable(
            headers=("lib_headers", LIB_HEADERS),
            items=("lib_table_items", []),
            density="compact",
            no_data_text="No saved entries yet. Run an analysis and save the K matrix from the Results page.",
        ):
            # Row index
            with v3.Template(
                v_slot_item_index="{ item }",
                __properties=[("v_slot_item_index", "v-slot:item.index")],
            ):
                html.Span("{{ item.index + 1 }}")

            # Name + laminate schedule
            with v3.Template(
                v_slot_item_name="{ item }",
                __properties=[("v_slot_item_name", "v-slot:item.name")],
            ):
                with html.Div():
                    html.Div(
                        "{{ item.name }}",
                        classes="font-weight-bold text-body-2",
                    )
                    with v3.VTable(
                        v_if="item.ply_rows && item.ply_rows.length",
                        density="compact",
                        classes="mt-1",
                        style="font-size: 0.75rem;",
                    ):
                        with html.Thead():
                            with html.Tr():
                                html.Th("#", style="padding:1px 4px;")
                                html.Th("Lamina", style="padding:1px 4px;")
                                html.Th("\u00b0", style="padding:1px 4px;")
                                html.Th("t (mm)", style="padding:1px 4px; text-align:right;")
                                html.Th("FAW (g/m\u00b2)", style="padding:1px 4px; text-align:right;")
                        with html.Tbody():
                            with html.Tr(
                                v_for="(ply, pi) in item.ply_rows",
                                key="pi",
                            ):
                                html.Td("{{ pi + 1 }}", style="padding:1px 4px;")
                                html.Td("{{ ply.lamina }}", style="padding:1px 4px;")
                                html.Td("{{ ply.angle }}\u00b0", style="padding:1px 4px;")
                                html.Td("{{ ply.t }}", style="padding:1px 4px; text-align:right;")
                                html.Td("{{ ply.faw }}", style="padding:1px 4px; text-align:right;")

            # K matrix
            with v3.Template(
                v_slot_item_k_matrix="{ item }",
                __properties=[("v_slot_item_k_matrix", "v-slot:item.k_matrix")],
            ):
                with html.Div(v_if="item.k_rows && item.k_rows.length"):
                    v3.VBtn(
                        "Copy TSV",
                        prepend_icon="mdi-content-copy",
                        size="x-small",
                        variant="tonal",
                        density="compact",
                        classes="mb-1",
                        click=(ctrl.copy_lib_k_tsv, "[item.index]"),
                    )
                    with v3.VTable(
                        density="compact",
                        style="font-size: 0.7rem; font-family: monospace;",
                    ):
                        with html.Thead():
                            with html.Tr():
                                html.Th("", style="padding:1px 4px;")
                                for col in K_COL_LABELS:
                                    html.Th(col, style="padding:1px 4px; text-align:right;")
                        with html.Tbody():
                            with html.Tr(
                                v_for="(kr, ki) in item.k_rows",
                                key="ki",
                            ):
                                html.Td(
                                    "{{ kr.label }}",
                                    style="padding:1px 4px; font-weight:600;",
                                )
                                for ci in range(6):
                                    html.Td(
                                        "{{ kr.c" + str(ci) + " }}",
                                        style="padding:1px 4px; text-align:right;",
                                    )

            # Actions column
            with v3.Template(
                v_slot_item_actions="{ item }",
                __properties=[("v_slot_item_actions", "v-slot:item.actions")],
            ):
                v3.VBtn(
                    "Use",
                    prepend_icon="mdi-arrow-right-bold",
                    size="small",
                    variant="tonal",
                    color="primary",
                    click=(ctrl.load_k_from_library, "[item.index]"),
                    classes="mb-1",
                )
                v3.VBtn(
                    icon="mdi-eye",
                    size="small",
                    variant="text",
                    click=(ctrl.on_lib_view, "[item.index]"),
                )
                v3.VBtn(
                    icon="mdi-delete",
                    size="small",
                    variant="text",
                    color="error",
                    click="lib_delete_idx = item.index; lib_delete_confirm = true",
                )

    # View dialog (raw JSON)
    with v3.VDialog(v_model=("lib_view_open", False), max_width="700"):
        with v3.VCard():
            v3.VCardTitle("{{ (stiffness_library && stiffness_library[lib_view_idx]) ? stiffness_library[lib_view_idx].name : '' }}")
            with v3.VCardText(style="white-space: pre-wrap; font-family: monospace; font-size: 0.85rem"):
                html.Span("{{ (stiffness_library && stiffness_library[lib_view_idx]) ? JSON.stringify(stiffness_library[lib_view_idx], null, 2) : '' }}")
            with v3.VCardActions():
                v3.VSpacer()
                v3.VBtn("Close", click="lib_view_open = false")

    # Delete confirmation dialog
    with v3.VDialog(v_model=("lib_delete_confirm", False), max_width="400"):
        with v3.VCard():
            v3.VCardTitle("Delete Entry?")
            v3.VCardText("Are you sure you want to remove this entry from the library?")
            with v3.VCardActions():
                v3.VSpacer()
                v3.VBtn("Cancel", click="lib_delete_confirm = false")
                v3.VBtn(
                    "Delete",
                    color="error",
                    click=(ctrl.confirm_delete_k_entry, "[lib_delete_idx]"),
                )
