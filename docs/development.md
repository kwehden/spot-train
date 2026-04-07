# Development Setup

Use a local virtual environment for all repository work.

## Create and activate a virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

On fish shell:

```bash
source .venv/bin/activate.fish
```

## Install dependencies

Project dependency metadata is defined separately from this bootstrap task. After Phase 0 configuration files are in place, install the project in the active virtualenv using the configured workflow.

## Run checks

After the project configuration is added, run formatting, lint, and test commands from the active virtualenv.
