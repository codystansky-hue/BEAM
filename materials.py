from dataclasses import dataclass
import numpy as np

@dataclass
class CompositeMaterial:
    """Engineering constants for a single orthotropic composite lamina."""
    E11: float
    E22: float
    G12: float
    nu12: float
    density: float
    ply_thickness: float
    cte11: float = 0.0
    cte22: float = 0.0
    
class Layup:
    def __init__(self, materials, angles):
        """
        materials: List of CompositeMaterial for each ply
        angles: List of ply angles (in degrees)
        """
        if len(materials) != len(angles):
            raise ValueError("Number of materials must match number of angles.")
        
        self.materials = materials
        self.angles = angles
        
    def total_thickness(self):
        return sum(m.ply_thickness for m in self.materials)


def assign_properties_to_mesh(mesh_data, layup):
    """
    Calculate global material orientation angle for each element.
    Returns element property definitions mapping elements to layup orientations.
    """
    elements = mesh_data['elements']
    tangents = mesh_data['tangents']
    
    properties = []
    
    # Process each element in the mesh
    for i, (element, tangent) in enumerate(zip(elements, tangents)):
        
        # Calculate the local curve tangency angle relative to global X
        # tangent is assumed to be a [dx, dy, dz] vector
        dx, dy = tangent[0], tangent[1]
        local_angle_rad = np.arctan2(dy, dx)
        local_angle_deg = np.degrees(local_angle_rad)
        
        element_layup = []
        # Calculate effective global angle for every ply in the element
        for material, ply_angle in zip(layup.materials, layup.angles):
            
            # The global orientation is the local spine tangent plus the user's ply angle
            global_angle = local_angle_deg + ply_angle
            
            element_layup.append({
                'material': material,
                'thickness': material.ply_thickness,
                'global_angle': global_angle
            })
            
        properties.append({
            'element_id': i + 1,  # 1-indexed
            'nodes': element,
            'layup': element_layup
        })
        
    return {
        'element_properties': properties,
        'total_thickness': layup.total_thickness(),
        'num_elements': len(elements)
    }
