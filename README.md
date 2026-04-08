# spot-train

Memory-backed Spot task orchestration MVP: Strands agent → world model → supervisor → Spot skills.

## Quick start

```bash
export SPOT_HOSTNAME=<robot-ip>
export SPOT_USERNAME=<username>
export SPOT_PASSWORD=<password>
./start.sh
```

This checks the environment, bootstraps the venv, runs lint + tests, and shows next steps.

## Prerequisites

- Python 3.10+ with `venv`
- Boston Dynamics Spot with SDK 5.1.x
- AWS credentials with Bedrock access (Claude Sonnet 4, Nova Lite)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev,spot,perception]"
pip install "strands-agents>=1.34,<2" "strands-agents-tools>=0.3,<1" "cmd2>=3.4,<4"
```

## Environment variables

```bash
# Spot connection (required)
export SPOT_HOSTNAME=<robot-ip>
export SPOT_USERNAME=<username>
export SPOT_PASSWORD=<password>

# Bedrock (optional, defaults shown)
export SPOT_TRAIN_BEDROCK_REGION=us-west-2
export SPOT_TRAIN_BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-20250514-v1:0
```

## Usage

### 1. Start e-stop (separate terminal)

```bash
source venv/bin/activate
python scripts/estop_control.py
# Press Enter to release e-stop
```

### 2. Record a map (first time only)

```bash
python scripts/record_map.py    # WASD to walk, 'n' to name waypoints, 'x' to save
python scripts/load_map.py      # load waypoints into world database
```

### 3. Run the agent REPL

```bash
python scripts/run.py              # connect to real Spot (default)
python scripts/run.py --dry-run    # fake adapters, no robot
```

### REPL commands

| Command | Action |
|---------|--------|
| `poweron` | Power on motors and stand |
| `sit` | Sit down (motors stay on) |
| `poweroff` | Sit down and power off |
| `status` | Show operator status |
| `places` | List known places |
| `stop` | Request software stop |
| `clear` | Clear stop state |
| `quit` | Exit and release lease |

Free-text input is sent to the Strands agent for tool-use (resolve, navigate, inspect, capture, verify).

## Baseline checks

```bash
./scripts/format.sh
./scripts/lint.sh
./scripts/test.sh
./scripts/check.sh
```

## Architecture

```
Strands agent → typed tool layer → deterministic supervisor → Spot/perception adapters → world memory
```

- Agent reasons over named entities and typed tools, not raw SDK calls
- Supervisor owns all side effects, retries, and state transitions
- World memory: SQLite with spatial, semantic, and episodic layers
- Perception: all 5 Spot cameras + depth → point clouds + Nova Lite VLM analysis
- Stop control: separate terminal process, independent of agent loop
