# 原始测试数据

每次正式测试写入一个全新的 `<session_id>/`。该目录保存逐请求、逐轮、资源时间序列、功能用例、错误以及 SHA-256 清单，是报告的真相源。

- 不要手工修改已经完成的 Session。
- `session_info.json` 必须为 `PASS`，运行内 `run_info.status` 必须为 `COMPLETE`。
- `baselines/` 只保存小体积的历史汇总，用于变更前后对照；不得冒充新配置结果。
- `single/` 保存手动一键单配置结果；顶层 `result.json` 是直接交付文件。
- `diagnostics/` 保存冒烟或中止证据；这些目录不得进入正式报告。
- 本目录默认被 Git 忽略，迁移测试工具时不需要复制历史原始结果。
