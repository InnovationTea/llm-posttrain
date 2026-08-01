from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("parse_sft_metrics.py")
SPEC = importlib.util.spec_from_file_location("parse_sft_metrics", MODULE_PATH)
assert SPEC and SPEC.loader
parse_sft_metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parse_sft_metrics)


class ParseSftMetricsTests(unittest.TestCase):
    def test_summarizes_warm_steps_and_throughput(self) -> None:
        lines = [
            "Visible NPU processes: 2",
            "Global batch size: 8",
        ]
        for step in range(1, 7):
            lines.append(
                f"global_step: {step}, train/loss: {1 / step}, "
                f"grad_norm: {step / 10}, step_time: {step}.0, total_tokens: 80"
            )
        parsed = parse_sft_metrics.parse_log("\n".join(lines))
        summary = parse_sft_metrics.summarize(parsed, expected_steps=6, warmup_steps=2)

        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["measured_step_ids"], [3, 4, 5, 6])
        self.assertEqual(summary["step_time"]["mean_s"], 4.5)
        self.assertAlmostEqual(summary["samples_per_second"], 8 / 4.5)
        self.assertAlmostEqual(summary["effective_tokens_per_second"], 320 / 18)
        self.assertEqual(summary["loss"]["count"], 6)

    def test_marks_errors_and_missing_timing(self) -> None:
        log = """
Global batch size: 8
global_step=1, train/loss=nan, grad_norm=1.0
RuntimeError: HCCL timeout
"""
        parsed = parse_sft_metrics.parse_log(log)
        summary = parse_sft_metrics.summarize(parsed, expected_steps=2, warmup_steps=0)

        self.assertEqual(summary["status"], "FAIL")
        self.assertFalse(summary["completed_expected_steps"])
        self.assertIsNone(summary["samples_per_second"])
        self.assertTrue(summary["severe_errors"])
        self.assertTrue(summary["nonfinite_metrics"])


if __name__ == "__main__":
    unittest.main()
