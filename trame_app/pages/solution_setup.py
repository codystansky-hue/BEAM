"""Page 2: Solution Setup — Boundary Conditions, Thermal, Snippet."""

import math
from trame.widgets import vuetify3 as v3, html


def _make_load_diagram_svg(angle_deg, F_total):
    """
    Return an SVG string illustrating the tip load direction.

    Coordinate convention shown in the diagram
    ─────────────────────────────────────────────
    • Horizontal (→) = beam span, +x₁ direction (GXBeam / CCX DOF-3)
    • Vertical  (↑)  = cross-section height, +x₃ direction (GXBeam Fz / CCX DOF-2)
    • A COMPRESSIVE load (F < 0) enters the beam tip from the right,
      pointing toward the root (←) with any transverse offset.
    • The angle θ is measured from the beam axis toward the cross-section
      vertical (+x₃, upward in diagram).
    • Remote reference node (●) is the kinematic RBE point; dashed lines
      show the rigid-body coupling to the tip face.
    """
    angle_deg = float(angle_deg or 0)
    theta = math.radians(angle_deg)
    F = float(F_total or -1000)
    absF = abs(F) if abs(F) > 1e-9 else 1.0

    Fx = F * math.cos(theta)
    Fz = F * math.sin(theta)

    W, H = 480, 200
    # Beam geometry in screen coords (SVG: y+ = down; we flip vertical labels)
    beam_y = 105          # centroidal axis screen-y
    beam_h = 22           # half-height of beam rect each side
    bx0, bx1 = 70, 300   # root x, tip x

    arr_len = 90          # arrow length in pixels
    tip_cx, tip_cy = bx1, beam_y

    # Force vector in screen:
    #   screen_dx = Fx / |F|           (+right = tension; -left = compression)
    #   screen_dy = -Fz / |F|          (screen-y is inverted vs. structural-y,
    #                                   so -Fz maps to downward screen movement
    #                                   when Fz is positive-upward)
    sdx = Fx / absF
    sdy = -Fz / absF      # flip: structural +z (up) → screen -y (up)

    # Remote reference node — source of the load arrow
    rp_x = tip_cx - sdx * arr_len
    rp_y = tip_cy - sdy * arr_len

    # Axial component endpoint (horizontal from tip)
    ax_ex = tip_cx - sdx * arr_len
    ax_ey = tip_cy

    # Transverse component endpoint (vertical from tip)
    tr_ex = tip_cx
    tr_ey = tip_cy - sdy * arr_len

    def arrow_head(x1, y1, x2, y2, size=8, color="white"):
        """SVG polygon arrowhead at (x2, y2) pointing from (x1,y1)."""
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1
        nx, ny = dx / L, dy / L
        px, py = -ny, nx
        pts = [
            (x2, y2),
            (x2 - size * nx + size * 0.4 * px, y2 - size * ny + size * 0.4 * py),
            (x2 - size * nx - size * 0.4 * px, y2 - size * ny - size * 0.4 * py),
        ]
        pts_str = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts)
        return f'<polygon points="{pts_str}" fill="{color}"/>'

    def fmt_n(v):
        return f"{v:+.0f} N"

    # Angle arc (drawn at tip, radius 28px, from 180° toward load direction in screen)
    arc_r = 28
    # arc start = leftward (beam axis, 180° in SVG = 180° from +x)
    # arc end   = direction of load vector
    load_screen_angle = math.atan2(sdy, sdx)   # angle of force vector in screen
    beam_axis_angle   = math.atan2(0, -1)       # 180° = leftward

    def arc_path(cx, cy, r, a_start, a_end):
        """SVG arc from a_start to a_end (radians), counterclockwise in screen coords."""
        # In SVG y-down, atan2 gives CW angles; we draw the shorter arc
        x1 = cx + r * math.cos(a_start)
        y1 = cy + r * math.sin(a_start)
        x2 = cx + r * math.cos(a_end)
        y2 = cy + r * math.sin(a_end)
        # sweep-flag=0 for CCW in SVG (y-down = CW visually)
        large = 1 if abs(a_end - a_start) > math.pi else 0
        sweep = 0
        return f"M {x1:.1f} {y1:.1f} A {r} {r} 0 {large} {sweep} {x2:.1f} {y2:.1f}"

    # Only show arc when angle is non-trivial
    show_arc = abs(theta) > math.radians(1)
    arc_mid_angle = (beam_axis_angle + load_screen_angle) / 2
    arc_label_x = tip_cx + (arc_r + 12) * math.cos(arc_mid_angle)
    arc_label_y = tip_cy + (arc_r + 12) * math.sin(arc_mid_angle)

    # Dashed coupling lines from remote node to a few points on the tip face
    coupling_ys = [beam_y - beam_h, beam_y, beam_y + beam_h]
    coupling_lines = "".join(
        f'<line x1="{rp_x:.1f}" y1="{rp_y:.1f}" '
        f'x2="{tip_cx:.1f}" y2="{cy:.1f}" '
        f'stroke="#555" stroke-width="1" stroke-dasharray="4,3"/>'
        for cy in coupling_ys
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"
     style="background:#1e1e1e; font-family:monospace; font-size:11px; display:block;">
  <defs>
    <marker id="ah_white" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="white"/>
    </marker>
    <marker id="ah_cyan"  markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#00e5ff"/>
    </marker>
    <marker id="ah_orange" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#ff9800"/>
    </marker>
    <marker id="ah_green" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#69f0ae"/>
    </marker>
  </defs>

  <!-- Axis labels -->
  <text x="{bx1 + 5}" y="{beam_y + 4}" fill="#666" font-size="10">+x₁ (span)</text>
  <text x="{bx1 + 5}" y="{beam_y - beam_h - 6}" fill="#666" font-size="10">+x₃ (up)</text>

  <!-- Beam body -->
  <rect x="{bx0}" y="{beam_y - beam_h}" width="{bx1 - bx0}" height="{beam_h * 2}"
        fill="#37474f" stroke="#607d8b" stroke-width="1.5" rx="2"/>

  <!-- Root hatch (fixed boundary symbol) -->
  <rect x="{bx0 - 14}" y="{beam_y - beam_h - 4}" width="14" height="{beam_h * 2 + 8}"
        fill="none" stroke="#546e7a" stroke-width="1.5"/>
  {''.join(
      f'<line x1="{bx0 - 14}" y1="{beam_y - beam_h - 4 + i * 8}" '
      f'x2="{bx0}" y2="{beam_y - beam_h - 4 + i * 8 + 8}" '
      f'stroke="#546e7a" stroke-width="1"/>'
      for i in range(6)
  )}

  <!-- Tip face (cross-section) -->
  <line x1="{bx1}" y1="{beam_y - beam_h - 6}" x2="{bx1}" y2="{beam_y + beam_h + 6}"
        stroke="#00bcd4" stroke-width="2.5"/>

  <!-- Rigid-body coupling dashed lines -->
  {coupling_lines}

  <!-- Remote reference node -->
  <circle cx="{rp_x:.1f}" cy="{rp_y:.1f}" r="6" fill="#ff9800" stroke="#fff" stroke-width="1.5"/>

  <!-- Axial component arrow (cyan, horizontal dashed) -->
  <line x1="{tip_cx:.1f}" y1="{tip_cy:.1f}" x2="{ax_ex:.1f}" y2="{ax_ey:.1f}"
        stroke="#00e5ff" stroke-width="1.5" stroke-dasharray="6,3"
        marker-end="url(#ah_cyan)"/>
  <!-- Transverse component arrow (green, vertical dashed) -->
  <line x1="{tip_cx:.1f}" y1="{tip_cy:.1f}" x2="{tr_ex:.1f}" y2="{tr_ey:.1f}"
        stroke="#69f0ae" stroke-width="1.5" stroke-dasharray="6,3"
        marker-end="url(#ah_green)"/>

  <!-- Resultant load arrow (white, solid) -->
  <line x1="{rp_x:.1f}" y1="{rp_y:.1f}" x2="{tip_cx:.1f}" y2="{tip_cy:.1f}"
        stroke="white" stroke-width="2"
        marker-end="url(#ah_white)"/>

  <!-- Angle arc + label -->
  {"" if not show_arc else
    f'<path d="{arc_path(tip_cx, tip_cy, arc_r, beam_axis_angle, load_screen_angle)}"'
    f' fill="none" stroke="#aaa" stroke-width="1.2" stroke-dasharray="3,2"/>'
    f'<text x="{arc_label_x:.1f}" y="{arc_label_y + 4:.1f}" fill="#ccc" font-size="10"'
    f' text-anchor="middle">{angle_deg:.0f}°</text>'
  }

  <!-- Labels -->
  <text x="{bx0 - 7}" y="{beam_y + beam_h + 18}" fill="#90a4ae" text-anchor="middle">ROOT</text>
  <text x="{bx1}" y="{beam_y + beam_h + 18}" fill="#00bcd4" text-anchor="middle">TIP</text>
  <text x="{rp_x:.1f}" y="{rp_y - 10:.1f}" fill="#ff9800" text-anchor="middle"
        font-size="10">Ref Node</text>

  <!-- Component value labels -->
  <text x="{(tip_cx + ax_ex) / 2:.1f}" y="{ax_ey - 6:.1f}"
        fill="#00e5ff" text-anchor="middle">Fx = {fmt_n(Fx)}</text>
  <text x="{tr_ex + (12 if Fz >= 0 else -12):.1f}" y="{(tip_cy + tr_ey) / 2 + 4:.1f}"
        fill="#69f0ae" text-anchor="{"start" if Fz >= 0 else "end"}">Fz = {fmt_n(Fz)}</text>
  <text x="{(tip_cx + rp_x) / 2 - 8:.1f}" y="{(tip_cy + rp_y) / 2 - 4:.1f}"
        fill="white" text-anchor="middle">|F| = {fmt_n(abs(F))}</text>
</svg>"""
    return svg

BC_OPTIONS = [
    "Fixed-Free (Cantilever)",
    "Pinned-Pinned",
    "Fixed-Pinned",
    "Fixed-Fixed",
]

DOF_ITEMS = [
    {"title": "UX", "value": 1},
    {"title": "UY", "value": 2},
    {"title": "UZ", "value": 3},
    {"title": "RX", "value": 4},
    {"title": "RY", "value": 5},
    {"title": "RZ", "value": 6},
]


def build_solution_setup_page(server):
    """Build the solution setup page UI inside the current layout context."""
    state, ctrl = server.state, server.controller

    # Keep load diagram in sync with the two driving state variables
    def _refresh_load_diagram(**_):
        state.load_diagram_svg = _make_load_diagram_svg(
            state.load_angle_deg, state.snippet_compressive_load
        )

    state.change("load_angle_deg", "snippet_compressive_load")(_refresh_load_diagram)
    _refresh_load_diagram()  # render once on page build

    # ---- Boundary Conditions ----
    with v3.VCard(classes="mb-4", variant="outlined"):
        v3.VCardTitle("Boundary Conditions")
        with v3.VCardText():
            with v3.VRow():
                with v3.VCol(cols=6):
                    v3.VSelect(
                        label="Global Beam Constraint (Affects Euler)",
                        v_model=("bc_type",),
                        items=("bc_options", BC_OPTIONS),
                        density="compact",
                    )
                with v3.VCol(cols=6):
                    with v3.VExpansionPanels():
                        with v3.VExpansionPanel(title="Override CCX 3D DOF Constraints"):
                            with v3.VExpansionPanelText():
                                v3.VSelect(
                                    label="CCX Root Nodes",
                                    v_model=("ccx_root_dofs",),
                                    items=("dof_items", DOF_ITEMS),
                                    multiple=True,
                                    chips=True,
                                    closable_chips=True,
                                    density="compact",
                                    classes="mb-2",
                                )
                                v3.VSelect(
                                    label="CCX Tip Nodes",
                                    v_model=("ccx_tip_dofs",),
                                    items=("dof_items",),
                                    multiple=True,
                                    chips=True,
                                    closable_chips=True,
                                    density="compact",
                                )

    # ---- Thermal & CCX Loads ----
    with v3.VCard(variant="outlined"):
        v3.VCardTitle("Thermal & CCX Loads")
        with v3.VCardText():
            with v3.VRow():
                with v3.VCol(cols=6):
                    v3.VCheckbox(
                        label="Include Static Thermal Pre-Stress",
                        v_model=("include_thermal",),
                        density="compact",
                    )

                    v3.VTextField(
                        v_if="include_thermal",
                        label="Temp Max +X (\u00b0C)",
                        v_model=("temp_max_x",),
                        type="number",
                        density="compact",
                        classes="mb-1",
                    )
                    v3.VTextField(
                        v_if="include_thermal",
                        label="Temp Min -X (\u00b0C)",
                        v_model=("temp_min_x",),
                        type="number",
                        density="compact",
                        classes="mb-1",
                    )
                    v3.VTextField(
                        v_if="include_thermal",
                        label="Reference Temp (\u00b0C)",
                        v_model=("temp_ref",),
                        type="number",
                        density="compact",
                    )

                with v3.VCol(cols=6):
                    v3.VTextField(
                        label="Tip Load Magnitude (N)",
                        v_model=("snippet_compressive_load",),
                        type="number",
                        density="compact",
                        hint="Negative = compression. Magnitude decomposed by load angle below.",
                        persistent_hint=True,
                        classes="mb-2",
                    )
                    v3.VTextField(
                        label="Load Angle from Beam Axis (°)",
                        v_model=("load_angle_deg",),
                        type="number",
                        density="compact",
                        hint="0° = purely axial. 30° = 30° toward cross-section vertical (+x₃). Applied as remote load via rigid-body tip reference node.",
                        persistent_hint=True,
                        classes="mb-3",
                    )
                    # Live load-direction diagram
                    html.Div(
                        v_html=("load_diagram_svg",),
                        style="border-radius:4px; overflow:hidden;",
                    )

    # ---- Solver Settings ----
    with v3.VCard(variant="outlined", classes="mt-4"):
        v3.VCardTitle("Solver Settings")
        with v3.VCardText():
            with v3.VRow():
                with v3.VCol(cols=6):
                    v3.VCardSubtitle("Cross-Section Solver", classes="px-0 mb-2")
                    v3.VSelect(
                        label="Stage 2 Cross-Section Solver",
                        v_model=("xs_solver",),
                        items=(
                            "xs_solver_options",
                            ["CLT (Built-in)", "SwiftComp", "VABS"],
                        ),
                        density="compact",
                        hint="CLT uses Classical Lamination Theory + Bredt's closed-section torsion. SwiftComp/VABS require external executables.",
                        persistent_hint=True,
                        classes="mb-3",
                    )
                    v3.VCardSubtitle("CalculiX", classes="px-0 mb-2")
                    v3.VCheckbox(
                        label="NLGEOM (Geometric Nonlinearity)",
                        v_model=("nlgeom_thermal",),
                        density="compact",
                        hint="Enable for large deformation thermal pre-stress. Slower and may not converge.",
                        persistent_hint=True,
                    )
                    v3.VAlert(
                        v_if="nlgeom_thermal",
                        type="warning",
                        density="compact",
                        text="NLGEOM can fail to converge with large thermal gradients. Use linear (off) if the buckle step never completes.",
                        classes="mt-1 mb-2",
                    )

    # ---- Active Configuration Summary ----
    with v3.VCard(variant="outlined", classes="mt-4"):
        v3.VCardTitle("Active Configuration Summary")
        with v3.VCardText():
            with v3.VTable(density="compact"):
                with html.Thead():
                    with html.Tr():
                        html.Th("Parameter", style="width: 40%;")
                        html.Th("Value")
                        html.Th("Unit")
                with html.Tbody():
                    # Geometry
                    with html.Tr():
                        html.Td("Geometry File", classes="font-weight-bold")
                        html.Td(v_text="geo_file_name || 'None'")
                        html.Td("")
                    with html.Tr():
                        html.Td("Span Length")
                        html.Td(v_text="span_length")
                        html.Td("m")
                    with html.Tr():
                        html.Td("Element Size")
                        html.Td(v_text="elem_size")
                        html.Td("mm")
                    with html.Tr():
                        html.Td("Elements Through Thickness")
                        html.Td(v_text="num_elem_thick")
                        html.Td("")
                    # Boundary conditions
                    with html.Tr(classes="bg-grey-darken-4"):
                        html.Td("Boundary Condition", classes="font-weight-bold", colspan=3)
                    with html.Tr():
                        html.Td("BC Type")
                        html.Td(v_text="bc_type")
                        html.Td("")
                    with html.Tr():
                        html.Td("CCX Root DOFs")
                        html.Td(v_text="ccx_root_dofs.join(', ')")
                        html.Td("")
                    with html.Tr():
                        html.Td("CCX Tip DOFs")
                        html.Td(v_text="ccx_tip_dofs.length ? ccx_tip_dofs.join(', ') : 'Free'")
                        html.Td("")
                    # Thermal
                    with html.Tr(classes="bg-grey-darken-4"):
                        html.Td("Thermal", classes="font-weight-bold", colspan=3)
                    with html.Tr():
                        html.Td("Include Thermal Pre-Stress")
                        html.Td(v_text="include_thermal ? 'Yes' : 'No'")
                        html.Td("")
                    with html.Tr(v_if="include_thermal"):
                        html.Td("Temp Max / Min / Ref")
                        html.Td(v_text="temp_max_x + ' / ' + temp_min_x + ' / ' + temp_ref")
                        html.Td("\u00b0C")
                    # Snippet
                    with html.Tr(classes="bg-grey-darken-4"):
                        html.Td("CCX Snippet", classes="font-weight-bold", colspan=3)
                    with html.Tr():
                        html.Td("Snippet Length")
                        html.Td(v_text="snippet_length")
                        html.Td("mm")
                    with html.Tr():
                        html.Td("Elements Along Z")
                        html.Td(v_text="snippet_elems_z")
                        html.Td("")
                    with html.Tr():
                        html.Td("Tip Load Magnitude")
                        html.Td(v_text="snippet_compressive_load")
                        html.Td("N")
                    with html.Tr():
                        html.Td("Load Angle")
                        html.Td(v_text="load_angle_deg + '° → Fx=' + (snippet_compressive_load * Math.cos(load_angle_deg * Math.PI / 180)).toFixed(1) + ' N, Fz=' + (snippet_compressive_load * Math.sin(load_angle_deg * Math.PI / 180)).toFixed(1) + ' N'")
                        html.Td("")
                    # Solver flags
                    with html.Tr(classes="bg-grey-darken-4"):
                        html.Td("Solver Flags", classes="font-weight-bold", colspan=3)
                    with html.Tr():
                        html.Td("NLGEOM")
                        html.Td(v_text="nlgeom_thermal ? 'ON' : 'OFF'")
                        html.Td("")
                    with html.Tr():
                        html.Td("GXBeam Elements")
                        html.Td(v_text="gxbeam_nelem")
                        html.Td("")
                    with html.Tr():
                        html.Td("Cross-Section Solver")
                        html.Td(v_text="xs_solver")
                        html.Td("")
                    # Solver paths
                    with html.Tr(classes="bg-grey-darken-4"):
                        html.Td("Solver Paths", classes="font-weight-bold", colspan=3)
                    with html.Tr():
                        html.Td("SwiftComp")
                        html.Td(v_text="swiftcomp_path", style="word-break: break-all;")
                        html.Td("")
                    with html.Tr():
                        html.Td("Julia (GXBeam)")
                        html.Td(v_text="gxbeam_path", style="word-break: break-all;")
                        html.Td("")
                    with html.Tr():
                        html.Td("CalculiX")
                        html.Td(v_text="ccx_path", style="word-break: break-all;")
                        html.Td("")
