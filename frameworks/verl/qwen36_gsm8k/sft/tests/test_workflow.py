"""Regression tests for the Qwen3.6 GSM8K SFT workflow."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
VERL_DIR = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import compare_gsm8k  # noqa: E402
import evaluate_gsm8k  # noqa: E402
import prepare_gsm8k_sft  # noqa: E402


class DataPreparationTests(unittest.TestCase):
    def test_to_messages_preserves_reference_answer(self) -> None:
        row = prepare_gsm8k_sft.to_messages(
            {"question": " What is 1 + 1? ", "answer": " Work. #### 2 \n"},
            "Show the answer.",
        )
        self.assertEqual(
            row,
            {
                "messages": [
                    {"role": "user", "content": "What is 1 + 1? Show the answer."},
                    {"role": "assistant", "content": "Work. #### 2"},
                ]
            },
        )


class EvaluationTests(unittest.TestCase):
    def test_extract_final_answer_prefers_last_marker(self) -> None:
        self.assertEqual(
            evaluate_gsm8k.extract_final_answer("draft #### 1\nfinal #### 1,200.00"),
            "1200",
        )

    def test_extract_final_answer_falls_back_to_last_number(self) -> None:
        self.assertEqual(evaluate_gsm8k.extract_final_answer("1 + 1 = 2"), "2")

class ComparisonTests(unittest.TestCase):
    def test_transition_report(self) -> None:
        pairs = [
            ({"index": 0, "correct": False}, {"index": 0, "correct": True}),
            ({"index": 1, "correct": True}, {"index": 1, "correct": False}),
            ({"index": 2, "correct": True}, {"index": 2, "correct": True}),
            ({"index": 3, "correct": False}, {"index": 3, "correct": False}),
        ]
        report, improved, regressed = compare_gsm8k.transition_report(pairs, "correct")
        self.assertEqual(
            report,
            {
                "wrong_to_right": 1,
                "right_to_wrong": 1,
                "both_correct": 1,
                "both_wrong": 1,
            },
        )
        self.assertEqual(improved, [0])
        self.assertEqual(regressed, [1])


class BackgroundLauncherTests(unittest.TestCase):
    def test_training_scripts_launch_training_directly_in_background(self) -> None:
        scripts = {
            "sft": SCRIPT_DIR / "run_sft.sh",
            "grpo": VERL_DIR / "qwen36_gsm8k" / "rl" / "run_grpo.sh",
        }
        expected_commands = {"sft": "nohup torchrun", "grpo": "nohup python3"}

        for name, path in scripts.items():
            with self.subTest(script=name):
                content = path.read_text(encoding="utf-8")
                self.assertNotIn("VERL_BACKGROUND_WORKER", content)
                self.assertNotIn("exec torchrun", content)
                self.assertNotIn("exec python3", content)
                self.assertIn(expected_commands[name], content)
                self.assertIn('>"${LOG_FILE}" 2>&1 &', content)


if __name__ == "__main__":
    unittest.main()
