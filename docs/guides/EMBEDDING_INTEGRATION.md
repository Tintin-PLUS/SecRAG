# Embedding Integration Guide

本文件直接交给 Embedding 负责人。你不需要先读完整项目；先阅读本页，再从 `src-tauri/src/embedding/` 开始。

## 1. 架构位置

框架负责 `Document → UTF-8 Parser → Chunk`。Embedding 负责 `Tokenizer → Prefix → Truncation/Padding → Inference → Pooling → Normalize`，并输出标准 `EmbeddingOutput`。随后框架的 `VectorIngestService` 完成校验、Profile 兼容性、SQLite 写入和 Index 状态。Query 使用同一 Embedding Space 生成向量，再交给 Retrieval。

真实模型有两条独立接入路线：

- **已实现的 Python Sidecar：** `python_sidecar.rs` 实现 Provider，通过 `http://127.0.0.1:8902/v1/embeddings` 调用 `embedding-service/server.py`。当前注册 `bge-small`、`m3e-base`、`bge-m3`。
- **Rust Provider：** 仍可实现新的 `EmbeddingProvider` 并注册到 `EmbeddingRegistry`。
- **外部程序：** 读取 Chunk 后生成 JSON，通过 UI 的“导入外部 Vector JSON”或对应 Tauri Command 写入；Query Vector 直接走 Raw Vector Search。这条路线不需要模型运行时进入主项目。

运行环境与模型的手工准备步骤见 `EMBEDDING_RUNTIME_SETUP.md`。

### Python Sidecar v1 协议

Rust 批量调用：

```text
POST /v1/embeddings
Content-Type: application/json
```

请求体为：

```json
{
  "model_id": "bge-small",
  "inputs": [
    {
      "request_id": "request-uuid",
      "input_type": "DOCUMENT",
      "text": "待向量化文本",
      "document_id": "document-uuid",
      "chunk_id": "chunk-uuid",
      "metadata": {}
    }
  ]
}
```

响应必须包含单一 `model_info` 和等长、等序、身份字段不变的 `outputs`。Rust 会同时检查 HTTP 状态、输出数量、request/input/chunk 映射、完整 ModelInfo、维度以及 NaN/Infinity。任何失败都不会静默回退到 Mock。

辅助端点：`GET /health` 返回协议、依赖、离线模式和已加载模型；`GET /v1/models` 返回三个模型空间。旧 `/embed` 仅为原压缩包兼容保留，不被主框架调用。

## 2. Rust Input

定义位于 `src-tauri/src/embedding/model.rs`：

```rust
pub struct EmbeddingInput {
    pub request_id: String,
    pub input_type: EmbeddingInputType, // DOCUMENT | QUERY in JSON
    pub text: String,
    pub document_id: Option<String>,
    pub chunk_id: Option<String>,
    pub metadata: HashMap<String, serde_json::Value>,
}
```

Document Input 必须保留 `chunk_id`；Query Input 通常只有 `request_id` 与 `text`。框架不做 Tokenizer、Prefix 或最大长度裁剪。

Document 示例：

```json
{
  "request_id": "doc-job-001-12",
  "input_type": "DOCUMENT",
  "text": "信用风险管理应综合评估交易对手资质……",
  "document_id": "document-uuid",
  "chunk_id": "chunk-uuid",
  "metadata": {"chunk_index": 12}
}
```

Query 示例：

```json
{
  "request_id": "query-20260901-001",
  "input_type": "QUERY",
  "text": "信用风险如何持续监测？",
  "document_id": null,
  "chunk_id": null,
  "metadata": {}
}
```

## 3. 必须返回的 Output

```rust
pub struct EmbeddingOutput {
    pub request_id: String,
    pub input_type: EmbeddingInputType,
    pub model_info: EmbeddingModelInfo,
    pub vector: Vec<f32>,
    pub chunk_id: Option<String>,
    pub metadata: HashMap<String, serde_json::Value>,
}
```

`model_info` 完整结构：

```json
{
  "model_id": "your-stable-model-id",
  "model_name": "Human Readable Name",
  "model_version": "1.0.0",
  "dimension": 768,
  "runtime": "onnxruntime-cpu",
  "precision": "int8",
  "normalize": true,
  "pooling": "mean",
  "max_length": 512,
  "query_prefix": "query: ",
  "document_prefix": "passage: ",
  "config_hash": "sha256-of-all-space-affecting-settings"
}
```

业务层直接依赖 `model_id`、`model_version`、`dimension`、`config_hash`、`vector`、`chunk_id`；其他字段用于审计、诊断和兼容性判断。字段不可伪造或省略。

## 4. Batch JSON Schema 与示例

外部导入顶层结构不是单个 `EmbeddingOutput`，而是减少重复信息的 `ExternalVectorBatch`：

```json
{
  "knowledge_base_id": "knowledge-base-uuid",
  "model_info": {
    "model_id": "bge-example",
    "model_name": "Example Model",
    "model_version": "1",
    "dimension": 4,
    "runtime": "external-test",
    "precision": "f32",
    "normalize": true,
    "pooling": "mean",
    "max_length": 512,
    "query_prefix": null,
    "document_prefix": null,
    "config_hash": "example-config-v1"
  },
  "vectors": [
    {"chunk_id":"existing-chunk-1","request_id":"job-1","vector":[0.1,0.2,0.3,0.4]},
    {"chunk_id":"existing-chunk-2","request_id":"job-2","vector":[0.2,0.1,0.4,0.3]}
  ]
}
```

完整模板在 `examples/external_vectors.template.json`。当前导入器接受 JSON 文本；导入前逐条检查：非空 batch、dimension > 0、每条数组长度、Chunk 是否存在、Chunk 是否属于目标知识库。校验通过后批量事务写入。

概念 JSON Schema：

```json
{
  "type":"object",
  "required":["knowledge_base_id","model_info","vectors"],
  "properties":{
    "knowledge_base_id":{"type":"string"},
    "model_info":{
      "type":"object",
      "required":["model_id","model_name","model_version","dimension","runtime","precision","normalize","pooling","config_hash"]
    },
    "vectors":{
      "type":"array","minItems":1,
      "items":{"type":"object","required":["chunk_id","vector"],"properties":{"chunk_id":{"type":"string"},"request_id":{"type":["string","null"]},"vector":{"type":"array","items":{"type":"number"}}}}
    }
  }
}
```

## 5. 维度、Normalize、Prefix 和 Pooling

- 维度可以是 512/768/1024 或其他正整数；框架不写死。Profile 与 Query 必须严格同维。
- Normalize 可为 true/false。当前 Store 使用 cosine，会再次除范数；仍必须如实记录。
- Query Prefix 与 Document Prefix 由模型适配器分别应用，框架不会拼接。
- Pooling 完全属于 Embedding 负责人；输出只能是最终单个 `Vec<f32>`。
- Tokenizer、特殊 token、padding、truncation、max length 属于 Embedding 负责人。
- ONNX/其他 Runtime、线程数、量化和模型加载属于 Embedding 负责人；Python SentenceTransformer Runtime 现已作为进程外 Sidecar 接入，未嵌入 Rust 二进制。

上述任何影响 Embedding Space 的变化都必须改变 `config_hash`。建议对模型文件哈希、Tokenizer 版本、max length、prefix、pooling、normalize、precision 与量化配置的 canonical JSON 求 SHA-256。

## 6. 当前 Sidecar Provider 与扩展 Rust Provider

当前实现位于：

- `src-tauri/src/embedding/python_sidecar.rs`：协议映射与严格响应校验；
- `src-tauri/src/embedding/service.rs`：Windows Python 子进程、健康检查、日志和退出清理；
- `embedding-service/server.py`：Tokenizer、模型加载、Pooling 和 Normalize；
- `src-tauri/src/commands/mod.rs::index_with_embedding`：读取 Chunk、分批推理、统一 Vector Ingest；
- `search_with_embedding` / `rag_query_with_embedding`：使用同一模型空间生成 Query Vector。

若未来改用纯 Rust Runtime，再实现新的 Provider：

实现文件建议新建 `src-tauri/src/embedding/real_provider.rs`，不要修改 `model.rs` 的公共类型：

```rust
impl EmbeddingProvider for YourProvider {
    fn model_info(&self) -> EmbeddingModelInfo { /* 准确描述 */ }
    fn embed(&self, input: EmbeddingInput) -> AppResult<EmbeddingOutput> {
        // 1 tokenizer/prefix/truncate
        // 2 inference/pooling/normalize
        // 3 原样传递 request_id、input_type、chunk_id、metadata
    }
}
```

然后在 `src-tauri/src/embedding/mod.rs` 导出，并在 `src-tauri/src/app/mod.rs`：

```rust
embeddings.register(Arc::new(YourProvider::load(config)?))?;
```

Provider 应 `Send + Sync`。模型加载失败必须返回明确错误；不要静默回退到 Mock，也不要把真实 Provider 的输出标记成 Mock。

## 7. 无 Rust 集成时先独立联调

1. 启动应用，创建知识库并扫描 `sample_docs`。
2. 从 SQLite 查询 Chunk ID：

   ```sql
   SELECT c.id,d.file_name,c.chunk_index,c.text
   FROM chunk c JOIN document d ON d.id=c.document_id
   WHERE d.knowledge_base_id='...';
   ```

3. 外部程序对这些文本批量生成 Vector，输出上述 JSON。
4. Embedding 页面粘贴 JSON 并导入。
5. Profile 卡片应显示正确 model_id、dimension、config_hash、runtime、Vector 数。
6. 在 Vector Search 选择该 Profile，粘贴外部程序生成的 Query Vector，运行 Raw Search，查看 score 与 Top-K Chunk。

Query Vector 不写入 `vector_record`，直接传入：

```text
search_by_vector(knowledge_base_id, embedding_profile_id, query_vector, top_k)
```

这使模型程序可以在完全独立的进程中先验证 Document/Query 一致性。

## 8. Index 重建规则

替换模型或改变任何 Space 配置时：

1. 生成新的 `model_version`/`config_hash`；
2. 对所有当前 Chunk 重新生成 Vector；
3. 导入会创建新 Profile，并把同知识库其他 Profile 标记 `STALE`；
4. Query 必须选择新 Profile；
5. 验证覆盖数量后，未来可调用 `delete_by_profile` 清理旧 Vector。

禁止为了省时间复用旧 Profile ID，禁止对旧 Vector 做截断/补零来适配新维度，禁止在同一 Profile 混用 Query/Document 配置。

## 9. 允许和不建议修改的文件

允许新增/修改：

- `embedding/real_provider.rs`（新增）
- `embedding/python_sidecar.rs`、`embedding-service/`（Sidecar 协议升级时）
- `embedding/mod.rs`（导出）
- `app/mod.rs`（注册 Provider）
- 独立模型配置、Provider 单元测试、真实 Embedding benchmark

尽量不要修改：

- `embedding/model.rs` 公共协议
- `embedding/integration.rs` 校验和事务语义
- `vector_store/store.rs` Trait
- SQLite 主键/唯一键和 Retrieval 的同 Profile 约束

如果协议确实不足，先与框架负责人评审并版本化，避免并行开发互相破坏。

## 10. 验证清单

```powershell
cd <仓库目录>\local-kb\src-tauri
cargo check --locked
cargo check
cd ..
npm.cmd run build
npm.cmd run tauri dev
```

- 相同文本与配置多次输出相同长度和数值（允许文档化的浮点容差）。
- Document 与 Query 使用各自正确 Prefix。
- 输出无 NaN/Infinity，非预期零向量报错。
- JSON Vector 数等于预期 Chunk 数。
- SQLite `vector_record.dimension` 与 Profile 一致。
- Raw Query 能返回 Top-K，且 Query 维度错误会被拒绝。
- 改变 pooling/normalize/prefix 后 `config_hash` 改变且旧 Index 为 STALE。

## 11. 常见错误

- **chunk not part of knowledge base：** JSON 使用了另一个 KB 的 Chunk ID，或文件修改后旧 Chunk ID 已被删除。
- **expected N values, got M：** Provider 输出维度与 `model_info.dimension` 不一致。
- **profile dimension/query dimension：** Raw Query 与所选 Profile 不同 Space。
- **no vectors / WAITING_EMBEDDING：** 只扫描了文档，尚未导入 Vector。
- **STALE：** 文件 hash 或 Embedding Space 变化，需要重新生成当前 Chunk 的 Vector。
- **结果效果差但链路正常：** 先确认 Query/Document Prefix、Pooling、Normalize 和 Tokenizer 完全匹配，再做模型效果判断；不要参考 Mock 质量。
- **Sidecar protocol/model_info differs：** Rust 与 Python 配置不一致，重新构建并重启两侧；禁止关闭兼容性校验。
- **sentence-transformers is not installed：** 运行 `scripts/setup-embedding.ps1`。
- **offline mode 找不到模型：** 设置正确的 `LOCAL_KB_MODEL_*` 本地目录，或明确执行下载脚本后恢复 offline=1。
