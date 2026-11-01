"""Run the frozen cases against the real model and record the results.

Usage: uv run python -m evals.run [--model M] [--only ID ...]

Reports only; the exit code is always 0 (evals never gate CI). Each result
file records fingerprints of everything that can change a score, so two
runs are compared only when their case and input fingerprints match.
"""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openai

from emporio import agent as agent_module
from emporio import prompt, tools
from emporio.agent import Agent, to_markdown
from emporio.config import DATA_DIR, Settings
from emporio.data import load_store
from evals.grade import grade, load_cases

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "evals" / "cases.toml"
RESULTS = ROOT / "evals" / "results"


def sha256(*paths: Path) -> str:
    h = hashlib.sha256()
    for path in paths:
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def parse_args(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()

    settings = Settings()
    model = args.model or settings.openai_model
    client = openai.OpenAI(api_key=settings.openai_api_key.get_secret_value())
    store = load_store()
    version, cases = load_cases(CASES)
    if args.only:
        cases = [c for c in cases if c.id in args.only]

    results: list[dict[str, Any]] = []
    returned: set[str | None] = set()
    for case in cases:
        clock = datetime.fromisoformat(case.clock)

        def fixed(c: datetime = clock) -> datetime:
            return c

        bot = Agent(client, store, model, settings.reasoning_effort, fixed)
        replies: list[str] = []
        calls: list[tuple[int, str, dict[str, Any]]] = []
        for i, text in enumerate(case.turns):
            turn = bot.reply(text)
            replies.append(turn.reply)
            calls += [(i, c.name, parse_args(c.arguments)) for c in turn.tool_calls]
            returned.add(turn.model)
        result = grade(case, replies, calls)
        results.append(
            {
                "id": case.id,
                "passed": result.passed,
                "failures": list(result.failures),
                "fallback": any(t.fallback for t in bot.turns),
                "transcript_md": to_markdown(bot.turns, case.id),
            }
        )
        mark = "PASS" if result.passed else "FAIL"
        print(f"{mark}  {case.id:28} {'; '.join(result.failures)}")

    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{len(results)} passed — model {model}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = RESULTS / f"{stamp}-{model}.json"
    record = {
        "case_set_version": version,
        "fingerprints": {
            "cases": sha256(CASES),
            "data": sha256(*sorted(DATA_DIR.glob("*.csv"))),
            "policy": sha256(Path(prompt.__file__).with_name("policy.md")),
            "prompt": sha256(Path(prompt.__file__)),
            "tools": sha256(Path(tools.__file__)),
            "agent": sha256(Path(agent_module.__file__)),
        },
        "git_rev": git("rev-parse", "--short", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "model_requested": model,
        "model_returned": sorted(m for m in returned if m),
        "reasoning_effort": settings.reasoning_effort,
        "only": args.only,
        "passed": passed,
        "total": len(results),
        "cases": results,
    }
    RESULTS.mkdir(exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
