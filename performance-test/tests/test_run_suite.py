import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_suite import is_relevant, load_corpus, quality_metrics  # noqa: E402


class RunSuiteTests(unittest.TestCase):
    def test_formal_suite_has_steady_state_warmup(self):
        config_path = Path(__file__).resolve().parents[1] / "config" / "retest.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(config["warmup_requests"], 30)

    def test_relevance_requires_all_must_terms_and_one_optional_term(self):
        self.assertTrue(is_relevant("毛利率为23.5%", ["毛利率"], ["23.5", "24.0"]))
        self.assertFalse(is_relevant("毛利率未披露", ["毛利率"], ["23.5", "24.0"]))
        self.assertFalse(is_relevant("23.5%", ["毛利率"], ["23.5"]))

    def test_quality_metrics_keep_rank_and_recall_meaning_separate(self):
        metrics = quality_metrics([False, True, False], total_relevant=2)
        self.assertEqual(metrics["hit"], 1)
        self.assertEqual(metrics["first_relevant_rank"], 2)
        self.assertEqual(metrics["reciprocal_rank"], 0.5)
        self.assertEqual(metrics["recall"], 0.5)
        self.assertGreater(metrics["ndcg"], 0.0)
        self.assertLess(metrics["ndcg"], 1.0)

    def test_quality_metrics_handle_no_relevant_corpus_items(self):
        metrics = quality_metrics([False, False], total_relevant=0)
        self.assertEqual(metrics["hit"], 0)
        self.assertEqual(metrics["recall"], 0.0)
        self.assertEqual(metrics["ndcg"], 0.0)

    def test_corpus_reader_releases_database_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "knowledge.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE chunks(content TEXT NOT NULL)")
                connection.execute("INSERT INTO chunks(content) VALUES ('证券测试')")
                connection.commit()
            finally:
                connection.close()
            self.assertEqual(load_corpus(database), ["证券测试"])
            database.unlink()
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
