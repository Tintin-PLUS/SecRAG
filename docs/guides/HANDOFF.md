# Handoff

## 【框架负责人】

已经完成：Tauri/React UI、Rust/SQLite 内核、Document/Chunk 增量生命周期、VectorStore、Mock/外部 JSON 导入，以及 Python SentenceTransformer Sidecar 融合。Rust 已注册 `bge-small`、`m3e-base`、`bge-m3` Provider，支持应用内服务启动/停止、批量整库索引、真实文本检索和真实 Embedding RAG。模型失败不会回退 Mock，模型空间由完整 `EmbeddingModelInfo` 隔离。

接下来负责：在有模型的 Windows 目标机做 GUI smoke test；增加索引进度/取消、Vector coverage/PARTIAL、模型目录哈希；评估 sqlite-vec 和正式安装包。保护 `embedding/model.rs`、`embedding/integration.rs`、`vector_store/store.rs` 及 SQLite 唯一键语义。

入口文件：`src-tauri/src/embedding/python_sidecar.rs`、`service.rs`、`src-tauri/src/commands/mod.rs`、`src/App.tsx`。

## 【Embedding 负责人】

先执行 `EMBEDDING_RUNTIME_SETUP.md`，至少准备 `models/bge-small`，再完成 sample_docs 的真实索引和 Query 回归。核实每个模型的许可证、模型/Tokenizer 版本、最大长度、实际 Pooling、Document/Query Prefix、Normalize 和 CPU 线程配置。

当前 Sidecar 显式 `normalize_embeddings=True`，Pooling 使用 SentenceTransformer 模型自身配置，Prefix 为空。若评测证明某模型需要不同策略，必须同时修改 Python/Rust ModelInfo、提升 `model_version/config_hash` 并重建索引；不能复用旧 Profile。

输出物：模型目录来源和哈希、固定配置清单、10 条可重复 Query、Top-K 标注结果、首次加载时间、batch 1/8/16/32 吞吐和峰值内存。权重和真实敏感资料不得提交 Git。

## 【性能负责人】

先运行 UI 现有 100/1000/10000 Chunk Vector 基准，再按 `PERFORMANCE_TESTING.md` 测真实 Sidecar。分开记录服务启动时间、首次模型加载、热态 Batch、文档索引总时长、Query P50/P95、Rust/Tauri 内存与 Python Sidecar 内存。

至少对 `bge-small` 进行完整 CPU-only 基线；有资源再比较 `m3e-base` 和 `bge-m3`。固定数据、chunk_size/overlap、线程、电源模式和模型配置。原始 CSV/脚本应可重复，不使用真实公司内部材料。

## 接口冻结结论

**Sidecar v1 和既有 Embedding v1 类型现在可以冻结并并行工作。** 可冻结边界包括 `EmbeddingInput`、`EmbeddingOutput`、`EmbeddingModelInfo`、`EmbeddingProvider`、`POST /v1/embeddings`、`VectorIngestService`、`VectorStore` 和 Raw Query Vector Search。

允许新增可选字段或新 Provider；不得删除/改义现有必填字段。模型空间设置发生变化时必须升级 `config_hash`。当前仍需并行跟踪的增强是模型目录哈希、Vector coverage/PARTIAL 和大批次 staging，它们不阻塞现有联调。
