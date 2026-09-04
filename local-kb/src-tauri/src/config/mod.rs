use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub database_path: PathBuf,
    pub chunk_size: usize,
    pub chunk_overlap: usize,
    pub llm_base_url: String,
    pub llm_model: String,
    pub llm_api_key: Option<String>,
    pub llm_thinking: bool,
    pub llm_reasoning_effort: String,
    pub llm_timeout_secs: u64,
    pub embedding_base_url: String,
    pub embedding_python: PathBuf,
    pub embedding_script: PathBuf,
    pub embedding_request_timeout_secs: u64,
    pub embedding_start_timeout_secs: u64,
    pub embedding_batch_size: usize,
    pub embedding_environment: HashMap<String, String>,
}

impl AppConfig {
    pub fn load(project_root: &Path) -> Self {
        let file_environment = read_env_file(&project_root.join(".env"));
        let value = |name: &str| {
            std::env::var(name)
                .ok()
                .or_else(|| file_environment.get(name).cloned())
                .filter(|item| !item.trim().is_empty())
        };
        let default_python = project_root
            .join(".venv")
            .join("Scripts")
            .join("python.exe");
        Self {
            database_path: project_root.join("data").join("local-kb.sqlite3"),
            chunk_size: 500,
            chunk_overlap: 80,
            llm_base_url: value("LOCAL_KB_LLM_BASE_URL")
                .unwrap_or_else(|| "https://api.deepseek.com".to_string()),
            llm_model: value("LOCAL_KB_LLM_MODEL")
                .unwrap_or_else(|| "deepseek-v4-flash".to_string()),
            llm_api_key: value("DEEPSEEK_API_KEY").or_else(|| value("LOCAL_KB_LLM_API_KEY")),
            llm_thinking: value("LOCAL_KB_DEEPSEEK_THINKING").is_some_and(|item| {
                matches!(
                    item.to_ascii_lowercase().as_str(),
                    "1" | "true" | "enabled" | "yes"
                )
            }),
            llm_reasoning_effort: value("LOCAL_KB_DEEPSEEK_REASONING_EFFORT")
                .unwrap_or_else(|| "high".to_string()),
            llm_timeout_secs: value("LOCAL_KB_LLM_TIMEOUT_SECS")
                .and_then(|item| item.parse().ok())
                .unwrap_or(300),
            embedding_base_url: value("LOCAL_KB_EMBEDDING_BASE_URL")
                .unwrap_or_else(|| "http://127.0.0.1:8902".to_string())
                .trim_end_matches('/')
                .to_string(),
            embedding_python: value("LOCAL_KB_EMBEDDING_PYTHON")
                .map(PathBuf::from)
                .unwrap_or_else(|| {
                    if default_python.is_file() {
                        default_python
                    } else {
                        PathBuf::from("python")
                    }
                }),
            embedding_script: value("LOCAL_KB_EMBEDDING_SCRIPT")
                .map(PathBuf::from)
                .unwrap_or_else(|| project_root.join("embedding-service").join("server.py")),
            embedding_request_timeout_secs: value("LOCAL_KB_EMBEDDING_REQUEST_TIMEOUT_SECS")
                .and_then(|item| item.parse().ok())
                .unwrap_or(180),
            embedding_start_timeout_secs: value("LOCAL_KB_EMBEDDING_START_TIMEOUT_SECS")
                .and_then(|item| item.parse().ok())
                .unwrap_or(30),
            embedding_batch_size: value("LOCAL_KB_EMBEDDING_BATCH_SIZE")
                .and_then(|item| item.parse().ok())
                .unwrap_or(32)
                .max(1),
            embedding_environment: [
                "LOCAL_KB_EMBEDDING_OFFLINE",
                "LOCAL_KB_EMBEDDING_MAX_BATCH_SIZE",
                "LOCAL_KB_EMBEDDING_ENCODE_BATCH_SIZE",
                "LOCAL_KB_MODEL_BGE_SMALL",
                "LOCAL_KB_MODEL_M3E_BASE",
                "LOCAL_KB_MODEL_BGE_M3",
            ]
            .into_iter()
            .filter_map(|name| value(name).map(|item| (name.to_string(), item)))
            .collect(),
        }
    }
}

fn read_env_file(path: &Path) -> HashMap<String, String> {
    let Ok(contents) = std::fs::read_to_string(path) else {
        return HashMap::new();
    };
    contents
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
        .filter_map(|line| line.strip_prefix("export ").unwrap_or(line).split_once('='))
        .map(|(name, value)| {
            let value = value.trim();
            let unquoted = value
                .strip_prefix('"')
                .and_then(|value| value.strip_suffix('"'))
                .or_else(|| {
                    value
                        .strip_prefix('\'')
                        .and_then(|value| value.strip_suffix('\''))
                })
                .unwrap_or(value);
            (name.trim().to_string(), unquoted.to_string())
        })
        .collect()
}
