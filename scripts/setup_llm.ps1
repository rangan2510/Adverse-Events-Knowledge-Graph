# LLM Setup Script for Drug-AE Knowledge Graph
# Downloads models from HuggingFace, converts to GGUF, quantizes, and starts servers

$ErrorActionPreference = "Stop"

# Configuration
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# Load HF_TOKEN from .env file
$envFile = Join-Path $ProjectRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^HF_TOKEN=(.+)$') {
            $env:HF_TOKEN = $Matches[1]
        }
    }
}
if (-not $env:HF_TOKEN) {
    Write-Host "WARNING: HF_TOKEN not found in .env file" -ForegroundColor Yellow
    Write-Host "  Some models may require authentication" -ForegroundColor Yellow
}
$ExternalDir = Join-Path $ProjectRoot "external"
$LlamaCppDir = Join-Path $ExternalDir "llama.cpp"
$HfModelsDir = Join-Path $ExternalDir "models"
$ModelsDir = "D:\llm\models"

# HuggingFace model repos
$PlannerHfRepo = "microsoft/Phi-4-mini-instruct"
$NarratorHfRepo = "microsoft/Phi-4"

# Output model names
$PlannerModel = "phi4mini.Q4_K_M.gguf"
$NarratorModel = "phi4.Q4_K_M.gguf"

# GPU layers to offload (adjust based on your VRAM)
$GpuLayers = 35

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  LLM Setup for Drug-AE Knowledge Graph" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Create directories
Write-Host "[1/7] Creating directories..." -ForegroundColor Yellow
foreach ($dir in @($ExternalDir, $HfModelsDir, $ModelsDir)) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  Created: $dir" -ForegroundColor Green
    } else {
        Write-Host "  Exists: $dir" -ForegroundColor Green
    }
}

# Step 2: Install/upgrade llama.cpp via winget
Write-Host ""
Write-Host "[2/7] Installing/upgrading llama.cpp..." -ForegroundColor Yellow
Write-Host "  Running: winget install ggml.llamacpp" -ForegroundColor Cyan
winget install ggml.llamacpp --accept-package-agreements --accept-source-agreements
# winget returns 0 for success, -1978335189 for "already installed", both are OK
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
    Write-Host "  WARNING: winget returned $LASTEXITCODE (may still be OK)" -ForegroundColor Yellow
}

# Verify installation
$llamaServer = Get-Command llama-server -ErrorAction SilentlyContinue
$llamaQuantize = Get-Command llama-quantize -ErrorAction SilentlyContinue
if ($llamaServer -and $llamaQuantize) {
    Write-Host "  Found llama-server: $($llamaServer.Source)" -ForegroundColor Green
    Write-Host "  Found llama-quantize: $($llamaQuantize.Source)" -ForegroundColor Green
} else {
    Write-Host "  ERROR: llama.cpp tools not found after install!" -ForegroundColor Red
    Write-Host "  Try manually: winget install ggml.llamacpp" -ForegroundColor Yellow
    exit 1
}

# Step 3: Clone llama.cpp repo (for conversion scripts)
Write-Host ""
Write-Host "[3/7] Setting up llama.cpp conversion tools..." -ForegroundColor Yellow
if (-not (Test-Path $LlamaCppDir)) {
    Write-Host "  Cloning llama.cpp repository (shallow)..." -ForegroundColor Cyan
    git clone --depth 1 https://github.com/ggerganov/llama.cpp $LlamaCppDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Failed to clone llama.cpp" -ForegroundColor Red
        exit 1
    }
    Write-Host "  Cloned to: $LlamaCppDir" -ForegroundColor Green
} else {
    Write-Host "  Already exists: $LlamaCppDir" -ForegroundColor Green
}

# Step 4: Install Python dependencies
Write-Host ""
Write-Host "[4/7] Installing Python dependencies..." -ForegroundColor Yellow
Write-Host "  Installing numpy, sentencepiece, transformers, gguf, protobuf..." -ForegroundColor Cyan
uv pip install numpy sentencepiece transformers gguf protobuf --index-strategy unsafe-best-match --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Failed to install base dependencies" -ForegroundColor Red
    exit 1
}
Write-Host "  Installing PyTorch (CPU)..." -ForegroundColor Cyan
uv pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Failed to install PyTorch" -ForegroundColor Red
    exit 1
}
Write-Host "  Dependencies installed" -ForegroundColor Green

# Step 5: Download models from HuggingFace
Write-Host ""
Write-Host "[5/7] Downloading models from HuggingFace..." -ForegroundColor Yellow

# Download Planner model (Phi-4-mini)
$plannerHfDir = Join-Path $HfModelsDir "Phi-4-mini-instruct"
$plannerPath = Join-Path $ModelsDir $PlannerModel
if (-not (Test-Path $plannerPath)) {
    if (-not (Test-Path $plannerHfDir)) {
        Write-Host "  Downloading $PlannerHfRepo..." -ForegroundColor Cyan
        $hfArgs = @("download", $PlannerHfRepo, "--local-dir", $plannerHfDir)
        if ($env:HF_TOKEN) { $hfArgs += @("--token", $env:HF_TOKEN) }
        uvx --from huggingface_hub hf @hfArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: Failed to download $PlannerHfRepo" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  Downloaded Phi-4-mini-instruct" -ForegroundColor Green
} else {
    Write-Host "  Planner model already quantized, skipping download" -ForegroundColor Green
}

# Download Narrator model (Phi-4)
$narratorHfDir = Join-Path $HfModelsDir "Phi-4"
$narratorPath = Join-Path $ModelsDir $NarratorModel
if (-not (Test-Path $narratorPath)) {
    if (-not (Test-Path $narratorHfDir)) {
        Write-Host "  Downloading $NarratorHfRepo..." -ForegroundColor Cyan
        $hfArgs = @("download", $NarratorHfRepo, "--local-dir", $narratorHfDir)
        if ($env:HF_TOKEN) { $hfArgs += @("--token", $env:HF_TOKEN) }
        uvx --from huggingface_hub hf @hfArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: Failed to download $NarratorHfRepo" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  Downloaded Phi-4" -ForegroundColor Green
} else {
    Write-Host "  Narrator model already quantized, skipping download" -ForegroundColor Green
}

# Step 6: Convert and quantize models
Write-Host ""
Write-Host "[6/7] Converting and quantizing models..." -ForegroundColor Yellow

$convertScript = Join-Path $LlamaCppDir "convert_hf_to_gguf.py"

# Convert and quantize Planner
if (-not (Test-Path $plannerPath)) {
    $plannerF16 = Join-Path $HfModelsDir "phi4mini.f16.gguf"
    
    # Convert to GGUF
    if (-not (Test-Path $plannerF16)) {
        Write-Host "  Converting Phi-4-mini to GGUF..." -ForegroundColor Cyan
        uv run python $convertScript $plannerHfDir --outfile $plannerF16
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: Failed to convert Phi-4-mini" -ForegroundColor Red
            exit 1
        }
    }
    
    # Quantize to Q4_K_M
    Write-Host "  Quantizing Phi-4-mini to Q4_K_M..." -ForegroundColor Cyan
    llama-quantize $plannerF16 $plannerPath Q4_K_M
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Failed to quantize Phi-4-mini" -ForegroundColor Red
        exit 1
    }
    
    $size = [math]::Round((Get-Item $plannerPath).Length / 1GB, 2)
    Write-Host "  Created: $PlannerModel ($size GB)" -ForegroundColor Green
} else {
    $size = [math]::Round((Get-Item $plannerPath).Length / 1GB, 2)
    Write-Host "  Planner model exists: $PlannerModel ($size GB)" -ForegroundColor Green
}

# Convert and quantize Narrator
if (-not (Test-Path $narratorPath)) {
    $narratorF16 = Join-Path $HfModelsDir "phi4.f16.gguf"
    
    # Convert to GGUF
    if (-not (Test-Path $narratorF16)) {
        Write-Host "  Converting Phi-4 to GGUF..." -ForegroundColor Cyan
        uv run python $convertScript $narratorHfDir --outfile $narratorF16
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: Failed to convert Phi-4" -ForegroundColor Red
            exit 1
        }
    }
    
    # Quantize to Q4_K_M
    Write-Host "  Quantizing Phi-4 to Q4_K_M..." -ForegroundColor Cyan
    llama-quantize $narratorF16 $narratorPath Q4_K_M
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Failed to quantize Phi-4" -ForegroundColor Red
        exit 1
    }
    
    $size = [math]::Round((Get-Item $narratorPath).Length / 1GB, 2)
    if ($size -lt 5) {
        Write-Host "  ERROR: Phi-4 model too small ($size GB), conversion likely failed" -ForegroundColor Red
        Write-Host "  Expected ~8-9 GB for Q4_K_M quantization" -ForegroundColor Yellow
        Remove-Item $narratorPath -Force
        exit 1
    }
    Write-Host "  Created: $NarratorModel ($size GB)" -ForegroundColor Green
} else {
    $size = [math]::Round((Get-Item $narratorPath).Length / 1GB, 2)
    if ($size -lt 5) {
        Write-Host "  ERROR: Existing Phi-4 model too small ($size GB), re-run setup" -ForegroundColor Red
        Remove-Item $narratorPath -Force
        exit 1
    }
    Write-Host "  Narrator model exists: $NarratorModel ($size GB)" -ForegroundColor Green
}

# Step 7: Start servers
Write-Host ""
Write-Host "[7/7] Starting LLM servers..." -ForegroundColor Yellow

# Start Planner server (port 8081)
Write-Host "  Starting Planner server (Phi-4-mini) on port 8081..." -ForegroundColor Cyan
Start-Process -FilePath "llama-server" -ArgumentList "-m `"$plannerPath`" --port 8081 --host 127.0.0.1 -ngl $GpuLayers" -WindowStyle Minimized

# Start Narrator server (port 8082)
Write-Host "  Starting Narrator server (Phi-4) on port 8082..." -ForegroundColor Cyan
Start-Process -FilePath "llama-server" -ArgumentList "-m `"$narratorPath`" --port 8082 --host 127.0.0.1 -ngl $GpuLayers" -WindowStyle Minimized

# Cleanup: Remove external folder to prevent uv sync from building llama.cpp
# Only cleanup if both models exist and are valid sizes
$plannerSize = [math]::Round((Get-Item $plannerPath).Length / 1GB, 2)
$narratorSize = [math]::Round((Get-Item $narratorPath).Length / 1GB, 2)
if ($plannerSize -gt 1 -and $narratorSize -gt 5) {
    Write-Host ""
    Write-Host "[Cleanup] Removing external folder..." -ForegroundColor Yellow
    if (Test-Path $ExternalDir) {
        Remove-Item -Path $ExternalDir -Recurse -Force
        Write-Host "  Removed: $ExternalDir" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "[Cleanup] Skipping - models may need re-conversion" -ForegroundColor Yellow
    Write-Host "  Planner: $plannerSize GB, Narrator: $narratorSize GB" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Servers running:" -ForegroundColor Green
Write-Host "  Planner (Phi-4-mini):  http://127.0.0.1:8081/v1" -ForegroundColor White
Write-Host "  Narrator (Phi-4):      http://127.0.0.1:8082/v1" -ForegroundColor White
Write-Host ""
Write-Host "Test with:" -ForegroundColor Yellow
Write-Host "  curl http://127.0.0.1:8081/health" -ForegroundColor White
Write-Host "  curl http://127.0.0.1:8082/health" -ForegroundColor White
Write-Host ""
Write-Host "Models stored in: $ModelsDir" -ForegroundColor Gray
Write-Host "Note: external/ folder was removed to prevent uv sync issues" -ForegroundColor Gray
Write-Host ""
