import os
import sys
import numpy as np
import asyncio
from unittest.mock import MagicMock, patch

# Add root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock problematic imports
sys.modules.setdefault("rhino3dm", MagicMock())
sys.modules.setdefault("gmsh", MagicMock())
sys.modules.setdefault("sgio", MagicMock())

from trame_app.engine import (
    run_stage_1_mesh,
    run_stage_2_global,
    run_stage_3_local,
    _INTERNAL_CACHE
)

class MockState(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    def __getattr__(self, key):
        return self[key]
    def __setattr__(self, key, value):
        self[key] = value
    def flush(self):
        pass

def test_backend_stages():
    state = MockState(
        geo_file_name="test.3dm",
        span_length=13.0,
        elem_size=2.0,
        num_elem_thick=2,
        swiftcomp_path="SwiftComp.exe",
        gxbeam_path="julia",
        ccx_path="ccx_MT.exe",
        bc_type="Fixed-Free (Cantilever)",
        ccx_root_dofs=[1, 2, 3, 4, 5, 6],
        ccx_tip_dofs=[],
        snippet_length=250.0,
        snippet_elems_z=25,
        snippet_compressive_load=-1000.0,
        include_thermal=False,
        nlgeom_thermal=False,
        temp_max_x=102.51,
        temp_min_x=-31.85,
        temp_ref=20.0,
        layup_plies=[{"lamina_name": "TestLamina", "angle": 0.0}],
        laminae=[{
            "name": "TestLamina",
            "E11": 140e9, "E22": 10e9, "G12": 5e9, "nu12": 0.3,
            "density": 1600.0, "thickness_mm": 0.15
        }],
        pipeline_log=[],
        has_mesh=False,
        result_runs_dir=None,
        result_k_mm=None,
        result_k_SI=None,
        result_P_cr_22=None,
        result_P_cr_33=None,
        result_deflections=None,
        result_ccx_factor=None,
        mesh_vtk_path=None,
        beam_vtk_path=None,
        buckling_vtk_path=None
    )

    print("--- Testing Stage 1 (Mesh) ---")
    with patch("trame_app.engine.ProfileMesher") as MockMesher, \
         patch("trame_app.engine.assign_properties_to_mesh") as MockAssign:
        
        # Setup mocks
        MockMesher.return_value.generate.return_value = {
            "nodes": np.random.rand(10, 3),
            "elements": [[0,1,2,3]],
            "tangents": [[1,0,0]]
        }
        MockAssign.return_value = {
            "element_properties": [{"id": 1}],
            "num_elements": 1
        }
        
        success = run_stage_1_mesh(state)
        print(f"Stage 1 Success: {success}")
        print(f"Cache keys: {_INTERNAL_CACHE.keys()}")
        assert _INTERNAL_CACHE["mesh"] is not None
        assert _INTERNAL_CACHE["props"] is not None
        # In real trame, update_state is called via call_soon_threadsafe
        # For this test, we can check if it returned True

    print("\n--- Testing Stage 2 (Global) ---")
    with patch("trame_app.engine.SwiftCompSolver") as MockSwift, \
         patch("trame_app.engine.GXBeamSolver") as MockGX:
        
        MockSwift.return_value.parse_results.return_value = np.eye(6)
        MockGX.return_value.parse_results.return_value = (np.zeros(6), "path")
        
        success = run_stage_2_global(state)
        print(f"Stage 2 Success: {success}")

    print("\n--- Testing Stage 3 (Local) ---")
    with patch("trame_app.engine.CalculiXSolver") as MockCCX:
        MockCCX.return_value.execute.return_value = True
        MockCCX.return_value.parse_results.return_value = 1.5
        
        success = run_stage_3_local(state)
        print(f"Stage 3 Success: {success}")

if __name__ == "__main__":
    # Simulate an event loop for call_soon_threadsafe
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        test_backend_stages()
        print("\nIntegration test logic passed!")
    except Exception as e:
        print(f"\nIntegration test FAILED: {e}")
        import traceback
        traceback.print_exc()
