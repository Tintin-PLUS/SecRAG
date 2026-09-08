import sys
import json
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from retest_suite import (  # noqa: E402
    DOCUMENTS_DIR,
    load_documents,
    load_queries,
    minimum_ram_gib,
    split_fixed,
)


class RetestSuiteTests(unittest.TestCase):
    def test_fixed_chunking_respects_size_and_overlap(self):
        chunks = split_fixed("一二三四五六七八九十", 6, 2)
        self.assertEqual(chunks, ["一二三四五六", "五六七八九十"])
        self.assertTrue(all(len(chunk) <= 6 for chunk in chunks))

    def test_q1_corpus_is_at_least_twice_original_size(self):
        documents = load_documents(DOCUMENTS_DIR)
        self.assertGreaterEqual(len(documents), 24)

    def test_q1_uses_only_the_original_thirty_four_grounded_questions(self):
        queries = load_queries()
        self.assertEqual(len(queries), 34)
        self.assertTrue(all(item.get("must_contain") for item in queries))
        self.assertTrue(all(item.get("category") for item in queries))

    def test_minimum_ram_formula_reserves_os_and_headroom(self):
        self.assertEqual(minimum_ram_gib(2 * 1024**3), 8)
        self.assertEqual(minimum_ram_gib(4 * 1024**3), 16)
        self.assertEqual(minimum_ram_gib(9 * 1024**3), 32)

    def test_formal_config_supports_reported_p99_and_all_storage_scales(self):
        config_path = Path(__file__).resolve().parents[1] / "config" / "retest.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        query_count = len(load_queries())
        per_round = ((config["minimum_requests_per_round"] + query_count - 1) // query_count) * query_count
        self.assertGreaterEqual(per_round * config["search_rounds"], 1000)
        self.assertEqual(config["storage"]["chunk_counts"], [100, 1000, 10000])

    def test_formal_chunk_matrix_is_small_and_uses_one_declared_baseline(self):
        config_path = Path(__file__).resolve().parents[1] / "config" / "retest.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["baseline_chunk_config"], "fixed-150-30")
        self.assertEqual(
            config["chunk_configs"],
            [
                {"name": "fixed-100-20", "strategy": "fixed", "chunk_size": 100, "overlap": 20},
                {"name": "fixed-150-30", "strategy": "fixed", "chunk_size": 150, "overlap": 30},
                {"name": "fixed-200-40", "strategy": "fixed", "chunk_size": 200, "overlap": 40},
                {"name": "structure-200", "strategy": "structure", "chunk_size": 200, "overlap": 0},
            ],
        )


if __name__ == "__main__":
    unittest.main()
