# Progressive Load Ramping

## Context

The app currently runs CalculiX buckling at a single load magnitude and returns one eigenvalue factor. The user wants to sweep load magnitude across a range, re-running CalculiX at each step, to find the onset of local buckling — especially valuable with NLGEOM thermal pre-stress where the critical load isn't a simple inverse scaling.

## Approach

The K matrix (Stage 2) is load-independent — compute it once. Only the CalculiX `*BUCKLE` step (Stage 3) needs to re-run at each load level. GXBeam deflections scale linearly from the reference run, so no Julia re-invocation per step.

## Files to Modify

| File | Changes |
|------|---------|
| `trame_app/state.py` | Add ramp state variables (config + results) |
| `trame_app/engine.py` | `_run_load_ramp_sync`, `run_load_ramp`, `_render_ramp_chart`; refactor `_run_stage_3` to accept `working_dir` |
| `trame_app/pages/solution_setup.py` | Ramp toggle + load range inputs (start/end/step) |
| `trame_app/pages/execution.py` | "Run Load Ramp" button + progress bar |
| `trame_app/pages/results.py` | Ramp results: summary card, iteration table, convergence chart |
| `trame_app.py` | Register `ctrl.run_load_ramp` controller |

## 1. State Variables (`state.py`)

```
ramp_enabled        False           Toggle in solution setup
ramp_load_start     -100.0          N (start of sweep)
ramp_load_end       -2000.0         N (end of sweep)
ramp_load_step      -100.0          N (increment, negative for compression)
ramp_running        False           Execution flag
ramp_progress       0               0–100 percent
ramp_log_string     ""              Live solver log
ramp_results        []              List of dicts per step
ramp_table_rows     []              Formatted for VDataTable
ramp_chart_b64      ""              Matplotlib convergence chart
ramp_critical_load  None            First load where factor ≤ 1.0
ramp_complete       False           Done flag
```

## 2. Engine (`engine.py`)

### Refactor `_run_stage_3`

Add optional `working_dir` parameter so the ramp loop can pass a unique subdirectory per step:
```python
def _run_stage_3(snap, log_cb=None, working_dir=None):
    runs_dir = working_dir or os.path.join(os.getcwd(), "runs")
```

### `_run_load_ramp_sync(snap, load_steps, progress_cb, log_cb)`

Loop over `load_steps`:
1. Create `runs/ramp/step_{i:03d}/` subdirectory
2. Copy `snap` with `snippet_compressive_load = load_steps[i]`
3. Call `_run_stage_3(modified_snap, log_cb, working_dir=step_dir)`
4. Collect `{load, ccx_factor, critical_load_kN, buckled, deflections_scaled}`
5. Linearly scale GXBeam deflections: `ref_defl * (load / ref_load)`
6. Handle convergence failures gracefully (record `ccx_factor=None`, continue)
7. Report progress

### `_render_ramp_chart(results)`

Dark-themed matplotlib:
- X: load magnitude (N)
- Y: buckling factor
- Horizontal line at factor = 1.0
- Points color-coded green (safe) / red (buckled)
- Vertical dashed line at interpolated critical load
- Returns base64 PNG

### `run_load_ramp(state)` — async wrapper

Follows `run_batch_analysis` pattern: sets running flags, builds load_steps list from state, calls `asyncio.to_thread(_run_load_ramp_sync, ...)`, formats results, renders chart.

## 3. UI: Solution Setup

Add a "Load Ramping" section in the Loads card (after the single-load field):
- `v3.VCheckbox` for `ramp_enabled`
- When enabled: show start/end/step `VTextField` fields
- Info alert explaining the feature
- Warning alert when NLGEOM is off (results will be trivially predictable)

## 4. UI: Execution Page

Add alongside existing pipeline buttons:
- "Run Load Ramp" button (color="warning", requires mesh + K matrix + ramp_enabled)
- Progress bar bound to `ramp_progress`
- Log output in expansion panel bound to `ramp_log_string`

## 5. UI: Results Page

New "Load Ramp Results" card (visible when `ramp_complete`):

**Summary alert:**
- Critical load found → red alert with load value
- All safe → green alert "No buckling in tested range"

**Iteration table (VDataTable):**
| Load (N) | Factor | Critical Load (kN) | u3 (mm) | Status |
|----------|--------|---------------------|---------|--------|

Buckled rows highlighted. Copy TSV button.

**Convergence chart** — base64 image from `_render_ramp_chart`.

## 6. Controller (`trame_app.py`)

```python
@ctrl.add("run_load_ramp")
def on_run_load_ramp():
    asyncio.ensure_future(run_load_ramp(state))
```

## Verification

1. Run with NLGEOM OFF, 3-step ramp (-500, -1000, -1500) — factors should scale ~linearly as F_ref/F
2. Run with NLGEOM ON, same steps — factors should deviate from linear scaling
3. Confirm progress bar and log update live during execution
4. Confirm buckled step is flagged red in the table
5. Confirm chart renders with critical-load marker
6. Confirm graceful handling of CalculiX convergence failure at one step
