use crate::{
    database::Database,
    error::{AppError, AppResult},
};
use chrono::Utc;
use rusqlite::{OptionalExtension, params};
use serde::{Deserialize, Serialize};
use std::path::Path;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KnowledgeBase {
    pub id: String,
    pub name: String,
    pub root_path: String,
    pub chunk_size: usize,
    pub chunk_overlap: usize,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Clone)]
pub struct KnowledgeBaseService {
    db: Database,
}
impl KnowledgeBaseService {
    pub fn new(db: Database) -> Self {
        Self { db }
    }
    pub fn create(
        &self,
        name: &str,
        root_path: &str,
        chunk_size: usize,
        chunk_overlap: usize,
    ) -> AppResult<KnowledgeBase> {
        if name.trim().is_empty() {
            return Err(AppError::InvalidInput(
                "knowledge base name is required".into(),
            ));
        }
        if chunk_size == 0 || chunk_overlap >= chunk_size {
            return Err(AppError::InvalidInput(
                "chunk_size must be > 0 and overlap must be smaller".into(),
            ));
        }
        let canonical = Path::new(root_path)
            .canonicalize()
            .map_err(|e| AppError::InvalidInput(format!("invalid root path: {e}")))?;
        if !canonical.is_dir() {
            return Err(AppError::InvalidInput(
                "knowledge base root must be a directory".into(),
            ));
        }
        let now = Utc::now().to_rfc3339();
        let kb = KnowledgeBase {
            id: Uuid::new_v4().to_string(),
            name: name.trim().into(),
            root_path: canonical.to_string_lossy().into_owned(),
            chunk_size,
            chunk_overlap,
            created_at: now.clone(),
            updated_at: now,
        };
        self.db.connection()?.execute("INSERT INTO knowledge_base(id,name,root_path,chunk_size,chunk_overlap,created_at,updated_at) VALUES(?1,?2,?3,?4,?5,?6,?7)",
            params![kb.id,kb.name,kb.root_path,kb.chunk_size as i64,kb.chunk_overlap as i64,kb.created_at,kb.updated_at])?;
        Ok(kb)
    }
    pub fn list(&self) -> AppResult<Vec<KnowledgeBase>> {
        let conn = self.db.connection()?;
        let mut stmt = conn.prepare("SELECT id,name,root_path,chunk_size,chunk_overlap,created_at,updated_at FROM knowledge_base ORDER BY created_at DESC")?;
        let rows = stmt.query_map([], |r| {
            Ok(KnowledgeBase {
                id: r.get(0)?,
                name: r.get(1)?,
                root_path: r.get(2)?,
                chunk_size: r.get::<_, i64>(3)? as usize,
                chunk_overlap: r.get::<_, i64>(4)? as usize,
                created_at: r.get(5)?,
                updated_at: r.get(6)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }
    pub fn get(&self, id: &str) -> AppResult<KnowledgeBase> {
        self.db.connection()?.query_row("SELECT id,name,root_path,chunk_size,chunk_overlap,created_at,updated_at FROM knowledge_base WHERE id=?1", [id], |r| Ok(KnowledgeBase { id:r.get(0)?,name:r.get(1)?,root_path:r.get(2)?,chunk_size:r.get::<_,i64>(3)? as usize,chunk_overlap:r.get::<_,i64>(4)? as usize,created_at:r.get(5)?,updated_at:r.get(6)? })).optional()?.ok_or_else(|| AppError::NotFound(format!("knowledge base {id}")))
    }
    pub fn delete(&self, id: &str) -> AppResult<()> {
        if self
            .db
            .connection()?
            .execute("DELETE FROM knowledge_base WHERE id=?1", [id])?
            == 0
        {
            return Err(AppError::NotFound(format!("knowledge base {id}")));
        }
        Ok(())
    }
}
