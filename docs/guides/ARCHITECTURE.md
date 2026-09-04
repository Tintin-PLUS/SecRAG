# Architecture

## 目标与边界

应用在 Windows PC 上闭环保存原文元数据、Chunk 和 Vector。前端只调用 Tauri Command，不直接访问 SQLite；Document、Embedding、Vector、Retrieval、RAG 通过稳定边界解耦。真实模型运行在仅监听 loopback 的 Python SentenceTransformer Sidecar 中；结构化行情库、Agent、Reranker 和服务型向量数据库仍不在当前范围。

```text
React UI
   │ Tauri IPC
   ▼
commands ──► KnowledgeBase / DocumentService ──► Parser + Chunker
   │                         │                         │
   │                         └──── SQLite metadata ◄──┘
   │
   ├──► EmbeddingRegistry ──► EmbeddingProvider (Mock / Python Sidecar)
   │                                  │ HTTP /v1/embeddings
   │                                  ▼
   │                         SentenceTransformer models
   │                                  │ EmbeddingOutput
   ├──► VectorIngestService ──────────┘
   │             │ validate compatibility + transaction
   │             ▼
   ├──► VectorStore Trait ──► SqliteVectorStore ──► SQLite BLOB
   │                                                   │
   ├──► RetrievalService ◄──── Rust cosine Top-K ◄─────┘
   │             │
   └──► RagService ──► Prompt ──► DeepSeekClient (optional external API)
```

## 模块职责

| 模块 | 职责 | 禁止依赖 |
|---|---|---|
| `document` | 文件 hash、UTF-8 解析、Chunk 生命周期、增量扫描 | 具体 Embedding |
| `chunk` | `Chunker` Trait 与 `FixedSizeChunker` | 数据库、模型 |
| `embedding` | 标准协议、Provider、Registry、Python Sidecar/进程管理、Ingest | UI、LLM |
| `vector_store` | 插入、搜索、删除、计数抽象 | 具体模型 |
| `retrieval` | 选择同一 Profile、文本/Raw Vector 检索 | SQLite 细节、模型名常量 |
| `rag` | Retrieval → Context → Prompt → LLM | SQLite |
| `llm` | DeepSeek Chat Completions、Bearer 鉴权、thinking 配置 | Embedding |
| `watcher` | notify 递归监听、debounce、触发文件级扫描 | UI 线程 |
| `benchmark` | 隔离数据的可重复微基准 | 生产数据 |

## 状态与生命周期

新增或内容 hash 改变：旧 Chunk 级联删除 Vector，只重建当前 Document，文档为 `WAITING_EMBEDDING`，已有 Profile 为 `STALE`。Mock 建索引后为 `MOCK_INDEXED`；外部真实 Vector 注入成功为 `INDEXED`。删除文件的扫描会删除 Document，并依靠外键级联清理 Chunk/Vector。

Profile 由 `(knowledge_base_id, model_id, model_version, config_hash)` 唯一确定。不同模型版本、维度、Pooling、Normalize、Prefix 或 Tokenizer 配置应产生不同 `config_hash`，因此不会在同一检索空间中混用。

## 并发和数据一致性

数据库连接由短时 `Mutex` 保护，WAL、foreign keys、busy timeout 已启用。批量 Vector 在写入前完成维度与 Chunk 归属检查；批量写入使用事务。模型推理不持有 SQLite 锁，并在 Tauri blocking worker 中执行。文件监听线程经 650 ms 静默窗口合并事件，不阻塞 Tauri UI。

## 可替换点

- sqlite-vec：新增 `VectorStore` 实现，保持 Command、Retrieval 和 Ingest 不变。
- 真实模型：当前 `PythonSidecarEmbeddingProvider` 已接入三个 SentenceTransformer 配置；仍可增加 Rust Provider，或通过 JSON 注入 Vector。
- 其他 LLM：实现新的 `LlmClient`，RAG 编排不变；当前产品路径固定为 DeepSeek。
- 其他 Chunk 策略：实现 `Chunker`，Document Service 选择策略。
