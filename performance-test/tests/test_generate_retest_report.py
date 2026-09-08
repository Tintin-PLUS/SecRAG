import re
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from generate_retest_report import CHART_FILES, scatter_svg, select_recommended_fixed  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
