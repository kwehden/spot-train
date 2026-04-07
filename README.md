# spot-train

Phase 0 bootstrap for a spec-driven Spot orchestration MVP.

## Prerequisites

The bootstrap assumes Python 3.10+ with `venv` support available. On Debian or Ubuntu, that usually means installing the matching `python3-venv` package before creating `.venv`.

For Spot SDK development, use a Python 3.10 virtualenv. The latest official Boston Dynamics SDK wheels currently publish PyPI classifiers through Python 3.10.

## Local setup

This repository assumes an in-project virtualenv.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

To include the Boston Dynamics Spot SDK packages used by this project:

```bash
python -m pip install -e ".[dev,spot]"
```

The `spot` extra pins the current official SDK client packages:

- `bosdyn-client==5.1.4`
- `bosdyn-mission==5.1.4`

Those packages pull in the matching `bosdyn-api` and `bosdyn-core` dependencies transitively.

To add the Strands + Amazon Bedrock + REPL stack, install the current packages directly:

```bash
python -m pip install "strands-agents==1.34.1" "strands-agents-tools==0.3.0" "cmd2==3.4.0"
```

The expected repository-level model-serving setup is:

- Strands for agent orchestration
- Amazon Bedrock for model serving
- `cmd2` for the interactive message-loop REPL

If you are wiring a local `.env`, set the Bedrock region and model identifier there.

## Runtime mode

Execution mode is selected through environment variables so deployment can switch between off-robot and robot-adjacent operation without code changes.

```bash
cp .env.example .env
set -a
. ./.env
set +a
```

Supported values:

- `SPOT_TRAIN_RUNTIME_MODE=off_robot`
- `SPOT_TRAIN_RUNTIME_MODE=robot_adjacent`

## Model Serving

The repository expects Strands to use Amazon Bedrock as the model-serving backend.

Minimum environment placeholders:

- `SPOT_TRAIN_MODEL_PROVIDER=bedrock`
- `SPOT_TRAIN_BEDROCK_REGION=us-west-2`
- `SPOT_TRAIN_BEDROCK_MODEL_ID=<bedrock-model-id>`

Use the actual Bedrock region and model ID for your account and deployment target.

## Baseline commands

```bash
./scripts/format.sh
./scripts/lint.sh
./scripts/test.sh
./scripts/check.sh
```

`./scripts/test.sh` treats "no tests collected" as success during bootstrap so Phase 0 can pass before the real test suite lands.
