use super::{
    model::{EmbeddingInput, EmbeddingModelInfo, EmbeddingOutput},
    provider::EmbeddingProvider,
};
use crate::error::{AppError, AppResult};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;

#[derive(Debug, Clone)]
struct SidecarModelDefinition {
    model_id: &'static str,
    model_name: &'static str,
    model_version: &'static str,
    dimension: usize,
    config_hash: &'static str,
}

const MODELS: &[SidecarModelDefinition] = &[
    SidecarModelDefinition {
        model_id: "bge-small",
        model_name: "BAAI/bge-small-zh-v1.5",
        model_version: "v1.5",
        dimension: 512,
        config_hash: "st-bge-small-zh-v1.5-f32-normalized-model-pooling-v1",
    },
    SidecarModelDefinition {
        model_id: "m3e-base",
        model_name: "moka-ai/m3e-base",
        model_version: "configured",
        dimension: 768,
        config_hash: "st-m3e-base-f32-normalized-model-pooling-v1",
    },
    SidecarModelDefinition {
        model_id: "bge-m3",
        model_name: "BAAI/bge-m3",
        model_version: "configured",
        dimension: 1024,
        config_hash: "st-bge-m3-f32-normalized-model-pooling-v1",
    },
];

pub fn supported_sidecar_models() -> Vec<EmbeddingModelInfo> {
    MODELS.iter().map(model_info).collect()
}

fn model_info(definition: &SidecarModelDefinition) -> EmbeddingModelInfo {
    EmbeddingModelInfo {
        model_id: definition.model_id.into(),
        model_name: definition.model_name.into(),
        model_version: definition.model_version.into(),
        dimension: definition.dimension,
        runtime: "python-sentence-transformers".into(),
        precision: "f32".into(),
        normalize: true,
        pooling: "model-defined".into(),
        max_length: None,
        query_prefix: None,
        document_prefix: None,
        config_hash: definition.config_hash.into(),
    }
}

#[derive(Debug, Serialize)]
struct EmbedRequest {
    model_id: String,
    inputs: Vec<EmbeddingInput>,
}

#[derive(Debug, Deserialize)]
struct EmbedResponse {
    model_info: EmbeddingModelInfo,
    outputs: Vec<EmbeddingOutput>,
}

#[derive(Debug, Deserialize)]
struct ErrorResponse {
    error: Option<String>,
}

#[derive(Clone)]
pub struct PythonSidecarEmbeddingProvider {
    base_url: String,
    info: EmbeddingModelInfo,
    timeout: Duration,
}

impl PythonSidecarEmbeddingProvider {
    pub fn new(base_url: impl Into<String>, model_id: &str, timeout: Duration) -> AppResult<Self> {
        let definition = MODELS
            .iter()
            .find(|model| model.model_id == model_id)
            .ok_or_else(|| {
                AppError::InvalidInput(format!("unsupported sidecar model {model_id}"))
            })?;
        Ok(Self {
            base_url: base_url.into().trim_end_matches('/').to_string(),
            info: model_info(definition),
            timeout,
        })
    }

    fn request(&self, inputs: Vec<EmbeddingInput>) -> AppResult<Vec<EmbeddingOutput>> {
        if inputs.is_empty() {
            return Ok(Vec::new());
        }
        // reqwest::blocking owns a private Tokio runtime. Keep the client local to
        // the blocking operation so it is also dropped on the blocking thread,
        // never while Tauri is tearing down its async runtime.
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(5).min(self.timeout))
            .timeout(self.timeout)
            .build()?;
        let response = client
            .post(format!("{}/v1/embeddings", self.base_url))
            .json(&EmbedRequest {
                model_id: self.info.model_id.clone(),
                inputs: inputs.clone(),
            })
            .send()?;
        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().unwrap_or_default();
            let message = serde_json::from_str::<ErrorResponse>(&body)
                .ok()
                .and_then(|error| error.error)
                .unwrap_or(body);
            return Err(AppError::Internal(format!(
                "embedding sidecar returned {status}: {message}"
            )));
        }
        let result: EmbedResponse = response.json()?;
        if result.model_info != self.info {
            return Err(AppError::IncompatibleEmbedding(
                "sidecar model_info differs from the registered provider configuration".into(),
            ));
        }
        if result.outputs.len() != inputs.len() {
            return Err(AppError::InvalidInput(format!(
                "sidecar returned {} outputs for {} inputs",
                result.outputs.len(),
                inputs.len()
            )));
        }
        for (input, output) in inputs.iter().zip(&result.outputs) {
            if output.request_id != input.request_id
                || output.input_type != input.input_type
                || output.chunk_id != input.chunk_id
            {
                return Err(AppError::InvalidInput(format!(
                    "sidecar output mapping mismatch for request {}",
                    input.request_id
                )));
            }
            if output.model_info != self.info || output.vector.len() != self.info.dimension {
                return Err(AppError::IncompatibleEmbedding(format!(
                    "sidecar output for {} is not in the expected embedding space",
                    input.request_id
                )));
            }
            if output.vector.iter().any(|value| !value.is_finite()) {
                return Err(AppError::InvalidInput(format!(
                    "sidecar output for {} contains NaN or infinity",
                    input.request_id
                )));
            }
        }
        Ok(result.outputs)
    }
}

impl EmbeddingProvider for PythonSidecarEmbeddingProvider {
    fn model_info(&self) -> EmbeddingModelInfo {
        self.info.clone()
    }

    fn embed(&self, input: EmbeddingInput) -> AppResult<EmbeddingOutput> {
        self.request(vec![input])?
            .into_iter()
            .next()
            .ok_or_else(|| AppError::Internal("embedding sidecar returned an empty result".into()))
    }

    fn embed_batch(&self, inputs: Vec<EmbeddingInput>) -> AppResult<Vec<EmbeddingOutput>> {
        self.request(inputs)
    }
}
