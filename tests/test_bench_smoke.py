import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


class BenchSmokeTests(unittest.TestCase):
    def test_bench_harness_runs_and_returns_json(self) -> None:
        cmd = [
            sys.executable,
            str(ROOT_DIR / "tools" / "bench_db.py"),
            "--n-keys",
            "20",
            "--change-rate",
            "0.5",
            "--n-events",
            "20",
            "--read-ratio",
            "0.6",
            "--ops-per-sec",
            "50",
            "--duration",
            "0.2",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT_DIR, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        payload = json.loads(proc.stdout.strip())
        self.assertTrue(payload.get("ok"))
        self.assertIn("results", payload)
        self.assertIn("state_set", payload["results"])
        self.assertIn("event_append", payload["results"])
        self.assertIn("mixed", payload["results"])


if __name__ == "__main__":
    unittest.main()
