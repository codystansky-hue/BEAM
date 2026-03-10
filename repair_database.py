import json
import os

db_path = r'c:\Users\Cody\Documents\Python Scripts\VABS-preprocessor\db\laminae.json'

if os.path.exists(db_path):
    with open(db_path, 'r') as f:
        data = json.load(f)
    
    modified = False
    for lamina in data:
        # Check if cte22 is obviously exploded (magnitude > 0.1)
        # Normal CTE is ~1e-5. 0.1 is 10,000x too large.
        if abs(lamina.get('cte22', 0)) > 1e-1:
            print(f"Fixing exploded CTE22 index {data.index(lamina)}: {lamina['cte22']} -> 25e-6")
            lamina['cte22'] = 25e-6
            modified = True
            
        if abs(lamina.get('cte11', 0)) > 1e-1:
            print(f"Fixing exploded CTE11 index {data.index(lamina)}: {lamina['cte11']} -> 0.0")
            lamina['cte11'] = 0.0
            modified = True

    if modified:
        with open(db_path, 'w') as f:
            json.dump(data, f, indent=4)
        print("Database patched successfully.")
    else:
        print("No exploded CTE values found.")
else:
    print("laminae.json not found.")
