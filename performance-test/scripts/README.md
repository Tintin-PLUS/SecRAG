# 脚本说明

| 文件 | 用途 |
|---|---|
| `retest_suite.py` | 唯一正式/冒烟测试入口，阶段严格顺序执行 |
| `single_retrieval.py` | 接收单组模型/切分/Top-K，输出顶层 `result.json` |
| `generate_retest_report.py` | 只读原始 Session，生成报告、聚合 JSON 和 8 张 SVG |
| `benchmark_utils.py` | 原子 JSON、分位数和 SHA-256 公共函数 |
| `validate_session.py` | 用 Python 验收深层 JSON，避免 Windows PowerShell 解析限制 |
| `run_suite.py` | 仅供执行器导入的进程监控与质量计算底层函数；不可直接运行 |
| `monitor_processes.ps1` | 按本轮 PID 采集 CPU、Working Set、Private Bytes |
| `prepare.ps1` | 在新电脑上执行单元测试、语法检查和 Release 构建 |

所有路径从仓库根目录推导，不依赖当前电脑的用户名或盘符。模型从 Hugging Face 本地缓存加载，正式测试强制离线模式。
