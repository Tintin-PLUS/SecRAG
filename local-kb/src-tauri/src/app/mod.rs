use crate::{
    config::AppConfig,
    database::Database,
    embedding::{
        DeterministicEmbeddingProvider, EmbeddingRegistry, EmbeddingServiceManager,
        PythonSidecarEmbeddingProvider, supported_sidecar_models,
    },
    error::AppResult,
    watcher::WatchRegistration,
};
use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{Arc, Mutex},
};

#[derive(Clone)]
pub struct AppState {
    pub db: Database,
    pub config: AppConfig,
    pub embeddings: EmbeddingRegistry,
    pub embedding_service: EmbeddingServiceManager,
    pub watchers: Arc<Mutex<HashMap<String, WatchRegistration>>>,
}
impl AppState {
    pub fn initialize() -> AppResult<Self> {
        let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf();
        let config = AppConfig::load(&project_root);
        let db = Database::open(&config.database_path)?;
        let embeddings = EmbeddingRegistry::default();
        embeddings.register(Arc::new(DeterministicEmbeddingProvider::default()))?;
        for model in supported_sidecar_models() {
            embeddings.register(Arc::new(PythonSidecarEmbeddingProvider::new(
                config.embedding_base_url.clone(),
                &model.model_id,
                std::time::Duration::from_secs(config.embedding_request_timeout_secs),
            )?))?;
        }
        let embedding_service = EmbeddingServiceManager::new(config.clone())?;
        Ok(Self {
            db,
            config,
            embeddings,
            embedding_service,
            watchers: Arc::new(Mutex::new(HashMap::new())),
        })
    }
}
