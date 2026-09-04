use crate::error::{AppError, AppResult};
use rusqlite::Connection;
use std::{
    path::{Path, PathBuf},
    sync::{Arc, Mutex, MutexGuard},
    time::Duration,
};

const SCHEMA: &str = r#"
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS knowledge_base (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  root_path TEXT NOT NULL UNIQUE,
  chunk_size INTEGER NOT NULL,
  chunk_overlap INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document (
  id TEXT PRIMARY KEY,
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
  file_path TEXT NOT NULL,
  file_name TEXT NOT NULL,
  file_hash TEXT NOT NULL,
  file_type TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(knowledge_base_id, file_path)
);
CREATE INDEX IF NOT EXISTS idx_document_kb ON document(knowledge_base_id);
CREATE TABLE IF NOT EXISTS chunk (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunk_document ON chunk(document_id);
CREATE TABLE IF NOT EXISTS embedding_profile (
  id TEXT PRIMARY KEY,
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
  model_id TEXT NOT NULL,
  model_name TEXT NOT NULL,
  model_version TEXT NOT NULL,
  dimension INTEGER NOT NULL,
  config_hash TEXT NOT NULL,
  runtime TEXT NOT NULL,
  precision TEXT NOT NULL,
  normalize INTEGER NOT NULL,
  pooling TEXT NOT NULL,
  max_length INTEGER,
  query_prefix TEXT,
  document_prefix TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(knowledge_base_id, model_id, model_version, config_hash)
);
CREATE INDEX IF NOT EXISTS idx_profile_kb ON embedding_profile(knowledge_base_id);
CREATE TABLE IF NOT EXISTS vector_record (
  chunk_id TEXT NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
  embedding_profile_id TEXT NOT NULL REFERENCES embedding_profile(id) ON DELETE CASCADE,
  dimension INTEGER NOT NULL,
  vector BLOB NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(chunk_id, embedding_profile_id)
);
CREATE INDEX IF NOT EXISTS idx_vector_profile ON vector_record(embedding_profile_id);
CREATE TABLE IF NOT EXISTS index_state (
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
  embedding_profile_id TEXT NOT NULL REFERENCES embedding_profile(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  detail TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(knowledge_base_id, embedding_profile_id)
);
CREATE TABLE IF NOT EXISTS llm_config (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  base_url TEXT NOT NULL,
  model TEXT NOT NULL,
  api_key_present INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (1, datetime('now'));
"#;

#[derive(Clone)]
pub struct Database {
    inner: Arc<Mutex<Connection>>,
    path: PathBuf,
}

impl Database {
    pub fn open(path: &Path) -> AppResult<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let connection = Connection::open(path)?;
        Self::configure(&connection)?;
        connection.execute_batch(SCHEMA)?;
        Ok(Self {
            inner: Arc::new(Mutex::new(connection)),
            path: path.to_path_buf(),
        })
    }

    pub fn open_in_memory() -> AppResult<Self> {
        let connection = Connection::open_in_memory()?;
        Self::configure(&connection)?;
        connection.execute_batch(SCHEMA)?;
        Ok(Self {
            inner: Arc::new(Mutex::new(connection)),
            path: PathBuf::from(":memory:"),
        })
    }

    fn configure(connection: &Connection) -> AppResult<()> {
        connection.busy_timeout(Duration::from_secs(5))?;
        connection.execute_batch(
            "PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        )?;
        Ok(())
    }

    pub fn connection(&self) -> AppResult<MutexGuard<'_, Connection>> {
        self.inner
            .lock()
            .map_err(|_| AppError::Internal("database mutex poisoned".into()))
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}
