import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "frameworks" / "verl" / "run_qwen3_6_27b_grpo_smoke.sh"
PREPARER = REPO_ROOT / "frameworks" / "verl" / "prepare_gsm8k_smoke.sh"


class Qwen36AscendSmokeScriptTests(unittest.TestCase):
    def test_launcher_declares_required_smoke_defaults(self):
        launcher = LAUNCHER.read_text(encoding="utf-8")

        self.assertIn("MODEL_PATH=${MODEL_PATH:-/mnt/model/Qwen3.6-27B}", launcher)
        self.assertIn("NDEVICES_PER_NODE=${NDEVICES_PER_NODE:-16}", launcher)
        self.assertIn("actor_rollout_ref.actor.strategy=fsdp2", launcher)

    def test_preparer_delegates_to_verl_gsm8k_preprocessor(self):
        preparer = PREPARER.read_text(encoding="utf-8")

        self.assertIn("examples/data_preprocess/gsm8k.py", preparer)
        self.assertIn('--local_save_dir "${DATA_DIR}"', preparer)

    def test_launcher_checks_inputs_and_limits_training(self):
        launcher = LAUNCHER.read_text(encoding="utf-8")

        self.assertIn('[[ ! -d "${MODEL_PATH}" ]]', launcher)
        self.assertIn('python3 -c "import torch_npu"', launcher)
        self.assertIn("algorithm.adv_estimator=grpo", launcher)
        self.assertIn("trainer.total_training_steps=${TOTAL_TRAINING_STEPS}", launcher)


if __name__ == "__main__":
    unittest.main()
