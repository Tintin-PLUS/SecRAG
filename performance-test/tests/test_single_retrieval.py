import sys
import json
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from single_retrieval import build_config, load_completed_result  # noqa: E402


class SingleRetrievalTests(unittest.TestCase):
    def test_build_config_maps_cli_parameters_to_one_fixed_run(self):
        config = build_config(
            model="bge-small",
            chunk_size=150,
            overlap=30,
            top_k=5,
            rounds=2,
            minimum_requests_per_round=68,
            warmup_requests=10,
            build_repetitions=2,
            torch_threads=4,
        )
        self.assertEqual(config["models"], ["bge-small"])
        self.assertEqual(config["top_k"], [5])
        self.assertEqual(config["chunk_configs"][0]["name"], "fixed-150-30")
        self.assertEqual(config["torch_threads"], 4)
        self.assertEqual(config["search_rounds"], 2)

    def test_build_config_rejects_overlap_not_smaller_than_chunk(self):
        with self.assertRaises(ValueError):
            build_config("bge-small", 100, 100, 5, 1, 34, 5, 1, None)

    def test_completed_run_path_is_read_directly_without_appending_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "run_result.json"
            result_path.write_text(json.dumps({"run_info": {"status": "COMPLETE"}}), encoding="utf-8")
            self.assertEqual(load_completed_result(result_path)["run_info"]["status"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
