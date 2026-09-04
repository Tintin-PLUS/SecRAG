# SQLite Schema

默认文件：`data/local-kb.sqlite3`。启动时幂等建表；连接启用 `foreign_keys=ON`、WAL、`synchronous=NORMAL` 和 5 秒 busy timeout。

## 表

### knowledge_base

`id` 主键；`name`；唯一 `root_path`；`chunk_size`；`chunk_overlap`；创建/更新时间。删除知识库级联全部业务数据。

### document

`id` 主键；`knowledge_base_id` 外键；唯一 `(knowledge_base_id,file_path)`；文件名、SHA-256、类型、状态和时间。当前状态为 `WAITING_EMBEDDING` 或 `MOCK_INDEXED`；外部 Vector 的索引总体状态存于 `index_state`。

### chunk

`id` 主键；`document_id` 外键；唯一 `(document_id,chunk_index)`；文本、JSON metadata 和创建时间。修改文档会删除其旧 Chunk 并重建。

### embedding_profile

保存完整 `EmbeddingModelInfo`：模型标识/版本、维度、配置哈希、runtime、precision、normalize、pooling、max length、query/document prefix。唯一键为 `(knowledge_base_id,model_id,model_version,config_hash)`。

### vector_record

复合主键 `(chunk_id,embedding_profile_id)`；保存冗余 `dimension`、little-endian `f32` BLOB 和时间。外键级联保证删除 Chunk/Profile 时清理 Vector。

### index_state

复合主键 `(knowledge_base_id,embedding_profile_id)`；状态为 `INDEXED`、`MOCK_INDEXED`、`STALE` 或逻辑空状态，并记录 detail/更新时间。

### llm_config / schema_version

`llm_config` 为未来可持久化非敏感 LLM 配置预留；当前 DeepSeek API Key 只读环境变量或项目根目录 `.env`，不写入 SQLite。`schema_version` 记录迁移基线。

## 常用诊断 SQL

```sql
SELECT id,name,root_path FROM knowledge_base;
SELECT file_name,status,file_hash FROM document;
SELECT document_id,COUNT(*) FROM chunk GROUP BY document_id;
SELECT embedding_profile_id,COUNT(*) FROM vector_record GROUP BY embedding_profile_id;
SELECT p.model_id,p.dimension,p.config_hash,s.status
FROM embedding_profile p LEFT JOIN index_state s ON s.embedding_profile_id=p.id;
```

不要手工修改 BLOB。维度由 Ingest 与 Search 双重校验；需要重新导入时应通过服务/API 执行。
