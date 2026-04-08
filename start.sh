#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$REPO_DIR/venv"

# ── Check Python ──
if ! command -v python3 &>/dev/null; then
    echo "❌ python3 not found. Install Python 3.10+ first."
    exit 1
fi

# ── Ensure venv ──
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "📦 Creating virtualenv at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    python -m pip install --upgrade pip -q
    python -m pip install -e ".[dev,spot,perception]" -q
    python -m pip install "strands-agents>=1.34,<2" "strands-agents-tools>=0.3,<1" "cmd2>=3.4,<4" -q
    echo "✅ Virtualenv ready."
else
    source "$VENV_DIR/bin/activate"
fi

# ── Ensure package is installed ──
pip install -e ".[perception]" -q

# ── Check Spot env vars ──
missing=()
[ -z "${SPOT_HOSTNAME:-}" ] && missing+=("SPOT_HOSTNAME")
[ -z "${SPOT_USERNAME:-}" ] && missing+=("SPOT_USERNAME")
[ -z "${SPOT_PASSWORD:-}" ] && missing+=("SPOT_PASSWORD")

if [ ${#missing[@]} -gt 0 ]; then
    echo "❌ Missing environment variables: ${missing[*]}"
    echo "   Export them or source your .env before running this script."
    exit 1
fi

echo "✅ Spot connection: $SPOT_USERNAME@$SPOT_HOSTNAME"

# ── Check runtime mode ──
echo "📋 Runtime mode: ${SPOT_TRAIN_RUNTIME_MODE:-off_robot}"

# ── Remind about e-stop ──
echo ""
echo "⚠️  BEFORE proceeding, open a separate terminal and run:"
echo ""
echo "     source $VENV_DIR/bin/activate"
echo "     python $REPO_DIR/scripts/estop_control.py"
echo ""
echo "   Release the e-stop there before issuing motor-on commands."
echo ""

# ── Run checks ──
echo "🔍 Running lint + tests ..."
python -m ruff check src/ tests/ --quiet
python -m pytest tests/ -ra --tb=short -q

echo ""
echo "✅ Stack ready. To launch the agent REPL:"
echo ""
echo "   source $VENV_DIR/bin/activate"
echo "   python $REPO_DIR/scripts/run.py              # real Spot (default)"
echo "   python $REPO_DIR/scripts/run.py --dry-run    # fake adapters, no robot"
echo ""
echo "   Helper scripts:"
echo "   python $REPO_DIR/scripts/record_map.py       # record a GraphNav map"
echo "   python $REPO_DIR/scripts/load_map.py         # load map into world DB"
