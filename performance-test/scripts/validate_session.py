"""Validate a completed benchmark session without PowerShell JSON depth limits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate_session(session_dir: Path) -> dict[str, Any]:
    info = json.loads((session_dir / "session_info.json").read_text(encoding="utf-8"))
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in session_dir.rglob("run_result.json")]
    invalid = [
        run.get("run_info", {}).get("run_id", "<missing-run-id>")
        for run in runs
        if run.get("run_info", {}).get("status") not in {"COMPLETE", "COMPLETE_WITH_ERRORS"}
    ]
    return {
        "valid": info.get("status") == "PASS" and bool(runs) and not invalid,
        "session_status": info.get("status"),
        "run_count": len(runs),
        "invalid_runs": invalid,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate_session(args.session_dir)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
