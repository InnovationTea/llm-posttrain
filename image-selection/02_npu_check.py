import torch
import torch_npu


print("="*50)

print(
    "NPU available:",
    torch.npu.is_available()
)


device=torch.device("npu:0")


x=torch.randn(
    1024,
    1024
).to(device)


y=torch.matmul(
    x,
    x
)


print(
    "matmul success:",
    y.shape
)


print(
    "NPU check PASS"
)