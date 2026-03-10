using Pkg
Pkg.activate(".")
if !haskey(Pkg.dependencies(), "GXBeam") || !haskey(Pkg.dependencies(), "JSON")
    Pkg.add("GXBeam")
    Pkg.add("JSON")
end

using GXBeam
using JSON
using LinearAlgebra

function write_vtk_beam(vtk_path, points_undeformed, points_deformed, displacements, rotations)
    """Write a VTK legacy ASCII polyline for the deformed beam."""
    n = length(points_deformed)
    open(vtk_path, "w") do f
        write(f, "# vtk DataFile Version 3.0\n")
        write(f, "GXBeam Deformed Beam\n")
        write(f, "ASCII\n")
        write(f, "DATASET POLYDATA\n")

        # Write deformed points
        write(f, "POINTS $n float\n")
        for p in points_deformed
            write(f, "$(p[1]) $(p[2]) $(p[3])\n")
        end

        # Single polyline connecting all points
        write(f, "\nLINES 1 $(n + 1)\n")
        write(f, "$n")
        for i in 0:(n-1)
            write(f, " $i")
        end
        write(f, "\n")

        # Point data
        write(f, "\nPOINT_DATA $n\n")

        # Displacement magnitude scalar
        write(f, "SCALARS displacement_magnitude float 1\n")
        write(f, "LOOKUP_TABLE default\n")
        for d in displacements
            mag = sqrt(d[1]^2 + d[2]^2 + d[3]^2)
            write(f, "$mag\n")
        end

        # Displacement vector
        write(f, "VECTORS displacement float\n")
        for d in displacements
            write(f, "$(d[1]) $(d[2]) $(d[3])\n")
        end

        # Rotation vector
        write(f, "VECTORS rotation float\n")
        for r in rotations
            write(f, "$(r[1]) $(r[2]) $(r[3])\n")
        end
    end
end

function main()
    if length(ARGS) < 2
        println("Usage: julia gxbeam_solver.jl <input_json> <output_json>")
        exit(1)
    end

    input_file = ARGS[1]
    output_file = ARGS[2]

    # Read input data
    input_data = JSON.parsefile(input_file)
    k_matrix = convert(Matrix{Float64}, hcat(input_data["stiffness_matrix"]...))
    L = convert(Float64, input_data["span"])
    tip_load = convert(Vector{Float64}, input_data["tip_load"])
    nelem = get(input_data, "nelem", 20)

    # Distributed thermal moments (per unit length, uniform along span)
    dist_moment = get(input_data, "distributed_moment", [0.0, 0.0, 0.0])
    dm_x = convert(Float64, dist_moment[1])
    dm_y = convert(Float64, dist_moment[2])
    dm_z = convert(Float64, dist_moment[3])
    has_dist = (abs(dm_x) + abs(dm_y) + abs(dm_z)) > 0.0

    # Distributed axial force (per unit length, uniform along span)
    dist_force_x = convert(Float64, get(input_data, "distributed_force_x", 0.0))

    # Discretize beam into nelem elements with nelem+1 equally-spaced points
    points = [[i * L / nelem, 0.0, 0.0] for i in 0:nelem]
    start_idx = collect(1:nelem)
    stop_idx = collect(2:nelem+1)

    # All elements share the same stiffness matrix
    stiffness_list = fill(k_matrix, nelem)

    # Create the assembly
    assembly = Assembly(points, start_idx, stop_idx, stiffness=stiffness_list)

    # Read boundary condition type (default: cantilever)
    bc_type = get(input_data, "bc_type", "cantilever")

    # Boundary conditions: configure based on bc_type.
    #
    # For non-cantilever cases the axial (Fx) load is applied at the tip node which
    # is a ROLLER support — transverse DOFs fixed, axial DOF free.  This is the
    # physically correct simply-supported model and avoids the mechanically
    # inconsistent situation of constraining ux at both ends while also applying
    # an interior axial force.
    if bc_type == "cantilever"
        # Root fully clamped, tip free with applied loads
        prescribed_conditions = Dict(
            1 => PrescribedConditions(ux=0, uy=0, uz=0, theta_x=0, theta_y=0, theta_z=0),
            nelem + 1 => PrescribedConditions(
                Fx=tip_load[1], Fy=tip_load[2], Fz=tip_load[3],
                Mx=tip_load[4], My=tip_load[5], Mz=tip_load[6]
            )
        )
    elseif bc_type == "pinned-pinned"
        # Root: full pin + suppress torsional rigid-body mode (theta_x=0).
        # Tip: roller — uy=0, uz=0 as displacement BCs; ux is free (axial roller).
        # IMPORTANT: do NOT prescribe Fy/Fz at the tip — those DOFs are already
        # constrained by uy=0/uz=0.  Prescribing both displacement and force for the
        # same DOF causes a singular stiffness matrix in GXBeam.
        # Axial load (Fx) and tip moments act on the free DOFs only.
        prescribed_conditions = Dict(
            1 => PrescribedConditions(ux=0, uy=0, uz=0, theta_x=0),
            nelem + 1 => PrescribedConditions(
                uy=0, uz=0,
                Fx=tip_load[1],
                Mx=tip_load[4], My=tip_load[5], Mz=tip_load[6]
            )
        )
    elseif bc_type == "fixed-pinned"
        # Root: clamped.  Tip: roller (uy=0, uz=0) + axial load on free ux DOF.
        # Again, no Fy/Fz at tip to avoid over-specification.
        prescribed_conditions = Dict(
            1 => PrescribedConditions(ux=0, uy=0, uz=0, theta_x=0, theta_y=0, theta_z=0),
            nelem + 1 => PrescribedConditions(
                uy=0, uz=0,
                Fx=tip_load[1],
                Mx=tip_load[4], My=tip_load[5], Mz=tip_load[6]
            )
        )
    elseif bc_type == "fixed-fixed"
        # Root: clamped.  Tip: fully fixed except axial (ux free, Fx applied).
        # uy=0, uz=0 and theta_x/y/z=0 are ALL displacement BCs at the tip.
        # Do NOT also prescribe Fy, Fz, Mx, My, Mz at the tip — those DOFs are
        # already constrained, so prescribing their forces/moments would cause
        # a singular stiffness matrix.  Only Fx acts on the free ux DOF.
        prescribed_conditions = Dict(
            1 => PrescribedConditions(ux=0, uy=0, uz=0, theta_x=0, theta_y=0, theta_z=0),
            nelem + 1 => PrescribedConditions(
                uy=0, uz=0, theta_x=0, theta_y=0, theta_z=0,
                Fx=tip_load[1]
            )
        )
    else
        error("Unknown bc_type: $bc_type")
    end

    # Build distributed loads dict (thermal moments + axial force, uniform on all elements)
    distributed_loads = Dict{Int, DistributedLoads{Float64}}()
    if has_dist || abs(dist_force_x) > 0.0
        for ielem in 1:nelem
            distributed_loads[ielem] = DistributedLoads(assembly, ielem;
                fx = (s) -> dist_force_x,
                mx = (s) -> dm_x,
                my = (s) -> dm_y,
                mz = (s) -> dm_z,
            )
        end
    end

    # Perform static analysis — try nonlinear first, fall back to linear.
    # Non-cantilever BCs with distributed loads can fail Newton-Raphson when
    # rotational DOFs are unconstrained; the linear solve always succeeds.
    system, state, converged = static_analysis(assembly;
        prescribed_conditions = prescribed_conditions,
        distributed_loads = distributed_loads,
    )

    if !converged
        println("Nonlinear solve did not converge — retrying with linear=true")
        system, state, converged = static_analysis(assembly;
            prescribed_conditions = prescribed_conditions,
            distributed_loads = distributed_loads,
            linear = true,
        )
    end

    if !converged
        println("GXBeam static analysis did not converge (both nonlinear and linear).")
        exit(1)
    end

    # Extract displacements and rotations at every point
    n_points = nelem + 1
    all_u = [state.points[i].u for i in 1:n_points]
    all_theta = [state.points[i].theta for i in 1:n_points]

    # Tip values (last point)
    tip_u = all_u[end]
    tip_theta = all_theta[end]

    # Build deformed coordinates for VTK
    points_undeformed = [[i * L / nelem, 0.0, 0.0] for i in 0:nelem]
    points_deformed = [
        [points_undeformed[i][1] + all_u[i][1],
         points_undeformed[i][2] + all_u[i][2],
         points_undeformed[i][3] + all_u[i][3]]
        for i in 1:n_points
    ]

    # Write VTK file
    vtk_dir = dirname(output_file)
    vtk_path = joinpath(vtk_dir == "" ? "." : vtk_dir, "gxbeam_deformed.vtk")
    write_vtk_beam(vtk_path, points_undeformed, points_deformed, all_u, all_theta)

    # Write JSON output — include full per-node displacement/rotation arrays
    all_u_list = [[u[1], u[2], u[3]] for u in all_u]
    all_theta_list = [[t[1], t[2], t[3]] for t in all_theta]

    output_data = Dict(
        "u1" => tip_u[1],
        "u2" => tip_u[2],
        "u3" => tip_u[3],
        "rot1" => tip_theta[1],
        "rot2" => tip_theta[2],
        "rot3" => tip_theta[3],
        "all_u" => all_u_list,
        "all_theta" => all_theta_list,
        "vtk_path" => vtk_path,
        "nelem" => nelem,
        "converged" => converged
    )

    open(output_file, "w") do f
        JSON.print(f, output_data, 4)
    end

    println("Analysis complete. Results written to $output_file")
    println("VTK deformed beam written to $vtk_path")
end

main()
