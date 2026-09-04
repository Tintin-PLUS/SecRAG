use crate::error::AppResult;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone)]
pub struct VectorRecordInput {
    pub chunk_id: String,
    pub embedding_profile_id: String,
    pub vector: Vec<f32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchHit {
    pub score: f32,
    pub chunk_id: String,
    pub document_id: String,
    pub file_name: String,
    pub file_path: String,
    pub chunk_index: usize,
    pub text: String,
}

pub trait VectorStore: Send + Sync {
    fn insert(&self, record: VectorRecordInput) -> AppResult<()>;
    fn insert_batch(&self, records: Vec<VectorRecordInput>) -> AppResult<usize>;
    fn search(&self, profile_id: &str, query: &[f32], top_k: usize) -> AppResult<Vec<SearchHit>>;
    fn delete_by_document(&self, document_id: &str) -> AppResult<usize>;
    fn delete_by_chunk(&self, chunk_id: &str) -> AppResult<usize>;
    fn delete_by_profile(&self, profile_id: &str) -> AppResult<usize>;
    fn count(&self, profile_id: Option<&str>) -> AppResult<usize>;
    fn clear(&self) -> AppResult<usize>;
}
