import sgio
import numpy as np
import os

print("SGIO imported successfully.")

# Try to read a dummy results block if we have one, or just check the API
try:
    # Check if we can instantiate a Model or something similar
    print(f"SGIO version: {sgio.__version__}")
    # print(f"Available attributes: {dir(sgio)}")
except Exception as e:
    print(f"Error checking SGIO: {e}")

# Check if we can find a .k file in /runs
runs_dir = r'c:\Users\Cody\Documents\Python Scripts\VABS-preprocessor\runs'
k_files = [f for f in os.listdir(runs_dir) if f.endswith('.k')]
if k_files:
    k_file = os.path.join(runs_dir, k_files[0])
    print(f"Found .k file: {k_file}")
    try:
        # Based on docs: model = sgio.readOutputModel('file.sg.k', 'sc', 'BM1')
        # Let's try to see if it works on a SwiftComp .k file
        # 'sc' is for SwiftComp, 'vabs' for VABS. 
        # For SwiftComp beam, the model is usually 'BM1' (Timoshenko)
        model = sgio.readOutputModel(k_file, 'sc', 'BM1')
        print("Successfully read output model using SGIO!")
        # print(dir(model))
    except Exception as e:
        print(f"Could not read .k with SGIO: {e}")
else:
    print("No .k files found in /runs to test.")
