# Project Guide

## 开发环境

- Windows 10/11 x86_64；只使用 `stable-x86_64-pc-windows-msvc`。
- Node.js 22.12+（推荐 24 LTS）与 npm；若 PowerShell 阻止 `npm.ps1`，始终使用 `npm.cmd`。
- Visual Studio Build Tools（Desktop development with C++）、Windows SDK、WebView2。
- 项目可以放在任意不含受限权限的本地目录，不需要 SQLite Server 或账号。
- 真实 Embedding 另需 Python 3.10–3.12、项目 `.venv`、`sentence-transformers` 和至少一个本地模型；详见 `EMBEDDING_RUNTIME_SETUP.md`。

核验命令：

```powershell
rustc --version
cargo --version
rustup show
node --version
npm.cmd --version
```

## 构建、测试和启动

```powershell
cd <仓库目录>\local-kb
npm.cmd ci
npm.cmd run build
cd src-tauri
cargo check --locked
cd ..
npm.cmd run tauri dev
```

前端 Vite 开发端口为 1420。`npm.cmd run tauri dev` 会同时启动 Vite 与 Rust/Tauri。生产前端产物为 `dist/`。

## 前后端交互

前端统一通过 `src/api/tauri.ts` 的 `call()` 调用 `src-tauri/src/commands/mod.rs`。参数在 TypeScript 使用 camelCase，例如 `knowledgeBaseId`，Tauri 映射到 Rust 的 `knowledge_base_id`。新增命令需要：

1. 在 `commands/mod.rs` 定义 `#[tauri::command]`；
2. 在 `lib.rs` 的 `generate_handler!` 注册；
3. 在 `src/types` 增加返回类型；
4. 在 UI 调用并显示后端错误。

前端不得直接读取 SQLite，Rust Command 也应委托给领域 Service，而不是堆积业务规则。

## Demo 操作

1. 知识库页创建 `sample_docs` 知识库。
2. 文件页重新扫描，确认 6 份文档和 Chunk 为 `WAITING_EMBEDDING`。
3. 无模型时生成 Mock Index；真实流程则启动 Sidecar、选择已准备模型并点击“为全部 Chunk 建立索引”。
4. 检索页选择与索引相同的真实模型验证 Top-K；也可使用 Mock 或 Raw Vector。
5. RAG 页选择相同真实模型验证 Context；配置 LLM 后验证外部回答。
6. 修改一个样例文件并重新扫描：只有该文档 Chunk 更新，Profile 变 `STALE`。
7. 性能页运行 100/1000/10000 Chunk 隔离基准。

## 数据、日志、配置

- SQLite：`data/local-kb.sqlite3`。
- 模型：`models/`，由用户或管理员手工准备，权重不入 Git。
- Python Sidecar：`embedding-service/server.py`；运行日志：`logs/embedding-service.log`。
- `.env`：Rust 会直接读取项目根目录文件；修改后重启应用。
- 模拟文档：`sample_docs/`；不要替换为内部敏感材料提交。
- DeepSeek：`LOCAL_KB_LLM_BASE_URL`、`LOCAL_KB_LLM_MODEL`、`DEEPSEEK_API_KEY`、thinking/timeout 配置，详见 `DEEPSEEK_INTEGRATION.md`。
- 默认 Chunk：500 字符、80 overlap，在创建知识库时可覆盖。
- Rust 日志目前写标准输出；Sidecar 写入 `logs/embedding-service.log`，日志目录已从 Git 排除。

## Debug

- 后端：在 `src-tauri` 运行 `cargo check --locked`，排错时可设置 `RUST_BACKTRACE=1`。
- 前端：先运行 `npm.cmd run build` 捕获 TypeScript 错误，再使用 WebView DevTools。
- SQLite：使用任意只读 SQLite 客户端执行 `SQLITE_SCHEMA.md` 的诊断 SQL。
- `WAITING_EMBEDDING`：正常状态，表示尚无 Vector；生成 Mock 或导入外部 Vector。
- `STALE`：文档或 Embedding Space 已变化，需要对当前 Chunk 重建 Vector。
- Raw Search 维度错误：选择对应 Profile，并确保数组长度等于 `dimension`。
- Sidecar 启动/模型加载错误：先看 Embedding 页面状态，再检查 `logs/embedding-service.log`。

## 安全注意事项

`.gitignore` 排除 `data/`、`models/`、日志、数据库、`.env` 和构建产物。DeepSeek API Key 只从环境或 `.env` 进入 Rust 进程，不在响应中回传。原始文件只在本地读取；只有用户明确配置 DeepSeek 并点击 RAG 时，拼装后的 Context 才会发送到 DeepSeek，因此正式使用前必须完成数据分级与出域审查。
