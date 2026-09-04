# Performance Testing

本文件交给性能负责人。当前框架提供 SQLite Read、Vector Insert、Vector Search 微基准，并已具备 Python Sidecar 真实 Embedding 的 Load/Batch 测量入口。

## 启动

GUI：`npm.cmd run tauri dev` → “性能测试”页 → 选择 100/1000/10000 Chunk 与维度 → 运行。数据使用隔离的内存 SQLite，不污染 `data/local-kb.sqlite3`。

后端入口：`src-tauri/src/benchmark/mod.rs::run(chunk_count, dimension)`；Tauri 命令：`run_benchmark`。建议未来增加 Criterion binary 时复用相同数据生成约定。

## 固定测试矩阵

每台机器至少测试：

| Chunk | Dimension | Insert | Search Top-5 | Search Top-10 | SQLite Read |
|---:|---:|---:|---:|---:|---:|
| 100 | 64 / 模型真实维度 | ✓ | ✓ | ✓ | ✓ |
| 1,000 | 64 / 模型真实维度 | ✓ | ✓ | ✓ | ✓ |
| 10,000 | 64 / 模型真实维度 | ✓ | ✓ | ✓ | ✓ |

每个组合预热 3 次，正式运行至少 10 次，记录 median、P95、min/max。关闭大型后台任务，记录是否接电、Windows 电源模式和温度/降频情况。

## 指标定义

- **Vector Insert：** 构造完成后，从 batch insert 开始到事务提交完成；报告 ms、vectors/s。
- **Search Top-K：** 从调用 Store 到获得已排序结果；报告 ms、queries/s。当前 fallback 为 O(N·D)。
- **SQLite Read：** 单 Chunk 主键读取延迟，仅作环境基线。
- **Incremental Update：** 修改一份固定大小文档，从事件/手动扫描开始到新 Chunk 写入、旧 Vector 删除、Index STALE；报告 ms 和受影响 Chunk。
- **Embedding Service Start：** 点击启动到 `/health` 返回协议 1；该时间不包括模型加载。
- **Embedding Model Load：** 第一次索引请求开始到日志出现 `loaded <model>`，或首批请求返回。
- **Batch Embedding：** 预分词策略固定，报告 texts/s、tokens/s、P50/P95 和 batch size。
- **CPU：** 测试期间 process CPU 平均/P95 与峰值。
- **RAM：** working set 与 private bytes 的基线、峰值、结束后稳态。

## Incremental Update 测试

1. 创建专用知识库并扫描 1000 Chunk 数据集，生成 Mock/真实 Index。
2. 记录修改前 Document/Chunk/Vector 数与目标文件 hash。
3. 只修改一个文件，运行手动扫描和 watcher 两种场景。
4. 验证只有目标 Document 的 Chunk ID 变化，旧 Vector 已删除，其他文档 ID/Chunk/Vector 不变，Profile 为 STALE。
5. 删除该文件并扫描，验证 Document/Chunk/Vector 级联清理。

## CPU/RAM 采集建议

可使用 Windows Performance Monitor 或 PowerShell `Get-Process` 定时采样目标进程。采样间隔建议 500 ms；记录 `CPU` 累计差分、`WorkingSet64`、`PrivateMemorySize64`。采样脚本与原始 CSV 应放在性能负责人自己的测试目录，不提交含本地路径或敏感文档的数据。

## 结果模板

```text
Date / Git commit:
Machine / CPU / cores / RAM:
Windows version / power mode:
Rust / Node version:
Vector store implementation:
Embedding model / version / config_hash (or Mock):
Dimension / normalize / pooling / precision:
Dataset / chunk_size / overlap / chunk count:

Scenario | N | Batch | Repetitions | Median ms | P95 ms | Throughput | Peak CPU | Peak RAM | Notes
Insert   |   |       |             |           |        |            |          |          |
Top-5    |   |       |             |           |        |            |          |          |
Top-10   |   |       |             |           |        |            |          |          |
Update   |   |       |             |           |        |            |          |          |
```

## 判读边界

Mock 结果只能比较框架与存储，不用于推断真实模型吞吐或检索准确率。内存 SQLite 结果用于稳定微基准；正式结论还需用磁盘数据库重复测试。接入 sqlite-vec 后必须保留相同数据、维度、Top-K 和机器矩阵，分别报告，不覆盖 fallback 基线。
