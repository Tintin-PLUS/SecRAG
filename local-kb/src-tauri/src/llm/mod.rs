use crate::error::{AppError, AppResult};
use async_trait::async_trait;
use reqwest::{Client, StatusCode};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::time::Duration;

const SYSTEM_PROMPT: &str = "你是证券本地知识库助手。只依据用户提供的本地资料回答；资料不足时明确说明，不得编造。回答应简洁，并引用资料编号。";

#[async_trait]
pub trait LlmClient: Send + Sync {
    async fn complete(&self, prompt: &str) -> AppResult<String>;
}

#[derive(Debug, Clone)]
pub struct DeepSeekConfig {
    pub base_url: String,
    pub api_key: String,
    pub model: String,
    pub thinking: bool,
    pub reasoning_effort: String,
    pub timeout: Duration,
}

#[derive(Clone)]
pub struct DeepSeekClient {
    config: DeepSeekConfig,
    client: Client,
}

#[derive(Debug, Serialize)]
struct ChatMessage<'a> {
    role: &'a str,
    content: &'a str,
}

#[derive(Debug, Deserialize)]
struct ChatCompletionResponse {
    choices: Vec<ChatChoice>,
}

#[derive(Debug, Deserialize)]
struct ChatChoice {
    message: ChatResponseMessage,
}

#[derive(Debug, Deserialize)]
struct ChatResponseMessage {
    content: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ApiErrorEnvelope {
    error: Option<ApiErrorBody>,
}

#[derive(Debug, Deserialize)]
struct ApiErrorBody {
    message: Option<String>,
}

impl DeepSeekClient {
    pub fn new(config: DeepSeekConfig) -> AppResult<Self> {
        let base_url = config.base_url.trim_end_matches('/').to_string();
        let parsed = reqwest::Url::parse(&base_url).map_err(|error| {
            AppError::InvalidInput(format!("invalid DeepSeek base URL: {error}"))
        })?;
        if parsed.scheme() != "https" && !parsed.host_str().is_some_and(is_loopback_host) {
            return Err(AppError::InvalidInput(
                "DeepSeek base URL must use HTTPS unless it points to loopback for tests".into(),
            ));
        }
        if config.api_key.trim().is_empty() {
            return Err(AppError::InvalidInput("DeepSeek API key is empty".into()));
        }
        if config.model.trim().is_empty() {
            return Err(AppError::InvalidInput("DeepSeek model is empty".into()));
        }
        if !matches!(config.reasoning_effort.as_str(), "low" | "high" | "max") {
            return Err(AppError::InvalidInput(
                "DeepSeek reasoning effort must be low, high, or max".into(),
            ));
        }
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(10).min(config.timeout))
            .timeout(config.timeout)
            .build()?;
        Ok(Self {
            config: DeepSeekConfig { base_url, ..config },
            client,
        })
    }

    fn request_body(&self, prompt: &str) -> Value {
        let mut body = json!({
            "model": self.config.model,
            "messages": [
                ChatMessage { role: "system", content: SYSTEM_PROMPT },
                ChatMessage { role: "user", content: prompt }
            ],
            "stream": false,
            "thinking": {
                "type": if self.config.thinking { "enabled" } else { "disabled" }
            }
        });
        if self.config.thinking {
            body["reasoning_effort"] = json!(self.config.reasoning_effort);
        }
        body
    }

    async fn error_message(status: StatusCode, response: reqwest::Response) -> AppError {
        let body = response.text().await.unwrap_or_default();
        let message = serde_json::from_str::<ApiErrorEnvelope>(&body)
            .ok()
            .and_then(|envelope| envelope.error)
            .and_then(|error| error.message)
            .unwrap_or_else(|| body.chars().take(500).collect());
        AppError::Internal(format!("DeepSeek API returned {status}: {message}"))
    }
}

fn is_loopback_host(host: &str) -> bool {
    matches!(host, "127.0.0.1" | "localhost" | "::1")
}

#[async_trait]
impl LlmClient for DeepSeekClient {
    async fn complete(&self, prompt: &str) -> AppResult<String> {
        if prompt.trim().is_empty() {
            return Err(AppError::InvalidInput("LLM prompt is empty".into()));
        }
        let response = self
            .client
            .post(format!("{}/chat/completions", self.config.base_url))
            .bearer_auth(&self.config.api_key)
            .json(&self.request_body(prompt))
            .send()
            .await?;
        let status = response.status();
        if !status.is_success() {
            return Err(Self::error_message(status, response).await);
        }
        let response: ChatCompletionResponse = response.json().await?;
        response
            .choices
            .into_iter()
            .next()
            .and_then(|choice| choice.message.content)
            .filter(|content| !content.trim().is_empty())
            .ok_or_else(|| {
                AppError::InvalidInput("DeepSeek response has no choices[0].message.content".into())
            })
    }
}
