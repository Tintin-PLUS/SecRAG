use super::model::{EmbeddingInput, EmbeddingModelInfo, EmbeddingOutput};
use crate::error::AppResult;

pub trait EmbeddingProvider: Send + Sync {
    fn model_info(&self) -> EmbeddingModelInfo;
    fn embed(&self, input: EmbeddingInput) -> AppResult<EmbeddingOutput>;
    fn embed_batch(&self, inputs: Vec<EmbeddingInput>) -> AppResult<Vec<EmbeddingOutput>> {
        inputs.into_iter().map(|input| self.embed(input)).collect()
    }
}
