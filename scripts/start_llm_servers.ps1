# Start LLM Servers for Drug-AE Knowledge Graph
# Controls which models run on GPU vs CPU
#
# Usage:
#   .\start_llm_servers.ps1                  # Default: Planner=GPU, Narrator=CPU
#   .\start_llm_servers.ps1 -BothGPU         # Both on GPU (needs ~12GB VRAM)
#   .\start_llm_servers.ps1 -BothCPU         # Both on CPU
#   .\start_llm_servers.ps1 -NarratorGPU     # Narrator=GPU, Planner=CPU
#   .\start_llm_servers.ps1 -Stop            # Stop all servers
#   .\start_llm_servers.ps1 -Minimized       # Start minimized

param(
    [switch]$Stop,
    [switch]$NarratorGPU,     # Put narrator (Phi-4) on GPU, planner on CPU
    [switch]$BothGPU,         # Both on GPU (needs ~12GB VRAM)
    [switch]$BothCPU,         # Both on CPU
    [int]$GpuLayers = 99,     # GPU layers when enabled (99 = all)
    [switch]$Minimized
)

$ModelsDir = "D:\llm\models"
$PlannerModel = Join-Path $ModelsDir "phi4mini.Q4_K_M.gguf"
$NarratorModel = Join-Path $ModelsDir "phi4.Q4_K_M.gguf"

# Stop existing servers
if ($Stop) {
    Write-Host "Stopping LLM servers..." -ForegroundColor Yellow
    Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "  Servers stopped" -ForegroundColor Green
    exit 0
}

# Determine GPU layers for each model
# Default: Planner on GPU (small, fast), Narrator on CPU (large, more RAM needed)
$plannerNgl = $GpuLayers  # GPU by default
$narratorNgl = 0          # CPU by default

if ($BothGPU) {
    $plannerNgl = $GpuLayers
    $narratorNgl = $GpuLayers
    Write-Host "Mode: Both models on GPU (~12GB VRAM)" -ForegroundColor Cyan
} elseif ($BothCPU) {
    $plannerNgl = 0
    $narratorNgl = 0
    Write-Host "Mode: Both models on CPU" -ForegroundColor Cyan
} elseif ($NarratorGPU) {
    $plannerNgl = 0
    $narratorNgl = $GpuLayers
    Write-Host "Mode: Planner=CPU, Narrator=GPU" -ForegroundColor Cyan
} else {
    # Default: Planner on GPU, Narrator on CPU
    Write-Host "Mode: Planner=GPU (~2.3GB), Narrator=CPU (~8.5GB RAM)" -ForegroundColor Cyan
}

# Verify models exist
if (-not (Test-Path $PlannerModel)) {
    Write-Host "ERROR: Planner model not found: $PlannerModel" -ForegroundColor Red
    Write-Host "  Run: .\scripts\setup_llm.ps1" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $NarratorModel)) {
    Write-Host "ERROR: Narrator model not found: $NarratorModel" -ForegroundColor Red
    Write-Host "  Run: .\scripts\setup_llm.ps1" -ForegroundColor Yellow
    exit 1
}

# Stop any existing servers
Write-Host "Stopping existing servers..." -ForegroundColor Yellow
Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

# Window style
$windowStyle = if ($Minimized) { "Minimized" } else { "Normal" }

# Start Planner server (port 8081)
$plannerArgs = "-m `"$PlannerModel`" --port 8081 --host 127.0.0.1 -ngl $plannerNgl"
$plannerDevice = if ($plannerNgl -gt 0) { "GPU" } else { "CPU" }
Write-Host "Starting Planner (Phi-4-mini) on port 8081 [$plannerDevice]..." -ForegroundColor Green
Start-Process -FilePath "llama-server" -ArgumentList $plannerArgs -WindowStyle $windowStyle

Start-Sleep -Seconds 2

# Start Narrator server (port 8082)
$narratorArgs = "-m `"$NarratorModel`" --port 8082 --host 127.0.0.1 -ngl $narratorNgl"
$narratorDevice = if ($narratorNgl -gt 0) { "GPU" } else { "CPU" }
Write-Host "Starting Narrator (Phi-4) on port 8082 [$narratorDevice]..." -ForegroundColor Green
Start-Process -FilePath "llama-server" -ArgumentList $narratorArgs -WindowStyle $windowStyle

# Wait for startup
Write-Host ""
Write-Host "Waiting for servers..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

# Health check with retries
$maxRetries = 15
$plannerOk = $false
$narratorOk = $false

for ($i = 0; $i -lt $maxRetries; $i++) {
    if (-not $plannerOk) {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:8081/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.status -eq "ok") { $plannerOk = $true }
        } catch {}
    }
    if (-not $narratorOk) {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:8082/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.status -eq "ok") { $narratorOk = $true }
        } catch {}
    }
    if ($plannerOk -and $narratorOk) { break }
    Write-Host "." -NoNewline
    Start-Sleep -Seconds 2
}
Write-Host ""

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Server Status" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
if ($plannerOk) {
    Write-Host "  Planner (Phi-4-mini):  OK [$plannerDevice]  http://127.0.0.1:8081/v1" -ForegroundColor Green
} else {
    Write-Host "  Planner (Phi-4-mini):  FAILED" -ForegroundColor Red
}
if ($narratorOk) {
    Write-Host "  Narrator (Phi-4):      OK [$narratorDevice]  http://127.0.0.1:8082/v1" -ForegroundColor Green
} else {
    Write-Host "  Narrator (Phi-4):      FAILED (CPU loading takes ~30s)" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Stop servers:  .\scripts\start_llm_servers.ps1 -Stop" -ForegroundColor Gray
Write-Host ""

if (-not $plannerOk) {
    exit 1
}
