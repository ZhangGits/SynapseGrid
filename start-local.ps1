# SynapseGrid Local Dev Mode
# Usage:
#   .\start-local.ps1          # start both
#   .\start-local.ps1 -Frontend # frontend only
#   .\start-local.ps1 -Backend  # backend only

param(
    [switch]$Frontend,
    [switch]$Backend
)

$startAll = -not ($Frontend -or $Backend)

function Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }

function Check-Deps {
    $python = Get-Command python -ErrorAction SilentlyContinue
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm -ErrorAction SilentlyContinue

    if (-not $python) {
        Write-Error "Python not found"
        exit 1
    }
    if (-not $node -or -not $npm) {
        Write-Error "Node.js / npm not found"
        exit 1
    }

    if (-not (Test-Path "frontend/node_modules")) {
        Warn "Installing frontend deps..."
        Set-Location frontend
        npm install
        Set-Location ..
    }

    $hasBackendDeps = $false
    try {
        python -c "import fastapi, uvicorn, pydantic" 2>$null
        $hasBackendDeps = $true
    } catch {}
    if (-not $hasBackendDeps) {
        Warn "Installing backend deps..."
        Set-Location backend
        pip install -r requirements.txt
        Set-Location ..
    }
}

function Start-Backend {
    Info "Starting backend (http://localhost:8000)"
    $env:SYNAPSEGRID_HMAC_KEY = "dev-only-change-me-must-be-32-bytes"
    $env:SYNAPSEGRID_CORS_ORIGINS = "http://localhost:5173,http://localhost:3000"
    $env:PYTHONPATH = "backend"
    Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload" -WorkingDirectory "$PSScriptRoot/backend"
    Ok "Backend started: http://localhost:8000"
}

function Start-Frontend {
    Info "Starting frontend (http://localhost:5173)"
    Start-Process -NoNewWindow -FilePath "npm" -ArgumentList "run", "dev" -WorkingDirectory "$PSScriptRoot/frontend"
    Ok "Frontend started: http://localhost:5173"
}

Check-Deps

if ($Backend) {
    Start-Backend
} elseif ($Frontend) {
    Start-Frontend
} else {
    Start-Backend
    Start-Sleep -Seconds 2
    Start-Frontend
    Info ""
    Ok "======================================="
    Ok "  SynapseGrid Local Dev Mode Started"
    Ok "  Frontend: http://localhost:5173"
    Ok "  Backend:  http://localhost:8000"
    Ok "  API Docs: http://localhost:8000/docs"
    Ok "======================================="
    Info ""
    Info "Press Ctrl+C to stop"
}

if ($startAll) {
    while ($true) {
        Start-Sleep -Seconds 10
    }
}