import torch
import torch.distributed as dist


dist.init_process_group(
    backend="hccl"
)


rank=dist.get_rank()

print(
    "rank:",
    rank
)


x=torch.tensor(
    [rank],
    device="npu"
)


dist.all_reduce(x)


print(
    "reduce result:",
    x
)


dist.destroy_process_group()


# 运行