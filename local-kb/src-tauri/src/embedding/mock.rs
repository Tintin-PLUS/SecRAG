use super::{
    model::{EmbeddingInput, EmbeddingModelInfo, EmbeddingOutput},
    provider::EmbeddingProvider,
};
use crate::error::AppResult;
use sha2::{Digest, Sha256};

#[derive(Debug, Clone)]
pub struct DeterministicEmbeddingProvider {
    dimension: usize,
}

impl DeterministicEmbeddingProvider {
    pub fn new(dimension: usize) -> Self {
        Self { dimension }
    }

    fn vectorize(&self, text: &str) -> Vec<f32> {
        let mut result = vec![0.0_f32; self.dimension];
        if self.dimension == 0 {
            return result;
        }
        let normalized = text.to_lowercase();
        let chars: Vec<char> = normalized.chars().collect();
        for width in 1..=3 {
            for token in chars.windows(width) {
                let token: String = token.iter().collect();
                let digest = Sha256::digest(token.as_bytes());
                let index =
                    u64::from_le_bytes(digest[0..8].try_into().unwrap()) as usize % self.dimension;
                let sign = if digest[8] & 1 == 0 { 1.0 } else { -1.0 };
                result[index] += sign;
            }
        }
        let norm = result.iter().map(|x| x * x).sum::<f32>().sqrt();
        if norm > 0.0 {
            result.iter_mut().for_each(|x| *x /= norm);
        }
        result
    }
}

impl Default for DeterministicEmbeddingProvider {
    fn default() -> Self {
        Self::new(64)
    }
}

impl EmbeddingProvider for DeterministicEmbeddingProvider {
    fn model_info(&self) -> EmbeddingModelInfo {
        EmbeddingModelInfo {
            model_id: "deterministic-mock-v1".into(),
            model_name: "Deterministic Mock".into(),
            model_version: "1".into(),
            dimension: self.dimension,
            runtime: "rust-mock".into(),
            precision: "f32".into(),
            normalize: true,
            pooling: "hashed-char-ngram".into(),
            max_length: None,
            query_prefix: None,
            document_prefix: None,
            config_hash: format!("mock-char-ngram-d{}-v1", self.dimension),
        }
    }

    fn embed(&self, input: EmbeddingInput) -> AppResult<EmbeddingOutput> {
        Ok(EmbeddingOutput {
            request_id: input.request_id,
            input_type: input.input_type,
            model_info: self.model_info(),
            vector: self.vectorize(&input.text),
            chunk_id: input.chunk_id,
            metadata: input.metadata,
        })
    }
}
