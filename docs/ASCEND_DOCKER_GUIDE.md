# verl Docker 目录与 Ascend NPU 镜像指南

> 基于 `docker/` 目录整理，涵盖目录结构总览与 18 个 Ascend NPU Dockerfile 的详细说明。

---

## 一、docker/ 目录总览

### 根目录文件

| 文件 | 说明 |
|------|------|
| `README.md` | Docker 使用文档，含构建方法、发布历史 |
| `Dockerfile.stable.vllm` | **当前稳定主线**，vLLM 推理，基于 `nvidia/cuda:12.9.1-devel-ubuntu22.04` |
| `Dockerfile.stable.sglang` | **当前稳定主线**，SGLang 推理 |
| `Dockerfile.stable.trtllm` | TensorRT-LLM 推理 |
| `Dockerfile.isaaclab230` | Isaac Lab 2.3.0 机器人仿真专用 |

### 子目录

| 子目录 | 平台 | 说明 |
|--------|------|------|
| `ascend/` | 华为昇腾 NPU | 18 个 Dockerfile，覆盖 CANN 8.2~9.0，A2/A3 芯片 |
| `aws/` | AWS | EFA 网络扩展 + SageMaker 部署 |
| `rocm/` | AMD GPU | 多个历史版本 |
| `verl0.4-cu124-torch2.6-fa2.7.4/` | NVIDIA | verl 0.4 历史镜像（CUDA 12.4，PyTorch 2.6） |
| `verl0.5-cu126-torch2.7.1-fa2.8.0/` | NVIDIA | verl 0.5 历史镜像（CUDA 12.6，PyTorch 2.7.1） |
| `verl0.5-cu126-torch2.7-fa2.7.4/` | NVIDIA | verl 0.5 另一变体 |
| `verl0.5-preview-cu128-torch2.7.1-fa2.8.0/` | NVIDIA | verl 0.5 preview（CUDA 12.8） |
| `verl0.6.1-experimental/` | NVIDIA | verl 0.6.1 实验性镜像 |
| `verl0.6-cu128-torch2.8.0-fa2.7.4/` | NVIDIA | verl 0.6 历史镜像（CUDA 12.8，PyTorch 2.8） |

**稳定版镜像说明**：`stable.vllm` / `stable.sglang` 叠加在 NVIDIA CUDA 基础镜像上，额外包含
flash_attn、Megatron-LM、Apex、TransformerEngine、DeepEP。预构建镜像托管于
[dockerhub verlai/verl](https://hub.docker.com/r/verlai/verl)。

---

## 二、Ascend NPU 镜像快速选型表

> `910b` 系列对应 A2 芯片；`a3` / `9392` 系列对应 A3 芯片。

| Dockerfile | CANN 版本 | 芯片 | 推理框架 | 推理框架版本 | PyTorch | verl 版本 |
|---|---|---|---|---|---|---|
| `Dockerfile.ascend_8.2.rc1_a2` | 8.2.RC1 | A2 (910b) | vLLM + vllm-ascend | v0.9.1 | 2.5.1 | latest main |
| `Dockerfile.ascend_8.2.rc1_a3` | 8.2.RC1 | A3 | vLLM + vllm-ascend | v0.9.1 | 2.5.1 | latest main |
| `Dockerfile.ascend_8.3.rc1_a2` | 8.3.RC1 | A2 (910b) | vLLM + vllm-ascend | v0.11.0 | 2.7.1 | latest main |
| `Dockerfile.ascend_8.3.rc1_a3` | 8.3.RC1 | A3 | vLLM + vllm-ascend | v0.11.0 | 2.7.1 | latest main |
| `Dockerfile.ascend.sglang_8.3.rc1_a2` | 8.3.RC1 | A2 (910b) | SGLang + sgl-kernel-npu | v0.5.8 | 2.7.1 | latest main |
| `Dockerfile.ascend.sglang_8.3.rc1_a3` | 8.3.RC1 | A3 | SGLang + sgl-kernel-npu | v0.5.8 | 2.7.1 | latest main |
| `Dockerfile.ascend_8.5.0_a2` | 8.5.0 | A2 (910b) | vLLM + vllm-ascend | v0.18.0 | 2.9.0 | latest main |
| `Dockerfile.ascend_8.5.0_a3` | 8.5.0 | A3 | vLLM + vllm-ascend | v0.13.0 | 2.8.0 | latest main |
| `Dockerfile.ascend_8.5.0_a2_v0.7.1` | 8.5.0 | A2 (910b) | vLLM + vllm-ascend | v0.13.0 | 2.8.0 | **v0.7.1** |
| `Dockerfile.ascend_8.5.0_a3_v0.7.1` | 8.5.0 | A3 | vLLM + vllm-ascend | v0.13.0 | 2.8.0 | **v0.7.1** |
| `Dockerfile.ascend.sglang_8.5.0_a2` | 8.5.0 | A2 (910b) | SGLang + sgl-kernel-npu | v0.5.10 | 2.8.0 | latest main |
| `Dockerfile.ascend.sglang_8.5.0_a3` | 8.5.0 | A3 | SGLang + sgl-kernel-npu | v0.5.10 | 2.8.0 | latest main |
| `Dockerfile.ascend_8.5.2_a2_qwen3-5` | **8.5.2** | A2 (910b) | vLLM + vllm-ascend | v0.18.0 | 2.9.0 | fixed commit |
| `Dockerfile.ascend_8.5.2_a3_qwen3-5` | **8.5.2** | A3 | vLLM + vllm-ascend | v0.18.0 | 2.9.0 | fixed commit |
| `Dockerfile.ascend_9.0.0_a2` | **9.0.0** | A2 (910b) | vLLM + vllm-ascend | v0.18.0 | 2.9.0 | latest main |
| `Dockerfile.ascend_9.0.0_a3` | **9.0.0** | A3 | vLLM + vllm-ascend | v0.18.0 | 2.9.0 | latest main |
| `Dockerfile.ascend_9.0.0_a2_v0.8.0` | **9.0.0** | A2 (910b) | vLLM + vllm-ascend | v0.18.0 | 2.9.0 | **v0.8.0** |
| `Dockerfile.ascend_9.0.0_a3_v0.8.0` | **9.0.0** | A3 | vLLM + vllm-ascend | v0.18.0 | 2.9.0 | **v0.8.0** |

---

## 三、各镜像详细说明

### CANN 8.2.rc1 系列（最早支持版本）

#### `Dockerfile.ascend_8.2.rc1_a2`

- **基础镜像**：`ascendhub/cann:8.2.rc1-910b-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910B（A2 架构）
- **PyTorch**：torch 2.5.1 + torch_npu 2.5.1 + torchvision 0.20.1
- **推理框架**：vLLM v0.9.1 + vllm-ascend v0.9.1（`VLLM_TARGET_DEVICE=empty` 编译）
- **训练框架**：MindSpeed (commit `f2b0977e`) + Megatron-LM core_v0.12.1
- **verl 版本**：latest main (`verl-project/verl`)
- **特殊说明**：Megatron-LM 路径通过 `PYTHONPATH` 注入，无 mbridge

#### `Dockerfile.ascend_8.2.rc1_a3`

- **基础镜像**：`ascendhub/cann:8.2.rc1-a3-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910（A3 架构，SOC `ascend910_9392`）
- **PyTorch**：torch 2.5.1 + torch_npu 2.5.1 + torchvision 0.20.1
- **推理框架**：vLLM v0.9.1 + vllm-ascend v0.9.1
- **训练框架**：MindSpeed (commit `f2b0977e`) + Megatron-LM core_v0.12.1
- **verl 版本**：latest main
- **特殊说明**：与 A2 版本结构相同，仅基础镜像和 CANN 库路径不同

---

### CANN 8.3.rc1 系列

#### `Dockerfile.ascend_8.3.rc1_a2`

- **基础镜像**：`ascendhub/cann:8.3.rc1-910b-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910B（A2）
- **PyTorch**：torch 2.7.1 + torch_npu 2.7.1 + torchvision 0.22.1 + transformers 4.57.6
- **推理框架**：vLLM v0.11.0 + vllm-ascend v0.11.0
- **训练框架**：MindSpeed (commit `f2b0977e`) + Megatron-LM core_v0.12.1
- **额外组件**：mbridge（用于 DeepSeek 等模型的 NPU 适配桥接）
- **verl 版本**：latest main
- **特殊说明**：构建时移除 `triton`、`triton-ascend`（防止与昇腾 triton 冲突）

#### `Dockerfile.ascend_8.3.rc1_a3`

- **基础镜像**：`ascendhub/cann:8.3.rc1-a3-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910（A3）
- **PyTorch**：torch 2.7.1 + torch_npu 2.7.1 + torchvision 0.22.1 + transformers 4.57.6
- **推理框架**：vLLM v0.11.0 + vllm-ascend v0.11.0
- **训练框架**：MindSpeed (commit `f2b0977e`) + Megatron-LM core_v0.12.1
- **额外组件**：mbridge
- **verl 版本**：latest main

#### `Dockerfile.ascend.sglang_8.3.rc1_a2`

- **基础镜像**：`ascendhub/cann:8.3.rc1-910b-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910B（A2）
- **PyTorch**：torch 2.7.1 + torch_npu-2.7.1.post2 + torchvision 0.22.1（从 gitcode.com/Ascend/pytorch 下载 .whl）
- **推理框架**：SGLang v0.5.8 + sgl-kernel-npu (commit `46b73de`，从源码本地编译)
- **训练框架**：MindSpeed (commit `f2b0977e`) + Megatron-LM core_v0.12.1
- **额外组件**：mbridge、ray 2.46.0、pybind11
- **verl 版本**：latest main (`verl-project/verl`)
- **特殊说明**：
  - A2 芯片的 DeepEP 默认以 A3 模式编译，此镜像额外执行 `build.sh -a deepep2` 重编为 A2 专用 deepep2 模式
  - pip 使用阿里云镜像加速

#### `Dockerfile.ascend.sglang_8.3.rc1_a3`

- **基础镜像**：`ascendhub/cann:8.3.rc1-a3-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910（A3）
- **PyTorch**：torch 2.7.1 + torch_npu-2.7.1.post2 + torchvision 0.22.1
- **推理框架**：SGLang v0.5.8 + sgl-kernel-npu (commit `46b73de`)
- **训练框架**：MindSpeed (commit `f2b0977e`) + Megatron-LM core_v0.12.1
- **额外组件**：mbridge、ray 2.46.0
- **verl 版本**：latest main
- **特殊说明**：sgl-kernel-npu 默认以 A3 模式编译，无需额外 deepep2 重编

---

### CANN 8.5.0 系列（vLLM + SGLang 双轨）

#### `Dockerfile.ascend_8.5.0_a2`

- **基础镜像**：`ascendhub/cann:8.5.0-910b-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910B（A2，SOC `ascend910b1`）
- **PyTorch**：通过 vllm-ascend requirements 安装；x86_64 额外安装 torch 2.9.0+cpu
- **推理框架**：vLLM v0.18.0 + vllm-ascend releases/v0.18.0（启用 `COMPILE_CUSTOM_KERNELS=1`）
- **训练框架**：MindSpeed (2.3.0_core_r0.12.1) + Megatron-LM core_v0.12.1
- **额外组件**：mbridge、transformers 4.57.6、triton-ascend（来自 osinfra.cn）
- **verl 版本**：latest main
- **特殊说明**：triton 从昇腾专属源 `triton-ascend.osinfra.cn` 安装，防止与官方 triton 冲突

#### `Dockerfile.ascend_8.5.0_a3`

- **基础镜像**：`ascendhub/cann:8.5.0-a3-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910（A3，SOC `ascend910_9392`）
- **PyTorch**：通过 vllm-ascend requirements；额外 `pip install mbridge torch_npu==2.8.0`
- **推理框架**：vLLM v0.13.0 + vllm-ascend releases/v0.13.0（注意：A3 用 v0.13.0，A2 用 v0.18.0）
- **训练框架**：MindSpeed (2.3.0_core_r0.12.1) + Megatron-LM core_v0.12.1
- **额外组件**：mbridge、torch_npu 2.8.0、transformers 4.57.6
- **verl 版本**：latest main
- **特殊说明**：使用华为云镜像源 `mirrors.huaweicloud.com`，`GIT_SSL_NO_VERIFY=true`

#### `Dockerfile.ascend_8.5.0_a2_v0.7.1`

- **基础镜像**：`ascendhub/cann:8.5.0-910b-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910B（A2，SOC `ascend910b1`）
- **PyTorch**：torch_npu 2.8.0（通过 `pip install mbridge==0.15.1 torch_npu==2.8.0` 安装）
- **推理框架**：vLLM v0.13.0 + vllm-ascend releases/v0.13.0
- **训练框架**：MindSpeed (2.3.0_core_r0.12.1) + Megatron-LM core_v0.12.1
- **额外组件**：mbridge==0.15.1（固定版本）、transformers 4.57.6
- **verl 版本**：**release/v0.7.1**（固定发布版）
- **特殊说明**：
  - verl 使用 `git submodule update --init --recursive --remote` 拉取子模块
  - 对 mbridge 中 DeepSeek V3 的 dequant 脚本打 `cuda→npu` patch（第 34、51 行）

#### `Dockerfile.ascend_8.5.0_a3_v0.7.1`

- **基础镜像**：`ascendhub/cann:8.5.0-a3-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910（A3，SOC `ascend910_9392`）
- **PyTorch**：torch_npu 2.8.0（通过 mbridge 间接安装）
- **推理框架**：vLLM v0.13.0 + vllm-ascend releases/v0.13.0（启用 `COMPILE_CUSTOM_KERNELS=1`）
- **训练框架**：MindSpeed (2.3.0_core_r0.12.1) + Megatron-LM core_v0.12.1
- **额外组件**：mbridge、transformers 4.57.6
- **verl 版本**：**release/v0.7.1**（固定发布版）
- **特殊说明**：同 A2 v0.7.1，含 DeepSeek cuda→npu patch

#### `Dockerfile.ascend.sglang_8.5.0_a2`

- **基础镜像**：`ascendhub/cann:8.5.0-910b-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910B（A2）
- **PyTorch**：torch 2.8.0 + torch_npu-2.8.0.post2 + torchvision 0.23.0
- **推理框架**：SGLang v0.5.10 + sgl-kernel-npu 预编译包（`2026.02.01`，cann8.5.0-910b）
- **训练框架**：MindSpeed (core_r0.16.0) + Megatron-LM core_r0.16.0
- **额外组件**：mbridge、triton-ascend（osinfra.cn）、click 8.2.1、nvtx、opencv-python-headless
- **verl 版本**：latest main（**注意：从 `volcengine/verl` 克隆，非 `verl-project/verl`**）
- **特殊说明**：sgl-kernel-npu 使用预发布的 zip 包（含 torch_memory_saver、sgl_kernel_npu、deep_ep whl）

#### `Dockerfile.ascend.sglang_8.5.0_a3`

- **基础镜像**：`ascendhub/cann:8.5.0-a3-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910（A3）
- **PyTorch**：torch 2.8.0 + torch_npu-2.8.0.post2 + torchvision 0.23.0
- **推理框架**：SGLang v0.5.10 + sgl-kernel-npu 预编译包（`2026.02.01`，cann8.5.0-a3）
- **训练框架**：MindSpeed (core_r0.16.0) + Megatron-LM core_r0.16.0
- **额外组件**：mbridge、triton-ascend（osinfra.cn）
- **verl 版本**：latest main（同为 `volcengine/verl`）
- **特殊说明**：与 A2 SGLang 版本除 sgl-kernel-npu 包名（`-a3-` 后缀）外完全相同

---

### CANN 8.5.2 系列（Qwen3-5 专版）

> 这两个镜像以 CANN 8.5.1 基础镜像为起点，在构建过程中**在线升级**到 CANN 8.5.2，是专为 Qwen3-5 系列模型优化的固定版本镜像。

#### `Dockerfile.ascend_8.5.2_a2_qwen3-5`

- **基础镜像**：`ascendhub/cann:8.5.1-910b-ubuntu22.04-py3.11`（构建中升级到 8.5.2）
- **目标芯片**：Ascend 910B（A2，SOC `ascend910b1`）
- **PyTorch**：torch 2.9.0 + torch_npu 2.9.0 + torchvision 0.24.0 + accelerate 1.13.0
- **推理框架**：vLLM v0.18.0 + vllm-ascend (commit `54879467`)
- **训练框架**：MindSpeed (core_r0.16.0) + Megatron-LM core_r0.16.0 + Megatron-Bridge (commit `de93536e`)
- **额外组件**：transformers (commit `cc7ab9be`)、mathruler
- **verl 版本**：**固定 commit** `4045d67063052dcb800c918c107b8d5a87046006`
- **特殊说明**：
  - 构建时动态下载并安装 `Ascend-cann-toolkit_8.5.2`、`Ascend-cann-910b-ops_8.5.2`、`Ascend-cann-nnal_8.5.2` 三个 .run 包（完成 8.5.1→8.5.2 升级）
  - 设置 `MAX_JOBS=1`、`MAKEFLAGS="-j1"`、`CMAKE_BUILD_PARALLEL_LEVEL=1` 防止 vllm-ascend 并发编译失败
  - Megatron-Bridge 通过 `--no-deps --no-build-isolation` 安装（`de93536e` 固定 commit）

#### `Dockerfile.ascend_8.5.2_a3_qwen3-5`

- **基础镜像**：`ascendhub/cann:8.5.1-a3-ubuntu22.04-py3.11`（构建中升级到 8.5.2）
- **目标芯片**：Ascend 910（A3，SOC `ascend910_9392`）
- **PyTorch**：torch 2.9.0 + torch_npu 2.9.0 + torchvision 0.24.0 + accelerate 1.13.0
- **推理框架**：vLLM v0.18.0 + vllm-ascend (commit `54879467`)
- **训练框架**：MindSpeed (core_r0.16.0) + Megatron-LM core_r0.16.0 + Megatron-Bridge (commit `de93536e`)
- **额外组件**：transformers (commit `cc7ab9be`)、mathruler
- **verl 版本**：**固定 commit** `4045d67063052dcb800c918c107b8d5a87046006`
- **特殊说明**：升级时 A3 芯片 ops 包为 `Ascend-cann-A3-ops_8.5.2`（A2 版使用 `910b-ops`），其余与 A2 版相同

---

### CANN 9.0.0 系列（最新版本）

#### `Dockerfile.ascend_9.0.0_a2`

- **基础镜像**：`ascendhub/cann:9.0.0-910b-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910B（A2，SOC `ascend910b1`）
- **PyTorch**：通过 vllm-ascend requirements 安装；x86_64 为 torch 2.9.0+cpu + torchvision 0.24.0+cpu
- **推理框架**：vLLM v0.18.0 + vllm-ascend releases/v0.18.0（启用 `COMPILE_CUSTOM_KERNELS=1`）
- **训练框架**：MindSpeed (core_r0.16.0) + Megatron-LM core_r0.16.0
- **额外组件**：mbridge、transformers (commit `cc7ab9be`)、nvidia-modelopt≥0.37.0、flash-linear-attention 0.5.0、qwen_vl_utils、viztracer、mathruler
- **verl 版本**：latest main
- **特殊说明**：
  - 相比 8.x 系列，增加了 nvidia-modelopt（量化工具）、flash-linear-attention、qwen_vl_utils（多模态）等
  - 对 mbridge 中 DeepSeek V3 dequant 脚本打 `cuda→npu` patch

#### `Dockerfile.ascend_9.0.0_a3`

- **基础镜像**：`ascendhub/cann:9.0.0-a3-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910（A3，SOC `ascend910_9392`）
- **PyTorch**：通过 vllm-ascend requirements 安装；x86_64 为 torch 2.9.0+cpu + torchvision 0.24.0+cpu
- **推理框架**：vLLM v0.18.0 + vllm-ascend releases/v0.18.0（启用 `COMPILE_CUSTOM_KERNELS=1`，`--no-build-isolation --no-deps`）
- **训练框架**：MindSpeed (core_r0.16.0) + Megatron-LM core_r0.16.0
- **额外组件**：mbridge、transformers (commit `cc7ab9be`)、nvidia-modelopt≥0.37.0、flash-linear-attention 0.5.0、qwen_vl_utils、viztracer、mathruler
- **verl 版本**：latest main
- **特殊说明**：与 A2 版本结构完全一致，仅基础镜像和 CANN 库路径不同；同样包含 DeepSeek cuda→npu patch

#### `Dockerfile.ascend_9.0.0_a2_v0.8.0`

- **基础镜像**：`ascendhub/cann:9.0.0-910b-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910B（A2，SOC `ascend910b1`）
- **PyTorch**：通过 vllm-ascend requirements；x86_64 为 torch/torchvision 2.9.0+cpu
- **推理框架**：vLLM v0.18.0 + vllm-ascend releases/v0.18.0
- **训练框架**：MindSpeed (core_r0.16.0) + Megatron-LM core_r0.16.0 + **Megatron-Bridge** (commit `de93536e`)
- **额外组件**：mbridge、transformers (commit `cc7ab9be`)、nvidia-modelopt≥0.37.0、flash-linear-attention 0.5.0、qwen_vl_utils、viztracer、mathruler
- **verl 版本**：**release/v0.8.0**（固定发布版）
- **特殊说明**：
  - 相比 `9.0.0_a2`，增加了 Megatron-Bridge（NeMo 桥接组件），并设置 `PYTHONPATH=/Megatron-Bridge/src`
  - verl 使用 `git submodule update --init --recursive --remote`
  - 含 DeepSeek cuda→npu patch

#### `Dockerfile.ascend_9.0.0_a3_v0.8.0`

- **基础镜像**：`ascendhub/cann:9.0.0-a3-ubuntu22.04-py3.11`
- **目标芯片**：Ascend 910（A3，SOC `ascend910_9392`）
- **PyTorch**：通过 vllm-ascend requirements；x86_64 为 torch/torchvision 2.9.0+cpu
- **推理框架**：vLLM v0.18.0 + vllm-ascend releases/v0.18.0
- **训练框架**：MindSpeed (core_r0.16.0) + Megatron-LM core_r0.16.0 + **Megatron-Bridge** (commit `de93536e`)
- **额外组件**：mbridge、transformers (commit `cc7ab9be`)、nvidia-modelopt≥0.37.0、flash-linear-attention 0.5.0、qwen_vl_utils、viztracer、mathruler
- **verl 版本**：**release/v0.8.0**（固定发布版）
- **特殊说明**：与 A2 v0.8.0 版本完全一致，仅基础镜像和 CANN 库路径不同；同样设置 `PYTHONPATH=/Megatron-Bridge/src`

---

## 四、选型建议

### 按芯片型号选择

- **Ascend 910B / 910B1（A2 架构）**：选文件名含 `_a2` 或 `_910b` 的镜像
- **Ascend 910（A3 架构，9392 系列）**：选文件名含 `_a3` 的镜像

### 按 CANN 版本选择

| 场景 | 推荐 CANN |
|------|-----------|
| 追求最新特性 + 最广模型支持 | **9.0.0** |
| 稳定性优先，已验证的生产环境 | **8.5.0** 或 **8.5.2** |
| 老版本硬件/软件栈兼容 | 8.2.rc1 / 8.3.rc1 |
| Qwen3-5 模型专用 | **8.5.2**（`_qwen3-5` 镜像） |

### 按推理框架选择

| 场景 | 框架 |
|------|------|
| 通用 RLHF 训练推理 | **vLLM**（覆盖所有 CANN 版本） |
| 需要更高吞吐 / 连续批处理 | **SGLang**（仅 8.3.rc1 和 8.5.0） |

### 按 verl 版本选择

- **latest main**：功能最新，适合实验和开发
- **release/v0.7.1**：`8.5.0_a2_v0.7.1` / `8.5.0_a3_v0.7.1`，稳定已发布版本
- **release/v0.8.0**：`9.0.0_a2_v0.8.0` / `9.0.0_a3_v0.8.0`，最新稳定发布版，含 Megatron-Bridge

### 快速决策

```
有 A2 芯片 + 想跑最新 verl main → Dockerfile.ascend_9.0.0_a2
有 A3 芯片 + 想跑最新 verl main → Dockerfile.ascend_9.0.0_a3
有 A2 芯片 + 需要稳定 v0.8.0   → Dockerfile.ascend_9.0.0_a2_v0.8.0
有 A3 芯片 + 需要稳定 v0.8.0   → Dockerfile.ascend_9.0.0_a3_v0.8.0
需要跑 Qwen3-5 模型            → Dockerfile.ascend_8.5.2_a2_qwen3-5 / _a3_qwen3-5
需要 SGLang 推理               → Dockerfile.ascend.sglang_8.5.0_a2 / _a3
```

---

## 五、关键组件版本演进

| 组件 | 8.2.rc1 | 8.3.rc1 | 8.5.0 | 8.5.2 | 9.0.0 |
|------|---------|---------|-------|-------|-------|
| PyTorch | 2.5.1 | 2.7.1 | 2.8.0~2.9.0 | 2.9.0 | 2.9.0 |
| vLLM | v0.9.1 | v0.11.0 | v0.13.0~v0.18.0 | v0.18.0 | v0.18.0 |
| MindSpeed | f2b0977e | f2b0977e | 2.3.0_core_r0.12.1 | core_r0.16.0 | core_r0.16.0 |
| Megatron-LM | core_v0.12.1 | core_v0.12.1 | core_v0.12.1 | core_r0.16.0 | core_r0.16.0 |
| Megatron-Bridge | ✗ | ✗ | ✗（v0.7.1 有）| ✓ | ✓（v0.8.0） |
| transformers | —— | 4.57.6 | 4.57.6 | cc7ab9be | cc7ab9be |

> **注**：`—` 表示该版本未明确指定，由依赖链决定；`✗` 表示未包含；`✓` 表示包含。
