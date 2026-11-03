"""Grade stored replies again with the current cases. No API calls.

Usage: uv run python -m evals.regrade RESULT.json [RESULT.json ...]

Writes `<stem>-regraded-v<N>.json` next to each input. The agent
fingerprints stay from the source run (they describe the code that produced
the replies); only `cases` and `grader` change, and `regraded_from` names
the source file.
"""

import json
import sys
from pathlib import Path
from typing import Any

from evals.grade import grade, load_cases
from evals.run import CASES, ROOT, sha256


def regrade(source: Path) -> Path:
    version, cases = load_cases(CASES)
    by_id = {c.id: c for c in cases}
    record: dict[str, Any] = json.loads(source.read_text())
    if "replies" not in record["cases"][0]:
        raise SystemExit(f"{source.name}: no raw replies stored; cannot re-grade")
    for entry in record["cases"]:
        calls = [tuple(c) for c in entry["tool_calls"]]
        result = grade(by_id[entry["id"]], entry["replies"], calls)
        entry["passed"] = result.passed
        entry["failures"] = list(result.failures)
    record["regraded_from"] = source.name
    record["case_set_version"] = version
    record["fingerprints"]["cases"] = sha256(CASES)
    record["fingerprints"]["grader"] = sha256(ROOT / "evals" / "grade.py")
    record["fingerprints"]["regrader"] = sha256(Path(__file__))
    record["passed"] = sum(1 for e in record["cases"] if e["passed"])
    out = source.with_name(f"{source.stem}-regraded-v{version}.json")
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(f"{record['passed']}/{record['total']}  {out.relative_to(ROOT)}")
    return out


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        regrade(Path(arg).resolve())
