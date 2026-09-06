# embedding-test：本地知识库检索评测子项目

这是SecRAG中的独立Rust＋Python评测服务，用来比较不同向量模型的检索表现。没有桌面界面；桌面Demo位于旁边的`local-kb`目录。

提供文档导入、向量与关键词混合检索，以及三模型评测。代码、正式评测脚本和必要样例保留；下载依赖、模型、编译产物、数据库与缓存不上传GitHub。

## 目录

```text
embedding-test/
├─ README.md                 # 本操作入口
├─ .gitignore                # 本子项目忽略规则
├─ Cargo.toml / Cargo.lock   # Rust依赖与版本锁
├─ requirements.txt          # Python直接依赖版本
├─ src/                      # Rust代码（位置不变）
├─ scripts/                  # 原有模型服务与导入工具
├─ eval/                     # 正式评测脚本和34条问题
├─ docs/
│  ├─ README.md              # 文档索引
│  ├─ API.md                 # 接口文档
│  └─ EVALUATION.md          # 指标与已知限制
├─ test_docs/                # 12份运行所需的测试样例
├─ data/.gitkeep             # 数据库运行时生成，不上传
└─ start.sh                  # 保留的Bash入口
```

`.venv/`、`target/`、`logs/`、`results/`等目录在安装或运行后生成，均被忽略。

## 1. 准备环境

Windows开发机需要：Git、Python 3.12、Rust stable MSVC工具链，以及Visual Studio C++ Build Tools和Windows SDK。本子项目不需要Node、Tauri、WebView2或独立数据库服务；SQLite由Rust依赖编译。

先打开PowerShell，进入仓库的子目录。以下以当前工作区为例；克隆到别处时改成自己的路径：

```powershell
Set-Location E:\Workspace\SecRAG\embedding-test
python --version
rustc --version
cargo --version
```

如果提示命令不存在，先安装对应工具并重新打开终端。所有后续终端都需要进入这个目录。

## 2. 安装依赖（首次需要联网）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
cargo fetch --locked
cargo build --release --locked
```

每条命令确认成功后再执行下一条。无需激活虚拟环境，直接调用其中的Python，避免PowerShell激活策略问题。`requirements.txt`固定直接依赖；间接依赖仍由pip解析，正式性能复现需另保存`pip freeze`结果。

不要删除`Cargo.lock`，也不要删除`--locked`来绕过版本不一致错误。网络或工具链不完整时先处理安装错误。

## 3. 准备模型（首次需要联网）

沿用原版 `scripts/embed.py`：输入一句话，让它下载模型并生成一次向量。模型继续存放在 Hugging Face 用户缓存，**不新建项目内的 models 文件夹，也不改缓存位置**。本机默认位置为 `C:\Users\pc\.cache\huggingface\hub`；其他用户一般为 `$env:USERPROFILE\.cache\huggingface\hub`，已有环境变量配置时以配置为准。

先准备本次验证过的两个模型，每条命令等待完成再继续：

```powershell
$env:PYTHONIOENCODING='utf-8'
'{"texts":["准备模型"],"model":"bge-small"}' | .\.venv\Scripts\python.exe .\scripts\embed.py
'{"texts":["准备模型"],"model":"m3e-base"}' | .\.venv\Scripts\python.exe .\scripts\embed.py
```

看到“模型加载完成”并输出 `vectors` 数组，表示模型已能推理。第一次下载需要等待；已经缓存的文件可以复用。原版下载脚本使用 `https://hf-mirror.com`，服务脚本设置离线加载，因此必须先完成这一步。服务脚本也会清除其自身进程中的代理变量；这里保留原版行为。

可选：需要测试第三个模型时再准备它。本次未下载和验证 BGE-M3：

```powershell
'{"texts":["准备模型"],"model":"bge-m3"}' | .\.venv\Scripts\python.exe .\scripts\embed.py
```

模型使用条件请查看各模型说明：[BGE-small](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[M3E-base](https://huggingface.co/moka-ai/m3e-base)、[BGE-M3](https://huggingface.co/BAAI/bge-m3)。

## 4. 启动服务：使用两个PowerShell终端

两个终端都保持运行。此子项目使用8901和8902端口；旁边的`local-kb`也使用8902，不要同时运行它的Embedding服务，避免连接到错误服务。

### 终端一：启动模型服务

```powershell
Set-Location E:\Workspace\SecRAG\embedding-test
.\.venv\Scripts\python.exe .\scripts\embed_server.py
```

看到模型加载完成和`http://127.0.0.1:8902`监听提示后继续。首次模型加载可能较慢。若出现加载失败，先修复模型准备问题；端口开启本身不证明模型能推理。

### 终端二：启动Rust知识库服务

```powershell
Set-Location E:\Workspace\SecRAG\embedding-test
cargo run --release --locked
```

看到`服务地址: http://127.0.0.1:8901`表示接口已监听。数据库会自动建立在`data/knowledge.db`。

Windows采用先手动启动模型服务的方式，因为Rust原有自动启动分支调用`python3`，Windows不一定有该命令。代码位置和业务检索算法保持不变。

## 5. 终端三：运行评测

**评测会先清空本子项目数据库中的文档和片段，再重新导入测试资料。这个数据库只用于实验，不要放个人业务资料。**

```powershell
Set-Location E:\Workspace\SecRAG\embedding-test
Invoke-RestMethod http://127.0.0.1:8902/health
Invoke-RestMethod http://127.0.0.1:8901/api/health

# 先测一个已下载的模型
.\.venv\Scripts\python.exe .\eval\eval_search.py bge-small
```

单独测试其他模型：

```powershell
.\.venv\Scripts\python.exe .\eval\eval_search.py m3e-base
.\.venv\Scripts\python.exe .\eval\eval_search.py bge-m3
```

三个模型都准备好后，不加参数会依次测试三者：

```powershell
.\.venv\Scripts\python.exe .\eval\eval_search.py
```

保存输出，便于之后写报告：

```powershell
New-Item -ItemType Directory -Path results -Force | Out-Null
$env:PYTHONIOENCODING='utf-8'
$runStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
.\.venv\Scripts\python.exe .\eval\eval_search.py bge-small 2>&1 |
  Tee-Object -FilePath "results\bge-small-$runStamp.txt"
```

输出包含Hit@3、MRR和平均Latency。具体统计方式及局限见[评测说明](docs/EVALUATION.md)。停止时在终端一和终端二分别按`Ctrl+C`；不要关闭其他项目的服务。

## Bash环境

Linux/macOS可使用`python3 -m venv .venv`和`source .venv/bin/activate`，再安装相同requirements、下载模型。优先同样分两个终端启动`python scripts/embed_server.py`与`cargo run --release --locked`。

已有`start.sh`使用Bash、python3和pip3，适合具备这些命令的环境；它不会替你准备缺失的模型。PowerShell用户按上面的分终端方法运行即可。

## GitHub提交范围

提交：源代码、正式`eval`脚本/题集、文档和必要测试样例、`Cargo.lock`、`requirements.txt`、忽略规则。

不提交：下载模型、Python虚拟环境、Rust target、数据库/WAL/SHM、日志、原始运行结果、系统缓存、密钥。本轮没有发现可单独删除的临时测试代码；正式评测脚本是本子项目用途的一部分，因此保留。

从仓库根目录检查将要加入的文件，不执行上传：

```powershell
git status --short --untracked-files=all -- embedding-test
git add --dry-run -- embedding-test
```

## 本次验证（2026-09-06）

在当前 Windows 电脑新建虚拟环境、安装依赖并完成 Rust release 编译后，按上述原版模型缓存方式运行了两个模型。每个模型均导入根目录 `test_docs/` 中的 12 份资料，生成 78 个片段，完成 34 道题。详细结果见 [评测说明](docs/EVALUATION.md)。BGE-M3 与 Linux/macOS 启动方式尚未在本次验证。

与用户提供的 `knowledge_base` 原版对照：`src/`、原有 `scripts/`、`eval/`、`test_docs/` 及 Cargo 文件和 `start.sh` 保持一致。只将说明文档集中到 `docs/`，补充 README、依赖清单与 Git 忽略规则。`test_docs/` 是程序输入，不能随说明文档一起移动。

为便于继续运行，本次重新安装的 `.venv/`、`target/` 和运行记录暂留本机，Git 会忽略它们。用户模型缓存保持原位置。发布到 GitHub 不需要把本机环境再次删掉，提交前检查忽略规则即可。
