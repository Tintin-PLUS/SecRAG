# Implementation Plan: SecRAG 性能与轻量化验证工具链

## Overview

在 `performance-test/` 内建立自包含、顺序执行的测试工具链，复用 `local-kb` 的 Rust 存储微基准和 `embedding-test` 的真实模型/题集。脚本开发与正式性能测试严格分阶段：脚本冻结并通过自检后，才启动正式测试；测试期间不修改脚本或并行执行其他 benchmark。

## Architecture Decisions

- 使用 Python 标准库作为主编排器，避免新增依赖；Windows 资源采样使用 PowerShell 原生命令。
- 在 `local-kb/src-tauri` 增加一个最小 CLI binary，直接调用现有 `benchmark::run`，避免复制 Rust 存储实现。
- 每个正式轮次输出 `run_result.json` 和 `manifest.json`；汇总报告由原始 JSON 生成，不使用截图作为数据源。
- `embedding-test/result` 图片只作功能参考，不进入本机基线或推荐结论。
- 本轮覆盖环境、Rust 存储微基准、三模型检索质量/延迟，以及本地 SQLite、Rust Mock、增量扫描、文件监听、删除级联和本地检索闭环；物理断网与桌面 UI 人工验收仍明确记录为未自动化，不伪造通过状态。

## Task List

### Phase 1: Foundation

- [x] Task 1: 建立有序目录、数据契约和校验自检
- [x] Task 2: 增加 Rust 存储微基准 CLI 并验证 JSON 输出

### Checkpoint: Foundation

- [x] Python 自检通过
- [x] Rust focused test/build 通过
- [x] 未启动正式性能测试

### Phase 2: Benchmark Runners

- [x] Task 3: 实现环境采集、存储矩阵编排和完整性清单
- [x] Task 4: 实现 embedding-test 服务生命周期、质量/延迟采集和资源采样
- [x] Task 4a: 实现 local-kb 本地闭环与增量更新验证
- [x] Task 5: 实现顺序总入口、汇总报告和使用说明
- [x] Task 5a: 从同一份 JSON 自动生成五类对比图和熵权主图

### Checkpoint: Script Freeze

- [x] 全部脚本自检和构建通过
- [x] 示例/探针输出不混入正式结果
- [x] 通过每轮 SHA-256 与配置快照记录脚本冻结状态和运行参数（当前环境不允许写入 `.git`，未建立冻结提交）

### Phase 3: Formal Tests

- [x] Task 6: 顺序运行本机环境与 Rust 存储矩阵
- [x] Task 7: 顺序运行 bge-small、m3e-base、bge-m3 检索测试
- [x] Task 8: 校验每轮 JSON、生成 manifest 与本机结果摘要

### Checkpoint: Complete

- [x] 所有有效轮次可重新解析和重算汇总
- [x] 失败/未测项目如实记录
- [x] 结果目录结构清晰，原始数据与报告分离
- [x] 技术选型、轻量性能、检索质量、功能闭环、选型结论各有至少一张图
- [x] 熵权主图已生成且标注相对评分边界

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 三个模型 CPU 测试耗时较长 | 中 | 模型和 Top-K 顺序执行；先探针后正式轮次 |
| 模型缓存或端口状态异常 | 高 | 启动前检查缓存和 8901/8902；只终止本轮启动的进程 |
| 现有评测会清空实验数据库 | 高 | 只使用 `embedding-test/data/knowledge.db`，运行前记录路径和用途 |
| 当前微基准单次测量 | 中 | CLI 重复调用并保存每个独立样本，不伪造单次 P95 |
| 图片结果来自其他电脑 | 高 | 不导入任何数值，仅作功能参考 |
| 物理断网与桌面 UI 未自动化 | 中 | 标记 `NOT_RUN` 和原因，避免将计划项写成实测通过 |

## Open Questions

- 无阻塞问题；使用当前缓存的三个模型和当前办公 PC 作为本轮实测环境。
