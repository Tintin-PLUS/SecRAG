# Embedding Runtime Setup

本文是 Windows 手工运行清单。Rust、前端和 SQLite 不需要额外数据库服务；只有真实 Embedding 需要 Python 环境及本地模型权重。

## 1. 安装 Python 依赖

确认 `python --version` 为 Python 3.10–3.12，然后在普通 PowerShell 中执行：

```powershell
cd <仓库目录>\local-kb
powershell -ExecutionPolicy Bypass -File .\scripts\setup-embedding.ps1
```

脚本只创建 `.venv` 并安装 `sentence-transformers` 及其依赖，不会在离线模式下主动加载模型。CPU 运行不要求 CUDA。

## 2. 准备至少一个模型

最轻量的首选验证模型是 `bge-small`：

```powershell
cd <仓库目录>\local-kb
powershell -ExecutionPolicy Bypass -File .\scripts\download-embedding-model.ps1 -Model bge-small
```

该步骤需要能够访问模型源，会产生网络下载。也可以由管理员离线分发已经完整下载的 SentenceTransformer 模型目录到 `models\bge-small`，此时不要执行下载脚本。

其他可选模型：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download-embedding-model.ps1 -Model m3e-base
powershell -ExecutionPolicy Bypass -File .\scripts\download-embedding-model.ps1 -Model bge-m3
```

只需准备实际要使用的模型。模型目录已被 Git 忽略，不要提交权重。

## 3. 创建本地 `.env`

```powershell
Copy-Item .env.example .env
```

至少确认以下配置。未下载的模型路径可以留空：

```dotenv
LOCAL_KB_EMBEDDING_BASE_URL=http://127.0.0.1:8902
# 留空时自动使用 .venv\Scripts\python.exe
LOCAL_KB_EMBEDDING_PYTHON=
# 留空时自动使用 embedding-service\server.py
LOCAL_KB_EMBEDDING_SCRIPT=
LOCAL_KB_EMBEDDING_OFFLINE=1
LOCAL_KB_MODEL_BGE_SMALL=<仓库绝对路径>\local-kb\models\bge-small
LOCAL_KB_MODEL_M3E_BASE=
LOCAL_KB_MODEL_BGE_M3=
```

Rust 会读取项目根目录 `.env`，启动 Python 子进程时把模型配置传给 Sidecar。修改 `.env` 后必须重启 Tauri 应用。

## 4. 构建并启动

启动前可先检查 8902 端口是否被其他进程占用：

```powershell
Get-NetTCPConnection -LocalPort 8902 -ErrorAction SilentlyContinue
```

```powershell
cd <仓库目录>\local-kb
npm.cmd ci
npm.cmd run build
cd src-tauri
cargo check --locked
cd ..
npm.cmd run tauri dev
```

进入 Embedding 页面，点击“启动服务”。界面应显示：

- 状态 `RUNNING`；
- 协议 `1`；
- Python 依赖“已安装”；
- 离线模式“开启”。

如需在应用外验证服务，保持服务运行后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-embedding.ps1
```

## 5. 完整业务流程

1. 知识库页创建指向当前仓库 `local-kb\sample_docs` 绝对路径的知识库。
2. 文件页点击“重新扫描”，确认产生 Document 和 Chunk。
3. Embedding 页启动服务，选择已准备的模型。
4. 点击“为全部 Chunk 建立索引”。首次加载模型时间可能明显长于后续请求。
5. Profile 显示 `INDEXED` 且 Vector 数与 Chunk 数一致。
6. 向量检索页选择“真实 Embedding”和相同模型，输入问题并搜索。
7. RAG 页选择相同模型。未配置 LLM 时仍返回检索 Context；配置 LLM 后才生成自然语言回答。

## 6. 可选 DeepSeek API

在 `.env` 中填写：

```dotenv
LOCAL_KB_LLM_BASE_URL=https://api.deepseek.com
LOCAL_KB_LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=your-deepseek-key
LOCAL_KB_DEEPSEEK_THINKING=disabled
```

启用 DeepSeek 会把检索出的 Context 发送到该地址。使用真实证券资料前必须完成数据出域审批。详细配置见 `DEEPSEEK_INTEGRATION.md`。

## 7. 排错顺序

1. 服务启动失败：查看 `logs\embedding-service.log`。
2. `sentence-transformers is not installed`：重新运行 `setup-embedding.ps1`。
3. 离线模式报告找不到模型：检查 `.env` 模型路径及目录完整性。
4. 端口占用：关闭旧的 8902 服务，或同时修改 `LOCAL_KB_EMBEDDING_BASE_URL`。
5. `model_info differs`：Rust/Python 两侧模型配置版本不一致，重新构建应用，不能绕过校验。
6. `no vectors for selected provider`：先用相同模型完成整库建索引。
7. 文件更新后 `STALE`：重新执行该知识库的模型索引。
