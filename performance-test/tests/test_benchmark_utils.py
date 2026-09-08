import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from benchmark_utils import (  # noqa: E402
    percentile,
    sha256_file,
    summarize_latency,
    validate_run,
    write_run,
)


class BenchmarkUtilsTests(unittest.TestCase):
    def test_percentile_interpolates_sorted_values(self):
        self.assertEqual(percentile([1.0, 2.0, 3.0, 4.0], 0.5), 2.5)
        self.assertAlmostEqual(percentile([1.0, 2.0, 3.0, 4.0], 0.95), 3.85)

    def test_summary_counts_failures_without_dropping_them(self):
        samples = [
            {"success": True, "latency_ms": 10.0},
            {"success": False, "latency_ms": 20.0},
            {"success": True, "latency_ms": 30.0},
        ]
        summary = summarize_latency(samples)
        self.assertEqual(summary["total_samples"], 3)
        self.assertEqual(summary["successful_samples"], 2)
        self.assertEqual(summary["failed_samples"], 1)
        self.assertEqual(summary["p50_ms"], 20.0)

    def test_validation_rejects_mismatched_summary_counts(self):
        payload = valid_payload()
        payload["summary"]["total_samples"] = 99
        self.assertIn("summary.total_samples", "\n".join(validate_run(payload)))

    def test_write_run_is_parseable_and_manifest_hash_matches(self):
        payload = valid_payload()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run-1"
            artifact = run_dir / "artifacts" / "service.log"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("test log", encoding="utf-8")
            result_path, manifest_path = write_run(run_dir, payload)
            loaded = json.loads(result_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["run_info"]["run_id"], "run-1")
            self.assertEqual(manifest["run_id"], "run-1")
            files = {item["path"]: item for item in manifest["files"]}
            self.assertEqual(files["run_result.json"]["sha256"], sha256_file(result_path))
            self.assertEqual(files["artifacts/service.log"]["sha256"], sha256_file(artifact))


def valid_payload():
    return {
        "schema_version": "1.0",
        "run_info": {"run_id": "run-1", "status": "COMPLETE"},
        "environment": {},
        "config": {},
        "dataset": {},
        "latency_samples": [
            {"success": True, "latency_ms": 10.0},
            {"success": False, "latency_ms": 20.0},
        ],
        "resource_samples": [],
        "quality_details": [],
        "case_results": [],
        "errors": [{"message": "expected failure"}],
        "summary": {"total_samples": 2, "successful_samples": 1, "failed_samples": 1},
        "integrity": {},
    }


if __name__ == "__main__":
    unittest.main()
