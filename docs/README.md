# 文档导航

仓库文档按“基础设施、训练实验、CreateMyCard 数据链路”三个主题组织。可执行代码和局部操作说明保留在对应模块目录，跨模块规范统一放在 `docs/`。

## 基础设施

- [verl Docker 目录与 Ascend NPU 镜像指南](ASCEND_DOCKER_GUIDE.md)
- 容器启动、环境检查和离线镜像拉取的常用命令见[仓库 README](../README.md)。

## Qwen3.6 GSM8K

- [全参数 SFT 流程](qwen36_gsm8k_sft.md)
- [GRPO 21-step 验证报告](qwen36_gsm8k_grpo_validation.md)
- [veRL 训练入口](../frameworks/verl/qwen36_gsm8k/README.md)

## CreateMyCard

- [业务总览与运行入口](../frameworks/verl/create_my_card/README.md)
- [数据生产交接说明](create_my_card/data-production-handoff.md)
- [数据质检规范](create_my_card/data-quality-spec.md)
- [Expression Profile v1](create_my_card/expression-profile-v1.md)

CreateMyCard 的正逆向转换器、SFT 数据构建脚本和源数据属于可执行模块，放在 `frameworks/verl/create_my_card/`；本目录只维护跨批次稳定的数据合同与验收规范。
