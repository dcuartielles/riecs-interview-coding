<#
.SYNOPSIS
    Installs the offline interview analysis system on Windows.
    Run this script BEFORE air-gapping the machine.

.NOTES
    Requirements:
    - Windows 10/11, PowerShell 5.1 or 7+
    - Administrator rights (for Ollama installer)
    - Internet access (run once before disconnecting)
    - Optional: NVIDIA GPU with drivers already installed

    Run with:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
        .\install-windows.ps1
#>

param(
    [string]$Model = "llama3.1:8b",
    [string]$InstallDir = "$env:USERPROFILE\interview-analyser",
    [switch]$PullAdditionalModels,
    [switch]$SkipPython
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

function Write-Step { param([string]$msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK   { param([string]$msg) Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn { param([string]$msg) Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Require-Admin {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Error "This script must be run as Administrator. Right-click PowerShell and select 'Run as Administrator'."
    }
}

Require-Admin

# --- 1. Python -----------------------------------------------------------
Write-Step "Checking Python >= 3.11"
if (-not $SkipPython) {
    try {
        $pyver = python --version 2>&1
        if ($pyver -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 11) {
            Write-OK "Found $pyver"
        } else {
            Write-Warn "Python 3.11+ not found ($pyver). Downloading installer..."
            $pyInstaller = "$env:TEMP\python-3.12.3-amd64.exe"
            Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe" -OutFile $pyInstaller
            Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
            Write-OK "Python installed. Relaunch this script if PATH is not updated."
        }
    } catch {
        Write-Error "Could not determine Python version: $_"
    }
}

# --- 2. Ollama -----------------------------------------------------------
Write-Step "Installing Ollama"
$ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
if (Test-Path $ollamaExe) {
    Write-OK "Ollama already installed at $ollamaExe"
} else {
    $ollamaInstaller = "$env:TEMP\OllamaSetup.exe"
    Write-Host "    Downloading Ollama installer..."
    Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $ollamaInstaller
    Start-Process -FilePath $ollamaInstaller -ArgumentList "/S" -Wait
    Write-OK "Ollama installed"
}

# Disable analytics before any model pull
[System.Environment]::SetEnvironmentVariable("OLLAMA_NO_ANALYTICS", "1", "Machine")
[System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "127.0.0.1:11434", "Machine")
$env:OLLAMA_NO_ANALYTICS = "1"
$env:OLLAMA_HOST = "127.0.0.1:11434"
Write-OK "OLLAMA_NO_ANALYTICS=1 set (machine-wide)"

# Start Ollama service
Write-Step "Starting Ollama service"
$ollamaService = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollamaService) {
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    Write-OK "Ollama service started"
} else {
    Write-OK "Ollama service already running"
}

# --- 3. Pull models ------------------------------------------------------
Write-Step "Pulling model: $Model  (this can take 5-30 minutes depending on connection)"
& $ollamaExe pull $Model
Write-OK "Model $Model downloaded"

if ($PullAdditionalModels) {
    Write-Step "Pulling additional models for higher-quality analysis"
    foreach ($m in @("llama3.2:3b", "mistral-small:22b")) {
        Write-Host "    Pulling $m ..."
        & $ollamaExe pull $m
        Write-OK "$m downloaded"
    }
}

# --- 4. Python virtual environment ---------------------------------------
Write-Step "Creating Python virtual environment in $InstallDir"
if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Force $InstallDir | Out-Null }
python -m venv "$InstallDir\.venv"
$pip = "$InstallDir\.venv\Scripts\pip.exe"
$python = "$InstallDir\.venv\Scripts\python.exe"
Write-OK "venv created"

Write-Step "Installing Python dependencies"
& $pip install --upgrade pip --quiet
& $pip install ollama pydantic pyyaml rich streamlit openpyxl python-docx --quiet
Write-OK "Dependencies installed"

# --- 5. Copy pipeline files ----------------------------------------------
Write-Step "Copying pipeline files to $InstallDir"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$specDir     = Split-Path -Parent $scriptDir
$pipelineDir = Join-Path $specDir "pipeline"
$promptsDir  = Join-Path $specDir "prompts"
$schemaDir   = Join-Path $specDir "output-schema"

foreach ($src in @($pipelineDir, $promptsDir, $schemaDir)) {
    if (Test-Path $src) {
        Copy-Item -Recurse -Force $src $InstallDir
        Write-OK "Copied $(Split-Path -Leaf $src)"
    } else {
        Write-Warn "Source not found, skipping: $src"
    }
}

# Copy config and UI entry point from spec root
foreach ($f in @("config.yaml", "app.py")) {
    $src = Join-Path $specDir $f
    if (Test-Path $src) {
        Copy-Item -Force $src $InstallDir
        Write-OK "Copied $f"
    } else {
        Write-Warn "Not found, skipping: $f"
    }
}

# Create interviews and output directories
New-Item -ItemType Directory -Force "$InstallDir\interviews" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\output"     | Out-Null
Write-OK "interviews/ and output/ directories created"

# --- 6. Launcher scripts --------------------------------------------------
$launcher = @"
@echo off
set OLLAMA_NO_ANALYTICS=1
set OLLAMA_HOST=127.0.0.1:11434
cd /d "$InstallDir"
.venv\Scripts\python.exe pipeline\main.py %*
"@
Set-Content -Path "$InstallDir\run-analysis.bat" -Value $launcher -Encoding ASCII
Write-OK "Launcher: $InstallDir\run-analysis.bat"

$uiLauncher = @"
@echo off
set OLLAMA_NO_ANALYTICS=1
set OLLAMA_HOST=127.0.0.1:11434
cd /d "$InstallDir"
.venv\Scripts\streamlit.exe run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless false --browser.gatherUsageStats false
"@
Set-Content -Path "$InstallDir\run-ui.bat" -Value $uiLauncher -Encoding ASCII
Write-OK "UI launcher: $InstallDir\run-ui.bat"

# --- 7. Offline model export (for air-gapped transfer) -------------------
Write-Step "Model storage location (for USB transfer to air-gapped machine)"
$modelPath = "$env:USERPROFILE\.ollama\models"
if (Test-Path $modelPath) {
    $size = (Get-ChildItem $modelPath -Recurse | Measure-Object -Property Length -Sum).Sum / 1GB
    Write-OK "Models stored at: $modelPath  (${size:F1} GB)"
    Write-Host "    To transfer: copy this entire folder to the same path on the air-gapped machine."
    Write-Host "    Air-gapped machine also needs Ollama installed (without pulling models)."
}

# --- Summary -------------------------------------------------------------
Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "  Installation complete" -ForegroundColor Green
Write-Host "  Install dir : $InstallDir" -ForegroundColor Green
Write-Host "  Model(s)    : $Model" -ForegroundColor Green
Write-Host "  UI          : $InstallDir\run-ui.bat  (opens browser at localhost:8501)" -ForegroundColor Green
Write-Host "  CLI         : $InstallDir\run-analysis.bat" -ForegroundColor Green
Write-Host "  Transcripts : place .txt/.docx files in $InstallDir\interviews\" -ForegroundColor Green
Write-Host "============================================================`n" -ForegroundColor Green
Write-Host "  BEFORE air-gapping:" -ForegroundColor Yellow
Write-Host "  1. Copy $env:USERPROFILE\.ollama\models to the target machine" -ForegroundColor Yellow
Write-Host "  2. Verify with: .\verify.py" -ForegroundColor Yellow
Write-Host "  3. Disconnect network adapter in Device Manager" -ForegroundColor Yellow
