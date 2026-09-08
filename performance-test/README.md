# performance-test：端侧知识库配置选型

本目录回答“如何为轻量化计划选择合适配置”。它不测试外部大模型，也不比较硬件升级前后。`embedding-test/result` 中其他电脑的截图只作功能参考，不进入基线、评分或图表。

## 目录与真相源

| 路径 | 说明 |
|---|---|
| `性能测试执行基准.md` | 必测指标与执行约束 |
| `端侧知识库技术选型与轻量化验证计划.md` | 五部分验证计划 |
| `config/` | 正式与冒烟矩阵，详见子目录 README |
| `scripts/` | 执行、报告及公共代码，详见子目录 README |
| `tests/` | 自动化测试，详见子目录 README |
| `run_single_test.ps1` | 手动传参的一键单配置检索测试 |
| `run_formal_tests.ps1` | 完整正式矩阵与报告入口 |
| `results/<session_id>/` | 每轮完整原始 JSON、日志、资源序列及哈希清单 |
| `reports/<session_id>/` | Markdown 报告、聚合 JSON 和 8 张 SVG 图 |
| `results/baselines/` | 仅保存小体积历史汇总，不能代替本机重测 |

原始数据和报告默认由 `.gitignore` 排除；代码、配置、说明和小体积基线摘要可迁移。每轮使用新 Session ID，禁止覆盖已完成结果。

## 新电脑准备

要求 Windows、PowerShell、Rust/Cargo，以及可运行 Python 3.11+ 的环境。仓库中的脚本默认使用 `embedding-test/.venv`：

```powershell
python -m venv .\embedding-test\.venv
.\embedding-test\.venv\Scripts\python.exe -m pip install -r .\embedding-test\requirements.txt
powershell -ExecutionPolicy Bypass -File .\performance-test\scripts\prepare.ps1
```

三个 Hugging Face 模型必须提前下载到本机缓存。正式测试强制离线加载，避免网络抖动和远端服务混入结果。

## 执行顺序

先用冒烟配置检查链路；它不产生正式结论：

```powershell
.\embedding-test\.venv\Scripts\python.exe .\performance-test\scripts\retest_suite.py --config .\performance-test\config\retest_smoke.json --session-dir .\performance-test\results\smoke-check --phase all
```

确认后独占机器执行正式测试和报告：

```powershell
powershell -ExecutionPolicy Bypass -File .\performance-test\run_formal_tests.ps1 -SessionId 20260907-small-chunks-34q
```

脚本严格串行执行冷启动、批量嵌入、检索、存储、线程限额硬件估量和功能闭环。资源采样器只监控本轮进程，不是独立并发压测。不要同时运行 IDE 索引、杀毒全盘扫描、模型下载或其他性能任务。

报告可从已有完整 Session 单独重建：

```powershell
.\embedding-test\.venv\Scripts\python.exe .\performance-test\scripts\generate_retest_report.py --session-dir .\performance-test\results\<session_id> --output-dir .\performance-test\reports\<session_id>
```

## 手动一键单次测试

只想验证一个模型、一个 fixed 切分和一个 Top-K 时，直接传参：

```powershell
powershell -ExecutionPolicy Bypass -File .\performance-test\run_single_test.ps1 -ChunkSize 150 -Overlap 30 -Model bge-small -TopK 5
```

默认执行 3 轮、每轮至少 334 个请求、30 次预热、3 次建库，结果写入新的 `results/single/<时间戳>/result.json`。它仍使用 24 篇语料和原始 34 题，并保留逐请求延迟、逐题质量、资源峰值及 artifacts。

可调参数：`-Rounds`、`-RequestsPerRound`、`-Warmup`、`-BuildRepetitions`、`-Threads`、`-OutputDir`。例如快速检查自定义目录：

```powershell
powershell -ExecutionPolicy Bypass -File .\performance-test\run_single_test.ps1 -ChunkSize 100 -Overlap 20 -TopK 3 -Rounds 1 -RequestsPerRound 34 -BuildRepetitions 1 -OutputDir .\performance-test\results\single\manual-100-20
```

`Overlap` 必须满足 `0 <= overlap < chunk_size`；已有且非空的输出目录会被拒绝，脚本不会覆盖历史结果。单次入口只测“嵌入+建库+检索质量/性能”，不会额外跑冷启动矩阵、存储规模或功能闭环；完整选型仍使用正式入口。

## 完整性规则

每个 run 至少保存：

- `run_result.json`：环境、参数、逐轮逐请求延迟、质量明细、成功/失败、资源采样和汇总；
- `manifest.json`：本 run 文件的相对路径、大小和 SHA-256；
- `artifacts/`：本地服务日志、SQLite 数据库、资源原始数据等。

Session 根目录保存 `session_info.json` 和 `session_manifest.json`。正式 Session 必须是 `PASS`，run 必须是 `COMPLETE` 或显式带错误的 `COMPLETE_WITH_ERRORS`；失败样本不能静默丢弃。报告只从这些 JSON 聚合，不手填指标。

单次运行目录结构：

```text
results/single/<session_id>/
├── result.json                         # 直接交付的单次完整结果
├── session_info.json                   # 参数、语料哈希、环境、状态
├── session_manifest.json               # 全目录 SHA-256 清单
└── 01-retrieval-<model>-fixed-<x>-<y>/
    ├── run_result.json                 # 与 result.json 同源
    ├── manifest.json
    └── artifacts/                      # SQLite、日志和资源采样
```

## 当前切分矩阵

当前 fixed 矩阵按中文字符计数：`100/20`、`150/30`、`200/40`，另有结构切分上限 `200`。`fixed-150-30` 是跨模型比较基准；三组 fixed overlap 均为 20%。依据及单位差异见 `config/README.md`。

## 边界

- 质量题只使用 `embedding-test/eval/test_queries.json` 中最初的 34 题；扩充语料保留为干扰项，不新增题。
- 自动化闭环使用本地 SQLite、Rust Mock Embedding、真实本地嵌入、文件监听和增量更新；不调用外部大模型。
- 自动化离线策略不等同人工拔网，交付前仍可做一次物理断网复核。
- 最低硬件结论来自本机峰值、保守公式和线程限额，不冒充多台低端物理机实测。
