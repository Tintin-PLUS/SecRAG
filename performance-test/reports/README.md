# 报告与图片

报告生成器将每个 Session 输出到独立子目录：

```text
reports/<session_id>/
├── 端侧知识库技术选型与轻量化验证报告-原始34题.md
├── report_data.json
├── charts/       # SVG 原图
└── previews/     # PNG 预览（可选）
```

报告只从 `results/<session_id>/run_result.json` 聚合，不允许手填指标。该目录默认被 Git 忽略；需要归档时连同对应原始 Session 一起保存。

