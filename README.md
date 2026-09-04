# SecRAG

SecRAG 是一个面向 Windows PC 的端侧本地知识库原型。桌面端使用 Tauri v2、React 和 Rust，数据保存在本地 SQLite；项目支持 Markdown/TXT 文档扫描、Chunk、Mock/真实 Embedding、向量检索、增量更新和简单 RAG。

当前仅支持 Windows x86_64 MSVC。真实 Embedding 由本地 Python SentenceTransformer Sidecar 提供；模型权重、依赖目录、数据库、日志和密钥均不进入 Git。

## 目录结构

```text
SecRAG/
├─ local-kb/               # 主程序源码
│  ├─ src/                 # React 前端
│  ├─ src-tauri/           # Rust/Tauri 后端
│  ├─ embedding-service/   # Python Embedding Sidecar
│  ├─ scripts/             # Embedding 环境与模型脚本
│  ├─ sample_docs/         # 可公开的演示资料
│  ├─ data/                # 本地运行数据，仅保留 .gitkeep
│  └─ models/              # 本地模型，仅保留 .gitkeep
└─ docs/
   ├─ guides/              # 架构、接口、部署和开发文档
   └─ project/             # 原始需求、环境说明和操作记录
```

## 1. 准备开发环境

请先安装：

- Git；
- Node.js 24 LTS（包含 npm）；
- Rust stable，目标为 `x86_64-pc-windows-msvc`；
- Visual Studio 2022 Build Tools，并勾选“使用 C++ 的桌面开发”和 Windows SDK；
- Microsoft Edge WebView2 Runtime（Windows 10/11 通常已安装）；
- 可选：Python 3.10–3.12，用于真实 Embedding。

在 PowerShell 中检查：

```powershell
git --version
node --version
npm.cmd --version
rustc --version
cargo --version
python --version
```

如尚未安装 Rust，可从 [rustup 官方网站](https://rustup.rs/) 安装，然后执行：

```powershell
rustup toolchain install stable-x86_64-pc-windows-msvc
rustup default stable-x86_64-pc-windows-msvc
```

## 2. 下载源码和依赖

```powershell
git clone https://github.com/Tintin-PLUS/SecRAG.git
cd .\SecRAG\local-kb

# 严格按 package-lock.json 安装前端依赖
npm.cmd ci

# 下载并缓存 Cargo.lock 中的 Rust 依赖
Set-Location .\src-tauri
cargo fetch --locked
Set-Location ..
```

PowerShell 若阻止 `npm.ps1`，请继续使用文档中的 `npm.cmd`。

## 3. 启动项目

不下载模型也可以使用 Mock Embedding 验证完整本地流程：

```powershell
# 在克隆后的 SecRAG\local-kb 目录执行
npm.cmd run tauri dev
```

首次运行会编译 Rust 依赖，耗时通常明显长于后续启动。打开应用后按以下顺序操作：

1. 在“知识库”页创建知识库，路径可选择仓库中的 `local-kb\sample_docs`；
2. 在“文件”页点击“重新扫描”；
3. 在“Embedding”页生成 Mock Index；
4. 在“向量检索”或“RAG 问答”页提问。

Mock Embedding 只用于验证调用链，不代表真实语义检索质量。

## 4. 启用真实 Embedding（可选）

先创建隔离的 Python 环境并安装依赖：

```powershell
# 在 SecRAG\local-kb 目录执行
powershell -ExecutionPolicy Bypass -File .\scripts\setup-embedding.ps1
```

再下载实际需要的模型。建议先使用体积较小的 `bge-small`：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download-embedding-model.ps1 -Model bge-small
```

可选模型为 `bge-small`、`m3e-base` 和 `bge-m3`。模型下载完成后：

```powershell
Copy-Item .env.example .env
```

打开 `.env`，把下载脚本输出的绝对目录填入对应变量，例如：

```dotenv
LOCAL_KB_MODEL_BGE_SMALL=E:\path\to\SecRAG\local-kb\models\bge-small
LOCAL_KB_EMBEDDING_OFFLINE=1
```

然后执行 `npm.cmd run tauri dev`，进入“Embedding”页启动服务并建立真实向量索引。更完整的步骤见 [真实 Embedding 运行清单](docs/guides/EMBEDDING_RUNTIME_SETUP.md)。

## 5. 配置 DeepSeek（可选）

未配置 LLM 时，本地检索和 Context 仍可运行。若需要生成式回答，在 `local-kb\.env` 中填写：

```dotenv
LOCAL_KB_LLM_BASE_URL=https://api.deepseek.com
LOCAL_KB_LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=your-key
```

启用后，检索得到的 Context 会发送到配置的外部服务。处理真实证券资料前应先完成数据分级和出域审批。不要提交 `.env` 或 API Key。

## 6. 构建检查

```powershell
# 在 SecRAG\local-kb 目录执行
npm.cmd run build

Set-Location .\src-tauri
cargo check --locked
Set-Location ..
```

生产前端产物会写入 `local-kb\dist`，Rust 构建产物会写入 `local-kb\src-tauri\target`；它们均已被 `.gitignore` 排除。

## 文档

文档统一收录在 [docs/README.md](docs/README.md)。架构、Embedding 接口、SQLite Schema、Vector Store、性能验证、DeepSeek 对接和已知问题均可从该索引进入。

## 发布前注意事项

- 不要提交 `node_modules`、`.venv`、`target`、`dist`、模型权重、数据库、日志或 `.env`；
- `sample_docs` 仅包含模拟演示资料，不要替换成内部敏感材料后提交；
- `package-lock.json` 与 `Cargo.lock` 应保留，用于可重复安装；
- 当前 `bundle.active=false`，项目面向开发运行，尚未生成签名安装包。
