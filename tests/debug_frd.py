import os

frd_path = r'c:\Users\Cody\Documents\Python Scripts\VABS-preprocessor\runs\snippet.frd'

if not os.path.exists(frd_path):
    print(f"File not found: {frd_path}")
else:
    with open(frd_path, 'r') as f:
        lines = f.readlines()
        
    print(f"Total lines: {len(lines)}")
    
    # Look for headers
    for i, line in enumerate(lines):
        if line.startswith(' -4'):
            print(f"Header at line {i+1}: '{line.strip()}'")
            # Print first 5 data lines
            for j in range(1, 6):
                if i + j < len(lines):
                    print(f"  Data {j}: '{lines[i+j][:60]}'")
            print("-" * 20)
            
    # Also find if there's a DISPR block
    for i, line in enumerate(lines):
        if 'DISPR' in line:
            print(f"Found DISPR at line {i+1}: '{line.strip()}'")
            break
