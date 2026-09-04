use crate::{
    config::AppConfig,
    error::{AppError, AppResult},
};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use std::{
    fs::OpenOptions,
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingServiceStatus {
    pub reachable: bool,
    pub managed: bool,
    pub pid: Option<u32>,
    pub base_url: String,
    pub python: String,
    pub script: String,
    pub loaded_models: Vec<String>,
    pub dependency_available: Option<bool>,
    pub offline: Option<bool>,
    pub protocol_version: Option<String>,
    pub error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct HealthResponse {
    status: String,
    protocol_version: String,
    dependency_available: bool,
    offline: bool,
    #[serde(default)]
    loaded_models: Vec<String>,
}

struct ManagedProcess {
    child: Mutex<Option<Child>>,
}

impl Drop for ManagedProcess {
    fn drop(&mut self) {
        if let Ok(child) = self.child.get_mut()
            && let Some(mut child) = child.take()
        {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[derive(Clone)]
pub struct EmbeddingServiceManager {
    config: AppConfig,
    process: Arc<ManagedProcess>,
}

impl EmbeddingServiceManager {
    pub fn new(config: AppConfig) -> AppResult<Self> {
        Ok(Self {
            config,
            process: Arc::new(ManagedProcess {
                child: Mutex::new(None),
            }),
        })
    }

    fn health(&self) -> Result<HealthResponse, String> {
        // Do not retain a reqwest::blocking client in Tauri managed state: its
        // internal runtime must not be dropped by a Tokio worker during shutdown.
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(1))
            .timeout(Duration::from_secs(3))
            .build()
            .map_err(|error| error.to_string())?;
        let response = client
            .get(format!("{}/health", self.config.embedding_base_url))
            .send()
            .map_err(|error| error.to_string())?;
        if !response.status().is_success() {
            return Err(format!("health endpoint returned {}", response.status()));
        }
        let health = response
            .json::<HealthResponse>()
            .map_err(|error| error.to_string())?;
        if health.status != "ok" {
            return Err(format!("unexpected health status {}", health.status));
        }
        if health.protocol_version != "1" {
            return Err(format!(
                "unsupported embedding protocol {}; expected 1",
                health.protocol_version
            ));
        }
        Ok(health)
    }

    pub fn status(&self) -> EmbeddingServiceStatus {
        let (managed, pid) = self
            .process
            .child
            .lock()
            .ok()
            .and_then(|mut guard| {
                if guard
                    .as_mut()
                    .is_some_and(|child| child.try_wait().ok().flatten().is_some())
                {
                    *guard = None;
                }
                Some((guard.is_some(), guard.as_ref().map(Child::id)))
            })
            .unwrap_or((false, None));
        match self.health() {
            Ok(health) => self.status_value(
                true,
                managed,
                pid,
                health.loaded_models,
                Some(health.dependency_available),
                Some(health.offline),
                Some(health.protocol_version),
                None,
            ),
            Err(error) => self.status_value(
                false,
                managed,
                pid,
                Vec::new(),
                None,
                None,
                None,
                Some(error),
            ),
        }
    }

    fn status_value(
        &self,
        reachable: bool,
        managed: bool,
        pid: Option<u32>,
        loaded_models: Vec<String>,
        dependency_available: Option<bool>,
        offline: Option<bool>,
        protocol_version: Option<String>,
        error: Option<String>,
    ) -> EmbeddingServiceStatus {
        EmbeddingServiceStatus {
            reachable,
            managed,
            pid,
            base_url: self.config.embedding_base_url.clone(),
            python: self.config.embedding_python.to_string_lossy().into_owned(),
            script: self.config.embedding_script.to_string_lossy().into_owned(),
            loaded_models,
            dependency_available,
            offline,
            protocol_version,
            error,
        }
    }

    pub fn start(&self) -> AppResult<EmbeddingServiceStatus> {
        if self.health().is_ok() {
            return Ok(self.status());
        }
        if !self.config.embedding_script.is_file() {
            return Err(AppError::NotFound(format!(
                "embedding service script {}",
                self.config.embedding_script.display()
            )));
        }
        let port = reqwest::Url::parse(&self.config.embedding_base_url)
            .ok()
            .and_then(|url| url.port_or_known_default())
            .ok_or_else(|| {
                AppError::InvalidInput("embedding base URL must contain a valid port".into())
            })?;
        let project_root = self
            .config
            .embedding_script
            .parent()
            .and_then(|path| path.parent())
            .ok_or_else(|| {
                AppError::Internal("cannot resolve project root from embedding script".into())
            })?;
        let logs = project_root.join("logs");
        std::fs::create_dir_all(&logs)?;
        let stdout = OpenOptions::new()
            .create(true)
            .append(true)
            .open(logs.join("embedding-service.log"))?;
        let stderr = stdout.try_clone()?;
        let child = Command::new(&self.config.embedding_python)
            .arg(&self.config.embedding_script)
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string())
            .current_dir(project_root)
            .envs(&self.config.embedding_environment)
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr))
            .spawn()
            .map_err(|error| {
                AppError::Internal(format!(
                    "failed to start embedding Python '{}': {error}",
                    self.config.embedding_python.display()
                ))
            })?;
        *self
            .process
            .child
            .lock()
            .map_err(|_| AppError::Internal("embedding process lock poisoned".into()))? =
            Some(child);
        let deadline =
            Instant::now() + Duration::from_secs(self.config.embedding_start_timeout_secs);
        while Instant::now() < deadline {
            if self.health().is_ok() {
                return Ok(self.status());
            }
            let exited = self
                .process
                .child
                .lock()
                .map_err(|_| AppError::Internal("embedding process lock poisoned".into()))?
                .as_mut()
                .and_then(|child| child.try_wait().ok().flatten());
            if let Some(exit) = exited {
                return Err(AppError::Internal(format!(
                    "embedding service exited during startup with {exit}; see logs/embedding-service.log"
                )));
            }
            thread::sleep(Duration::from_millis(250));
        }
        let _ = self.stop();
        Err(AppError::Internal(format!(
            "embedding service did not become healthy within {} seconds; see logs/embedding-service.log",
            self.config.embedding_start_timeout_secs
        )))
    }

    pub fn stop(&self) -> AppResult<EmbeddingServiceStatus> {
        let child = self
            .process
            .child
            .lock()
            .map_err(|_| AppError::Internal("embedding process lock poisoned".into()))?
            .take();
        if let Some(mut child) = child {
            child.kill()?;
            child.wait()?;
        }
        Ok(self.status())
    }
}
