use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EmbeddingInputType {
    Document,
    Query,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingInput {
    pub request_id: String,
    pub input_type: EmbeddingInputType,
    pub text: String,
    pub document_id: Option<String>,
    pub chunk_id: Option<String>,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EmbeddingModelInfo {
    pub model_id: String,
    pub model_name: String,
    pub model_version: String,
    pub dimension: usize,
    pub runtime: String,
    pub precision: String,
    pub normalize: bool,
    pub pooling: String,
    pub max_length: Option<usize>,
    pub query_prefix: Option<String>,
    pub document_prefix: Option<String>,
    pub config_hash: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingOutput {
    pub request_id: String,
    pub input_type: EmbeddingInputType,
    pub model_info: EmbeddingModelInfo,
    pub vector: Vec<f32>,
    pub chunk_id: Option<String>,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExternalVectorItem {
    pub chunk_id: String,
    pub vector: Vec<f32>,
    pub request_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExternalVectorBatch {
    pub knowledge_base_id: String,
    pub model_info: EmbeddingModelInfo,
    pub vectors: Vec<ExternalVectorItem>,
}
