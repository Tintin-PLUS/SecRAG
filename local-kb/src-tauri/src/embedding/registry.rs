use super::{model::EmbeddingModelInfo, provider::EmbeddingProvider};
use crate::error::{AppError, AppResult};
use std::{
    collections::HashMap,
    sync::{Arc, RwLock},
};

#[derive(Clone, Default)]
pub struct EmbeddingRegistry {
    providers: Arc<RwLock<HashMap<String, Arc<dyn EmbeddingProvider>>>>,
}

impl EmbeddingRegistry {
    pub fn register(&self, provider: Arc<dyn EmbeddingProvider>) -> AppResult<()> {
        let id = provider.model_info().model_id;
        self.providers
            .write()
            .map_err(|_| AppError::Internal("embedding registry poisoned".into()))?
            .insert(id, provider);
        Ok(())
    }
    pub fn get(&self, model_id: &str) -> AppResult<Arc<dyn EmbeddingProvider>> {
        self.providers
            .read()
            .map_err(|_| AppError::Internal("embedding registry poisoned".into()))?
            .get(model_id)
            .cloned()
            .ok_or_else(|| AppError::NotFound(format!("embedding provider {model_id}")))
    }
    pub fn model_ids(&self) -> AppResult<Vec<String>> {
        let mut ids = self
            .providers
            .read()
            .map_err(|_| AppError::Internal("embedding registry poisoned".into()))?
            .keys()
            .cloned()
            .collect::<Vec<_>>();
        ids.sort();
        Ok(ids)
    }

    pub fn model_infos(&self) -> AppResult<Vec<EmbeddingModelInfo>> {
        let mut infos = self
            .providers
            .read()
            .map_err(|_| AppError::Internal("embedding registry poisoned".into()))?
            .values()
            .map(|provider| provider.model_info())
            .collect::<Vec<_>>();
        infos.sort_by(|a, b| a.model_id.cmp(&b.model_id));
        Ok(infos)
    }
}
