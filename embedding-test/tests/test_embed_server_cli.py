import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from embed_server import parse_startup_args  # noqa: E402


class EmbedServerCliTests(unittest.TestCase):
    def test_defaults_preserve_existing_startup(self):
        self.assertEqual(parse_startup_args([]), (8902, "bge-small", None))

    def test_accepts_port_and_preload_model(self):
        self.assertEqual(parse_startup_args(["8912", "m3e-base"]), (8912, "m3e-base", None))

    def test_accepts_optional_torch_thread_limit(self):
        self.assertEqual(parse_startup_args(["8912", "bge-m3", "4"]), (8912, "bge-m3", 4))

    def test_rejects_invalid_torch_thread_limit(self):
        with self.assertRaises(ValueError):
            parse_startup_args(["8902", "bge-small", "0"])

    def test_rejects_unknown_model(self):
        with self.assertRaises(ValueError):
            parse_startup_args(["8902", "unknown"])


if __name__ == "__main__":
    unittest.main()
