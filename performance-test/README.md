# performance-test：端侧知识库技术选型测试

本目录存放"端侧知识库技术选型测试方案"及其配套记录模板，服务于课题交付物之一《端侧知识库技术选型对比分析报告》。

## 内容

| 文件 | 用途 |
|---|---|
| `端侧知识库技术选型测试方案.md` | 测试方案主文档：测试目标与边界、环境基线、可复现语料、通用指标定义、测试矩阵、既往数据复核、sqlite-vec 对照（必做）、结果模板、判读边界、执行清单 |
| `results-template.csv` | 汇总结果记录表（对应测试方案第 8 节模板），便于逐场景填写与对比 |
| `quality-results.csv` | 检索质量汇总记录表（Hit@k / MRR@k / nDCG@k / Recall@k / Precision@k） |

## 使用建议

1. 先按测试方案第 2 节记录环境基线。
2. 逐行填入 `results-template.csv` 与 `quality-results.csv`；每次正式测试一行。
3. 原始 CSV / 日志放性能负责人自己的测试目录（`local-kb/data/experiments/<run_id>/`、`embedding-test/data/<run_id>/`），不提交 Git，也不包含本地路径、真实文档或密钥。
4. 结论引用必须区分来源：官方资料 / 代码检查 / 实际测试。

## 关联文档

- 框架内置微基准：`../docs/guides/PERFORMANCE_TESTING.md`
- 检索质量评测子项目：`../embedding-test/`
- 向量存储设计：`../docs/guides/VECTOR_STORE.md`
- 向量模型口径说明：`../docs/guides/EMBEDDING_INTEGRATION.md`
