use super::{
    model::{EmbeddingInput, EmbeddingOutput},
    provider::EmbeddingProvider,
};
use crate::error::AppResult;
use std::sync::Arc;

#[derive(Clone)]
pub struct EmbeddingAdapter {
    provider: Arc<dyn EmbeddingProvider>,
}
impl EmbeddingAdapter {
    pub fn new(provider: Arc<dyn EmbeddingProvider>) -> Self {
        Self { provider }
    }
    pub fn embed(&self, input: EmbeddingInput) -> AppResult<EmbeddingOutput> {
        self.provider.embed(input)
    }
    pub fn embed_batch(&self, inputs: Vec<EmbeddingInput>) -> AppResult<Vec<EmbeddingOutput>> {
        self.provider.embed_batch(inputs)
    }
}
