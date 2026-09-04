use super::model::{EmbeddingInputType, EmbeddingModelInfo, EmbeddingOutput, ExternalVectorBatch};
use crate::{
    database::Database,
    error::{AppError, AppResult},
    vector_store::{SqliteVectorStore, VectorRecordInput, VectorStore},
};
use chrono::Utc;
use rusqlite::{OptionalExtension, params};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngestResult {
    pub profile_id: String,
    pub inserted: usize,
    pub status: String,
}

#[derive(Clone)]
pub struct VectorIngestService {
    db: Database,
    store: SqliteVectorStore,
}

impl VectorIngestService {
    pub fn new(db: Database) -> Self {
        Self {
            store: SqliteVectorStore::new(db.clone()),
            db,
        }
    }

    pub fn ingest_embedding(
        &self,
        knowledge_base_id: &str,
        output: EmbeddingOutput,
        mock: bool,
    ) -> AppResult<IngestResult> {
        self.ingest_embeddings(knowledge_base_id, vec![output], mock)
    }

    pub fn ingest_embeddings(
        &self,
        knowledge_base_id: &str,
        outputs: Vec<EmbeddingOutput>,
        mock: bool,
    ) -> AppResult<IngestResult> {
        if outputs.is_empty() {
            return Err(AppError::InvalidInput(
                "embedding output batch is empty".into(),
            ));
        }
        let model_info = outputs[0].model_info.clone();
        let items = outputs
            .into_iter()
            .map(|output| {
                if output.input_type != EmbeddingInputType::Document {
                    return Err(AppError::InvalidInput(
                        "only document vectors can be ingested".into(),
                    ));
                }
                let chunk_id = output.chunk_id.ok_or_else(|| {
                    AppError::InvalidInput("document embedding requires chunk_id".into())
                })?;
                if output.model_info != model_info {
                    return Err(AppError::IncompatibleEmbedding(
                        "batch contains multiple embedding spaces".into(),
                    ));
                }
                Ok((chunk_id, output.vector))
            })
            .collect::<AppResult<Vec<_>>>()?;
        self.ingest_items(knowledge_base_id, model_info, items, mock)
    }

    pub fn ingest_external(&self, batch: ExternalVectorBatch) -> AppResult<IngestResult> {
        let items = batch
            .vectors
            .into_iter()
            .map(|v| (v.chunk_id, v.vector))
            .collect();
        self.ingest_items(&batch.knowledge_base_id, batch.model_info, items, false)
    }

    fn ingest_items(
        &self,
        kb_id: &str,
        info: EmbeddingModelInfo,
        items: Vec<(String, Vec<f32>)>,
        mock: bool,
    ) -> AppResult<IngestResult> {
        if info.dimension == 0 {
            return Err(AppError::InvalidInput(
                "embedding dimension must be greater than zero".into(),
            ));
        }
        if items.is_empty() {
            return Err(AppError::InvalidInput("vector batch is empty".into()));
        }
        let now = Utc::now().to_rfc3339();
        let profile_id = {
            let conn = self.db.connection()?;
            let exists: Option<String> = conn
                .query_row("SELECT id FROM knowledge_base WHERE id=?1", [kb_id], |r| {
                    r.get(0)
                })
                .optional()?;
            if exists.is_none() {
                return Err(AppError::NotFound(format!("knowledge base {kb_id}")));
            }
            let existing: Option<String> = conn.query_row(
                "SELECT id FROM embedding_profile WHERE knowledge_base_id=?1 AND model_id=?2 AND model_version=?3 AND config_hash=?4",
                params![kb_id, info.model_id, info.model_version, info.config_hash], |r| r.get(0)).optional()?;
            existing.unwrap_or_else(|| Uuid::new_v4().to_string())
        };
        {
            let mut conn = self.db.connection()?;
            let tx = conn.transaction()?;
            tx.execute("INSERT OR IGNORE INTO embedding_profile(id,knowledge_base_id,model_id,model_name,model_version,dimension,config_hash,runtime,precision,normalize,pooling,max_length,query_prefix,document_prefix,created_at)
                VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15)", params![profile_id,kb_id,info.model_id,info.model_name,info.model_version,info.dimension as i64,info.config_hash,info.runtime,info.precision,info.normalize as i32,info.pooling,info.max_length.map(|v|v as i64),info.query_prefix,info.document_prefix,now])?;
            let stored_dim: i64 = tx.query_row(
                "SELECT dimension FROM embedding_profile WHERE id=?1",
                [&profile_id],
                |r| r.get(0),
            )?;
            if stored_dim as usize != info.dimension {
                return Err(AppError::IncompatibleEmbedding(
                    "stored profile dimension differs from model_info".into(),
                ));
            }
            for (chunk_id, vector) in &items {
                if vector.len() != info.dimension {
                    return Err(AppError::InvalidInput(format!(
                        "chunk {chunk_id}: expected {} values, got {}",
                        info.dimension,
                        vector.len()
                    )));
                }
                if vector.iter().any(|value| !value.is_finite()) {
                    return Err(AppError::InvalidInput(format!(
                        "chunk {chunk_id}: vector contains NaN or infinity"
                    )));
                }
                let chunk_kb: Option<String> = tx.query_row("SELECT d.knowledge_base_id FROM chunk c JOIN document d ON d.id=c.document_id WHERE c.id=?1", [chunk_id], |r| r.get(0)).optional()?;
                if chunk_kb.as_deref() != Some(kb_id) {
                    return Err(AppError::InvalidInput(format!(
                        "chunk {chunk_id} is not part of knowledge base {kb_id}"
                    )));
                }
            }
            tx.execute("UPDATE index_state SET status='STALE',detail='another embedding space was activated',updated_at=?2 WHERE knowledge_base_id=?1 AND embedding_profile_id<>?3", params![kb_id,now,profile_id])?;
            tx.commit()?;
        }
        let records = items
            .into_iter()
            .map(|(chunk_id, vector)| VectorRecordInput {
                chunk_id,
                embedding_profile_id: profile_id.clone(),
                vector,
            })
            .collect();
        let inserted = self.store.insert_batch(records)?;
        let status = if mock { "MOCK_INDEXED" } else { "INDEXED" }.to_string();
        self.db.connection()?.execute("INSERT INTO index_state(knowledge_base_id,embedding_profile_id,status,detail,updated_at) VALUES(?1,?2,?3,NULL,?4)
            ON CONFLICT(knowledge_base_id,embedding_profile_id) DO UPDATE SET status=excluded.status,detail=NULL,updated_at=excluded.updated_at", params![kb_id,profile_id,status,now])?;
        self.db.connection()?.execute("UPDATE document SET status=?3,updated_at=?4 WHERE knowledge_base_id=?1 AND EXISTS(SELECT 1 FROM chunk c WHERE c.document_id=document.id) AND NOT EXISTS(
            SELECT 1 FROM chunk c WHERE c.document_id=document.id AND NOT EXISTS(SELECT 1 FROM vector_record v WHERE v.chunk_id=c.id AND v.embedding_profile_id=?2))",
            params![kb_id,profile_id,status,now])?;
        Ok(IngestResult {
            profile_id,
            inserted,
            status,
        })
    }
}
