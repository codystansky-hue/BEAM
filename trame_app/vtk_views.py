"""PyVista plotter management and VTK view switching."""

import pyvista as pv
from trame_vtk.modules.vtk.serializers.cache import PROP_CACHE

# Mesh cache: avoids re-reading the same VTK file on every warp factor change.
# Key = vtk_path, Value = pv.DataSet. Call invalidate_mesh_cache() after a new solve.
_mesh_cache: dict = {}


def clear_serializer_cache():
    """Clear trame-vtk's property delta cache.

    The serializer caches property values (scalarRange, valueRange, etc.) and
    only sends deltas to vtk.js.  After a scene rebuild (plotter.clear +
    add_mesh) the old cached values no longer correspond to the new actors,
    so the client receives incomplete updates with mismatched scalar ranges.
    Clearing the cache forces a full re-serialization on the next view.update().
    """
    PROP_CACHE.clear()


def invalidate_mesh_cache(*paths):
    """Remove specific paths from the cache (or clear all if no args given)."""
    if paths:
        for p in paths:
            _mesh_cache.pop(p, None)
    else:
        _mesh_cache.clear()


def create_plotter():
    """Create an off-screen PyVista plotter for trame embedding."""
    plotter = pv.Plotter(off_screen=True)
    plotter.set_background("#1e1e1e") # Dark grey for better contrast
    plotter.render() # Establish renderer/interactor immediately
    return plotter


def show_mesh_preview(plotter, vtk_path, show_edges=True):
    """Load a 2D cross-section mesh VTK and display it."""
    plotter.clear()
    plotter.enable_parallel_projection() # 2D look
    mesh = pv.read(vtk_path)
    plotter.add_mesh(
        mesh,
        show_edges=show_edges,
        color="cyan",
        edge_color="white",
        line_width=1,
        point_size=5,
        render_points_as_spheres=True,
        show_scalar_bar=False
    )

    plotter.view_xy()
    plotter.reset_camera(bounds=mesh.bounds)


def _scalar_clim(mesh, scalar_name):
    """Return a stable (vmin, vmax) for scalar_name from the unwarped mesh.

    Falls back to (0, 1) if the range is degenerate (all-zero eigenmodes, etc.)
    so the colormap is never collapsed to a single value.
    """
    arr = mesh.point_data.get(scalar_name)
    if arr is None:
        arr = mesh.cell_data.get(scalar_name)  # stress arrays may be cell-centred
    if arr is None:
        return (0.0, 1.0)
    vmin, vmax = float(arr.min()), float(arr.max())
    if vmax <= vmin or (vmax - vmin) < 1e-30 * max(abs(vmin), abs(vmax), 1.0):
        # Degenerate range — expand symmetrically so the bar is visible
        centre = 0.5 * (vmin + vmax)
        half = max(abs(centre) * 0.01, 1e-10)
        return (centre - half, centre + half)
    return (vmin, vmax)


def _force_scalar_range(plotter, vmin, vmax):
    """Pin vmin/vmax on every scalar-displaying mapper+LUT.

    Must be called BEFORE plotter.render() so that VTK's pipeline does not
    auto-adjust ranges, and BEFORE view.update() so that the serializer reads
    the correct values.
    """
    for actor in plotter.actors.values():
        mapper = actor.GetMapper()
        if mapper is None or not mapper.GetScalarVisibility():
            continue
        mapper.SetScalarRange(vmin, vmax)
        # Tell mapper to use its OWN scalar range, not auto-derive from LUT
        mapper.SetUseLookupTableScalarRange(False)
        lut = mapper.GetLookupTable()
        if lut is not None:
            lut.SetRange(vmin, vmax)


def _read_cached(vtk_path):
    """Return cached mesh for vtk_path, reading from disk only on first call."""
    if vtk_path not in _mesh_cache:
        _mesh_cache[vtk_path] = pv.read(vtk_path)
    return _mesh_cache[vtk_path]


def show_deformed_beam(plotter, vtk_path, warp_factor=1.0, show_edges=True,
                       show_undeformed=True, reset_camera=True):
    """Load a deformed beam VTK and display with displacement coloring."""
    plotter.clear()
    plotter.disable_parallel_projection()
    mesh = _read_cached(vtk_path)

    if "displacement" in mesh.point_data:
        # Pin color range to the unwarped scalar data so it never jumps
        clim = _scalar_clim(mesh, "displacement_magnitude")
        warped = mesh.warp_by_vector("displacement", factor=float(warp_factor))
        plotter.add_mesh(
            warped,
            scalars="displacement_magnitude",
            cmap="viridis",
            clim=clim,
            show_edges=show_edges,
            edge_color="black",
            line_width=0.5,
            scalar_bar_args={"title": "Displacement (m)", "color": "white"},
        )
        if show_undeformed:
            plotter.add_mesh(
                mesh,
                style="wireframe",
                color="white",
                opacity=0.15,
                line_width=0.5,
                show_scalar_bar=False,
            )
        _force_scalar_range(plotter, *clim)
        plotter.render()
        plotter.view_xz()
        if reset_camera:
            plotter.reset_camera(bounds=mesh.bounds)
    else:
        plotter.add_mesh(mesh, show_edges=show_edges, color="cyan")
        plotter.view_xz()
        if reset_camera:
            plotter.reset_camera(bounds=mesh.bounds)


def show_buckling_mode(plotter, vtk_path, warp_factor=1.0,
                       scalar_name="displacement_magnitude", show_edges=True,
                       show_undeformed=True, reset_camera=True):
    """Load a buckling mode VTK and display with mode shape coloring."""
    plotter.clear()
    plotter.disable_parallel_projection()
    mesh = _read_cached(vtk_path)

    if scalar_name not in mesh.point_data and scalar_name not in mesh.cell_data:
        scalar_name = "displacement_magnitude"

    if "displacement" in mesh.point_data:
        # Pin color range to the unwarped scalar data — stable across all warp factors
        clim = _scalar_clim(mesh, scalar_name)
        warped = mesh.warp_by_vector("displacement", factor=float(warp_factor))
        plotter.add_mesh(
            warped,
            scalars=scalar_name,
            cmap="turbo",
            clim=clim,
            show_edges=show_edges,
            edge_color="black",
            line_width=0.5,
            scalar_bar_args={"title": scalar_name, "color": "white"},
        )
        if show_undeformed:
            plotter.add_mesh(
                mesh,
                style="wireframe",
                color="white",
                opacity=0.15,
                line_width=0.5,
                show_scalar_bar=False,
            )
        _force_scalar_range(plotter, *clim)
        plotter.render()
        if reset_camera:
            plotter.reset_camera(bounds=mesh.bounds)
    else:
        plotter.add_mesh(mesh, show_edges=show_edges, color="cyan")
        plotter.view_xz()
        if reset_camera:
            plotter.reset_camera(bounds=mesh.bounds)


def show_snippet_preview(plotter, vtk_path, show_edges=True):
    """Load a 3D snippet mesh VTK and display it (no results, just geometry)."""
    plotter.clear()
    plotter.disable_parallel_projection()  # 3D look
    mesh = pv.read(vtk_path)
    plotter.add_mesh(
        mesh,
        show_edges=show_edges,
        color="cyan",
        edge_color="white",
        line_width=0.5,
        opacity=0.85,
        show_scalar_bar=False,
    )

    plotter.view_xz()
    plotter.reset_camera(bounds=mesh.bounds)


def autoscale_data_range(plotter):
    """Reset scalar bar color range to the full min/max of the active scalar data."""
    for actor in plotter.actors.values():
        mapper = actor.GetMapper()
        if mapper is None:
            continue
        mapper.Update()
        ds = mapper.GetInputDataObject(0, 0)
        if ds is None:
            continue
        pd = ds.GetPointData()
        cd = ds.GetCellData()
        arr = pd.GetScalars() or cd.GetScalars()
        if arr is None:
            name = mapper.GetArrayName()
            if name:
                arr = pd.GetArray(name) or cd.GetArray(name)
        if arr is None:
            continue
        rng = arr.GetRange()
        if rng[0] < rng[1]:
            mapper.SetScalarRange(rng[0], rng[1])
            mapper.SetUseLookupTableScalarRange(False)
            lut = mapper.GetLookupTable()
            if lut is not None:
                lut.SetRange(rng[0], rng[1])
    clear_serializer_cache()
    plotter.render()
