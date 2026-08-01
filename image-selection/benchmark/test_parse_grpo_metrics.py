from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("parse_grpo_metrics.py")
SPEC = importlib.util.spec_from_file_location("parse_grpo_metrics", MODULE_PATH)
assert SPEC and SPEC.loader
parse_grpo_metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parse_grpo_metrics)


class ParseGrpoMetricsTests(unittest.TestCase):
    def test_summarizes_timing_and_rollout_throughput(self) -> None:
        lines = []
        for step in range(1, 7):
            lines.append(
                f"global_step: {step}, timing_s/gen: {step * 2}, "
                f"timing_s/update_actor: {step}, timing_s/step: {step * 3}, "
                "response_length/mean: 100, critic/rewards/mean: 0.5"
            )
        parsed = parse_grpo_metrics.parse_log("\n".join(lines))
        summary = parse_grpo_metrics.summarize(
            parsed, 6, 2, prompt_batch_size=8, rollout_n=4, npu_count=16
        )

        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["measured_step_ids"], [3, 4, 5, 6])
        self.assertEqual(summary["timing_s"]["step"]["mean"], 13.5)
        self.assertAlmostEqual(
            summary["rollout_output_tokens_per_second"],
            (4 * 8 * 4 * 100) / (6 + 8 + 10 + 12),
        )
        self.assertEqual(summary["reward_mean"]["mean"], 0.5)

    def test_marks_incomplete_error_log_failed(self) -> None:
        log = "global_step=1, actor/loss=nan\nRuntimeError: NPU out of memory"
        parsed = parse_grpo_metrics.parse_log(log)
        summary = parse_grpo_metrics.summarize(parsed, 2, 0, 8, 4, 16)
        self.assertEqual(summary["status"], "FAIL")
        self.assertTrue(summary["severe_errors"])
        self.assertTrue(summary["nonfinite_metrics"])


if __name__ == "__main__":
    unittest.main()
