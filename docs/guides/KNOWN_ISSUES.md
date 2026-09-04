# Known Issues

1. **Vector Store 是 fallback。** 当前 SQLite BLOB + Rust cosine 为 O(N·D)，适合 Demo 与接口验证，不适合大规模低延迟检索。sqlite-vec 尚未接入。
2. **Mock 不代表语义效果。** 确定性字符 n-gram hashing 只帮助验证流程，不能用于模型选型或业务准确率结论。
3. **解析格式有限。** 仅支持 UTF-8 `.md`/`.txt`；PDF、Word、图片、扫描件和非 UTF-8 编码尚未实现。
4. **Watcher 仅在当前进程。** 需要在文件页启动，应用重启后不会自动恢复；网络盘和编辑器原子替换行为需额外测试。
5. **数据库连接模型偏简单。** 单个 `rusqlite::Connection` 由 Mutex 保护，足够 Demo；高并发应改为连接池/读写分离并细化事务。
6. **索引完成度未按 Chunk 百分比计算。** 外部批量可只导入部分 Chunk，`INDEXED` 表示该批成功，不代表所有当前 Chunk 都覆盖；后续应增加 coverage 统计与 `PARTIAL`。
7. **DeepSeek 出域风险。** 用户配置 DeepSeek 后，检索 Context 会发送至 `api.deepseek.com`；原型未实现脱敏、审批、域名白名单或 DLP。
8. **DeepSeek API Key 存储仍是开发方案。** Key 从环境变量或已被 Git 忽略的 `.env` 读取，未集成 Windows Credential Manager；不要在多人共享 PC 上长期明文保存。
9. **DeepSeek 模型名是外部变化项。** 当前配置依据官方 `deepseek-v4-flash` / `deepseek-v4-pro`；服务升级后需重新核对官方模型列表。
10. **无安装包签名。** `bundle.active=false`，当前验收面向开发运行；正式部署需要代码签名、安装包和企业 WebView2 策略验证。
11. **Benchmark 是微基准。** UI 基准仍只覆盖 SQLite Insert/Read 与 Vector Insert/Search；真实 Embedding Load/Throughput 需要按 `PERFORMANCE_TESTING.md` 外部采样。
12. **删除知识库不可撤销。** UI 目前没有二次确认或回收站；只删除数据库记录，不删除用户原始目录。
13. **前端路径选择为文本输入。** 当前未引入文件对话框插件；用户需粘贴绝对路径。
14. **Python 和模型不随项目自动安装。** 用户必须创建 `.venv`、安装依赖并准备模型目录；这是为了避免静默下载和不可控部署。
15. **模型配置清单是人工信任边界。** 自定义 `LOCAL_KB_MODEL_*` 路径必须确实指向对应模型；当前只校验输出维度，尚未计算完整权重目录哈希。
16. **Sidecar HTTP 使用 JSON float 数组。** 大批量向量会产生序列化开销；当前默认 Rust batch 为 32，生产评估后可换二进制协议。
17. **建索引批次推理完成后统一写库。** 中途模型失败不会写入新批次，但大知识库会暂存全部输出，后续应实现 staging/原子切换。

优先级建议：先补充模型目录哈希与 Vector coverage/PARTIAL 状态，再评估 sqlite-vec，随后补充敏感数据治理、Windows 凭据存储、格式解析和正式打包。
