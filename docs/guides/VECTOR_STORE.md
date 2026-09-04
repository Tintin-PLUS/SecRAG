# Vector Store

## 当前实现

`VectorStore` Trait 定义 `insert`、`insert_batch`、`search`、按 Document/Chunk/Profile 删除、`count` 和 `clear`。业务层只依赖该 Trait 的语义；`SqliteVectorStore` 把 `f32` 以 little-endian BLOB 写入 SQLite，搜索时读取同一 Profile 的 Vector，在 Rust 侧计算 cosine 并排序 Top-K。

这是需求允许的 Windows 稳定 fallback。它优先保证 SQLite、外部 Vector 注入和检索调用链可运行，不宣称适合大规模生产数据。

## 数据约束

- 一个 Search 必须指定一个 `embedding_profile_id`。
- Query 长度必须等于 Profile 维度；每条写入 Vector 也必须等于 `model_info.dimension`。
- Chunk 必须属于目标知识库。
- 同批输出不得混入不同 `EmbeddingModelInfo`。
- 零向量 cosine 定义为 0 分，空 Query 被拒绝。
- `(chunk_id,profile_id)` 冲突采用更新语义。

## 为什么没有直接依赖 sqlite-vec

本期目标平台为 Windows MSVC，而 sqlite-vec 的扩展装载、版本与分发需要单独做兼容性验证。为避免底层扩展阻塞整体原型，当前选择无扩展的 bundled SQLite。这个选择的代价是搜索为 O(N·D)，且读取全部候选 BLOB；文档量较大时延迟和内存开销会上升。

## 替换为 sqlite-vec

1. 新建 `SqliteVecStore` 并实现现有 `VectorStore` Trait。
2. Schema migration 创建 vec virtual table；保留 `embedding_profile` 和 `index_state`。
3. 对不同 dimension 建独立 virtual table/partition，或按 sqlite-vec 当前官方能力选择策略。
4. Ingest 仍先做 Profile、Chunk 和 dimension 校验。
5. Retrieval 不改 API，只替换注入的 Store。
6. 针对 64/512/768/1024 维和 100/1000/10000 Chunk 做一致性与性能回归。

不要在 Command 或 RagService 中调用 sqlite-vec SQL，否则会破坏替换边界。

## 相似度约定

当前返回 cosine similarity，范围通常为 `[-1,1]`，越大越相似。框架不会强制外部模型 Normalize；cosine 自身除以范数。模型负责人必须在 `model_info.normalize` 中如实声明，并把差异包含在 `config_hash`。不要把不同 normalize/pooling/prefix 配置的 Vector 放到一个 Profile。

