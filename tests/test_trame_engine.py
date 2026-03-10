"""Tests for trame_app/engine.py — pipeline runner with mocked solvers."""

import os
import sys
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Mock rhino3dm before importing engine (which imports mesher -> rhino3dm)
sys.modules.setdefault("rhino3dm", MagicMock())
sys.modules.setdefault("gmsh", MagicMock())
sys.modules.setdefault("sgio", MagicMock())

from trame_app.engine import (
    _snapshot_state,
    _build_layup,
    _compute_target_thickness,
    run_stage_1_mesh,
    run_stage_2_global,
    run_stage_3_local,
)


def _make_snap():
    """Create a minimal state snapshot for testing."""
    return {
        "geo_file_name": "test.3dm",
        "span_length": 13.0,
        "elem_size": 2.0,
        "num_elem_thick": 2,
        "swiftcomp_path": "SwiftComp.exe",
        "gxbeam_path": "julia",
        "ccx_path": "ccx_MT.exe",
        "bc_type": "Fixed-Free (Cantilever)",
        "ccx_root_dofs": [1, 2, 3, 4, 5, 6],
        "ccx_tip_dofs": [],
        "snippet_length": 250.0,
        "snippet_elems_z": 25,
        "snippet_compressive_load": -1000.0,
        "include_thermal": False,
        "nlgeom_thermal": False,
        "temp_max_x": 102.51,
        "temp_min_x": -31.85,
        "temp_ref": 20.0,
        "layup_plies": [
            {"lamina_name": "TestLamina", "angle": 0.0},
        ],
        "laminae": [
            {
                "name": "TestLamina",
                "E11": 140e9,
                "E22": 10e9,
                "G12": 5e9,
                "nu12": 0.3,
                "density": 1600.0,
                "thickness_mm": 0.15,
                "cte11": 0.0,
                "cte22": 0.0,
            }
        ],
    }


class TestSnapshotState:
    def test_copies_all_keys(self):
        class MockState:
            def __getitem__(self, key):
                return getattr(self, key)
            geo_file_name = "test.3dm"
            span_length = 13.0
            elem_size = 2.0
            num_elem_thick = 2
            swiftcomp_path = "SwiftComp.exe"
            gxbeam_path = "julia"
            ccx_path = "ccx_MT.exe"
            bc_type = "Fixed-Free (Cantilever)"
            ccx_root_dofs = [1, 2, 3]
            ccx_tip_dofs = []
            snippet_length = 250.0
            snippet_elems_z = 25
            snippet_compressive_load = -1000.0
            include_thermal = False
            nlgeom_thermal = False
            temp_max_x = 100.0
            temp_min_x = -30.0
            temp_ref = 20.0
            layup_plies = [{"lamina_name": "X", "angle": 0}]
            laminae = [{"name": "X"}]

        snap = _snapshot_state(MockState())
        assert snap["geo_file_name"] == "test.3dm"
        # Verify lists are copies, not references
        assert snap["ccx_root_dofs"] is not MockState.ccx_root_dofs


class TestBuildLayup:
    def test_builds_from_snap(self):
        snap = _make_snap()
        layup = _build_layup(snap)
        assert len(layup.materials) == 1
        assert layup.angles[0] == 0.0

    def test_skips_missing_lamina(self):
        snap = _make_snap()
        snap["layup_plies"] = [{"lamina_name": "NonExistent", "angle": 45}]
        layup = _build_layup(snap)
        assert len(layup.materials) == 0


class TestComputeTargetThickness:
    def test_computes_from_plies(self):
        snap = _make_snap()
        t = _compute_target_thickness(snap)
        assert abs(t - 0.15) < 1e-6

    def test_fallback_on_empty(self):
        snap = _make_snap()
        snap["layup_plies"] = []
        t = _compute_target_thickness(snap)
        assert t == 0.25


class DictMock(dict):
    """A dict that also supports attribute access."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)
    def __setattr__(self, name, value):
        self[name] = value

class TestRunStages:
    @patch("trame_app.engine.ProfileMesher")
    @patch("os.path.exists")
    def test_mesh_failure_returns_false(self, MockExists, MockMesher):
        MockExists.return_value = True
        state = DictMock()
        state.num_elem_thick = 2
        state.elem_size = 2.0
        state.layup_plies = []
        state.laminae = []
        state.pipeline_log = []
        state.geo_file_name = "test.3dm"
        
        instance = MockMesher.return_value
        instance.generate.side_effect = RuntimeError("No .3dm file")

        success = run_stage_1_mesh(state)
        assert success is False
        assert any("FAIL" in line for line in state.pipeline_log)

    @patch("trame_app.engine.CalculiXSolver")
    @patch("trame_app.engine.GXBeamSolver")
    @patch("trame_app.engine.SwiftCompSolver")
    @patch("trame_app.engine.assign_properties_to_mesh")
    @patch("trame_app.engine.ProfileMesher")
    @patch("os.path.exists")
    def test_full_pipeline_stages(
        self, MockExists, MockMesher, MockAssign, MockSwift, MockGX, MockCCX
    ):
        MockExists.return_value = True
        
        # Setup mock state
        state = DictMock()
        state.geo_file_name = "test.3dm"
        state.span_length = 13.0
        state.elem_size = 2.0
        state.num_elem_thick = 2
        state.swiftcomp_path = "SwiftComp.exe"
        state.gxbeam_path = "julia"
        state.ccx_path = "ccx_MT.exe"
        state.bc_type = "Fixed-Free (Cantilever)"
        state.ccx_root_dofs = [1, 2, 3, 4, 5, 6]
        state.ccx_tip_dofs = []
        state.snippet_length = 250.0
        state.snippet_elems_z = 25
        state.snippet_compressive_load = -1000.0
        state.include_thermal = False
        state.nlgeom_thermal = False
        state.temp_max_x = 102.51
        state.temp_min_x = -31.85
        state.temp_ref = 20.0
        state.layup_plies = [{"lamina_name": "TestLamina", "angle": 0.0}]
        state.laminae = [{
            "name": "TestLamina", "E11": 140e9, "E22": 10e9, "G12": 5e9, "nu12": 0.3,
            "density": 1600.0, "thickness_mm": 0.15, "cte11": 0.0, "cte22": 0.0,
        }]
        state.pipeline_log = []
        state.has_mesh = False

        # Mock mesher
        mock_nodes = np.array([
            [0, 0, 0], [10, 0, 0], [10, 1, 0], [0, 1, 0],
        ], dtype=float)
        mock_elems = np.array([[0, 1, 2, 3]])
        mock_tangents = np.array([[1, 0, 0]])
        MockMesher.return_value.generate.return_value = {
            "nodes": mock_nodes,
            "elements": mock_elems,
            "tangents": mock_tangents,
        }

        # Mock material mapping
        MockAssign.return_value = {
            "element_properties": [
                {
                    "element_id": 1,
                    "nodes": [0, 1, 2, 3],
                    "layup": [
                        {
                            "material": MagicMock(E11=140e9, cte11=0.0),
                            "thickness": 0.15,
                            "global_angle": 0.0,
                        }
                    ],
                }
            ],
            "total_thickness": 0.15,
            "num_elements": 1,
        }

        # Mock SwiftComp
        MockSwift.return_value.parse_results.return_value = np.eye(6) * 1e6

        # Mock GXBeam
        MockGX.return_value.parse_results.return_value = (
            np.array([0.0, 0.0, -0.01, 0.0, 0.001, 0.0]),
            "beam.vtk",
        )

        # Mock CalculiX
        MockCCX.return_value.execute.return_value = True
        MockCCX.return_value.parse_results.return_value = 2.5

        # Execute stages
        assert run_stage_1_mesh(state) is True
        assert state.has_mesh is True
        
        assert run_stage_2_global(state) is True
        assert state.result_k_mm is not None
        
        assert run_stage_3_local(state) is True
        assert state.result_ccx_factor == 2.5


