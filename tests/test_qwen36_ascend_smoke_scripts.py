import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "frameworks" / "verl" / "run_qwen3_6_27b_grpo_smoke.sh"


class Qwen36AscendSmokeScriptTests(unittest.TestCase):
    def test_launcher_declares_required_smoke_defaults(self):
        launcher = LAUNCHER.read_text(encoding="utf-8")

        self.assertIn("MODEL_PATH=${MODEL_PATH:-/mnt/model/Qwen3.6-27B}", launcher)
        self.assertIn("NDEVICES_PER_NODE=${NDEVICES_PER_NODE:-16}", launcher)
        self.assertIn("actor_rollout_ref.actor.strategy=fsdp2", launcher)


if __name__ == "__main__":
    unittest.main()
