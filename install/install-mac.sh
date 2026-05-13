#!/usr/bin/env bash
# install-mac.sh — Installs the offline interview analysis system on macOS.
# Run this script BEFORE air-gapping the machine.
#
# Requirements:
#   - macOS 13 (Ventura) or later
#   - Homebrew (will be installed if missing)
#   - Internet access (run once before disconnecting)
#   - Apple Silicon (M1/M2/M3) strongly recommended; Intel supported
#
# Usage:
#   chmod +x install-mac.sh
#   ./install-mac.sh [--model llama3.1:8b] [--dir ~/interview-analyser] [--extra-models]

set -euo pipefail

# --- defaults ---
MODEL="llama3.1:8b"
INSTALL_DIR="$HOME/interview-analyser"
EXTRA_MODELS=false

# --- argument parsing ---
while [[ $# -gt 0 ]]; do
    case $1 in
        --model)        MODEL="$2";        shift 2 ;;
        --dir)          INSTALL_DIR="$2";  shift 2 ;;
        --extra-models) EXTRA_MODELS=true; shift ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

step()  { echo; echo "==> $*"; }
ok()    { echo "    [OK] $*"; }
warn()  { echo "    [WARN] $*"; }

# --- 1. Homebrew -----------------------------------------------------------
step "Checking Homebrew"
if command -v brew &>/dev/null; then
    ok "Homebrew found: $(brew --version | head -1)"
else
    warn "Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for Apple Silicon
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
    fi
    ok "Homebrew installed"
fi

# --- 2. Python 3.11+ -------------------------------------------------------
step "Checking Python >= 3.11"
if command -v python3 &>/dev/null; then
    PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
    PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
    if [[ $PY_MAJOR -ge 3 && $PY_MINOR -ge 11 ]]; then
        ok "Python $(python3 --version)"
    else
        warn "Python 3.11+ required. Installing via Homebrew..."
        brew install python@3.12
        ok "Python 3.12 installed"
    fi
else
    brew install python@3.12
    ok "Python 3.12 installed"
fi
PYTHON=$(command -v python3.12 || command -v python3.11 || command -v python3)

# --- 3. Ollama -------------------------------------------------------------
step "Installing Ollama"
if command -v ollama &>/dev/null; then
    ok "Ollama already installed: $(ollama --version)"
else
    brew install ollama
    ok "Ollama installed via Homebrew"
fi

# Disable analytics
export OLLAMA_NO_ANALYTICS=1
export OLLAMA_HOST="127.0.0.1:11434"
# Persist to shell profile
PROFILE="$HOME/.zprofile"
grep -q "OLLAMA_NO_ANALYTICS" "$PROFILE" 2>/dev/null || {
    echo 'export OLLAMA_NO_ANALYTICS=1'      >> "$PROFILE"
    echo 'export OLLAMA_HOST=127.0.0.1:11434' >> "$PROFILE"
}
ok "OLLAMA_NO_ANALYTICS=1 set"

# Start Ollama server in background
step "Starting Ollama server"
if pgrep -x ollama &>/dev/null; then
    ok "Ollama already running"
else
    ollama serve &>/dev/null &
    sleep 3
    ok "Ollama server started (PID $!)"
fi

# --- 4. Pull models --------------------------------------------------------
step "Pulling model: $MODEL  (may take 5–30 minutes)"
ollama pull "$MODEL"
ok "Model $MODEL downloaded"

if [[ $EXTRA_MODELS == true ]]; then
    step "Pulling additional models"
    for m in "llama3.2:3b" "mistral-small:22b"; do
        echo "    Pulling $m ..."
        ollama pull "$m"
        ok "$m downloaded"
    done
fi

# --- 5. Python virtual environment ----------------------------------------
step "Creating Python virtual environment in $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
"$PYTHON" -m venv "$INSTALL_DIR/.venv"
PIP="$INSTALL_DIR/.venv/bin/pip"
PYTHON_VENV="$INSTALL_DIR/.venv/bin/python"
ok "venv at $INSTALL_DIR/.venv"

step "Installing Python dependencies"
"$PIP" install --upgrade pip --quiet
"$PIP" install ollama pydantic pyyaml rich streamlit openpyxl python-docx --quiet
ok "Dependencies installed"

# --- 6. Copy pipeline files -----------------------------------------------
step "Copying pipeline files to $INSTALL_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC_DIR="$(dirname "$SCRIPT_DIR")"

for subdir in pipeline prompts output-schema; do
    src="$SPEC_DIR/$subdir"
    if [[ -d "$src" ]]; then
        cp -r "$src" "$INSTALL_DIR/"
        ok "Copied $subdir/"
    else
        warn "Source not found, skipping: $src"
    fi
done

for f in config.yaml app.py; do
    src="$SPEC_DIR/$f"
    if [[ -f "$src" ]]; then
        cp "$src" "$INSTALL_DIR/"
        ok "Copied $f"
    else
        warn "Not found, skipping: $f"
    fi
done

mkdir -p "$INSTALL_DIR/interviews" "$INSTALL_DIR/output"
ok "interviews/ and output/ directories created"

# --- 7. Launcher scripts --------------------------------------------------
cat > "$INSTALL_DIR/run-analysis.sh" << 'LAUNCHER'
#!/usr/bin/env bash
export OLLAMA_NO_ANALYTICS=1
export OLLAMA_HOST=127.0.0.1:11434
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pgrep -x ollama &>/dev/null || (ollama serve &>/dev/null & sleep 2)
"$DIR/.venv/bin/python" "$DIR/pipeline/main.py" "$@"
LAUNCHER
chmod +x "$INSTALL_DIR/run-analysis.sh"
ok "Launcher: $INSTALL_DIR/run-analysis.sh"

cat > "$INSTALL_DIR/run-ui.sh" << 'UILAUNCHER'
#!/usr/bin/env bash
export OLLAMA_NO_ANALYTICS=1
export OLLAMA_HOST=127.0.0.1:11434
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pgrep -x ollama &>/dev/null || (ollama serve &>/dev/null & sleep 2)
"$DIR/.venv/bin/streamlit" run "$DIR/app.py" \
    --server.address 127.0.0.1 --server.port 8501 \
    --server.headless false --browser.gatherUsageStats false
UILAUNCHER
chmod +x "$INSTALL_DIR/run-ui.sh"
ok "UI launcher: $INSTALL_DIR/run-ui.sh"

# --- 8. Offline transfer info --------------------------------------------
step "Model storage location (for offline transfer)"
MODEL_PATH="$HOME/.ollama/models"
if [[ -d "$MODEL_PATH" ]]; then
    SIZE=$(du -sh "$MODEL_PATH" 2>/dev/null | awk '{print $1}')
    ok "Models stored at: $MODEL_PATH  ($SIZE)"
    echo "    To transfer to an air-gapped Mac:"
    echo "    1. Copy $MODEL_PATH to a USB drive"
    echo "    2. On target machine: install Ollama (brew install ollama)"
    echo "    3. Copy models back to ~/.ollama/models"
    echo "    4. Do NOT run 'ollama pull' on the air-gapped machine"
fi

# --- Summary --------------------------------------------------------------
echo
echo "============================================================"
echo "  Installation complete"
echo "  Install dir : $INSTALL_DIR"
echo "  Model(s)    : $MODEL"
echo "  UI          : $INSTALL_DIR/run-ui.sh  (opens browser at localhost:8501)"
echo "  CLI         : $INSTALL_DIR/run-analysis.sh"
echo "  Transcripts : place .txt/.docx files in $INSTALL_DIR/interviews/"
echo "============================================================"
echo
echo "  BEFORE air-gapping:"
echo "  1. Copy $HOME/.ollama/models to target machine"
echo "  2. Run: python $INSTALL_DIR/pipeline/verify.py"
echo "  3. Disable Wi-Fi and Ethernet (System Settings > Network)"
