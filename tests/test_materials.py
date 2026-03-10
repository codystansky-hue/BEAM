import pytest
import numpy as np
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from materials import CompositeMaterial, Layup, assign_properties_to_mesh

def test_layup_thickness():
    """Test that Layup correctly calculates total thickness from its plies."""
    # Create a mock material
    mat = CompositeMaterial(
        E11=140e9, 
        E22=10e9, 
        G12=5e9, 
        nu12=0.3, 
        density=1500.0, 
        ply_thickness=0.125
    )
    
    # Create 4 plies of the material at various angles
    materials = [mat, mat, mat, mat]
    angles = [0, 45, -45, 90]
    
    layup = Layup(materials, angles)
    
    # 4 * 0.125 = 0.5
    assert layup.total_thickness() == pytest.approx(0.5)
    
def test_assign_properties_to_mesh():
    """Test that global ply orientation is correctly calculated from local element tangent."""
    
    # Mock a mesh dictionary.
    # We only need 'elements' and 'tangents' for assign_properties_to_mesh.
    # Element 1 tangent: horizontal, so angle = 0 deg
    # Element 2 tangent: diagonal, dx=1, dy=1, so angle = 45 deg
    tangent_0_deg = np.array([1.0, 0.0, 0.0])
    tangent_45_deg = np.array([1.0, 1.0, 0.0])
    
    mesh_data = {
        'elements': [[0, 1, 2, 3], [4, 5, 6, 7]],
        'tangents': np.array([tangent_0_deg, tangent_45_deg])
    }
    
    # Create a single ply layup at 45 degrees
    mat = CompositeMaterial(
        E11=140e9, 
        E22=10e9, 
        G12=5e9, 
        nu12=0.3, 
        density=1500.0, 
        ply_thickness=0.25
    )
    
    layup = Layup(materials=[mat], angles=[45.0])
    
    # Run the function
    result = assign_properties_to_mesh(mesh_data, layup)
    
    props = result['element_properties']
    
    assert len(props) == 2
    
    # Element 1: local 0 + ply 45 = 45 global
    assert props[0]['layup'][0]['global_angle'] == pytest.approx(45.0)
    
    # Element 2: local 45 + ply 45 = 90 global
    assert props[1]['layup'][0]['global_angle'] == pytest.approx(90.0)
