# SecRAG

SecRAG 是一个面向 Windows PC 的端侧本地知识库原型。桌面端使用 Tauri v2、React 和 Rust，数据保存在本地 SQLite；项目支持 Markdown/TXT 文档扫描、Chunk、Mock/真实 Embedding、向量检索、增量更新和简单 RAG。

当前仅支持 Windows x86_64 MSVC。真实 Embedding 由本地 Python SentenceTransformer Sidecar 提供；模型权重、依赖目录、数据库、日志和密钥均不进入 Git。

## 目录结构

```text
SecRAG/
├─ embedding-test/         # 测试脚本目录
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
- Node.js 22.12 或更高版本（推荐 24 LTS，包含 npm）；
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

本项目已在 Node.js 22.17.1、npm 10.9.2、Rust 1.98.1 MSVC、Python 3.12.8 和 `sentence-transformers` 5.7.0 上完成安装、构建和启动验证。

如尚未安装 Rust，可从 [rustup 官方网站](https://rustup.rs/) 安装，然后执行：

```powershell
rustup toolchain install stable-x86_64-pc-windows-msvc
rustup default stable-x86_64-pc-windows-msvc
```

rustup 安装完成后请重新打开 PowerShell；若当前窗口仍找不到 Cargo，可临时执行：

```powershell
$env:Path="$env:USERPROFILE\.cargo\bin;$env:Path"
cargo --version
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

如果 `npm.cmd` 已安装但当前终端找不到它，先运行 `where.exe npm.cmd`。标准 Windows 安装可临时这样调用：

```powershell
& 'C:\Program Files\nodejs\npm.cmd' --version
& 'C:\Program Files\nodejs\npm.cmd' ci
```

如果 npm 报用户缓存目录 `EPERM`，改用项目内缓存：

```powershell
npm.cmd ci --cache .\.npm-cache --no-audit --no-fund
```

`.npm-cache` 已被 Git 忽略，安装完成后可以安全删除。

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

再下载实际需要的模型。建议先使用体积较小的 `bge-small`；需要第二个模型时再下载 `m3e-base`：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download-embedding-model.ps1 -Model bge-small
powershell -ExecutionPolicy Bypass -File .\scripts\download-embedding-model.ps1 -Model m3e-base
```

`bge-m3` 体积明显更大，不是首次验证必需项。模型下载完成后：

```powershell
Copy-Item .env.example .env
```

打开 `.env`，把下载脚本输出的绝对目录填入对应变量，例如：

```dotenv
LOCAL_KB_MODEL_BGE_SMALL=E:\path\to\SecRAG\local-kb\models\bge-small
LOCAL_KB_MODEL_M3E_BASE=E:\path\to\SecRAG\local-kb\models\m3e-base
LOCAL_KB_EMBEDDING_OFFLINE=1
```

然后执行 `npm.cmd run tauri dev`，进入“Embedding”页启动服务并建立真实向量索引。更完整的步骤见 [真实 Embedding 运行清单](docs/guides/EMBEDDING_RUNTIME_SETUP.md)。

## 5. 常见安装与启动问题

- `setup-embedding.ps1` 只有在最后打印 `Embedding Python environment is ready.` 时才算成功；若 `venv`、pip 或导入失败，脚本会立即返回错误。
- `npm ci` 出现 `spawn EPERM`：关闭可能占用 `node_modules` 的程序，删除残留的 `node_modules`，然后使用上面的项目内缓存命令重试。
- `cargo fetch --locked` 提示锁文件需要更新：不要删除 `--locked` 绕过；先确认仓库文件完整且 `Cargo.toml`/`Cargo.lock` 来自同一提交。
- Vite 开发地址是 `http://localhost:1420`。Windows 上可能实际监听 IPv6 `::1`，因此 `http://127.0.0.1:1420` 被拒绝不代表启动失败。
- 首次 `npm.cmd run tauri dev` 需要完整编译 Rust 依赖，看到 `Running target\debug\local-kb.exe` 后才表示桌面进程已启动。
- Embedding 服务启动失败时查看 `local-kb\logs\embedding-service.log`，并检查 8902 端口是否已被其他进程占用。

端口检查命令：

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object LocalPort -in 1420, 8902
```

## 6. 配置 DeepSeek（可选）

未配置 LLM 时，本地检索和 Context 仍可运行。若需要生成式回答，在 `local-kb\.env` 中填写：

```dotenv
LOCAL_KB_LLM_BASE_URL=https://api.deepseek.com
LOCAL_KB_LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=your-key
```

启用后，检索得到的 Context 会发送到配置的外部服务。处理真实证券资料前应先完成数据分级和出域审批。不要提交 `.env` 或 API Key。

## 7. 构建检查

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
