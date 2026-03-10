"""Page 1: Pre-Processing — Geometry, Materials, Layup."""

import math
import os
import base64
import tempfile
import logging

from trame.widgets import vuetify3 as v3, html

def _copy_js(text_expr):
    """Return a trame.trigger call that sends text to the server for clipboard copy."""
    return f"trame.trigger('_do_copy', [{text_expr}])"

from trame_app.state import (
    FIBERS_DB, RESINS_DB, LAMINAE_DB, LAYUPS_DB, save_db,
)

log = logging.getLogger(__name__)


def _cln(v):
    """Safely convert to float, defaulting to 0.0."""
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------
# Fiber / Resin table helpers (display GPa/MPa, store Pa)
# ---------------------------------------------------------------
_FIBER_GPa_KEYS = ["E11_t", "E11_c", "E22", "G12"]
_FIBER_MPa_KEYS = ["Xt", "Xc"]
_RESIN_GPa_KEYS = ["E_t", "E_c", "E"]
_RESIN_MPa_KEYS = ["Xt", "Xc", "S"]
_LAMINA_GPa_KEYS = ["E11_t", "E11_c", "E11", "E22", "G12"]
_LAMINA_MPa_KEYS = ["Xt", "Xc", "Yt", "Yc", "S12"]


def _fiber_display_headers():
    return [
        {"title": "Name", "key": "name"},
        {"title": "E11_t (GPa)", "key": "E11_t_d"},
        {"title": "E11_c (GPa)", "key": "E11_c_d"},
        {"title": "E22 (GPa)", "key": "E22_d"},
        {"title": "G12 (GPa)", "key": "G12_d"},
        {"title": "nu12", "key": "nu12"},
        {"title": "Density (kg/m3)", "key": "density"},
        {"title": "Xt (MPa)", "key": "Xt_d"},
        {"title": "Xc (MPa)", "key": "Xc_d"},
        {"title": "α11 (µm/m/K)", "key": "cte11_d"},
        {"title": "α22 (µm/m/K)", "key": "cte22_d"},
    ]


def _fiber_display_rows(fibers):
    rows = []
    for i, f in enumerate(fibers):
        row = {"_idx": i, "name": f.get("name", "")}
        for k in _FIBER_GPa_KEYS:
            row[f"{k}_d"] = round(f.get(k, 0) / 1e9, 3)
        for k in _FIBER_MPa_KEYS:
            row[f"{k}_d"] = round(f.get(k, 0) / 1e6, 1)
        row["nu12"] = f.get("nu12", 0)
        row["density"] = f.get("density", 0)
        row["cte11_d"] = round(f.get("cte11", 0) * 1e6, 3)
        row["cte22_d"] = round(f.get("cte22", 0) * 1e6, 3)
        rows.append(row)
    return rows


def _resin_display_headers():
    return [
        {"title": "Name", "key": "name"},
        {"title": "E_t (GPa)", "key": "E_t_d"},
        {"title": "E_c (GPa)", "key": "E_c_d"},
        {"title": "nu", "key": "nu"},
        {"title": "Density (kg/m3)", "key": "density"},
        {"title": "S (MPa)", "key": "S_d"},
        {"title": "Xt (MPa)", "key": "Xt_d"},
        {"title": "Xc (MPa)", "key": "Xc_d"},
        {"title": "α (µm/m/K)", "key": "cte_d"},
    ]


def _resin_display_rows(resins):
    rows = []
    for i, r in enumerate(resins):
        row = {"_idx": i, "name": r.get("name", "")}
        for k in _RESIN_GPa_KEYS:
            row[f"{k}_d"] = round(r.get(k, 0) / 1e9, 3)
        for k in _RESIN_MPa_KEYS:
            row[f"{k}_d"] = round(r.get(k, 0) / 1e6, 1)
        row["nu"] = r.get("nu", 0)
        row["density"] = r.get("density", 0)
        row["Xt_d"] = round(r.get("Xt", 0) / 1e6, 1)
        row["Xc_d"] = round(r.get("Xc", 0) / 1e6, 1)
        row["cte_d"] = round(r.get("cte", 0) * 1e6, 2)
        rows.append(row)
    return rows


def _lamina_display_headers():
    return [
        {"title": "Name", "key": "name"},
        {"title": "E11 (GPa)", "key": "E11_d"},
        {"title": "E22 (GPa)", "key": "E22_d"},
        {"title": "G12 (GPa)", "key": "G12_d"},
        {"title": "nu12", "key": "nu12"},
        {"title": "Thickness (mm)", "key": "thickness_mm"},
        {"title": "Density (kg/m3)", "key": "density"},
        {"title": "α11 (µm/m/K)", "key": "cte11_d"},
        {"title": "α22 (µm/m/K)", "key": "cte22_d"},
    ]


def _lamina_display_rows(laminae):
    rows = []
    for i, lm in enumerate(laminae):
        row = {"_idx": i, "name": lm.get("name", "")}
        for k in _LAMINA_GPa_KEYS:
            if k in lm:
                row[f"{k}_d"] = round(lm[k] / 1e9, 3)
        row["nu12"] = lm.get("nu12", 0)
        row["thickness_mm"] = lm.get("thickness_mm", 0)
        row["density"] = lm.get("density", 0)
        row["cte11_d"] = round(lm.get("cte11", 0) * 1e6, 3)
        row["cte22_d"] = round(lm.get("cte22", 0) * 1e6, 3)
        rows.append(row)
    return rows


# ---------------------------------------------------------------
# TSV export helpers
# ---------------------------------------------------------------
def _fiber_tsv(fibers):
    header = "Name\tE11_t(GPa)\tE11_c(GPa)\tE22(GPa)\tG12(GPa)\tnu12\tDensity(kg/m3)\tXt(MPa)\tXc(MPa)\tα11(µm/m/K)\tα22(µm/m/K)"
    lines = [header]
    for f in fibers:
        lines.append("\t".join([
            f.get("name", ""),
            str(round(f.get("E11_t", 0) / 1e9, 3)),
            str(round(f.get("E11_c", 0) / 1e9, 3)),
            str(round(f.get("E22", 0) / 1e9, 3)),
            str(round(f.get("G12", 0) / 1e9, 3)),
            str(f.get("nu12", 0)),
            str(f.get("density", 0)),
            str(round(f.get("Xt", 0) / 1e6, 1)),
            str(round(f.get("Xc", 0) / 1e6, 1)),
            str(round(f.get("cte11", 0) * 1e6, 3)),
            str(round(f.get("cte22", 0) * 1e6, 3)),
        ]))
    return "\n".join(lines)


def _resin_tsv(resins):
    header = "Name\tE_t(GPa)\tE_c(GPa)\tnu\tDensity(kg/m3)\tS(MPa)\tXt(MPa)\tXc(MPa)\tα(µm/m/K)"
    lines = [header]
    for r in resins:
        lines.append("\t".join([
            r.get("name", ""),
            str(round(r.get("E_t", 0) / 1e9, 3)),
            str(round(r.get("E_c", 0) / 1e9, 3)),
            str(r.get("nu", 0)),
            str(r.get("density", 0)),
            str(round(r.get("S", 0) / 1e6, 1)),
            str(round(r.get("Xt", 0) / 1e6, 1)),
            str(round(r.get("Xc", 0) / 1e6, 1)),
            str(round(r.get("cte", 0) * 1e6, 2)),
        ]))
    return "\n".join(lines)


def _lamina_tsv(laminae):
    header = "Name\tE11(GPa)\tE22(GPa)\tG12(GPa)\tnu12\tThickness(mm)\tDensity(kg/m3)\tα11(µm/m/K)\tα22(µm/m/K)"
    lines = [header]
    for lm in laminae:
        lines.append("\t".join([
            lm.get("name", ""),
            str(round(lm.get("E11", lm.get("E11_t", 0)) / 1e9, 3)),
            str(round(lm.get("E22", 0) / 1e9, 3)),
            str(round(lm.get("G12", 0) / 1e9, 3)),
            str(lm.get("nu12", 0)),
            str(round(lm.get("thickness_mm", 0), 4)),
            str(lm.get("density", 0)),
            str(round(lm.get("cte11", 0) * 1e6, 3)),
            str(round(lm.get("cte22", 0) * 1e6, 3)),
        ]))
    return "\n".join(lines)


# ---------------------------------------------------------------
# Edit dialog builders
# ---------------------------------------------------------------
def _build_fiber_edit_dialog(server):
    state, ctrl = server.state, server.controller

    with v3.VDialog(v_model=("edit_fiber_open", False), max_width=650):
        with v3.VCard():
            v3.VCardTitle("Edit Fiber")
            with v3.VCardText():
                v3.VTextField(label="Name", v_model=("edit_fiber_name", ""), density="compact", classes="mb-2")
                with v3.VRow(dense=True):
                    with v3.VCol(cols=6):
                        v3.VTextField(label="E11 Tension (GPa)", v_model=("edit_fiber_e11_t", 0.0), type="number", density="compact")
                        v3.VTextField(label="E11 Comp. (GPa)", v_model=("edit_fiber_e11_c", 0.0), type="number", density="compact")
                        v3.VTextField(label="E22 (GPa)", v_model=("edit_fiber_e22", 0.0), type="number", density="compact")
                        v3.VTextField(label="G12 (GPa)", v_model=("edit_fiber_g12", 0.0), type="number", density="compact")
                        v3.VTextField(label="nu12", v_model=("edit_fiber_nu12", 0.0), type="number", density="compact")
                    with v3.VCol(cols=6):
                        v3.VTextField(label="Density (kg/m3)", v_model=("edit_fiber_density", 0.0), type="number", density="compact")
                        v3.VTextField(label="Xt (MPa)", v_model=("edit_fiber_xt", 0.0), type="number", density="compact")
                        v3.VTextField(label="Xc (MPa)", v_model=("edit_fiber_xc", 0.0), type="number", density="compact")
                        v3.VTextField(label="CTE11 (µm/m/K)", v_model=("edit_fiber_cte11", 0.0), type="number", density="compact")
                        v3.VTextField(label="CTE22 (µm/m/K)", v_model=("edit_fiber_cte22", 0.0), type="number", density="compact")
            with v3.VCardActions():
                v3.VSpacer()
                v3.VBtn("Cancel", click="edit_fiber_open = false", variant="text")
                v3.VBtn("Save", click=ctrl.save_edit_fiber, color="primary", variant="tonal")

    @ctrl.add("open_edit_fiber")
    def _open_edit_fiber(idx):
        fibers = list(state.fibers)
        if idx < 0 or idx >= len(fibers):
            return
        f = fibers[idx]
        state.edit_fiber_idx = idx
        state.edit_fiber_name = f.get("name", "")
        state.edit_fiber_e11_t = round(f.get("E11_t", 0) / 1e9, 3)
        state.edit_fiber_e11_c = round(f.get("E11_c", 0) / 1e9, 3)
        state.edit_fiber_e22 = round(f.get("E22", 0) / 1e9, 3)
        state.edit_fiber_g12 = round(f.get("G12", 0) / 1e9, 3)
        state.edit_fiber_nu12 = f.get("nu12", 0)
        state.edit_fiber_density = f.get("density", 0)
        state.edit_fiber_xt = round(f.get("Xt", 0) / 1e6, 1)
        state.edit_fiber_xc = round(f.get("Xc", 0) / 1e6, 1)
        state.edit_fiber_cte11 = round(f.get("cte11", 0) * 1e6, 3)
        state.edit_fiber_cte22 = round(f.get("cte22", 0) * 1e6, 3)
        state.edit_fiber_open = True

    @ctrl.add("save_edit_fiber")
    def _save_edit_fiber():
        idx = int(state.edit_fiber_idx)
        fibers = list(state.fibers)
        if idx < 0 or idx >= len(fibers):
            return
        fibers[idx] = {
            "name": state.edit_fiber_name or "Unnamed",
            "E11_t": _cln(state.edit_fiber_e11_t) * 1e9,
            "E11_c": _cln(state.edit_fiber_e11_c) * 1e9,
            "E22": _cln(state.edit_fiber_e22) * 1e9,
            "G12": _cln(state.edit_fiber_g12) * 1e9,
            "nu12": _cln(state.edit_fiber_nu12),
            "density": _cln(state.edit_fiber_density),
            "Xt": _cln(state.edit_fiber_xt) * 1e6,
            "Xc": _cln(state.edit_fiber_xc) * 1e6,
            "cte11": _cln(state.edit_fiber_cte11) * 1e-6,
            "cte22": _cln(state.edit_fiber_cte22) * 1e-6,
        }
        state.fibers = fibers
        save_db(FIBERS_DB, state.fibers)
        state.fiber_rows = _fiber_display_rows(state.fibers)
        state.fiber_tsv = _fiber_tsv(state.fibers)
        state.edit_fiber_open = False
        log.info("Updated fiber at index %d", idx)

    @ctrl.add("delete_fiber_by_idx")
    def _delete_fiber_by_idx(idx):
        fibers = list(state.fibers)
        if 0 <= idx < len(fibers):
            name = fibers[idx].get("name", "?")
            fibers.pop(idx)
            state.fibers = fibers
            save_db(FIBERS_DB, state.fibers)
            state.fiber_rows = _fiber_display_rows(state.fibers)
            state.fiber_tsv = _fiber_tsv(state.fibers)
            log.info("Deleted fiber: %s", name)


def _build_resin_edit_dialog(server):
    state, ctrl = server.state, server.controller

    with v3.VDialog(v_model=("edit_resin_open", False), max_width=650):
        with v3.VCard():
            v3.VCardTitle("Edit Resin")
            with v3.VCardText():
                v3.VTextField(label="Name", v_model=("edit_resin_name", ""), density="compact", classes="mb-2")
                with v3.VRow(dense=True):
                    with v3.VCol(cols=6):
                        v3.VTextField(label="E_t (GPa)", v_model=("edit_resin_e_t", 0.0), type="number", density="compact")
                        v3.VTextField(label="E_c (GPa)", v_model=("edit_resin_e_c", 0.0), type="number", density="compact")
                        v3.VTextField(label="nu", v_model=("edit_resin_nu", 0.0), type="number", density="compact")
                        v3.VTextField(label="Density (kg/m3)", v_model=("edit_resin_density", 0.0), type="number", density="compact")
                    with v3.VCol(cols=6):
                        v3.VTextField(label="S (MPa)", v_model=("edit_resin_s", 0.0), type="number", density="compact")
                        v3.VTextField(label="Xt (MPa)", v_model=("edit_resin_xt", 0.0), type="number", density="compact")
                        v3.VTextField(label="Xc (MPa)", v_model=("edit_resin_xc", 0.0), type="number", density="compact")
                        v3.VTextField(label="CTE (µm/m/K)", v_model=("edit_resin_cte", 0.0), type="number", density="compact")
            with v3.VCardActions():
                v3.VSpacer()
                v3.VBtn("Cancel", click="edit_resin_open = false", variant="text")
                v3.VBtn("Save", click=ctrl.save_edit_resin, color="primary", variant="tonal")

    @ctrl.add("open_edit_resin")
    def _open_edit_resin(idx):
        resins = list(state.resins)
        if idx < 0 or idx >= len(resins):
            return
        r = resins[idx]
        state.edit_resin_idx = idx
        state.edit_resin_name = r.get("name", "")
        state.edit_resin_e_t = round(r.get("E_t", 0) / 1e9, 3)
        state.edit_resin_e_c = round(r.get("E_c", 0) / 1e9, 3)
        state.edit_resin_nu = r.get("nu", 0)
        state.edit_resin_density = r.get("density", 0)
        state.edit_resin_s = round(r.get("S", 0) / 1e6, 1)
        state.edit_resin_xt = round(r.get("Xt", 0) / 1e6, 1)
        state.edit_resin_xc = round(r.get("Xc", 0) / 1e6, 1)
        state.edit_resin_cte = round(r.get("cte", 0) * 1e6, 2)
        state.edit_resin_open = True

    @ctrl.add("save_edit_resin")
    def _save_edit_resin():
        idx = int(state.edit_resin_idx)
        resins = list(state.resins)
        if idx < 0 or idx >= len(resins):
            return
        resins[idx] = {
            "name": state.edit_resin_name or "Unnamed",
            "E_t": _cln(state.edit_resin_e_t) * 1e9,
            "E_c": _cln(state.edit_resin_e_c) * 1e9,
            "nu": _cln(state.edit_resin_nu),
            "density": _cln(state.edit_resin_density),
            "S": _cln(state.edit_resin_s) * 1e6,
            "Xt": _cln(state.edit_resin_xt) * 1e6,
            "Xc": _cln(state.edit_resin_xc) * 1e6,
            "cte": _cln(state.edit_resin_cte) * 1e-6,
        }
        state.resins = resins
        save_db(RESINS_DB, state.resins)
        state.resin_rows = _resin_display_rows(state.resins)
        state.resin_tsv = _resin_tsv(state.resins)
        state.edit_resin_open = False
        log.info("Updated resin at index %d", idx)

    @ctrl.add("delete_resin_by_idx")
    def _delete_resin_by_idx(idx):
        resins = list(state.resins)
        if 0 <= idx < len(resins):
            name = resins[idx].get("name", "?")
            resins.pop(idx)
            state.resins = resins
            save_db(RESINS_DB, state.resins)
            state.resin_rows = _resin_display_rows(state.resins)
            state.resin_tsv = _resin_tsv(state.resins)
            log.info("Deleted resin: %s", name)


def _build_lamina_edit_dialog(server):
    state, ctrl = server.state, server.controller

    with v3.VDialog(v_model=("edit_lamina_open", False), max_width=500):
        with v3.VCard():
            v3.VCardTitle("Edit Lamina")
            with v3.VCardText():
                v3.VAlert(
                    type="info", density="compact", classes="mb-3",
                    text="Only name, thickness, and CTE are editable. Moduli come from SwiftComp.",
                )
                v3.VTextField(label="Name", v_model=("edit_lamina_name", ""), density="compact", classes="mb-2")
                v3.VTextField(label="Thickness (mm)", v_model=("edit_lamina_thickness", 0.0), type="number", density="compact", classes="mb-2")
                v3.VTextField(label="CTE11 (µm/m/K)", v_model=("edit_lamina_cte11", 0.0), type="number", density="compact")
                v3.VTextField(label="CTE22 (µm/m/K)", v_model=("edit_lamina_cte22", 0.0), type="number", density="compact")
            with v3.VCardActions():
                v3.VSpacer()
                v3.VBtn("Cancel", click="edit_lamina_open = false", variant="text")
                v3.VBtn("Save", click=ctrl.save_edit_lamina, color="primary", variant="tonal")

    @ctrl.add("open_edit_lamina")
    def _open_edit_lamina(idx):
        laminae = list(state.laminae)
        if idx < 0 or idx >= len(laminae):
            return
        lm = laminae[idx]
        state.edit_lamina_idx = idx
        state.edit_lamina_name = lm.get("name", "")
        state.edit_lamina_thickness = lm.get("thickness_mm", 0)
        state.edit_lamina_cte11 = round(lm.get("cte11", 0) * 1e6, 3)
        state.edit_lamina_cte22 = round(lm.get("cte22", 0) * 1e6, 3)
        state.edit_lamina_open = True

    @ctrl.add("save_edit_lamina")
    def _save_edit_lamina():
        idx = int(state.edit_lamina_idx)
        laminae = list(state.laminae)
        if idx < 0 or idx >= len(laminae):
            return
        laminae[idx] = {
            **laminae[idx],
            "name": state.edit_lamina_name or "Unnamed",
            "thickness_mm": _cln(state.edit_lamina_thickness),
            "cte11": _cln(state.edit_lamina_cte11) * 1e-6,
            "cte22": _cln(state.edit_lamina_cte22) * 1e-6,
        }
        state.laminae = laminae
        save_db(LAMINAE_DB, state.laminae)
        state.lamina_rows = _lamina_display_rows(state.laminae)
        state.lamina_tsv = _lamina_tsv(state.laminae)
        state.edit_lamina_open = False
        log.info("Updated lamina at index %d", idx)

    @ctrl.add("delete_lamina_by_idx")
    def _delete_lamina_by_idx(idx):
        laminae = list(state.laminae)
        if 0 <= idx < len(laminae):
            name = laminae[idx].get("name", "?")
            laminae.pop(idx)
            state.laminae = laminae
            save_db(LAMINAE_DB, state.laminae)
            state.lamina_rows = _lamina_display_rows(state.laminae)
            state.lamina_tsv = _lamina_tsv(state.laminae)
            log.info("Deleted lamina: %s", name)


# ---------------------------------------------------------------
# Page builder
# ---------------------------------------------------------------
def build_preprocessing_page(server):
    """Build the pre-processing page UI inside the current layout context."""
    state, ctrl = server.state, server.controller

    # Edit dialogs (rendered at top level so they float over content)
    _build_fiber_edit_dialog(server)
    _build_resin_edit_dialog(server)
    _build_lamina_edit_dialog(server)

    # Save confirmation snackbar
    with v3.VSnackbar(
        v_model=("save_snackbar_open", False),
        timeout=2500,
        color="success",
        location="bottom end",
    ):
        html.Span(v_text="save_snackbar_text")

    # ---- Geometry & Mesh Settings ----
    with v3.VCard(classes="mb-4", variant="outlined"):
        v3.VCardTitle("Geometry & Mesh")
        with v3.VCardText():
            # -- Geometry upload --
            with v3.VRow():
                with v3.VCol(cols=6):
                    v3.VFileInput(
                        label="Select 2D Spline (.3dm, .dxf)",
                        accept=".3dm,.dxf",
                        show_size=True,
                        v_model=("geo_file_input", None),
                        prepend_icon="mdi-file-cad-box",
                        classes="mb-2",
                    )
                    v3.VBtn(
                        "Upload Geometry",
                        click=ctrl.on_geo_upload,
                        color="primary",
                        variant="tonal",
                        block=True,
                        disabled=("!geo_file_input",),
                        classes="mb-2",
                    )
                    v3.VAlert(
                        v_if="geo_file_name",
                        type="success",
                        density="compact",
                        text=("'Using: ' + geo_file_name",),
                        classes="mb-0",
                    )
                    v3.VAlert(
                        v_if="!geo_file_name",
                        type="warning",
                        density="compact",
                        text="Please upload a .3dm or .dxf spline file.",
                        classes="mb-0",
                    )
                with v3.VCol(cols=6):
                    v3.VTextField(
                        label="Global Beam Span Length (m)",
                        v_model=("span_length",),
                        type="number",
                        step=0.1,
                        density="compact",
                    )

            v3.VDivider(classes="my-3")

            # -- Cross-section mesh --
            v3.VCardSubtitle("Cross-Section Mesh", classes="px-0 pb-2 text-medium-emphasis")
            with v3.VRow():
                with v3.VCol(cols=6):
                    v3.VTextField(
                        label="Element Size Along Curve (mm)",
                        v_model=("elem_size",),
                        type="number",
                        step=0.5,
                        density="compact",
                    )
                with v3.VCol(cols=6):
                    v3.VTextField(
                        label="Elements Through Thickness",
                        v_model=("num_elem_thick",),
                        type="number",
                        min=1,
                        max=10,
                        density="compact",
                    )

            v3.VDivider(classes="my-3")

            # -- 3D snippet mesh (CalculiX local buckling) + GXBeam discretisation --
            v3.VCardSubtitle("3D Snippet Mesh (Local Buckling)", classes="px-0 pb-2 text-medium-emphasis")
            with v3.VRow():
                with v3.VCol(cols=4):
                    v3.VTextField(
                        label="Snippet Length (mm)",
                        v_model=("snippet_length",),
                        type="number",
                        step=10,
                        density="compact",
                    )
                with v3.VCol(cols=4):
                    v3.VTextField(
                        label="Elements Along Z",
                        v_model=("snippet_elems_z",),
                        type="number",
                        density="compact",
                    )
                with v3.VCol(cols=4):
                    v3.VTextField(
                        label="GXBeam Beam Elements",
                        v_model=("gxbeam_nelem",),
                        type="number",
                        density="compact",
                        hint="Elements along span (default 20)",
                        persistent_hint=True,
                    )

    # File upload handler
    @ctrl.add("on_geo_upload")
    def _handle_geo_upload():
        fi = state.geo_file_input
        if not fi:
            log.warning("No file selected for upload.")
            return

        os.makedirs("meshes", exist_ok=True)

        # fi from trame is usually a list: [{name, content, ...}]
        if isinstance(fi, list):
            if len(fi) == 0:
                return
            fi = fi[0]

        name = fi.get("name", "upload.3dm")
        content = fi.get("content", b"")

        if isinstance(content, str):
            try:
                # Trame VFileInput content usually starts with data:application/octet-stream;base64,...
                if "," in content:
                    content = content.split(",")[-1]
                content = base64.b64decode(content)
            except Exception as e:
                log.error("Failed to decode base64: %s", e)
                return

        ext = os.path.splitext(name)[1].lower() or ".3dm"
        save_path = f"meshes/last_uploaded{ext}"
        try:
            with open(save_path, "wb") as f:
                f.write(content)
            state.geo_file_name = name
            state.geo_upload_path = save_path
            state.geo_file_input = None  # Clear input
            log.info("Uploaded geometry file: %s (%d bytes) → %s", name, len(content), save_path)
        except Exception as e:
            log.error("Failed to save uploaded file: %s", e)

    # ---- Material Library ----
    with v3.VCard(classes="mb-4", variant="outlined"):
        v3.VCardTitle("Material Library")
        with v3.VCardText():
            with v3.VTabs(v_model=("material_tab", 0)):
                v3.VTab(text="Constituents (Fibers/Resins)", value=0)
                v3.VTab(text="Lamina Generator", value=1)
                v3.VTab(text="Layup Designer", value=2)

            with v3.VWindow(v_model=("material_tab",)):
                # ---- Tab 0: Constituents ----
                with v3.VWindowItem(value=0):
                    _build_constituents_tab(server)

                # ---- Tab 1: Lamina Generator ----
                with v3.VWindowItem(value=1):
                    _build_lamina_tab(server)

                # ---- Tab 2: Layup Designer ----
                with v3.VWindowItem(value=2):
                    _build_layup_tab(server)


def _build_constituents_tab(server):
    """Fiber and Resin management."""
    state, ctrl = server.state, server.controller

    with v3.VRow():
        # ---- Fibers Column ----
        with v3.VCol(cols=6):
            v3.VCardTitle("Fibers", classes="text-h6")

            # Copy-to-clipboard
            with v3.VRow(dense=True, justify="end", classes="mb-1"):
                with v3.VCol(cols="auto"):
                    v3.VBtn(
                        "Copy as TSV",
                        prepend_icon="mdi-content-copy",
                        size="small",
                        variant="text",
                        click=_copy_js("fiber_tsv"),
                    )

            # Fiber table
            v3.VDataTable(
                headers=("fiber_headers", _fiber_display_headers()),
                items=("fiber_rows", []),
                density="compact",
                hover=True,
                items_per_page=-1,
            )
            # Per-row edit / delete via select
            with v3.VRow(dense=True, align="center", classes="mt-1 mb-1"):
                with v3.VCol():
                    v3.VSelect(
                        label="Select fiber to edit / delete",
                        items=("fibers.map((f,i)=>({title:f.name,value:i}))",),
                        v_model=("sel_fiber_idx", None),
                        density="compact",
                        hide_details=True,
                        clearable=True,
                    )
                with v3.VCol(cols="auto"):
                    v3.VBtn(
                        icon="mdi-pencil", size="small", variant="tonal",
                        disabled=("sel_fiber_idx === null || sel_fiber_idx === undefined",),
                        click=(ctrl.open_edit_fiber, "[sel_fiber_idx]"),
                    )
                with v3.VCol(cols="auto"):
                    v3.VBtn(
                        icon="mdi-delete", size="small", variant="tonal", color="error",
                        disabled=("sel_fiber_idx === null || sel_fiber_idx === undefined",),
                        click=(ctrl.delete_fiber_by_idx, "[sel_fiber_idx]"),
                    )

            # New fiber form
            with v3.VExpansionPanels(classes="mt-2"):
                with v3.VExpansionPanel(title="Add New Fiber"):
                    with v3.VExpansionPanelText():
                        # ---- PDF Datasheet Import ----
                        with v3.VRow(dense=True, align="center", classes="mb-2"):
                            with v3.VCol(cols=8):
                                v3.VFileInput(
                                    label="Import from datasheet PDF",
                                    accept=".pdf",
                                    v_model=("fiber_pdf_input", None),
                                    density="compact",
                                    hide_details=True,
                                    prepend_icon="mdi-file-pdf-box",
                                )
                            with v3.VCol(cols=4):
                                v3.VBtn(
                                    "Parse",
                                    click=ctrl.parse_fiber_pdf,
                                    color="secondary",
                                    variant="tonal",
                                    size="small",
                                    block=True,
                                    disabled=("!fiber_pdf_input",),
                                )
                        v3.VAlert(
                            v_if="pdf_fiber_summary",
                            density="compact",
                            type=("pdf_fiber_summary.startsWith('ERROR') ? 'error' : 'success'",),
                            text=("pdf_fiber_summary",),
                            classes="mb-2",
                        )
                        v3.VDivider(classes="mb-2")
                        # ---- Manual fields ----
                        v3.VTextField(label="Fiber Name", v_model=("new_fiber_name", "Carbon T700"), density="compact", classes="mb-1")
                        with v3.VRow(dense=True):
                            with v3.VCol(cols=6):
                                v3.VTextField(label="E11 Tension (GPa)", v_model=("new_fiber_e11_t", None), type="number", density="compact")
                                v3.VTextField(label="E11 Comp. (GPa)", v_model=("new_fiber_e11_c", None), type="number", density="compact")
                                v3.VTextField(label="E22 (GPa)", v_model=("new_fiber_e22", None), type="number", density="compact")
                                v3.VTextField(label="G12 (GPa)", v_model=("new_fiber_g12", None), type="number", density="compact")
                            with v3.VCol(cols=6):
                                v3.VTextField(label="Xt (MPa)", v_model=("new_fiber_xt", None), type="number", density="compact")
                                v3.VTextField(label="Xc (MPa)", v_model=("new_fiber_xc", None), type="number", density="compact")
                                v3.VTextField(label="nu12", v_model=("new_fiber_nu12", None), type="number", density="compact")
                                v3.VTextField(label="Density (kg/m3)", v_model=("new_fiber_density", None), type="number", density="compact")
                                v3.VTextField(label="CTE11 (µm/m/K)", v_model=("new_fiber_cte11", 0.0), type="number", density="compact")
                                v3.VTextField(label="CTE22 (µm/m/K)", v_model=("new_fiber_cte22", 0.0), type="number", density="compact")

                        v3.VBtn("Save Fiber", click=ctrl.save_fiber, color="primary", classes="mt-2")

        # ---- Resins Column ----
        with v3.VCol(cols=6):
            v3.VCardTitle("Resins", classes="text-h6")

            # Copy-to-clipboard
            with v3.VRow(dense=True, justify="end", classes="mb-1"):
                with v3.VCol(cols="auto"):
                    v3.VBtn(
                        "Copy as TSV",
                        prepend_icon="mdi-content-copy",
                        size="small",
                        variant="text",
                        click=_copy_js("resin_tsv"),
                    )

            # Resin table
            v3.VDataTable(
                headers=("resin_headers", _resin_display_headers()),
                items=("resin_rows", []),
                density="compact",
                hover=True,
                items_per_page=-1,
            )
            # Per-row edit / delete via select
            with v3.VRow(dense=True, align="center", classes="mt-1 mb-1"):
                with v3.VCol():
                    v3.VSelect(
                        label="Select resin to edit / delete",
                        items=("resins.map((r,i)=>({title:r.name,value:i}))",),
                        v_model=("sel_resin_idx", None),
                        density="compact",
                        hide_details=True,
                        clearable=True,
                    )
                with v3.VCol(cols="auto"):
                    v3.VBtn(
                        icon="mdi-pencil", size="small", variant="tonal",
                        disabled=("sel_resin_idx === null || sel_resin_idx === undefined",),
                        click=(ctrl.open_edit_resin, "[sel_resin_idx]"),
                    )
                with v3.VCol(cols="auto"):
                    v3.VBtn(
                        icon="mdi-delete", size="small", variant="tonal", color="error",
                        disabled=("sel_resin_idx === null || sel_resin_idx === undefined",),
                        click=(ctrl.delete_resin_by_idx, "[sel_resin_idx]"),
                    )

            # New resin form
            with v3.VExpansionPanels(classes="mt-2"):
                with v3.VExpansionPanel(title="Add New Resin"):
                    with v3.VExpansionPanelText():
                        # ---- PDF Datasheet Import ----
                        with v3.VRow(dense=True, align="center", classes="mb-2"):
                            with v3.VCol(cols=8):
                                v3.VFileInput(
                                    label="Import from datasheet PDF",
                                    accept=".pdf",
                                    v_model=("resin_pdf_input", None),
                                    density="compact",
                                    hide_details=True,
                                    prepend_icon="mdi-file-pdf-box",
                                )
                            with v3.VCol(cols=4):
                                v3.VBtn(
                                    "Parse",
                                    click=ctrl.parse_resin_pdf,
                                    color="secondary",
                                    variant="tonal",
                                    size="small",
                                    block=True,
                                    disabled=("!resin_pdf_input",),
                                )
                        v3.VAlert(
                            v_if="pdf_resin_summary",
                            density="compact",
                            type=("pdf_resin_summary.startsWith('ERROR') ? 'error' : 'success'",),
                            text=("pdf_resin_summary",),
                            classes="mb-2",
                        )
                        v3.VDivider(classes="mb-2")
                        # ---- Manual fields ----
                        v3.VTextField(label="Resin Name", v_model=("new_resin_name", "Epoxy 3501"), density="compact", classes="mb-1")
                        with v3.VRow(dense=True):
                            with v3.VCol(cols=6):
                                v3.VTextField(label="Tensile Modulus (GPa)", v_model=("new_resin_e_t", None), type="number", density="compact")
                                v3.VTextField(label="Compressive Modulus (GPa)", v_model=("new_resin_e_c", None), type="number", density="compact")
                                v3.VTextField(label="Xt (MPa)", v_model=("new_resin_xt", 0.0), type="number", density="compact")
                            with v3.VCol(cols=6):
                                v3.VTextField(label="Shear Strength (MPa)", v_model=("new_resin_s", None), type="number", density="compact")
                                v3.VTextField(label="Isotropic nu", v_model=("new_resin_nu", None), type="number", density="compact")
                                v3.VTextField(label="Density (kg/m3)", v_model=("new_resin_density", None), type="number", density="compact")
                                v3.VTextField(label="Xc (MPa)", v_model=("new_resin_xc", 0.0), type="number", density="compact")
                                v3.VTextField(label="CTE (µm/m/K)", v_model=("new_resin_cte", 0.0), type="number", density="compact")

                        v3.VBtn("Save Resin", click=ctrl.save_resin, color="primary", classes="mt-2")

    # ---- Callbacks ----
    @ctrl.add("save_fiber")
    def _save_fiber():
        fiber = {
            "name": state.new_fiber_name or "Unnamed",
            "E11_t": _cln(state.new_fiber_e11_t) * 1e9,
            "E11_c": _cln(state.new_fiber_e11_c) * 1e9,
            "E22": _cln(state.new_fiber_e22) * 1e9,
            "G12": _cln(state.new_fiber_g12) * 1e9,
            "nu12": _cln(state.new_fiber_nu12),
            "density": _cln(state.new_fiber_density),
            "Xt": _cln(state.new_fiber_xt) * 1e6,
            "Xc": _cln(state.new_fiber_xc) * 1e6,
            "cte11": _cln(state.new_fiber_cte11) * 1e-6,
            "cte22": _cln(state.new_fiber_cte22) * 1e-6,
        }
        state.fibers = [*state.fibers, fiber]
        save_db(FIBERS_DB, state.fibers)
        state.fiber_rows = _fiber_display_rows(state.fibers)
        state.fiber_tsv = _fiber_tsv(state.fibers)
        state.save_snackbar_text = f"Fiber saved: {fiber['name']}"
        state.save_snackbar_open = True
        log.info("Saved fiber: %s", fiber["name"])

    @ctrl.add("save_resin")
    def _save_resin():
        resin = {
            "name": state.new_resin_name or "Unnamed",
            "E_t": _cln(state.new_resin_e_t) * 1e9,
            "E_c": _cln(state.new_resin_e_c) * 1e9,
            "nu": _cln(state.new_resin_nu),
            "density": _cln(state.new_resin_density),
            "S": _cln(state.new_resin_s) * 1e6,
            "Xt": _cln(state.new_resin_xt) * 1e6,
            "Xc": _cln(state.new_resin_xc) * 1e6,
            "cte": _cln(state.new_resin_cte) * 1e-6,
        }
        state.resins = [*state.resins, resin]
        save_db(RESINS_DB, state.resins)
        state.resin_rows = _resin_display_rows(state.resins)
        state.resin_tsv = _resin_tsv(state.resins)
        state.save_snackbar_text = f"Resin saved: {resin['name']}"
        state.save_snackbar_open = True
        log.info("Saved resin: %s", resin["name"])

    # ---- PDF parse helpers ----
    def _decode_pdf_input(fi):
        """Extract raw bytes from a trame VFileInput value."""
        if isinstance(fi, list):
            fi = fi[0] if fi else None
        if not fi:
            return None, None
        name = fi.get("name", "upload.pdf")
        content = fi.get("content", b"")
        if isinstance(content, str):
            if "," in content:
                content = content.split(",", 1)[-1]
            content = base64.b64decode(content)
        return name, content

    def _write_tmp_pdf(content: bytes) -> str:
        """Write PDF bytes to a temp file and return its path."""
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.write(content)
        f.close()
        return f.name

    @ctrl.add("parse_fiber_pdf")
    def _parse_fiber_pdf():
        import os
        from pdf_parser import parse_material_datasheet
        name, content = _decode_pdf_input(state.fiber_pdf_input)
        if not content:
            state.pdf_fiber_summary = "ERROR: No file selected."
            return
        tmp = _write_tmp_pdf(content)
        try:
            r = parse_material_datasheet(tmp)
        finally:
            os.unlink(tmp)

        if r.get("_type") == "resin":
            state.pdf_fiber_summary = "ERROR: PDF appears to be a resin datasheet, not a fiber."
            return
        if r.get("_type") == "unknown":
            state.pdf_fiber_summary = "ERROR: Could not identify material type. " + r.get("_summary", "")
            return

        # Populate form fields (convert SI → display units)
        state.new_fiber_name = r.get("name", name.replace(".pdf", ""))
        state.new_fiber_e11_t = round(r["E11_t"] / 1e9, 3)   if "E11_t" in r else state.new_fiber_e11_t
        state.new_fiber_e11_c = round(r["E11_c"] / 1e9, 3)   if "E11_c" in r else state.new_fiber_e11_c
        state.new_fiber_e22   = round(r["E22"]   / 1e9, 3)   if "E22"   in r else state.new_fiber_e22
        state.new_fiber_g12   = round(r["G12"]   / 1e9, 3)   if "G12"   in r else state.new_fiber_g12
        state.new_fiber_nu12  = r.get("nu12", state.new_fiber_nu12)
        state.new_fiber_density = r.get("density", state.new_fiber_density)
        state.new_fiber_xt    = round(r["Xt"] / 1e6, 1)      if "Xt"    in r else state.new_fiber_xt
        state.new_fiber_xc    = round(r["Xc"] / 1e6, 1)      if "Xc"    in r else state.new_fiber_xc
        state.new_fiber_cte11 = round(r["cte11"] * 1e6, 3)   if "cte11" in r else state.new_fiber_cte11
        state.new_fiber_cte22 = round(r["cte22"] * 1e6, 3)   if "cte22" in r else state.new_fiber_cte22

        warn_str = ("  Note: " + " | ".join(r["_warnings"])) if r["_warnings"] else ""
        state.pdf_fiber_summary = f"Parsed: {r['_type'].upper()} — {r.get('name', '')} · E11={round(r.get('E11_t',0)/1e9,1)} GPa · Xt={round(r.get('Xt',0)/1e6,0)} MPa{warn_str}"
        log.info("PDF fiber parse: %s", state.pdf_fiber_summary)

    @ctrl.add("parse_resin_pdf")
    def _parse_resin_pdf():
        import os
        from pdf_parser import parse_material_datasheet
        name, content = _decode_pdf_input(state.resin_pdf_input)
        if not content:
            state.pdf_resin_summary = "ERROR: No file selected."
            return
        tmp = _write_tmp_pdf(content)
        try:
            r = parse_material_datasheet(tmp)
        finally:
            os.unlink(tmp)

        if r.get("_type") == "fiber":
            state.pdf_resin_summary = "ERROR: PDF appears to be a fiber datasheet, not a resin."
            return
        if r.get("_type") == "unknown":
            state.pdf_resin_summary = "ERROR: Could not identify material type. " + r.get("_summary", "")
            return

        # Populate form fields (convert SI → display units)
        state.new_resin_name    = r.get("name", name.replace(".pdf", ""))
        state.new_resin_e_t     = round(r["E_t"]  / 1e9, 3) if "E_t"  in r else state.new_resin_e_t
        state.new_resin_e_c     = round(r["E_c"]  / 1e9, 3) if "E_c"  in r else state.new_resin_e_c
        state.new_resin_nu      = r.get("nu", state.new_resin_nu)
        state.new_resin_density = r.get("density", state.new_resin_density)
        state.new_resin_s       = round(r["S"]   / 1e6, 1)  if "S"    in r else state.new_resin_s
        state.new_resin_xt      = round(r["Xt"]  / 1e6, 1)  if "Xt"   in r else state.new_resin_xt
        state.new_resin_xc      = round(r["Xc"]  / 1e6, 1)  if "Xc"   in r else state.new_resin_xc
        state.new_resin_cte     = round(r["cte"] * 1e6, 2)  if "cte"  in r else state.new_resin_cte

        warn_str = ("  Note: " + " | ".join(r["_warnings"])) if r["_warnings"] else ""
        state.pdf_resin_summary = f"Parsed: {r['_type'].upper()} — {r.get('name', '')} · E_t={round(r.get('E_t',0)/1e9,2)} GPa · Xt={round(r.get('Xt',0)/1e6,1)} MPa{warn_str}"
        log.info("PDF resin parse: %s", state.pdf_resin_summary)

    @state.change("fibers")
    def _update_fiber_rows(fibers, **kwargs):
        state.fiber_rows = _fiber_display_rows(fibers)
        state.fiber_tsv = _fiber_tsv(fibers)

    @state.change("resins")
    def _update_resin_rows(resins, **kwargs):
        state.resin_rows = _resin_display_rows(resins)
        state.resin_tsv = _resin_tsv(resins)


def _build_lamina_tab(server):
    """Lamina Generator — fiber + resin + Vf → SwiftComp material SG → homogenized lamina."""
    state, ctrl = server.state, server.controller

    # Copy-to-clipboard
    with v3.VRow(dense=True, justify="end", classes="mb-1"):
        with v3.VCol(cols="auto"):
            v3.VBtn(
                "Copy as TSV",
                prepend_icon="mdi-content-copy",
                size="small",
                variant="text",
                click=_copy_js("lamina_tsv"),
            )

    # Saved laminae table
    v3.VDataTable(
        headers=("lamina_headers", _lamina_display_headers()),
        items=("lamina_rows", []),
        density="compact",
        hover=True,
        items_per_page=-1,
        classes="mb-2",
    )
    # Per-row edit / delete via select
    with v3.VRow(dense=True, align="center", classes="mt-1 mb-4"):
        with v3.VCol():
            v3.VSelect(
                label="Select lamina to edit / delete",
                items=("laminae.map((l,i)=>({title:l.name,value:i}))",),
                v_model=("sel_lamina_idx", None),
                density="compact",
                hide_details=True,
                clearable=True,
            )
        with v3.VCol(cols="auto"):
            v3.VBtn(
                icon="mdi-pencil", size="small", variant="tonal",
                disabled=("sel_lamina_idx === null || sel_lamina_idx === undefined",),
                click=(ctrl.open_edit_lamina, "[sel_lamina_idx]"),
            )
        with v3.VCol(cols="auto"):
            v3.VBtn(
                icon="mdi-delete", size="small", variant="tonal", color="error",
                disabled=("sel_lamina_idx === null || sel_lamina_idx === undefined",),
                click=(ctrl.delete_lamina_by_idx, "[sel_lamina_idx]"),
            )

    v3.VDivider(classes="mb-4")

    v3.VCardTitle("Lamina Generator", classes="text-subtitle-1 font-weight-bold pb-2")

    # Warning if no constituents loaded
    v3.VAlert(
        v_if="fibers.length === 0 || resins.length === 0",
        type="warning",
        text="Save a fiber and resin first (Constituents tab).",
        density="compact",
        classes="mb-3",
    )

    with v3.VRow(v_if="fibers.length > 0 && resins.length > 0"):
        with v3.VCol(cols=12):
            # UD / Woven toggle
            with v3.VBtnToggle(
                v_model=("lamina_type", "ud"),
                mandatory=True,
                density="compact",
                classes="mb-4",
            ):
                v3.VBtn("UD Fiber", value="ud", prepend_icon="mdi-fiber")
                v3.VBtn("Woven Fabric", value="woven", prepend_icon="mdi-grid")

    # UD-specific fields
    with v3.VRow(v_if="fibers.length > 0 && resins.length > 0 && lamina_type === 'ud'"):
        with v3.VCol(cols=6):
            v3.VSelect(
                label="Fiber",
                v_model=("sel_fiber_idx", 0),
                items=("fibers.map((f, i) => ({title: f.name, value: i}))",),
                density="compact",
            )
            v3.VSelect(
                label="Resin / Matrix",
                v_model=("sel_resin_idx", 0),
                items=("resins.map((r, i) => ({title: r.name, value: i}))",),
                density="compact",
            )
            v3.VSlider(
                label="Fiber Volume Fraction (Vf)",
                v_model=("lamina_vf", 0.6),
                min=0.1,
                max=0.9,
                step=0.01,
                thumb_label="always",
            )
            v3.VSelect(
                label="Packing",
                v_model=("lamina_packing", "hexagonal"),
                items=(
                    "packing_options",
                    [
                        {"title": "Hexagonal (recommended)", "value": "hexagonal"},
                        {"title": "Square", "value": "square"},
                    ],
                ),
                density="compact",
            )
        with v3.VCol(cols=6):
            v3.VTextField(
                label="Lamina Name",
                v_model=("new_lamina_name", ""),
                density="compact",
                classes="mb-2",
            )
            v3.VTextField(
                label="Fiber Areal Weight (FAW, g/m²)",
                v_model=("lamina_faw", 150.0),
                type="number",
                density="compact",
                classes="mb-2",
            )
            v3.VAlert(
                type="info",
                density="compact",
                text=("'Est. Cured Thickness: ' + lamina_cured_thickness_text",),
                classes="mb-4",
            )

    # Woven-specific fields
    with v3.VRow(v_if="fibers.length > 0 && resins.length > 0 && lamina_type === 'woven'"):
        with v3.VCol(cols=6):
            v3.VSelect(
                label="Yarn (Fiber entry)",
                v_model=("sel_fiber_idx", 0),
                items=("fibers.map((f, i) => ({title: f.name, value: i}))",),
                density="compact",
            )
            v3.VSelect(
                label="Resin / Matrix",
                v_model=("sel_resin_idx", 0),
                items=("resins.map((r, i) => ({title: r.name, value: i}))",),
                density="compact",
            )
            v3.VSelect(
                label="Weave Pattern",
                v_model=("woven_pattern", "plain"),
                items=(
                    "weave_options",
                    [
                        {"title": "Plain weave", "value": "plain"},
                        {"title": "Twill weave", "value": "twill"},
                        {"title": "Satin weave", "value": "satin"},
                    ],
                ),
                density="compact",
            )
            v3.VSlider(
                label="Fiber Volume Fraction (Vf)",
                v_model=("woven_vf", 0.6),
                min=0.1,
                max=0.9,
                step=0.01,
                thumb_label="always",
            )
        with v3.VCol(cols=6):
            v3.VTextField(
                label="Yarn Spacing (mm)",
                v_model=("woven_yarn_spacing", 1.0),
                type="number",
                step=0.1,
                density="compact",
                classes="mb-2",
            )
            v3.VTextField(
                label="Yarn Width (mm)",
                v_model=("woven_yarn_width", 0.5),
                type="number",
                step=0.05,
                density="compact",
                classes="mb-2",
            )
            v3.VTextField(
                label="Yarn Thickness (mm)",
                v_model=("woven_yarn_thickness", 0.2),
                type="number",
                step=0.02,
                density="compact",
                classes="mb-2",
            )
            v3.VTextField(
                label="Lamina Name",
                v_model=("new_lamina_name", ""),
                density="compact",
                classes="mb-2",
            )
            v3.VTextField(
                label="Fiber Areal Weight (FAW, g/m²)",
                v_model=("lamina_faw", 150.0),
                type="number",
                density="compact",
                classes="mb-2",
            )

    # Homogenisation method selector + Run/Save buttons
    with v3.VRow(v_if="fibers.length > 0 && resins.length > 0", classes="mt-2"):
        with v3.VCol(cols=4):
            v3.VSelect(
                label="Homogenisation Method",
                v_model=("lamina_homog_method",),
                items=(
                    "homog_method_options",
                    ["Micromechanics (Built-in)", "SwiftComp Material SG"],
                ),
                density="compact",
                hint="Built-in uses ROM/Chamis/Schapery (UD only). Woven layups require SwiftComp.",
                persistent_hint=True,
            )
    with v3.VRow(v_if="fibers.length > 0 && resins.length > 0", classes="mt-2"):
        with v3.VCol(cols="auto"):
            v3.VBtn(
                v_text="'Compute — ' + lamina_homog_method",
                click=ctrl.run_material_sg,
                color="primary",
                loading=("lamina_sg_running",),
                disabled=("lamina_sg_running",),
            )
        with v3.VCol(cols="auto"):
            v3.VBtn(
                "Save Lamina",
                click=ctrl.save_lamina,
                color="secondary",
                variant="tonal",
                disabled=("!lamina_sg_props",),
            )

    # SG result preview
    v3.VAlert(
        v_if="lamina_sg_preview",
        type=("lamina_sg_preview.startsWith('ERROR') ? 'error' : 'success'",),
        density="compact",
        text=("lamina_sg_preview",),
        classes="mt-2",
    )

    # Manual CTE entry (SwiftComp does not output thermal coefficients)
    with v3.VRow(v_if="fibers.length > 0 && resins.length > 0", classes="mt-1"):
        with v3.VCol(cols=12):
            v3.VAlert(
                type="info",
                density="compact",
                classes="mb-2",
                text="CTE values are auto-computed from constituent CTEs (Schapery/SwiftComp). Override below if needed.",
            )
        with v3.VCol(cols=6):
            v3.VTextField(
                label="CTE11 (µm/m/K)",
                v_model=("new_lamina_cte11", 0.0),
                type="number",
                density="compact",
            )
        with v3.VCol(cols=6):
            v3.VTextField(
                label="CTE22 (µm/m/K)",
                v_model=("new_lamina_cte22", 0.0),
                type="number",
                density="compact",
            )

    # ---- Tow Count Estimator ----
    with v3.VExpansionPanels(classes="mt-4", v_if="fibers.length > 0"):
        with v3.VExpansionPanel(title="Estimate FAW from Tow Count"):
            with v3.VExpansionPanelText():
                with v3.VRow(dense=True):
                    with v3.VCol(cols=4):
                        v3.VSelect(
                            label="Tow Count",
                            v_model=("lamina_tow_k", 3),
                            items=(
                                "tow_count_options",
                                [
                                    {"title": "1k (1,000 fil.)", "value": 1},
                                    {"title": "3k (3,000 fil.)", "value": 3},
                                    {"title": "6k (6,000 fil.)", "value": 6},
                                    {"title": "12k (12,000 fil.)", "value": 12},
                                    {"title": "24k (24,000 fil.)", "value": 24},
                                    {"title": "48k (48,000 fil.)", "value": 48},
                                ],
                            ),
                            density="compact",
                            hide_details=True,
                        )
                    with v3.VCol(cols=4):
                        v3.VTextField(
                            label="Filament Diameter (µm)",
                            v_model=("lamina_filament_dia_um", 7.0),
                            type="number",
                            step=0.5,
                            density="compact",
                            hide_details=True,
                        )
                    with v3.VCol(cols=4):
                        v3.VTextField(
                            label="Tow Spread Width (mm)",
                            v_model=("lamina_tow_width_mm", 3.0),
                            type="number",
                            step=0.5,
                            density="compact",
                            hide_details=True,
                        )
                with v3.VRow(dense=True, classes="mt-2 align-center"):
                    with v3.VCol(cols=8):
                        v3.VAlert(
                            v_if="lamina_est_faw_text",
                            type="info",
                            density="compact",
                            text=("'Estimated FAW: ' + lamina_est_faw_text",),
                        )
                    with v3.VCol(cols=4):
                        v3.VBtn(
                            "Apply to FAW",
                            click=ctrl.apply_tow_faw,
                            color="secondary",
                            variant="tonal",
                            disabled=("!lamina_est_faw_text",),
                            block=True,
                        )

    # Callbacks
    @ctrl.add("save_lamina")
    def _save_lamina():
        props = state.lamina_sg_props
        if not props:
            log.warning("save_lamina: no SG props — run material SG first")
            return

        idx_f = int(state.sel_fiber_idx or 0)
        faw = float(state.lamina_faw or 150.0)
        fiber = state.fibers[idx_f] if state.fibers else {}
        f_dens = fiber.get("density", 1800.0)
        vf = float(state.lamina_vf if state.lamina_type == "ud" else state.woven_vf or 0.6)
        thick_mm = 0.0
        if f_dens > 0 and vf > 0:
            thick_mm = ((faw / 1000.0) / (f_dens * vf)) * 1000.0

        lam_props = dict(props)
        lam_props["name"] = state.new_lamina_name or f"{fiber.get('name', 'Lamina')}"
        lam_props["thickness_mm"] = thick_mm
        lam_props["cte11"] = _cln(state.new_lamina_cte11) * 1e-6
        lam_props["cte22"] = _cln(state.new_lamina_cte22) * 1e-6

        state.laminae = [*state.laminae, lam_props]
        save_db(LAMINAE_DB, state.laminae)
        state.lamina_rows = _lamina_display_rows(state.laminae)
        state.lamina_tsv = _lamina_tsv(state.laminae)
        state.lamina_sg_props = None
        state.lamina_sg_preview = ""
        state.save_snackbar_text = f"Lamina saved: {lam_props['name']}"
        state.save_snackbar_open = True
        log.info("Saved lamina: %s (t=%.4f mm)", lam_props["name"], thick_mm)

    @state.change("laminae")
    def _update_lamina_rows(laminae, **kwargs):
        state.lamina_rows = _lamina_display_rows(laminae)
        state.lamina_tsv = _lamina_tsv(laminae)

    # Compute cured thickness text reactively (UD mode)
    @state.change("sel_fiber_idx", "lamina_vf", "lamina_faw")
    def _update_cured_thickness(sel_fiber_idx=0, lamina_vf=0.6, lamina_faw=150.0, **kwargs):
        idx = int(sel_fiber_idx or 0)
        vf = float(lamina_vf or 0.6)
        faw = float(lamina_faw or 150.0)
        if state.fibers and idx < len(state.fibers):
            f_dens = state.fibers[idx].get("density", 1800.0)
            if f_dens > 0 and vf > 0:
                thick_mm = ((faw / 1000.0) / (f_dens * vf)) * 1000.0
                state.lamina_cured_thickness_text = f"{thick_mm:.4f} mm"
                return
        state.lamina_cured_thickness_text = "N/A"

    # Tow count → FAW estimator
    @state.change("lamina_tow_k", "lamina_filament_dia_um", "lamina_tow_width_mm", "sel_fiber_idx")
    def _update_tow_faw(lamina_tow_k=3, lamina_filament_dia_um=7.0, lamina_tow_width_mm=3.0,
                        sel_fiber_idx=0, **kwargs):
        try:
            n_fil = int(lamina_tow_k or 3) * 1000
            d_um = float(lamina_filament_dia_um or 7.0)
            pitch_mm = float(lamina_tow_width_mm or 3.0)
            if pitch_mm <= 0 or d_um <= 0:
                state.lamina_est_faw_text = ""
                return
            rho_g_cm3 = 1.76  # default (carbon fiber)
            idx = int(sel_fiber_idx or 0)
            if state.fibers and idx < len(state.fibers):
                rho_g_cm3 = state.fibers[idx].get("density", 1760.0) / 1000.0
            d_cm = d_um * 1e-4
            pitch_cm = pitch_mm / 10.0
            faw = n_fil * (math.pi / 4.0 * d_cm ** 2) * rho_g_cm3 / pitch_cm
            state.lamina_est_faw_text = f"{faw:.1f} g/m²"
            state._tow_est_faw_value = faw
        except Exception:
            state.lamina_est_faw_text = ""

    @ctrl.add("apply_tow_faw")
    def _apply_tow_faw():
        val = getattr(state, "_tow_est_faw_value", None)
        if val is not None:
            state.lamina_faw = round(val, 1)


def _build_layup_tab(server):
    """Layup Designer — stack plies from laminae."""
    state, ctrl = server.state, server.controller

    with v3.VRow():
        # ---- Saved Layups ----
        with v3.VCol(cols=12):
            with v3.VExpansionPanels(classes="mb-4"):
                with v3.VExpansionPanel(title="Saved Layups"):
                    with v3.VExpansionPanelText():
                        with v3.VList(density="compact", v_if="layups.length > 0"):
                            with v3.VListItem(
                                v_for="ly, li in layups",
                                key="li",
                            ):
                                with v3.VListItemTitle():
                                    v3.VChip(
                                        text=("ly.name + ' — ' + ly.plies.length + ' plies'",),
                                        size="small",
                                    )
                                with v3.Template(v_slot_append=True):
                                    v3.VBtn(
                                        "Load",
                                        size="small",
                                        color="primary",
                                        variant="text",
                                        click="layup_plies = [...ly.plies]",
                                    )
                                    v3.VBtn(
                                        "Delete",
                                        size="small",
                                        color="error",
                                        variant="text",
                                        click=(ctrl.delete_layup, "[li]"),
                                    )
                        v3.VAlert(
                            v_if="layups.length === 0",
                            text="No layups saved yet.",
                            type="info",
                            density="compact",
                        )

    with v3.VRow():
        # ---- Build Layup ----
        with v3.VCol(cols=5):
            v3.VCardTitle("Build Layup Stack", classes="text-h6 pb-2")

            v3.VAlert(
                v_if="laminae.length === 0",
                type="warning",
                text="Create laminae first.",
                density="compact",
            )

            with v3.VRow(v_if="laminae.length > 0", dense=True):
                with v3.VCol(cols=7):
                    v3.VSelect(
                        label="Lamina",
                        v_model=("sel_ply_lamina_idx", 0),
                        items=("laminae.map((l, i) => ({title: l.name, value: i}))",),
                        density="compact",
                    )
                with v3.VCol(cols=5):
                    v3.VTextField(
                        label="Angle (deg)",
                        v_model=("sel_ply_angle", 0),
                        type="number",
                        step=15,
                        density="compact",
                    )

            with v3.VRow(dense=True, classes="mt-1"):
                with v3.VCol(cols="auto"):
                    v3.VBtn("Add Ply", click=ctrl.add_ply, color="primary", variant="outlined", size="small")
                with v3.VCol(cols="auto"):
                    v3.VBtn("Clear All", click="layup_plies = []", color="error", variant="text", size="small")

            v3.VDivider(classes="my-3")

            v3.VTextField(
                label="Layup Name",
                v_model=("save_layup_name", "Quasi-Isotropic 8-ply"),
                density="compact",
                classes="mb-2",
            )
            v3.VBtn("Save Layup", click=ctrl.save_layup, color="primary")

        # ---- Ply Stack List ----
        with v3.VCol(cols=7):
            v3.VCardTitle("Current Ply Stack", classes="text-h6 pb-2")

            with v3.VList(density="compact", v_if="layup_plies.length > 0"):
                with v3.VListItem(
                    v_for="(ply, pi) in layup_plies",
                    key="pi",
                    classes="pl-0 pr-1",
                ):
                    with v3.VListItemTitle():
                        v3.VChip(text=("'#' + (pi + 1)",), size="x-small", classes="mr-2")
                        html.Span(v_text="ply.lamina_name", classes="mr-4 text-body-2")
                    with v3.Template(v_slot_append=True):
                        # Angle display or inline edit
                        html.Span(
                            v_if="edit_ply_idx !== pi",
                            v_text="String(ply.angle) + '°'",
                            classes="text-caption mr-1",
                        )
                        v3.VTextField(
                            v_if="edit_ply_idx === pi",
                            v_model=("edit_ply_angle_val", 0),
                            type="number",
                            step=15,
                            density="compact",
                            style="max-width:72px",
                            hide_details=True,
                            classes="mr-1",
                        )
                        v3.VBtn(
                            v_if="edit_ply_idx === pi",
                            icon="mdi-check",
                            size="x-small",
                            variant="tonal",
                            color="success",
                            click=(ctrl.commit_ply_angle, "[pi]"),
                        )
                        v3.VBtn(
                            v_if="edit_ply_idx !== pi",
                            icon="mdi-pencil",
                            size="x-small",
                            variant="text",
                            click="edit_ply_idx = pi; edit_ply_angle_val = ply.angle",
                        )
                        v3.VBtn(
                            icon="mdi-arrow-up",
                            size="x-small",
                            variant="text",
                            disabled=("pi === 0",),
                            click=(ctrl.move_ply_up, "[pi]"),
                        )
                        v3.VBtn(
                            icon="mdi-arrow-down",
                            size="x-small",
                            variant="text",
                            disabled=("pi === layup_plies.length - 1",),
                            click=(ctrl.move_ply_down, "[pi]"),
                        )
                        v3.VBtn(
                            icon="mdi-delete",
                            size="x-small",
                            variant="text",
                            color="error",
                            click=(ctrl.remove_ply, "[pi]"),
                        )

            v3.VAlert(
                v_if="layup_plies.length === 0",
                text="No plies in current stack.",
                type="info",
                density="compact",
            )

            v3.VAlert(
                v_if="layup_total_thickness > 0",
                type="info",
                density="compact",
                text=("'Total Thickness: ' + layup_total_thickness.toFixed(3) + ' mm'",),
                classes="mt-2",
            )

    # ---- Callbacks ----
    @ctrl.add("add_ply")
    def _add_ply():
        idx = int(state.sel_ply_lamina_idx or 0)
        if not state.laminae or idx >= len(state.laminae):
            return
        lam = state.laminae[idx]
        ply = {"lamina_name": lam["name"], "angle": float(state.sel_ply_angle or 0)}
        state.layup_plies = [*state.layup_plies, ply]

    @ctrl.add("remove_ply")
    def _remove_ply(idx):
        plies = list(state.layup_plies)
        if 0 <= idx < len(plies):
            plies.pop(idx)
            state.layup_plies = plies

    @ctrl.add("move_ply_up")
    def _move_ply_up(idx):
        plies = list(state.layup_plies)
        if 0 < idx < len(plies):
            plies[idx - 1], plies[idx] = plies[idx], plies[idx - 1]
            state.layup_plies = plies

    @ctrl.add("move_ply_down")
    def _move_ply_down(idx):
        plies = list(state.layup_plies)
        if 0 <= idx < len(plies) - 1:
            plies[idx], plies[idx + 1] = plies[idx + 1], plies[idx]
            state.layup_plies = plies

    @ctrl.add("commit_ply_angle")
    def _commit_ply_angle(idx):
        plies = list(state.layup_plies)
        if 0 <= idx < len(plies):
            plies[idx] = {**plies[idx], "angle": float(state.edit_ply_angle_val or 0)}
            state.layup_plies = plies
        state.edit_ply_idx = -1

    @ctrl.add("save_layup")
    def _save_layup():
        if not state.layup_plies:
            return
        name = state.save_layup_name or "Unnamed Layup"
        layup = {"name": name, "plies": list(state.layup_plies)}
        state.layups = [*state.layups, layup]
        save_db(LAYUPS_DB, state.layups)
        log.info("Saved layup: %s (%d plies)", name, len(state.layup_plies))

    @ctrl.add("delete_layup")
    def _delete_layup(idx):
        layups = list(state.layups)
        if 0 <= idx < len(layups):
            layups.pop(idx)
            state.layups = layups
            save_db(LAYUPS_DB, state.layups)

    # Reactive total thickness (VList reads layup_plies directly)
    @state.change("layup_plies")
    def _update_ply_stack(layup_plies, **kwargs):
        total = 0.0
        for p in layup_plies:
            lam = next((x for x in state.laminae if x["name"] == p["lamina_name"]), None)
            total += lam["thickness_mm"] if lam else 0.0
        state.layup_total_thickness = total
