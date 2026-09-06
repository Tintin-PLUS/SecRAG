# 端侧知识库技术选型报告：实施方案

编写日期：2026-09-05。代码基线：`1918c04`（9.4运行成功版本）。项目：`E:\Workspace\SecRAG`。

本文是完成报告的实施方案，不是已经得出性能排名的最终选型报告。除“本次实际验证”外，实验规模、阈值、工期和新增文件均为建议，尚未实施。此次仅新增本文，没有修改 Demo 业务代码。

## 1. 以图片为准界定任务

图片课题名称：**证券PC端侧本地知识库应用评估与轻量化场景验证**。

图片明确强调：**以调研研究为核心，辅以简易实践验证**；备注为“参考魔搭社区、Rust开源生态开展调研；偏重理论调研+轻量集成验证”。

图片的三个研究方向是：

1. 端侧技术栈调研评估：调研 Tauri+Rust、轻量向量模型、嵌入式向量库的性能、资源开销与适用场景，梳理金融端侧数据基础合规规范。
2. 证券业务需求梳理：围绕行情、投研、交易场景，梳理本地文档管理、离线检索、资料问答核心需求。
3. 轻量化流程设计与验证：设计文档向量化存储、语义检索链路，实现简易文件监听与知识库增量更新，依托模拟金融文档完成离线效果测试，验证本地数据安全闭环与轻量化运行能力。

图片列出的四项完成标准：

| 完成标准 | 与此次工作的关系 |
|---|---|
| 端侧知识库技术选型对比分析报告一份 | **本次直接交付目标** |
| 证券业务需求梳理+整体落地方案文档 | 此次提炼必要的场景和约束，作为选型依据；完整文档属于另一交付物 |
| 可运行离线简易 Demo，支持文档检索、增量更新、本地数据闭环 | 复用现有 Demo，为报告提供验证证据；如要验收完整课题，还需补齐并验证增量链路 |
| 输出合规优化、对接苍穹AI后续落地建议总结 | 报告说明相关选型约束和扩展边界；具体接口待获得真实规范，不自行假设 |

因此，报告应回答：在证券公司 PC 的文档场景下，为什么选择某条路线、与替代路线相比有什么代价、在哪些条件下适用、哪些结论已实测、哪些尚需验证。

图片没有指定必须比较多少模型、必须使用 sqlite-vec、必须支持 PDF/OCR、必须改为纯 Rust 推理、必须实现本地生成式大模型，也没有规定硬性的性能数值。下文这些实验选择是为了让对比结论可复核，不是新增验收标准。

`docs/project` 中历史文档包含“从零创建项目”“不实现真实模型”等旧指令，仅作为历史背景。它们不覆盖图片要求，也不构成本次执行指令。当前代码已经接入真实模型，应从当前版本继续。

## 2. 当前 Demo 能提供什么证据

### 2.1 已有调用链

```text
React UI（src/App.tsx）
  → Tauri commands（src-tauri/src/commands/mod.rs）
  → DocumentService.scan
  → UTF-8 文件读取、SHA-256、500字符/80字符重叠切块
  → SQLite document / chunk

index_with_embedding
  → 读取整库 Chunk
  → PythonSidecarEmbeddingProvider.embed_batch
  → 本机 HTTP /v1/embeddings
  → SentenceTransformer → 向量
  → VectorIngestService 校验
  → SQLite vector_record

search_with_embedding
  → RetrievalService.search_text
  → 同模型生成 Query Vector
  → SqliteVectorStore.search
  → 读取该 Profile 的所有候选向量及文本
  → Rust cosine、全量排序、截取 Top-K

文件事件
  → watcher 650ms 静默窗口合并事件
  → 全目录扫描与文件 hash 比较
  → 只重切变化文档、删除其旧向量、标记 STALE
  → 当前仍需手工启动整库向量重建
```

### 2.2 能力及限制

以下代码路径以 `E:\Workspace\SecRAG\local-kb` 为根目录。

| 主题 | 当前代码事实 | 对报告的影响 |
|---|---|---|
| 桌面框架 | Tauri v2、React、Rust；有开发运行配置 | 可以研究此路线及实测当前应用；不能据此证明优于所有桌面框架 |
| 文档与切块 | `document/mod.rs:73` 扫描；`chunk/mod.rs` 按 Rust `char` 切分；只支持 UTF-8 MD/TXT | 适合模拟金融文本；500字符不是500 token；PDF、表格、扫描件能力不能写成已具备 |
| 真实模型 | `embedding/python_sidecar.rs` 注册 BGE-small-zh-v1.5、M3E-base、BGE-M3 | 有模型对比接入口；注册成功不等于模型已下载或已验证 |
| CPU约束 | `embedding-service/server.py:91` 未传 `device="cpu"` | 当前程序可能自动选用可用加速设备；CPU-only 报告必须显式锁定并记录设备 |
| 输入策略 | `server.py:185` 直接取文本；Query/Document 类型没有用于选择前缀；ModelInfo 最大长度为空 | 应核实每个模型的实际 tokenizer、截断、pooling、前缀；不能仅凭元数据声明正确 |
| 向量库 | `vector_store/sqlite_store.rs` 是 SQLite BLOB + Rust cosine；无 sqlite-vec 依赖 | 可作为基线；应明确它不是已经启用向量扩展的实现 |
| 搜索成本 | 全量距离计算、读取文本、存全部候选、全量排序 | 距离计算约 O(ND)，排序另有 O(N log N)；内存还包含候选文本，不能只按向量字节数估算 |
| 可替换性 | 有 `VectorStore` Trait，但 `retrieval/mod.rs:14`、`embedding/integration.rs:22` 仍持有具体 `SqliteVectorStore` | 文档“只替换注入的Store”比代码现状更理想化；正式切换需小幅依赖注入改造 |
| 增量更新 | `watcher/mod.rs:29` 触发 scan；`commands/mod.rs:282` 仍读全部 Chunk 做 Embedding | 已有文件级增量解析，不是端到端自动增量索引；两段耗时必须分开测 |
| 索引覆盖率 | 一个批次写入成功即可将 Profile 标为 INDEXED；其他 Profile 会被标 STALE | INDEXED不等于完整覆盖；不同候选最好使用独立实验数据库，避免互相影响状态 |
| 性能页 | `benchmark/mod.rs:21` 单次内存库插入、Top-5/10、主键读取；N 被截到10000 | 不是磁盘/整链路/模型质量评测；直接输入100000也不会真正测100000 |
| 测试数据 | `sample_docs` 有6份模拟金融文档 | 可以冒烟验证，不足以据此评价证券业务检索效果 |
| 离线边界 | Python默认离线；RAG有Key就会构造外部DeepSeek请求 | 离线向量检索与外部生成回答必须分开。当前没有本地生成模型 |
| 部署 | `bundle.active=false`；`app/mod.rs:27` 使用编译时 `CARGO_MANIFEST_DIR` 推导资源目录 | 可验证开发机运行；复制EXE到别处不能直接视为可分发部署完成 |

额外需要在报告披露的工程边界：扫描会忽略 WalkDir 错误，随后按缺失路径清理数据库记录；目录不可访问时可能误判删除。写入 Profile/向量/状态不是同一个总事务；后台扫描与索引并发存在一致性窗口。它们不阻止开展隔离的静态语料实验，但不能在未测试时宣称异常恢复或事务闭环已经完备。

### 2.3 本次实际验证

| 验证 | 结果 | 证据边界 |
|---|---|---|
| Git状态 | 检查开始时工作树无改动，基线1918c04 | 之后只增加本文 |
| `cargo check --locked --offline` | 通过 | Rust编译检查，不代表业务正确 |
| `npm.cmd run build` | 通过 | 首次因沙箱esbuild进程EPERM失败；获执行授权后原命令通过，未修改源码 |
| `cargo test --locked --offline` | 命令成功，但单元测试和文档测试均为0个 | 不能写“功能自动化测试通过” |
| BGE-small本地CPU冒烟 | 离线加载本地模型，对2条文本编码；shape=[2,512]，数值有限，范数约1 | 只验证模型加载/输出；不是经Tauri/SQLite的端到端测试，也不是质量或性能基准 |
| Python环境 | Python 3.12.8；sentence-transformers 5.7.0；torch 2.14.0；transformers 5.16.1 | 来自当前`.venv`的包元数据 |
| Rust/Node | rustc 1.98.1；当前命令环境Node v24.19.0 | 与历史README中的Node版本不完全相同，应以测试实际运行环境为准 |
| 本地模型目录 | 存在bge-small、m3e-base；BGE-small实际加载后的max_seq_length为512 | M3E本轮未推理；BGE-M3本轮未发现本地目录 |
| CPU型号/内存 | 沙箱中的CIM查询拒绝访问 | 本轮不填写硬件型号和RAM容量，不推断低配置适用性 |

## 3. 报告怎么做对比

建议采取“文献调研覆盖候选 + 少量受控实验验证关键取舍”的结构。

| 层次 | 建议比较对象 | 最小证据 | 可选加深 |
|---|---|---|---|
| 桌面框架 | 当前Tauri+Rust 与 Electron | 官方架构/部署依赖对比；测当前Tauri整套运行资源 | 做等功能最小Electron壳，测相同页面和同一个后端；不是重写Demo |
| 轻量向量模型 | BGE-small-zh-v1.5 与 已有M3E-base研究对照 | 相同语料与查询上的质量、CPU吞吐、内存和体积 | BGE-M3作为较大模型参照；不强制下载 |
| 嵌入式向量存储 | 当前SQLite BLOB+Rust 与 sqlite-vec | 相同向量、查询、磁盘配置下的写入/检索/一致性小实验 | 需要更大规模时再调研ANN路线；本轮不强制引入服务型数据库 |
| 轻量部署 | 当前Python SentenceTransformer Sidecar | 完整依赖、模型、索引、进程资源及准备步骤 | 同一模型PyTorch FP32 vs ONNX INT8；纯Rust ONNX实现只作后续路线 |

Tauri在Windows依赖WebView2；Electron随应用使用Chromium和Node.js。可据此讨论分发及维护差异，但“内存一定更低、启动一定更快”必须通过等价应用实测才能下结论。[Tauri前置依赖](https://v2.tauri.app/start/prerequisites/)、[Electron官方解释](https://www.electronjs.org/docs/latest/why-electron)。

**M3E-base需要单独标记授权限制。** 官方模型卡的License段落声明非商用、仅供研究。它适合本课题研究对照；未经进一步授权核实，不能直接列为证券公司落地推荐。BGE-small模型卡标MIT，仍需把实际下载版本及许可证文件归档。[M3E-base模型卡](https://huggingface.co/moka-ai/m3e-base#-license)、[BGE-small模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5)。

sqlite-vec是嵌入式扩展候选，不要默认它提供HNSW或对数级搜索。作者公开说明其精确扫描定位；当前官方文档提供vec0和标量距离函数两条KNN路径。报告记录实际所测版本与算法。[作者发布说明](https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/index.html)、[KNN文档](https://alexgarcia.xyz/sqlite-vec/features/knn.html)。

建议先确定硬门槛，再做取舍：目标机可运行、离线检索、模型授权适用、数据边界满足要求、检索质量达到事先商定的标准。未通过门槛的候选不因速度快而成为推荐。通过后比较质量、P95延迟、峰值内存、安装体积和维护成本；不要用事后调整的权重制造“赢家”。

## 4. 测试环境如何配置

### 4.1 环境角色

最低成本从现有Windows开发机开始，统一CPU测试；有条件再借一台接近公司PC的机器复核推荐方案。

| 环境 | 建议用途 | 注意 |
|---|---|---|
| 当前开发机 | 代码改造、所有候选基线 | 固定电源模式、线程、运行版本；记录实际硬件 |
| 代表性目标PC | 复核最后1—2个候选 | 例如8GB或16GB内存的办公机只是候选测试档位，不是图片规定配置 |
| 干净Windows用户/虚拟机 | 验证离线启动及依赖准备 | 虚拟机性能结果与物理机分列；限制线程不能等同于验证了一台低配PC |

每台机器记录：CPU完整型号/物理核/逻辑核、RAM、磁盘类型、Windows版本、WebView2版本、Node/npm/Rust/Python版本、软件包锁定信息、GPU是否存在、实际推理device、接电和电源模式。不要公开机器序列号、用户名等无关信息。

### 4.2 当前机器：先复核，不重新安装

现有机器已经有依赖和两个模型目录，不需要从头下载。

```powershell
Set-Location E:\Workspace\SecRAG\local-kb
git rev-parse HEAD
node --version
& 'C:\Program Files\nodejs\npm.cmd' --version
rustc --version
cargo --version
& .\.venv\Scripts\python.exe --version
& .\.venv\Scripts\python.exe -m pip check

# 这些CIM命令在普通本地PowerShell中收集；若权限不足，手工从系统信息填写。
Get-CimInstance Win32_Processor |
  Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
Get-CimInstance Win32_OperatingSystem |
  Select-Object Caption,Version,TotalVisibleMemorySize

& 'C:\Program Files\nodejs\npm.cmd' run build
Set-Location .\src-tauri
cargo check --locked --offline
cargo test --locked --offline
Set-Location ..
```

`cargo test`必须核对实际测试数量。当前0个测试只是说明测试基础尚未补齐。

### 4.3 新机器准备顺序

1. Windows x64；开发机安装Git、Node（团队固定版本）、Rust MSVC工具链、Visual Studio C++ Build Tools和Windows SDK、WebView2；真实模型使用Python 3.12。Tauri系统依赖依据[官方前置要求](https://v2.tauri.app/start/prerequisites/)。
2. 在联网准备阶段，用同一Git提交的`package-lock.json`执行`npm.cmd ci`；在`src-tauri`执行`cargo fetch --locked`。
3. 创建项目`.venv`；依据已经验证的Python包锁定清单安装。当前`sentence-transformers>=3.0,<6`只是范围约束，不能保证复现，需要新增精确版本锁定和来源清单。
4. 只准备要比较的模型；保存模型来源、不可变revision、许可证和文件哈希。现有下载脚本不固定revision，应补参数；也要补Python退出码检查，避免下载失败仍打印ready。
5. 断网之前准备完整模型目录与Python依赖。离线测试期间不得首次下载或首次在线导出ONNX。

联网初次安装现有Demo的可用命令如下，已有环境不必重复运行：

```powershell
Set-Location E:\Workspace\SecRAG\local-kb
npm.cmd ci
Set-Location .\src-tauri
cargo fetch --locked
Set-Location ..
powershell -ExecutionPolicy Bypass -File .\scripts\setup-embedding.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\download-embedding-model.ps1 -Model bge-small
```

正式离线分发Python依赖时，在**相同Windows架构/Python版本**的联网准备机生成wheelhouse，用已锁定清单执行`pip download --only-binary=:all:`，然后在目标机`pip install --no-index --find-links ... -r ...`。若某依赖没有匹配wheel，先解决构建/分发问题，不在断网机临时联网安装。不要假设复制整个`.venv`能可靠迁移。

### 4.4 离线、线程和模型路径

当前Rust会读取`local-kb\.env`；Python脚本直接启动时不会自行读取它。已有`.env`不要覆盖，也不要打印到测试日志。

以下配置名当前有效，在Tauri管理Sidecar的路径中可使用：

```dotenv
LOCAL_KB_EMBEDDING_BASE_URL=http://127.0.0.1:8902
LOCAL_KB_EMBEDDING_OFFLINE=1
LOCAL_KB_MODEL_BGE_SMALL=E:\Workspace\SecRAG\local-kb\models\bge-small
LOCAL_KB_MODEL_M3E_BASE=E:\Workspace\SecRAG\local-kb\models\m3e-base
LOCAL_KB_EMBEDDING_BATCH_SIZE=32
LOCAL_KB_EMBEDDING_ENCODE_BATCH_SIZE=32
```

从同一PowerShell启动程序时，可以设置已有库识别的线程/离线环境变量：

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:OMP_NUM_THREADS='4'
$env:MKL_NUM_THREADS='4'
$env:TOKENIZERS_PARALLELISM='false'
```

实际CPU强制选择还必须在Python加载时传`device="cpu"`，并在首次推理前调用`torch.set_num_threads(4)`、`torch.set_num_interop_threads(1)`。这些值是建议实验配置；`LOCAL_KB_DEVICE`、`LOCAL_KB_TORCH_THREADS`等自定义变量当前没有实现，不能仅写进`.env`就认为生效。若新增这些变量，也要补Rust配置透传和运行时回读。

SentenceTransformer未指定设备时会自动选择可用设备；其ONNX路径也需要显式指定CPU provider。[Sentence Transformers运行优化文档](https://www.sbert.net/docs/sentence_transformer/usage/efficiency.html)。

### 4.5 测试数据隔离及Release运行

建议实验目录使用`local-kb/data/experiments/<run_id>/`，该父目录已被Git忽略。每个候选单独建立数据库，禁止测试入口默认打开现有`data/local-kb.sqlite3`。截图/可公开汇总另放`docs/evidence/`，先检查是否包含资料正文、本地用户名等信息。

GUI联调用`npm.cmd run tauri dev`。正式耗时实验使用Release编译；不把Vite和Cargo编译时间纳入用户检索延迟。新增CLI后使用`cargo run --release --locked --bin kb-bench -- ...`，编译在正式采样前完成。

当前EXE依赖编译机目录，测“移动目录/另一台PC可运行”前需改资源路径：用户数据取Tauri app-data目录，资源取resource目录，Python和模型路径支持显式配置。报告可以先把跨机分发标成未完成，不强制本轮制作签名安装包。

## 5. 测试数据和方法

### 5.1 两类数据分开准备

**工程容量数据集**：生成固定随机种子的向量、Query和模拟文本，用于存储与性能。建议1,000与10,000 Chunk为基本档，100 Chunk用于快速检查；100,000作为可选压力档。随机向量应有足够多不同样本，避免现有模97生成法的大量重复。报告不能用复制同一句话扩容后的结果代表真实业务检索质量。

**语义质量数据集**：沿用图片要求的“模拟金融文档”。建议先准备50—100份内容有差异的MD/TXT，包含投研摘要、风险制度、交易规则/流程、行情解读文本；无需接实时行情系统。再整理约100条问题，其中约80条可回答、20条无答案/资料不足。数字为项目建议，可以随时间缩减并诚实说明样本规模。

问题至少覆盖：术语改写、具体条件/数字、证券简称、中英混合、相似制度干扰、不同日期版本、需要多个证据的查询、确实无答案。两人交叉复核标注有助于减少主观偏差；这是一项建议的人工协作方式，不代表本次已经安排人员。

每条问题保存：

```json
{
  "query_id": "q001",
  "split": "test",
  "scenario": "risk_policy",
  "query": "模拟制度中信用风险应如何持续监测？",
  "answerable": true,
  "relevance": [
    {"source_id": "risk_001", "source_version": "v1", "evidence_id": "p003", "grade": 2}
  ]
}
```

这只是格式示例，必须依据语料核对问题及证据。不要把数据库随机UUID写死到标注中：当前重切块会生成新UUID。优先标到固定原文段落/偏移，再由每次切块结果映射到证据；固定切块实验也可使用文档相对路径+文档hash+chunk_index作为稳定键。不同切块策略比较时不能复用未经映射的旧Chunk标签。

用独立开发集调整前缀、阈值、batch或切块参数，最后固定配置评估测试集。近重复文档与相关问题应按来源分组划分，避免同样内容同时用于调参和验收。质量指标不把同一问题重复运行十次当成十条独立问题。

### 5.2 实验矩阵：分层控制变量

| 实验 | 改变什么 | 固定什么 | 记录什么 |
|---|---|---|---|
| 模型对比 | BGE-small vs M3E研究对照 | 同语料/切块/查询/Store、CPU线程、精度基线 | Hit@5、Recall@5、MRR@10；加载、编码吞吐、Query耗时、峰值RAM |
| 存储对比 | fallback vs sqlite-vec | 完全相同的向量文件/Query、维度、Top-K、磁盘、批次 | 写入ms及vectors/s、Store P50/P95、DB大小、结果一致性 |
| 端到端检索 | 候选整套路线 | 同业务查询与语料、同测试机 | Query编码+传输+检索+元数据返回总耗时，成功率 |
| 文档更新 | 新增/修改/删除/不变 | 固定原始库和变更文件大小 | 扫描、变化Chunk、待重建向量、重建耗时、可检索时点 |
| 离线闭环 | 联网准备后断网 | 模型、DB、查询、功能 | 本地检索是否成功、是否有外部请求尝试、模型缺失是否明确失败 |
| 轻量化 | 空闲、模型已加载、建库、查询 | 完整应用进程树 | Python/Tauri/WebView2资源、磁盘各部分大小 |

主对比先固定当前500字符/80重叠，并统计每个模型实际token截断比例，防止静默丢失证据。若发现严重截断，再单独设300/50或token切块实验；不要在模型对比中同时偷偷改变切块。

BGE官方建议短查询检索长段落时评估查询指令；v1.5无前缀也可工作，因此“没加前缀”不等于模型无法使用。应以开发集做有/无前缀对照，把最终选择写入ModelInfo与配置hash。[BGE查询指令说明](https://huggingface.co/BAAI/bge-small-zh-v1.5#frequently-asked-questions)。

### 5.3 指标口径

- `Hit@5`：可回答问题中，Top-5至少命中一条相关证据的问题比例。
- `Recall@5`：每条可回答问题召回的相关证据数/该问题相关证据总数，再对问题取平均。多相关证据时，它与Hit@5不同。
- `MRR@10`：Top-10中第一条相关证据排名的倒数，再取平均；未命中计0。
- `nDCG@10`：可选，适用于0/1/2分级相关性；与本项目标注口径一起说明。
- 无答案问题：单独报告误接受率。当前总会返回Top-K，必须新增基于开发集校准的拒答/空结果策略，才能声称具备无答案识别；否则只报告分数分布与该能力缺失。
- Store耗时：原始Query Vector输入至Top-K连同约定字段返回。若sqlite-vec先只返回ID，要把回表取文本计入相同口径；也可额外分别报告纯KNN内核耗时。
- 端到端耗时：文本Query进入服务到结果可返回；包括Query Embedding及HTTP/JSON开销；若没有采UI绘制，不写成“点击到显示”。
- 索引耗时：分别报告解析/切块、Embedding、写向量和状态确认；首次模型加载单列，不能混进热态吞吐。

热态检索每组合预热3次，正式至少100次请求，最好是固定查询集循环3轮。输出原始每次耗时，计算median/P95/min/max并记录分位数算法。写入使用新实验库重复至少3次，不能把upsert已有记录当成首次插入。

冷态至少区分“重启进程后的首次模型加载”和“系统文件缓存也冷”。重启Python不会清空Windows文件缓存，不能称完全冷启动。无需为了本课题清理系统缓存；报告如实命名即可。

Python当前`elapsed_ms`从encode前开始计时，首次请求含模型加载，但不包含完整响应JSON序列化/发送；Rust也没有消费该字段。应新增分段计时，外部计时保留总耗时，避免各自指标混用。

### 5.4 CPU、内存与体积

每500ms采样专属应用进程树，至少分列Tauri、其WebView2子进程、Python Sidecar。不要只看`local-kb.exe`，也不要误把浏览器其他WebView2进程算进来。模型逐个独立进程测试：当前Sidecar会缓存多个模型，不重启会污染后一个模型的内存结果。

CPU百分比建议统一为：`100 × Δ进程CPU时间 / Δ墙钟时间 / 逻辑核数`，表示占整机算力比例；若用不除核数的“核占用百分比”，必须标明可以超过100%。

记录WorkingSet和PrivateBytes，保存基线/峰值/结束稳态。多个进程WorkingSet相加可能重复计共享页，标作“工作集之和”，不要当作去重后的物理内存；PrivateBytes也不等于驻留物理内存。

磁盘分列：应用文件、Python运行时及依赖、模型权重、原始资料、索引数据库与WAL/SHM、日志。另报总离线部署体积；WebView2已安装与需要额外准备分别说明。`node_modules/target/debug`是开发依赖，不能算运行包；Python与模型又不能被漏算。

仅作量级检查：10,000条512维f32向量的原始值为10,000×512×4=20,480,000字节，约19.53MiB。这不包含SQLite、文本、索引、事务日志和内存对象，不能替代实测。

## 6. 需要增加哪些代码

下面路径均为相对于`local-kb`的**拟新增/拟修改位置**。先做A组即可支撑最小研究报告；B组用于更强证据或完整Demo验收；C组是后续路线。

### A组：直接为报告服务的最小增补

| 文件 | 修改或新增职责 | 完成判据 |
|---|---|---|
| `embedding-service/server.py` | 显式CPU/线程；实际max_length、输入前缀；分离load/encode计时；健康/诊断返回实际device | 日志能确认device=cpu；Query/Document处理与声明一致；冷/热测量可分离 |
| `embedding-service/model_manifest.json`（新增） | 固定模型来源/revision/权重和tokenizer哈希、许可、pooling、normalize、截断/前缀/精度 | 同一文件与配置产生同一指纹；配置变化新建Profile |
| `embedding/python_sidecar.rs`、`config/mod.rs` | Rust与Python共用或生成同一模型清单；保留完整ModelInfo校验；透传新增运行设置 | 不通过删除兼容性校验来解决model_info differs |
| `benchmark/mod.rs` | 拆出BenchmarkConfig/Trial/汇总；memory与file模式；多Query、预热、重复、实际N/维度/seed、JSON导出 | 同配置可复跑；参数不静默截断；不触碰业务数据库 |
| `src-tauri/src/bin/kb-bench.rs`（新增） | 无GUI CLI，调用现有Database/Document/Provider/Store；执行存储、建库、检索、更新实验 | Release运行后生成原始数据与manifest；不依赖手点UI |
| `evaluation/dataset.rs`、`evaluation/metrics.rs`（新增） | 读取语料和标注、导出query/hits、按稳定证据ID算指标 | 手工构造的小例子能验证命中、未命中、多相关证据、空集处理 |
| `scripts/collect-env.ps1`（新增） | 采环境、版本和脱敏配置 | 包含完整复现信息，不读取/输出API Key |
| `scripts/measure-processes.ps1`（新增） | 按指定根PID追踪应用子进程与采样CSV | 含Python和WebView2；进程退出有记录 |
| `scripts/run-evaluation.ps1`（新增） | 执行固定矩阵、逐模型启动退出、独立run_id、保存退出码 | 失败保留日志且不记成0ms/成功样本 |
| `embedding-service/requirements.lock.txt`（新增） | 固定实际验证过的Python依赖；另记录wheel来源和哈希 | 同平台干净venv可离线重建 |

CLI初版无需上Criterion，也不必加专门的性能GUI。优先复用当前Rust服务，避免另写一套Python检索算法却把结果当作Rust Demo性能。

建议新增CLI接口如下，**当前版本没有这些命令，需要实现后才能执行**：

```powershell
# 在local-kb\src-tauri下；配置中的DB/输出目录必须是独立实验目录。
cargo run --release --locked --bin kb-bench -- storage --config ..\eval\storage.json
cargo run --release --locked --bin kb-bench -- retrieval --config ..\eval\retrieval.json
cargo run --release --locked --bin kb-bench -- incremental --config ..\eval\incremental.json
```

配置最少包含：`store`、`db_path`、`dataset_path`、`query_path`、`model_manifest`、`dimension`、`top_k`、`batch_size`、`warmup`、`repetitions`、`seed`、`output_dir`。CLI在初始化时显式构造实验Database，不调用默认AppState打开业务库。

建议输出目录：

```text
data/experiments/<run_id>/
  manifest.json          # Git提交、实际配置、数据与模型指纹、软件/硬件
  trials.jsonl           # 每次运行时间、成功/失败、计时边界
  resources.csv          # 时间戳、PID/父PID、CPU、WorkingSet、PrivateBytes
  retrieval_hits.jsonl   # query_id、稳定证据ID、rank、score
  metrics.json           # 数量、指标及统计方法
  summary.csv            # 报告表格的数据源
  experiment.sqlite3     # 此次独立数据库
```

### A组附加：sqlite-vec小验证

若报告希望给出实测的存储对比，最省事的是先在`kb-bench`增加隔离适配器，不必第一天就替换GUI生产路径。若时间不足，也可以把sqlite-vec列为“文献调研，未本地验证”，但必须保留证据边界。

实施要点：

1. 新增`vector_store/sqlite_vec_store.rs`，在实验入口创建vec0表；锁定sqlite-vec crate版本并验证Windows MSVC编译。官方有Rust注册示例，与现有bundled rusqlite路线可衔接，但具体版本组合仍需实测。[Rust集成文档](https://alexgarcia.xyz/sqlite-vec/rust.html)。
2. 相同维度、相同cosine度量；vec0默认示例使用L2，要显式配置cosine。当前API是“相似度越大越好”，扩展返回“距离越小越好”，cosine路径转换为`score=1-distance`。[KNN及距离配置](https://alexgarcia.xyz/sqlite-vec/features/knn.html)。
3. 第一版每个Profile独立表或独立实验库，512/768维分别建表。不能先跨模型全局Top-K再事后过滤Profile，那会漏掉正确结果。
4. 维护整数rowid与现有Chunk UUID映射；表名由内部生成，禁止拼接任意外部输入。
5. vec0表不自动获得现有普通表的外键级联语义；必须处理Chunk/Profile删除和事务一致性。实验阶段也要验证修改/删除后无陈旧命中。
6. 使用同一批预计算向量文件，比较结果及距离容差；并列分数用稳定ID作为次序规则或按并列集合判定，避免把平局排序差异当错误。
7. 明确比的是“当前fallback实现 vs 当前sqlite-vec实现”；不把全量读取文本带来的差异归为Rust语言劣势。时间允许可另增“仅Top-K回表”的fallback优化作第三条曲线。

若最终接入GUI，还需：

```rust
// 设计示意，未实施：让Ingest与Retrieval接收同一个Store实例。
pub struct RetrievalService {
    db: Database,
    store: std::sync::Arc<dyn VectorStore>,
}
```

同步改`VectorIngestService`的构造函数和`AppState`的Store工厂，再替换commands中的构造调用。数据库schema_version目前只是记录1，尚无真正迁移调度器；新增迁移时需要有版本分支、事务和回滚测试，不能只追加一条版本号记录。

### B组：完整增量链路和闭环验证

报告可以先如实评价当前“监听→增量解析→手动全量建向量”路线。如果要同时支撑图片中Demo的增量更新验收，建议补以下最小链路：

1. 把`index_with_embedding`中的整库处理抽成`IndexingService`。
2. 新增`index_pending(profile_id)`，只取当前Profile没有向量的当前Chunk。用`NOT EXISTS`关联vector_record；不能只看document.status，它不是按Profile区分的。
3. 每个知识库用串行任务队列协调scan与index；watcher只入队。保留手动“更新变化向量”入口，自动监听完成后触发相同服务。
4. 计算coverage=`当前Profile有向量的当前Chunk数/当前Chunk总数`。使用EMPTY/PARTIAL/BUILDING/INDEXED/FAILED等状态；扫描变化及删除后重算，不能仅凭一次batch成功宣布整库完成。
5. 小Demo可先用串行队列+分批提交+失败PARTIAL状态，失败重试剩余Chunk；如需查询持续读旧完整快照，再增加staging/原子切换，属于更进一步设计。
6. 保存发生变更的文档hash或generation，在写入前确认Chunk仍属于本次版本；否则重新入队，不写入过期结果。
7. 扫描失败时保留已有记录并报告错误；只有成功完成的目录扫描才进行“文件确实删除”的差集清理。记录ScanResult.errors，不把部分失败显示成全部成功。

增量验收例：固定10,000 Chunk的库只修改一个有10个Chunk的文档，记录旧/新Chunk ID与向量数；确认其他文档向量未重新计算、旧内容不再命中、新内容在更新完成后可以命中。10个Chunk只是示例，实际需记录重切后的数量。删除场景和没有内容变化的保存场景也要测。

离线闭环建议在`config/mod.rs`和`rag/mod.rs`新增明确策略，例如`offline_strict`：开启时在构造外部LLM客户端之前直接禁止远端调用，即便继承了Key也不能出域。这个配置当前不存在，需要实现。Embedding客户端也应验证URL为明确允许的loopback地址；仅Python服务端绑定本机不足以限制Rust配置指向外部URL。

在功能未补前，报告实验只执行本地检索；不调用可能带已有Key的RAG生成路径。不要以“.env里填了OFFLINE=1”证明整应用不会联网。

### C组：可选优化，不作为此次报告完成条件

- 同一个BGE-small做PyTorch FP32 / ONNX FP32 / ONNX INT8对照，固定tokenizer、pooling、normalize，并同时测质量损失与CPU收益。导出和量化在准备阶段完成；不预设INT8必然更快。[Sentence Transformers ONNX说明](https://www.sbert.net/docs/sentence_transformer/usage/efficiency.html)。
- 模型INT8量化与输出向量量化分开记录：量化推理模型不意味着SQLite中的f32向量自动变小。
- 纯Rust推理Provider、ONNX Runtime分发、PDF/Word/OCR、全文/混合检索、reranker、完整权限系统、签名安装包都可写入后续路线，不用为完成第1项报告同时开发。
- 若调研BGE-M3，官方1024维/8192序列长度可作为候选能力；当前SentenceTransformer接法只输出dense向量，不应宣称已经验证其sparse或多向量检索。[BGE-M3模型卡](https://huggingface.co/BAAI/bge-m3)。

## 7. 最少增加哪些测试

建议在`src-tauri/tests/`补真正可检验业务行为的集成测试；Python输入处理测试放`embedding-service/tests/`。多数测试用可控向量和临时库即可，真实模型测试单列，不能要求所有单元测试每次加载大模型。

| 测试 | 断言 |
|---|---|
| 向量库一致性 | 已知非零向量Top-K/距离正确；维度错误、NaN/Infinity被拒绝；平局规则明确 |
| 空间隔离 | 相同维度的不同模型/配置也不能混搜；跨知识库Chunk导入失败 |
| 覆盖率 | 只导入部分向量时不能标完整；同批重复Chunk不虚增覆盖率 |
| 增量 | 修改只影响目标文档；新向量可查询；删除不留陈旧结果；不变文档不重复Embedding |
| 异常 | 模型中途失败后可重试；scan错误不删除未确认缺失的数据；并发更新不写过期向量 |
| 评测指标 | 手工已知排序验证Hit/Recall/MRR；无答案问题不混入Recall分母 |
| 离线策略 | strict模式下，即使存在测试Key，也不会构造/调用外部LLM；模型缺失明确失败，不静默在线下载或回退Mock |

这些测试是计划，不是本次已经通过的检查。首次落地时优先覆盖实际实现的A组与选定的B组，避免为了测试数量写镜像代码。

## 8. 如何验证图片要求的“本地数据安全闭环”

报告分清三层证据：代码的数据流设计、运行观察、尚未完成的安全措施。仅数据保存在本地，不等于已经合规。

建议用专属实验环境和模拟金融文档完成以下流程：

1. 联网准备依赖和模型，保存指纹；关闭应用后断开该测试机网络或在隔离环境限制出站，保留loopback。
2. 启动应用/Sidecar，导入资料、真实向量化、检索、修改文档、更新向量、再次检索；重启后复核持久化结果。
3. 使用连接记录或网络跟踪，区分本地8902通信、开发期1420通信、外部连接。简单Get-NetTCPConnection快照只能发现当时连接，不能证明从未发起短连接；严格的“无外发”结论需覆盖完整实验窗口的记录。
4. 检查外发请求尝试也应记录，不能只因断网请求失败就写“不发生外发”。避免把系统其他进程流量归因于Demo。
5. 检查原文、Chunk、Vector、DB/WAL、日志、备份和异常信息分别存在哪里。删除数据库行不等于物理擦除磁盘历史页，当前不宣称安全擦除。

基础规范部分优先梳理适用范围与对应技术措施。已查阅的官方入口包括[证券期货业网络和信息安全管理办法](https://www.csrc.gov.cn/csrc/c101953/c7202800/content.shtml)及[JR/T 0197-2020金融数据安全分级指南](https://std.samr.gov.cn/hb/search/stdHBDetailed?id=B081D125A6762DB8E05397BE0A0A5EA7)。法律、监管要求和推荐性行业标准要分列，交付时复核版本与本机构适用性；这份技术报告不直接替代公司合规审核。

可以写一张小表：数据分类分级→只用模拟资料/建立来源标签；访问控制→用户目录权限与后续鉴权；数据传输→默认离线和出域开关；凭据→后续Windows凭据存储；日志→不记录敏感正文和Key；生命周期→删除/备份/WAL的边界。准确标出“当前已有/本轮验证/后续建议”，不把建议冒充实现。

关于苍穹AI，只写适配边界：当前本地检索已返回文件名、Chunk和分数，可封装统一工具/检索接口；还需取得平台的认证、协议、部署域、输入输出及审计要求。不要假设DeepSeek客户端直接等同于苍穹AI接入。

## 9. 最终报告建议目录与写法

建议正文约12—18页，篇幅是建议；原始实验数据和命令放附录，不用截图堆页数。

| 章节 | 应写内容 | 所需证据 |
|---|---|---|
| 1 研究目标与范围 | 按图片解释PC端、离线、轻量化及研究边界 | 图片要求对应表 |
| 2 业务场景与技术约束 | 行情资料、投研、交易流程/制度；文档管理、检索、问答 | 模拟场景、目标PC假设；未调研公司真实流程需明确 |
| 3 评价方法 | 候选、门槛、变量、数据集、指标、实验限制 | 固定实验配置与标注方法 |
| 4 桌面框架对比 | Tauri+Rust、Electron：架构、资源、部署、维护与兼容性 | 官方资料；当前Tauri实测；未做等价Electron实验就不填虚构性能 |
| 5 向量模型对比 | 中文检索效果、CPU开销、输入策略、模型体积、许可 | 模型卡、实际ModelInfo、质量表、性能表 |
| 6 嵌入式存储对比 | fallback、sqlite-vec：算法、事务、增量、检索性能、部署成本 | 同向量磁盘实验与一致性记录 |
| 7 Demo验证 | 离线检索、文件监听、增量更新、资源占用 | 命令/原始数据、有限截图、异常案例 |
| 8 安全边界与部署分析 | 数据流、基础规范、依赖/模型供应链、Python体积、出域边界 | 官方规范入口、配置/运行记录、待补措施 |
| 9 场景化选型结论 | 推荐组合、适用条件、放弃原因、限制与替代方案 | 逐条指向前文实验或资料 |
| 附录 | Git提交、环境、模型/数据指纹、原始结果、复现步骤、参考资料 | 完整证据包 |

建议至少形成：一张总对比表、一张模型效果表、一张存储规模-延迟图、一张完整运行资源/磁盘表、一张离线及增量用例表。图表均从原始数据生成，空白测试项写“未测”，不填0。

结果表模板：

| 方案 | 证据类型 | Hit@5 | Recall@5 | MRR@10 | 端到端P95 ms | 索引texts/s | 应用树PrivateBytes峰值 MiB | 总部署MiB | 许可/边界 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| BGE-small + fallback | 待正式实验 | — | — | — | — | — | — | — | 记录实际版本 |
| M3E-base + fallback | 研究对照，待实验 | — | — | — | — | — | — | — | 模型卡限制非商用 |
| BGE-small + sqlite-vec | 待小集成实验 | — | — | — | — | — | — | — | 与fallback同向量 |

为计划实验可以暂定目标，例如“10,000 Chunk热态端到端P95≤1秒、Hit@5≥85%、整套进程PrivateBytes峰值≤2GiB”。这些**不是图片标准、行业标准或实测结果**，应在测量前由项目组根据实际目标机和业务容忍度确定。时间有限时也可以只报告观察值与适用性，不承诺未经确认的SLA。

结论用条件句表达，例如：“在机器A、语料版本B、N条Chunk和配置C下，方案X达到事先约定目标；方案Y的质量变化为……、资源代价为……，因此在……场景选X，在……情况下复评Y。”不能现在预写某模型最佳。

## 10. 建议实施顺序

以下按一名主要实施者约8—10个工作日估算，取决于Rust熟悉程度、模型环境和标注工作量；不是新的任务期限。

| 顺序 | 工作 | 当阶段交付 |
|---|---|---|
| 第1天 | 图片要求对应表、候选资料卡、环境版本固定、CPU与前缀配置核实 | 报告前3章初稿、环境清单 |
| 第2—3天 | 模拟语料/标注；增加CLI、分段计时、结果导出和关键测试 | 可重复跑的单候选实验 |
| 第4天 | BGE-small与M3E研究对照的质量/CPU/资源测试 | 模型结果表及原始数据 |
| 第5—6天 | sqlite-vec隔离小验证，与fallback做相同向量磁盘对比 | 存储对比与一致性证据 |
| 第7天 | 当前增量流程与离线验证；如需完整Demo验收，补B组最小增量服务 | 能力边界/用例结果；新增功能单列 |
| 第8天 | 代表性目标机复核与部署体积统计；无目标机则写限制 | 适用配置边界 |
| 第9—10天 | 整理图表、安全约束、场景结论与复现附录 | 完整报告及证据包 |

时间不足时优先缩减BGE-M3、ONNX、Electron性能小壳和生产打包；保留候选文献对比、真实模型效果、当前资源、离线验证及证据边界。sqlite-vec来不及实测时明确列为后续验证，不能宣称已比较优劣。

推荐第一步：**增加CPU与模型配置回读、离线实验CLI、原始结果导出，随后固定语料和标注。** 这些工作比继续扩充UI更直接支撑技术选型报告。

## 11. 开发与Git操作建议

本轮未创建分支、提交或推送。开始实现时，可以按以下方式保留当前Demo基线：

```powershell
Set-Location E:\Workspace\SecRAG
git status --short
git switch -c feat/selection-evaluation
```

一个功能一个小提交，例如“固定CPU与模型配置”“增加实验CLI”“增加检索评测”“增加sqlite-vec基准”。每次提交前查看`git diff`，只暂存明确文件路径。不要使用`git add .`将实验资料、环境信息或日志整批加入。

提交源码、评测脚本、可公开的模拟标注、脱敏结果摘要；不提交`.env`、模型、`.venv`、真实金融资料、数据库和原始敏感日志。Git分支是本地版本线，`git push -u origin feat/selection-evaluation`才会上传远端；确定文件内容可公开后再执行。

报告的每条实验结论保留对应Git提交和run_id。代码改动后，只有受影响的指标需要重跑；不能将不同模型配置或切块版本的结果放在同一行假装来自同一实验。
