import re
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from generate_retest_report import CHART_FILES, entropy_svg, scatter_svg, select_recommended_fixed  # noqa: E402


class GenerateRetestReportTests(unittest.TestCase):
    def test_report_has_exactly_eight_required_charts(self):
        self.assertEqual(len(CHART_FILES), 8)

    def test_scatter_uses_small_fixed_markers(self):
        svg = scatter_svg(
            "test",
            [{"x": 1.0, "y": 2.0, "color": "#123456", "label": "p"}],
            "x",
            "y",
        )
        radii = [float(value) for value in re.findall(r'<circle[^>]+r="([0-9.]+)"', svg)]
        self.assertTrue(radii)
        self.assertLessEqual(max(radii), 4.5)

    def test_recommended_fixed_chunk_is_selected_from_measured_ndcg(self):
        rows = [
            {"chunk_config": "fixed-100-20", "strategy": "fixed", "top_k": 3, "hybrid_quality": {"ndcg": 0.70}},
            {"chunk_config": "fixed-200-40", "strategy": "fixed", "top_k": 3, "hybrid_quality": {"ndcg": 0.75}},
            {"chunk_config": "structure-200", "strategy": "structure", "top_k": 3, "hybrid_quality": {"ndcg": 0.80}},
        ]
        self.assertEqual(select_recommended_fixed(rows), "fixed-200-40")

    def test_entropy_chart_identifies_all_models_profiles_chunks_and_topk(self):
        rows = []
        for profile, ram, threads in (("低配估算", 8, 4), ("办公PC估算", 16, 8), ("高配估算", 32, 14)):
            for model in ("bge-small", "m3e-base", "bge-m3"):
                for chunk in ("fixed-300-50", "fixed-500-80", "fixed-800-120"):
                    for top_k in (3, 5, 10):
                        rows.append({"profile": profile, "ram_gib": ram, "torch_threads": threads, "model": model, "chunk_config": chunk, "top_k": top_k, "entropy_score": 50.0, "quality_score": 50.0})
        weights = {profile: {"p50_cost": 0.3, "p95_cost": 0.3, "qps": 0.4} for profile in ("低配估算", "办公PC估算", "高配估算")}

        svg = entropy_svg(rows, weights)

        self.assertIn("81 个实测组合", svg)
        self.assertIn("低配估算 · 8 GB · 4线程", svg)
        self.assertIn("bge-small", svg)
        self.assertIn("m3e-base", svg)
        self.assertIn("bge-m3", svg)
        self.assertIn("300/50", svg)
        self.assertIn("K=3", svg)
        radii = [float(value) for value in re.findall(r'<circle[^>]+r="([0-9.]+)"', svg)]
        self.assertTrue(radii)
        self.assertLessEqual(max(radii), 3.5)


if __name__ == "__main__":
    unittest.main()
