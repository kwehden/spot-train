"""cmd2-based REPL for the Spot-Train Strands agent."""

from __future__ import annotations

import os

import cmd2

from spot_train.agent.tools import all_tools, get_active_task, set_active_task
from spot_train.models import Task, TaskStatus

SYSTEM_PROMPT = """\
You are a Spot robot operator assistant. You help a human operator manage \
Boston Dynamics Spot in an indoor lab by translating natural-language \
instructions into tool calls.

Available tools let you: resolve place/asset names, navigate to places, \
inspect places, capture evidence, verify conditions, relocalize, check \
operator status, and summarize tasks.

Rules:
- Always resolve a target first using resolve_target before other operations.
- Use get_place_context to learn about a resolved place.
- A supervised task is automatically created for each instruction you receive. \
  All tools including navigation, inspection, capture, and verification will \
  work within this task context.
- Report results clearly and concisely.
- If a tool returns an error or blocked status, explain what happened.
- Never fabricate observations or evidence.
- When you finish handling an instruction, call summarize_task to produce \
  a final summary for the operator.
"""


class SpotTrainREPL(cmd2.Cmd):
    """Interactive REPL for issuing instructions to the Spot-Train agent."""

    intro = (
        "=== Spot-Train Agent REPL ===\n"
        "Type an instruction for Spot, or use commands below.\n"
        "  status  — show current operator status\n"
        "  places  — list known places\n"
        "  stop    — request stop\n"
        "  clear   — clear stop state\n"
        "  quit    — exit\n"
    )

    def __init__(self, session: dict, agent: object, **kwargs):
        super().__init__(allow_cli_args=False, **kwargs)
        self.prompt = "spot> "
        self.session = session
        self.agent = agent
        self.hidden_commands.extend(["alias", "macro", "run_script", "shell", "shortcuts"])

    def default(self, statement: cmd2.Statement) -> None:
        """Create a supervised task and send the instruction to the agent."""
        text = str(statement).strip()
        if not text:
            return

        # Create a task record for this instruction
        repo = self.session["repository"]
        task = repo.create_task(Task(instruction=text, status=TaskStatus.CREATED))
        set_active_task(task.task_id)
        self.poutput(f"[task {task.task_id[:12]}...] {text}")

        try:
            result = self.agent(text)
            self._print_agent_result(result)
        except KeyboardInterrupt:
            self.poutput("\n[interrupted]")
        except Exception as exc:
            self.poutput(f"[error] {exc}")
        finally:
            set_active_task(None)

    def _print_agent_result(self, result) -> None:
        msg = getattr(result, "message", result)
        if hasattr(msg, "content"):
            content = msg.content
        elif isinstance(msg, dict) and "content" in msg:
            content = msg["content"]
        else:
            self.poutput(str(msg))
            return
        for block in content:
            if hasattr(block, "text"):
                self.poutput(block.text)
            elif isinstance(block, dict) and "text" in block:
                self.poutput(block["text"])
            elif isinstance(block, str):
                self.poutput(block)

    def do_status(self, _statement) -> None:
        """Show current operator status."""
        handler = self.session["handler"]
        tid = get_active_task()
        result = handler.handle("get_operator_status", {"task_id": tid} if tid else {})
        self.poutput(result.model_dump_json(indent=2))

    def do_places(self, _statement) -> None:
        """List known places."""
        repo = self.session["repository"]
        for place in repo.list_places():
            aliases = repo.list_place_aliases(place.place_id)
            alias_str = ", ".join(a.alias for a in aliases)
            self.poutput(f"  {place.canonical_name} [{place.place_id}] aliases: {alias_str}")

    def do_stop(self, _statement) -> None:
        """Request stop."""
        adapter = self.session["spot_adapter"]
        outcome = adapter.request_stop(reason="operator REPL stop")
        self.poutput(f"Stop: {outcome.message}")

    def do_clear(self, _statement) -> None:
        """Clear stop state."""
        adapter = self.session["spot_adapter"]
        outcome = adapter.clear_stop()
        self.poutput(f"Clear: {outcome.message}")

    def do_quit(self, _statement) -> bool:
        """Exit the REPL."""
        self.poutput("Exiting.")
        return True


def create_agent(*, model_id: str | None = None, region: str | None = None):
    """Create a Strands Agent wired to Bedrock."""
    from strands import Agent
    from strands.models.bedrock import BedrockModel

    model_id = model_id or os.environ.get(
        "SPOT_TRAIN_BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
    )
    region = region or os.environ.get("SPOT_TRAIN_BEDROCK_REGION", "us-west-2")

    model = BedrockModel(model_id=model_id, region_name=region)
    agent = Agent(model=model, tools=all_tools(), system_prompt=SYSTEM_PROMPT)
    return agent


def run_repl(*, mode: str = "dry_run", model_id: str | None = None, region: str | None = None):
    """Bootstrap session, create agent, and launch the REPL."""
    from spot_train.agent.session import create_dry_run_session, create_robot_session

    if mode == "robot":
        print("Connecting to Spot...")
        session = create_robot_session()
        print(f"✅ Connected. Lease held: {session['spot_adapter'].has_lease}")
    else:
        session = create_dry_run_session()
        print("✅ Dry-run session ready (fake adapters).")

    agent = create_agent(model_id=model_id, region=region)
    print(f"✅ Agent ready (model: {model_id or 'claude-sonnet-4'})")

    repl = SpotTrainREPL(session=session, agent=agent)
    try:
        repl.cmdloop()
    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        spot = session.get("spot_adapter")
        if hasattr(spot, "release_lease"):
            spot.release_lease()
            print("Lease released.")
