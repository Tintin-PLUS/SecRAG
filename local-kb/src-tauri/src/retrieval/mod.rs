use crate::{
    database::Database,
    embedding::{EmbeddingInput, EmbeddingInputType, EmbeddingProvider},
    error::{AppError, AppResult},
    vector_store::{SearchHit, SqliteVectorStore, VectorStore},
};
use rusqlite::OptionalExtension;
use std::{collections::HashMap, sync::Arc};
use uuid::Uuid;

#[derive(Clone)]
pub struct RetrievalService {
    db: Database,
    store: SqliteVectorStore,
}
impl RetrievalService {
    pub fn new(db: Database) -> Self {
        Self {
            store: SqliteVectorStore::new(db.clone()),
            db,
        }
    }
    pub fn search_by_vector(
        &self,
        kb_id: &str,
        profile_id: &str,
        query: &[f32],
        top_k: usize,
    ) -> AppResult<Vec<SearchHit>> {
        let profile_kb: Option<String> = self
            .db
            .connection()?
            .query_row(
                "SELECT knowledge_base_id FROM embedding_profile WHERE id=?1",
                [profile_id],
                |r| r.get(0),
            )
            .optional()?;
        if profile_kb.as_deref() != Some(kb_id) {
            return Err(AppError::IncompatibleEmbedding(
                "profile does not belong to the selected knowledge base".into(),
            ));
        }
        self.store.search(profile_id, query, top_k)
    }
    pub fn search_text(
        &self,
        kb_id: &str,
        query: &str,
        top_k: usize,
        provider: Arc<dyn EmbeddingProvider>,
    ) -> AppResult<Vec<SearchHit>> {
        let info = provider.model_info();
        let profile_id:Option<String>=self.db.connection()?.query_row("SELECT id FROM embedding_profile WHERE knowledge_base_id=?1 AND model_id=?2 AND model_version=?3 AND config_hash=?4",rusqlite::params![kb_id,info.model_id,info.model_version,info.config_hash],|r|r.get(0)).optional()?;
        let profile_id=profile_id.ok_or_else(||AppError::NotFound("this knowledge base has no vectors for the selected provider; run Mock Index first".into()))?;
        let output = provider.embed(EmbeddingInput {
            request_id: Uuid::new_v4().to_string(),
            input_type: EmbeddingInputType::Query,
            text: query.into(),
            document_id: None,
            chunk_id: None,
            metadata: HashMap::new(),
        })?;
        self.search_by_vector(kb_id, &profile_id, &output.vector, top_k)
    }
}
