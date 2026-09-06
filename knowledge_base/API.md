# 知识库模块 API 文档

**服务地址**: `http://127.0.0.1:8901`

## 接口列表

### 1. 导入文档

```
POST /api/ingest
```

**请求**:
```json
{
  "file_path": "test_docs/catl_2024_q3.md",
  "model": "bge-small"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file_path | string | 是 | 文件路径（支持 .md .txt .pdf） |
| model | string | 否 | embedding模型，默认 bge-small |

**响应**:
```json
{
  "doc_id": "3afaf130-a44b-427d-a524-8f7e584b132d",
  "title": "catl_2024_q3",
  "model": "bge-small",
  "chunk_count": 4,
  "status": "success"
}
```

---

### 2. 检索

```
POST /api/search
```

**请求**:
```json
{
  "query": "宁德时代毛利率",
  "top_k": 3,
  "model": "bge-small"
}
```

**响应**:
```json
{
  "chunks": [
    {
      "doc_id": "3afaf130-...",
      "position": 1,
      "content": "毛利率方面，2024年三季度综合毛利率为23.5%...",
      "score": 0.0325,
      "title": "catl_2024_q3",
      "source": "test_docs/catl_2024_q3.md"
    }
  ],
  "query": "宁德时代毛利率",
  "model": "bge-small",
  "count": 3
}
```

检索方式：BM25 + 向量检索，通过自适应 RRF 融合排序。

---

### 3. 信号召回

```
POST /api/recall
```

**请求**:
```json
{
  "signal_type": "price_surge",
  "symbol": "300750",
  "name": "宁德时代",
  "top_k": 5
}
```

| signal_type | 自动构造的查询 |
|-------------|--------------|
| price_surge | {name} 涨幅 原因 分析 利好 |
| price_drop | {name} 下跌 风险 利空 跟踪 |
| volume_anomaly | {name} 成交量 异动 资金 |

---

### 4. 文档列表

```
GET /api/documents
```

---

### 5. 统计

```
GET /api/stats
```

**响应**:
```json
{
  "document_count": 10,
  "chunk_count": 42,
  "vector_count": 42,
  "database": "data/knowledge.db"
}
```

---

### 6. 健康检查

```
GET /api/health
```

---

### 7. 查询分析

```
GET /api/analyze?q=宁德时代毛利率
```

**响应**:
```json
{
  "query": "宁德时代毛利率",
  "terms": [
    { "term": "宁德时代", "doc_freq": 2, "idf": "2.944" },
    { "term": "毛利率", "doc_freq": 6, "idf": "1.609" }
  ],
  "specificity": "0.682",
  "vector_weight": "0.591",
  "bm25_weight": "0.946"
}
```

---

### 8. 可用模型

```
GET /api/models
```

---

## 模型说明

| key | 全称 | 大小 | 维度 |
|-----|------|------|------|
| bge-small | BAAI/bge-small-zh-v1.5 | ~100MB | 512 |
| m3e-base | moka-ai/m3e-base | ~400MB | 768 |
| bge-m3 | BAAI/bge-m3 | ~2.3GB | 1024 |

## 架构

```
A同学 Agent进程 (8900)
        │
        ▼ HTTP
B同学 知识库服务 (8901) ←→ SQLite (knowledge.db)
        │
        ▼ HTTP
   Embedding服务 (8902) ← Python常驻，模型加载一次
```

## 启动方式

```bash
cd ~/Desktop/knowledge_base
cargo run
```

会自动启动 Embedding 服务（8902），然后启动知识库 API（8901）。
