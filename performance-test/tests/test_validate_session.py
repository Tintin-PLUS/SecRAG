import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from validate_session import validate_session  # noqa: E402


class ValidateSessionTests(unittest.TestCase):
    def test_accepts_pass_session_with_complete_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "session_info.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            run = root / "01-run"
            run.mkdir()
            (run / "run_result.json").write_text(
                json.dumps({"run_info": {"run_id": "one", "status": "COMPLETE"}}), encoding="utf-8"
            )
            summary = validate_session(root)
            self.assertTrue(summary["valid"])
            self.assertEqual(summary["run_count"], 1)

    def test_rejects_running_session_and_incomplete_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "session_info.json").write_text(json.dumps({"status": "RUNNING"}), encoding="utf-8")
            run = root / "01-run"
            run.mkdir()
            (run / "run_result.json").write_text(
                json.dumps({"run_info": {"run_id": "one", "status": "RUNNING"}}), encoding="utf-8"
            )
            summary = validate_session(root)
            self.assertFalse(summary["valid"])
            self.assertEqual(summary["invalid_runs"], ["one"])


if __name__ == "__main__":
    unittest.main()
