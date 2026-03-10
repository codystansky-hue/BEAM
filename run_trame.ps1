# run_trame.ps1
# Usage: 
#   .\run_trame.ps1          - Run normally
#   .\run_trame.ps1 -Watch   - Run with automatic restart on file changes (requires watchdog)

param (
    [switch]$Watch
)

$VENV_PYTHON = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $VENV_PYTHON)) {
    Write-Error "Virtual environment not found at .\.venv. Please create it first."
    exit 1
}

if ($Watch) {
    # Check if watchdog is installed
    & $VENV_PYTHON -c "import watchdog" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Watchdog not found. Installing watchdog..." -ForegroundColor Cyan
        & $VENV_PYTHON -m pip install watchdog
    }

    Write-Host "Starting Trame with hot-reload (watching .py files)..." -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow
    
    # Use watchmedo from watchdog to restart on changes
    & $VENV_PYTHON -m watchdog.watchmedo auto-restart --patterns="*.py;*.jl" --recursive --ignore-directories --ignore-patterns="runs/*;db/*;meshes/*;.claude/*;__pycache__/*" -- $VENV_PYTHON trame_app.py
} else {
    Write-Host "Starting Trame application..." -ForegroundColor Green
    & $VENV_PYTHON trame_app.py
}
