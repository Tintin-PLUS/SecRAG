# SecRAG 文档索引

除仓库根目录 `README.md` 和运行所需的 `local-kb/sample_docs` 外，项目说明文档统一放在本目录。

## 开发与使用

- [项目指南](guides/PROJECT_GUIDE.md)
- [系统架构](guides/ARCHITECTURE.md)
- [真实 Embedding 运行清单](guides/EMBEDDING_RUNTIME_SETUP.md)
- [Embedding 对接协议](guides/EMBEDDING_INTEGRATION.md)
- [DeepSeek 对接](guides/DEEPSEEK_INTEGRATION.md)
- [Vector Store](guides/VECTOR_STORE.md)
- [SQLite Schema](guides/SQLITE_SCHEMA.md)
- [性能测试](guides/PERFORMANCE_TESTING.md)
- [已知问题](guides/KNOWN_ISSUES.md)
- [项目交接](guides/HANDOFF.md)

## 端侧知识库技术选型测试

技术选型对比所需的完整测试方案、通用指标定义、测试矩阵与结果记录模板统一放在仓库根目录的 [`performance-test/`](../performance-test/)，主文档为 `performance-test/端侧知识库技术选型测试方案.md`。本文 `guides/PERFORMANCE_TESTING.md` 侧重框架内置微基准的运行方式，二者互补。

## 项目原始资料

- [项目构建需求](project/PROJECT_REQUIREMENTS.txt)
- [环境说明](project/ENVIRONMENT_NOTES.txt)
- [使用流程记录](project/USAGE_PROCEDURE.txt)

文档中的代码相对路径默认从 `local-kb` 目录开始；仓库安装和启动入口以根目录 [README](../README.md) 为准。
