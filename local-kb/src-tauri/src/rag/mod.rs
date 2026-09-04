use crate::{
    config::AppConfig,
    embedding::EmbeddingProvider,
    error::{AppError, AppResult},
    llm::{DeepSeekClient, DeepSeekConfig, LlmClient},
    retrieval::RetrievalService,
    vector_store::SearchHit,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RagResponse {
    pub answer: String,
    pub sources: Vec<SearchHit>,
    pub llm_used: bool,
    pub warning: Option<String>,
}

#[derive(Clone)]
pub struct RagService {
    retrieval: RetrievalService,
    config: AppConfig,
}
impl RagService {
    pub fn new(retrieval: RetrievalService, config: AppConfig) -> Self {
        Self { retrieval, config }
    }
    pub async fn answer(
        &self,
        kb_id: &str,
        question: &str,
        top_k: usize,
        provider: Arc<dyn EmbeddingProvider>,
    ) -> AppResult<RagResponse> {
        let provider_info = provider.model_info();
        let is_mock = provider_info.runtime == "rust-mock";
        let retrieval = self.retrieval.clone();
        let kb_id = kb_id.to_owned();
        let query = question.to_owned();
        // Real embedding currently uses reqwest::blocking. Running it directly in
        // this async command blocks a Tokio worker and can panic when reqwest's
        // private runtime is dropped. Keep the full synchronous retrieval path on
        // Tokio's dedicated blocking pool.
        let sources = tokio::task::spawn_blocking(move || {
            retrieval.search_text(&kb_id, &query, top_k, provider)
        })
        .await
        .map_err(|error| AppError::Internal(format!("RAG retrieval task failed: {error}")))??;
        let context = sources
            .iter()
            .enumerate()
            .map(|(i, s)| {
                format!(
                    "[资料{} | {} | chunk {}]\n{}",
                    i + 1,
                    s.file_name,
                    s.chunk_index,
                    s.text
                )
            })
            .collect::<Vec<_>>()
            .join("\n\n");
        let prompt =
            format!("问题：{question}\n\n本地资料：\n{context}\n\n请给出简洁回答并引用资料编号。");
        match &self.config.llm_api_key {
            Some(key) => {
                let client = DeepSeekClient::new(DeepSeekConfig {
                    base_url: self.config.llm_base_url.clone(),
                    api_key: key.clone(),
                    model: self.config.llm_model.clone(),
                    thinking: self.config.llm_thinking,
                    reasoning_effort: self.config.llm_reasoning_effort.clone(),
                    timeout: Duration::from_secs(self.config.llm_timeout_secs),
                })?;
                let answer = client.complete(&prompt).await?;
                Ok(RagResponse {
                    answer,
                    sources,
                    llm_used: true,
                    warning: is_mock.then(|| {
                        "当前检索使用 Mock Embedding，仅验证工程调用链，不代表真实语义质量。"
                            .into()
                    }),
                })
            }
            None => Ok(RagResponse {
                answer: "DeepSeek API 未配置。检索已经完成并返回下方本地 Context；在 .env 中配置 DEEPSEEK_API_KEY 后可生成回答。".into(),
                sources,
                llm_used: false,
                warning: is_mock.then(|| {
                    "Mock Embedding 仅用于工程链路验证，不代表真实检索质量。".into()
                }),
            }),
        }
    }
}
