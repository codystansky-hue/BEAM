import os
import numpy as np
import rhino3dm
import logging

log = logging.getLogger(__name__)


class _PolylineCurve:
    """Duck-type adapter wrapping a polyline point array to match the
    rhino3dm curve interface used by ProfileMesher.generate().

    Domain is arc-length parameterised: T0=0, T1=total curve length.
    PointAt(t) interpolates position linearly along that arc length.
    """

    class _Domain:
        def __init__(self, t1):
            self.T0 = 0.0
            self.T1 = t1

    class _Point:
        __slots__ = ("X", "Y", "Z")
        def __init__(self, x, y, z):
            self.X, self.Y, self.Z = x, y, z

    def __init__(self, pts):
        self._pts = np.asarray(pts, dtype=float)
        diffs = np.linalg.norm(np.diff(self._pts, axis=0), axis=1)
        self._cum = np.insert(np.cumsum(diffs), 0, 0.0)
        self.Domain = self._Domain(float(self._cum[-1]))

    def PointAt(self, t):
        x = float(np.interp(t, self._cum, self._pts[:, 0]))
        y = float(np.interp(t, self._cum, self._pts[:, 1]))
        z = float(np.interp(t, self._cum, self._pts[:, 2]))
        return self._Point(x, y, z)

class ProfileMesher:
    def __init__(self, filename, thickness=0.25, num_elements_thickness=2, element_size_along_curve=5.0, vtk_out_path=None):
        """
        Initialize the mathematically native python mesher for a 2D spine curve open section.
        """
        self.filename = filename
        self.thickness = thickness
        self.num_elements_thickness = num_elements_thickness
        self.element_size_along_curve = element_size_along_curve
        self.vtk_out_path = vtk_out_path
        self.nodes = None
        self.elements = None
        self.tangents = None
        
    def _read_dxf_curve(self):
        """Read a DXF file and return a _PolylineCurve adapter.

        Supports LWPOLYLINE, POLYLINE, and SPLINE entities (fit points then
        control points as fallback).  Unit scaling is read from $INSUNITS.
        """
        try:
            import ezdxf
        except ImportError:
            raise ImportError(
                "ezdxf is required for DXF support. Install it with: pip install ezdxf"
            )

        doc = ezdxf.readfile(self.filename)

        # DXF $INSUNITS → mm scale factor
        # https://help.autodesk.com/view/OARX/2024/ENU/?guid=GUID-A6565F32-3852-4E47-8F86-9D2B73B0B7E6
        insunits = doc.header.get("$INSUNITS", 4)
        unit_map = {
            1: 25.4,      # inches
            2: 304.8,     # feet
            4: 1.0,       # mm (default)
            5: 10.0,      # cm
            6: 1000.0,    # m
        }
        self.scale_to_mm = unit_map.get(insunits, 1.0)

        pts = None
        msp = doc.modelspace()
        for entity in msp:
            etype = entity.dxftype()
            if etype == "LWPOLYLINE":
                verts = list(entity.vertices())
                pts = np.array([[v[0], v[1], 0.0] for v in verts], dtype=float)
                break
            elif etype == "POLYLINE":
                verts = list(entity.vertices)
                pts = np.array(
                    [[v.dxf.location.x, v.dxf.location.y, v.dxf.location.z]
                     for v in verts],
                    dtype=float,
                )
                break
            elif etype == "SPLINE":
                raw = list(entity.fit_points) or list(entity.control_points)
                pts = np.array([[p[0], p[1], p[2]] for p in raw], dtype=float)
                break

        if pts is None or len(pts) < 2:
            raise ValueError(
                "No LWPOLYLINE, POLYLINE, or SPLINE entity found in the DXF file."
            )

        if self.scale_to_mm != 1.0:
            log.info("DXF units: scale factor %.4g → converting to mm", self.scale_to_mm)
            pts *= self.scale_to_mm
        else:
            log.info("DXF units: already mm, no scaling")

        return _PolylineCurve(pts)

    def _read_curve(self):
        """Read the spline file and extract the curve, dispatching by extension."""
        ext = os.path.splitext(self.filename)[1].lower()
        if ext == ".dxf":
            return self._read_dxf_curve()

        # --- Rhino .3dm path ---
        model = rhino3dm.File3dm.Read(self.filename)
        if not model:
            raise ValueError(f"Could not read {self.filename}")
            
        # Detect Unit System and set scale factor to Millimeters
        # rhino3dm.UnitSystem enum values (from rhino3dm source):
        #   0=None, 2=Millimeters, 3=Centimeters, 4=Meters, 5=Kilometers,
        #   8=Inches, 9=Feet
        unit_sys = int(model.Settings.ModelUnitSystem)
        unit_map = {
            2: 1.0,      # mm -> mm
            3: 10.0,     # cm -> mm
            4: 1000.0,   # m -> mm
            5: 1000000.0,# km -> mm
            8: 25.4,     # inch -> mm
            9: 304.8     # feet -> mm
        }
        self.scale_to_mm = unit_map.get(unit_sys, 1.0)
        
        curve = None
        # First, try to find a standalone curve
        for obj in model.Objects:
            if obj.Geometry.ObjectType == rhino3dm.ObjectType.Curve:
                curve = obj.Geometry
                break
                
        # Fallback: if user exported surface/Brep, try to grab its longest edge curve
        if not curve:
            for obj in model.Objects:
                if obj.Geometry.ObjectType == rhino3dm.ObjectType.Brep:
                    brep = obj.Geometry
                    if hasattr(brep, 'Edges') and len(brep.Edges) > 0:
                        edges = []
                        for i in range(len(brep.Edges)):
                            try:
                                edge_curve = brep.Edges[i].ToNurbsCurve()
                                edges.append(edge_curve)
                            except:
                                pass
                        
                        if edges:
                            def approx_len(c):
                                try:
                                    if hasattr(c, "GetLength"):
                                        return c.GetLength()
                                    bbox = c.GetBoundingBox()
                                    if bbox.IsValid:
                                        return bbox.Max.DistanceTo(bbox.Min)
                                except:
                                    pass
                                return 0
                                
                            curve = max(edges, key=approx_len)
                            break
                            
        if not curve:
            raise ValueError("No valid curve or surface edge found in the 3dm file.")
            
        return curve

    def generate(self):
        """Run the entire discretization & meshing workflow perfectly natively, returning dict."""
        log.info("Mesher: reading curve from %s", self.filename)
        curve = self._read_curve()
        
        # 1. Estimate Length and Discretize Parameter Space
        domain = curve.Domain
        
        # Dense evaluation to compute true arc-length parameterization
        dense_t = np.linspace(domain.T0, domain.T1, 2000)
        dense_pts = np.array([[pt.X, pt.Y, pt.Z] for pt in (curve.PointAt(t) for t in dense_t)])
        
        # Apply Unit Scaling to Millimeters (only if source is NOT already mm)
        if self.scale_to_mm != 1.0:
            log.info("Rhino units: scale factor %.4g → converting to mm", self.scale_to_mm)
            dense_pts *= self.scale_to_mm
        else:
            log.info("Rhino units: already mm, no scaling")
        
        # Calculate cumulative chord lengths
        chord_lengths = np.linalg.norm(np.diff(dense_pts, axis=0), axis=1)
        cum_length = np.insert(np.cumsum(chord_lengths), 0, 0.0)
        total_length = cum_length[-1]
        
        num_segments = max(2, int(total_length / self.element_size_along_curve))
        
        # Target uniform arc-lengths
        target_lengths = np.linspace(0, total_length, num_segments + 1)
        
        # Interpolate coordinates directly based on arc-length distance
        points = np.zeros((num_segments + 1, 3))
        for i in range(3):
            points[:, i] = np.interp(target_lengths, cum_length, dense_pts[:, i])
            
        num_pts = len(points)
        
        # 2. General 2D Plane Normal using SVD (works for any planar orientation)
        centered = points - np.mean(points, axis=0)
        try:
            _, s, vh = np.linalg.svd(centered)
            plane_normal = vh[2]
            # Fallback if perfectly straight line (1D)
            if s[1] < 1e-6:
                plane_normal = np.array([0., 0., 1.])
        except:
            plane_normal = np.array([0., 0., 1.])
            
        plane_normal = plane_normal / np.linalg.norm(plane_normal)
        
        # 3. Compute segments and mathematically perfect Miter normals at joints
        segments = np.diff(points, axis=0)
        seg_lengths = np.linalg.norm(segments, axis=1)
        seg_lengths[seg_lengths == 0] = 1.0 # Protect divide by zeros
        seg_dirs = segments / seg_lengths[:, np.newaxis]
        
        normals = np.zeros_like(points)
        for i in range(num_pts):
            if i == 0:
                n = np.cross(plane_normal, seg_dirs[0])
            elif i == num_pts - 1:
                n = np.cross(plane_normal, seg_dirs[-1])
            else:
                t1 = seg_dirs[i-1]
                t2 = seg_dirs[i]
                n1 = np.cross(plane_normal, t1)
                n2 = np.cross(plane_normal, t2)
                
                n_bisect = n1 + n2
                norm_n = np.linalg.norm(n_bisect)
                if norm_n > 1e-6:
                    n_bisect = n_bisect / norm_n
                    # Scale offset magnitude by inverse cos to ensure sharp miter corners perfectly track uniform thickness
                    proj = np.dot(n_bisect, n1)
                    if proj > 1e-3:
                        n_bisect = n_bisect / proj
                    n = n_bisect
                else:
                    n = n1
            normals[i] = n
            
        # Ensure normals point INWARD (towards centroid of the open curve)
        centroid = np.mean(points, axis=0)
        vec_from_centroid = points - centroid
        if np.mean(np.sum(normals * vec_from_centroid, axis=1)) > 0:
            normals = -normals
            
        # 4. Generate beautifully structured Quad Nodes via pure mathematical normal extrusion
        # Generate the FIRST physical half of the shell (Offset inwards perfectly flush with 0)
        n_layers = self.num_elements_thickness
        fractions = np.linspace(0.0, 1.0, n_layers + 1)
        
        half_nodes = np.zeros((num_pts, n_layers + 1, 3))
        for idx_pt in range(num_pts):
            pt = points[idx_pt]
            n = normals[idx_pt]
            for idx_l, frac in enumerate(fractions):
                half_nodes[idx_pt, idx_l] = pt + n * (frac * self.thickness)
                
        half_nodes_flat = half_nodes.reshape(-1, 3)
        num_half_nodes = len(half_nodes_flat)
        
        # 5. Connect Elements & Assign Local Tangents for Material Engine mapping
        half_elements = []
        half_tangents = []
        for i in range(num_pts - 1):
            t_seg = seg_dirs[i]
            for j in range(n_layers):
                n1 = i * (n_layers + 1) + j
                n2 = (i + 1) * (n_layers + 1) + j
                n3 = (i + 1) * (n_layers + 1) + (j + 1)
                n4 = i * (n_layers + 1) + (j + 1)
                
                half_elements.append([n1, n2, n3, n4])
                half_tangents.append(t_seg)
                
        # 6. MIRROR PROCESS: Mirror the entire top half downward across the Trailing Edge's inner face Y-axis
        # The trailing edge is the most extreme point on the curve (usually max X for airfoils/booms)
        inner_nodes = half_nodes[:, -1, :] # The nodes at exactly 1.0 thickness offset
        trailing_edge_idx = np.argmax(inner_nodes[:, 0])
        y_mirror = inner_nodes[trailing_edge_idx, 1] # Find the flat Y-coordinate of the trailing edge
        
        # Mirror all coordinates in the top half exactly across the y_mirror line
        bottom_half_nodes = np.copy(half_nodes_flat)
        bottom_half_nodes[:, 1] = 2.0 * y_mirror - bottom_half_nodes[:, 1]
        
        raw_nodes = np.vstack((half_nodes_flat, bottom_half_nodes))
        
        # Merge coincident nodes to stitch the mesh halves together
        # We use a simple 1 micron precision rounding to guarantee the overlapping nodes at the flat trailing edge snap together
        rounded_nodes = np.round(raw_nodes, decimals=3)
        rounded_nodes[np.abs(rounded_nodes) < 1e-6] = 0.0
        
        unique_nodes, inverse_indices = np.unique(rounded_nodes, axis=0, return_inverse=True)
        
        # The unique nodes are our final node list
        self.nodes = raw_nodes[np.unique(inverse_indices, return_index=True)[1]]
        
        # Duplicate the elements, but offset their node connectivity indices by the number of nodes in the first half
        bottom_elements = np.array(half_elements) + num_half_nodes
        
        # Note: Since the geometry was mirrored across the Y axis, we MUST reverse the winding order of the bottom
        # elements so their cell normals continue to face "outwards/inwards" consistently instead of flipping inside-out.
        bottom_elements_reversed = bottom_elements[:, [0, 3, 2, 1]]
        
        raw_elements = np.vstack((half_elements, bottom_elements_reversed))
        
        # Remap all element connectivity to the new merged unique node indices
        self.elements = inverse_indices[raw_elements]
        
        # Duplicate the tangents
        self.tangents = np.vstack((half_tangents, half_tangents))
        
        log.info(
            "Mesher: done — %d nodes, %d elements (thickness=%.3f mm, elem_size=%.1f mm, n_layers=%d)",
            len(self.nodes), len(self.elements),
            self.thickness, self.element_size_along_curve, self.num_elements_thickness,
        )

        # Write to VTK natively
        if self.vtk_out_path:
            self._write_vtk()
            log.info("Mesher: VTK written to %s", self.vtk_out_path)

        return {
            'nodes': self.nodes,
            'elements': self.elements,
            'tangents': self.tangents
        }
        
    def _write_vtk(self):
        """Writes the natively generated mesh to a legacy ASCII Paraview VTK file."""
        num_nodes = len(self.nodes)
        num_elements = len(self.elements)
        
        with open(self.vtk_out_path, 'w') as f:
            f.write("# vtk DataFile Version 3.0\n")
            f.write("ProfileMesher Output\n")
            f.write("ASCII\n")
            f.write("DATASET UNSTRUCTURED_GRID\n")
            f.write(f"POINTS {num_nodes} float\n")
            for pt in self.nodes:
                # Convert mm → m to match all other VTK outputs
                f.write(f"{pt[0]/1000.0:.6f} {pt[1]/1000.0:.6f} {pt[2]/1000.0:.6f}\n")
                
            f.write(f"\nCELLS {num_elements} {num_elements * 5}\n")
            for elem in self.elements:
                f.write(f"4 {elem[0]} {elem[1]} {elem[2]} {elem[3]}\n")
                
            f.write(f"\nCELL_TYPES {num_elements}\n")
            for _ in range(num_elements):
                f.write("9\n") # 9 is VTK_QUAD
