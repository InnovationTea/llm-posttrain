#!/usr/bin/env python3
"""Check the Ascend runtime, BF16 autograd, and HCCL communication."""

from __future__ import annotations

import os
import platform
import sys
import traceback
from datetime import timedelta


def main() -> int:
    rank = int(os.getenv("RANK", "0"))
    local_rank = int(os.getenv("LOCAL_RANK", "0"))
    world_size = int(os.getenv("WORLD_SIZE", "1"))

    try:
        import torch
        import torch.distributed as dist
        import torch_npu
    except Exception:
        print(f"[rank {rank}] Failed to import torch/torch_npu")
        traceback.print_exc()
        return 1

    if rank == 0:
        print("=== Ascend environment ===")
        print("Python:", sys.version.replace("\n", " "))
        print("Platform:", platform.platform())
        print("torch:", torch.__version__)
        print("torch_npu:", torch_npu.__version__)
        print("ASCEND_VISIBLE_DEVICES:", os.getenv("ASCEND_VISIBLE_DEVICES"))
        print("ASCEND_RT_VISIBLE_DEVICES:", os.getenv("ASCEND_RT_VISIBLE_DEVICES"))

    try:
        device_count = torch.npu.device_count()
        if not torch.npu.is_available() or device_count == 0:
            raise RuntimeError("No available NPU devices")
        if local_rank >= device_count:
            raise RuntimeError(
                f"LOCAL_RANK={local_rank} exceeds visible NPU count {device_count}"
            )

        if rank == 0:
            print("Visible NPU count:", device_count)
            for index in range(device_count):
                print(f"NPU {index}:", torch.npu.get_device_name(index))

        device = torch.device(f"npu:{local_rank}")
        torch.npu.set_device(local_rank)

        # Exercise the BF16 forward and backward path used by training.
        left = torch.randn(
            256,
            256,
            dtype=torch.bfloat16,
            device=device,
            requires_grad=True,
        )
        right = torch.randn(
            256,
            256,
            dtype=torch.bfloat16,
            device=device,
            requires_grad=True,
        )
        output = left @ right
        loss = output.float().square().mean()
        loss.backward()
        torch.npu.synchronize()

        for name, tensor in {
            "output": output,
            "loss": loss,
            "left.grad": left.grad,
            "right.grad": right.grad,
        }.items():
            if tensor is None or not torch.isfinite(tensor.float()).all().item():
                raise RuntimeError(f"BF16 {name} contains NaN or Inf")

        if world_size > 1:
            dist.init_process_group(
                backend="hccl",
                timeout=timedelta(minutes=2),
            )
            value = torch.tensor([rank + 1.0], device=device)
            dist.all_reduce(value)
            torch.npu.synchronize()

            expected = world_size * (world_size + 1) / 2
            torch.testing.assert_close(
                value.cpu(),
                torch.tensor([expected]),
            )
            passed_checks = "BF16 autograd and HCCL"
        else:
            passed_checks = "BF16 autograd"

        print(f"[rank {rank}] {device}: {passed_checks} PASS")
    except Exception:
        print(f"[rank {rank}] Ascend environment check FAILED")
        traceback.print_exc()
        return 2
    finally:
        if dist.is_initialized():
            dist.destroy_process_group()

    if rank == 0:
        print("All Ascend environment checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
