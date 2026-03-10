import sgio
import os
import numpy as np

runs_dir = r'c:\Users\Cody\Documents\Python Scripts\VABS-preprocessor\runs'
k_file = os.path.join(runs_dir, 'beam.sc1.k')

if os.path.exists(k_file):
    print("--- Testing BM2 (Timoshenko) ---")
    try:
        model = sgio.readOutputModel(k_file, 'sc', 'BM2')
        print(f"Type of model: {type(model)}")
        arr = np.array(model.stff)
        print(f"stff as array shape: {arr.shape}")
        print(f"stff as array:\n{arr}")
    except Exception as e:
        print(f"Error reading BM2: {e}")
else:
    print("File not found.")
