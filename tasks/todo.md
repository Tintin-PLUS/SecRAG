# SecRAG 性能测试执行任务

## Phase 1: Foundation

- [x] 建立测试计划、脚本与自检基础结构。
- [x] 先写数据汇总/完整性校验自检，再实现最小代码使其通过。
- [x] 增加调用现有 `benchmark::run` 的 Rust CLI。
- [x] 验证 Python 自检和 Rust focused test/build。

## Phase 2: Script Freeze

- [x] 实现环境采集和 storage benchmark 顺序矩阵。
- [x] 实现 embedding 服务编排、逐题质量/延迟和进程树资源采样。
- [x] 实现本地建库、增量扫描、文件监听、删除级联与 Mock 检索闭环。
- [x] 实现每轮 `run_result.json`、`manifest.json` 和总报告。
- [x] 实现五类对比图和熵权主图；图表数据只来自本轮 JSON。
- [x] 完善 `performance-test/README.md`。
- [x] 完成脚本自检和隔离冒烟；此后正式测试期间不改脚本。

## Phase 3: Formal Tests

- [x] 顺序运行环境采集。
- [x] 顺序运行 Rust storage benchmark。
- [x] 顺序运行三个真实模型；不并行测试。
- [x] 校验所有结果并生成汇总报告。
- [x] 记录失败、未测能力和适用边界。
