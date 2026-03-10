import json
import os

db_dir = r"c:\Users\Cody\Documents\Python Scripts\VABS-preprocessor\db"

files = ["fibers.json", "resins.json", "laminae.json"]

for filename in files:
    path = os.path.join(db_dir, filename)
    if not os.path.exists(path):
        continue
        
    with open(path, "r") as f:
        data = json.load(f)
        
    for item in data:
        # Fibers
        if "cte11" in item and abs(item["cte11"]) > 1e-4:
            print(f"Patching {filename}: {item.get('name')} cte11 {item['cte11']} -> {item['cte11']*1e-6}")
            item["cte11"] *= 1e-6
        if "cte22" in item and abs(item["cte22"]) > 1e-4:
            print(f"Patching {filename}: {item.get('name')} cte22 {item['cte22']} -> {item['cte22']*1e-6}")
            item["cte22"] *= 1e-6
        # Resin
        if "cte" in item and abs(item["cte"]) > 1e-4:
            print(f"Patching {filename}: {item.get('name')} cte {item['cte']} -> {item['cte']*1e-6}")
            item["cte"] *= 1e-6
            
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
