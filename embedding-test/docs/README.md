# 文档与测试资料索引

- [安装、模型下载、启动与评测](../README.md)：统一操作入口。
- [API说明](API.md)：HTTP请求和返回字段。
- [测试说明](EVALUATION.md)：题集、指标、运行边界和结果保存。
- [测试资料](../test_docs/)：12份MD样例，与`eval/test_queries.json`配套。

说明文档统一放在本目录，根目录保留入口README。`test_docs/`是程序运行需要的测试输入，保留在子项目根目录，与`eval/`并列，不归入说明文档；评测脚本和批量导入脚本均使用这个路径。

`src/`、`scripts/`和`eval/`保留代码位置。`requirements.txt`是依赖安装清单，`Cargo.lock`是Rust版本锁文件，应保留在根目录，不作为普通说明文档移动。
