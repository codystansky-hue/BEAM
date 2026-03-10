import numpy as np

# Mock mesh data similar to what mesher.py generates
num_pts = 40
chord = 187.0
thickness = 0.25
element_size = 5.0

# 1. 2D points along a semi-circle or line
x = np.linspace(-chord/2, chord/2, num_pts)
y = np.zeros_like(x) # Flat for simplicity

# 2. Extrude thickness
nodes = []
for i in range(num_pts):
    nodes.append([x[i], y[i]])
    nodes.append([x[i], y[i] + thickness])
nodes = np.array(nodes)

elements = []
for i in range(num_pts - 1):
    n1 = 2*i
    n2 = 2*(i+1)
    n3 = 2*(i+1) + 1
    n4 = 2*i + 1
    elements.append([n1, n2, n3, n4])

# 3. Shoelace area sum (from solvers.py)
sg_area = 0.0
for elem in elements:
    pts = nodes[[elem[0], elem[1], elem[2], elem[3]]]
    n = len(pts)
    e_area_shoelace = 0.0
    for j in range(n):
        j2 = (j + 1) % n
        e_area_shoelace += pts[j, 0] * pts[j2, 1] - pts[j2, 0] * pts[j, 1]
    sg_area += e_area_shoelace

total_area = abs(sg_area) / 2.0
print(f"Chord: {chord} mm")
print(f"Thickness: {thickness} mm")
print(f"Expected Area: {chord * thickness} mm^2")
print(f"Calculated Shoelace Area: {total_area} mm^2")

# 4. Check if SwiftComp input format is the issue
# If we have 167000 MPa and 46.75 mm^2 area.
# EA should be 167000 * 46.75 = 7.8e6.
# If EA is 1.67e5, it means Area = 1.0 was used.
