use crate::{
    chunk::{Chunker, FixedSizeChunker},
    database::Database,
    error::{AppError, AppResult},
    knowledge_base::KnowledgeBaseService,
};
use chrono::Utc;
use rusqlite::{OptionalExtension, params};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    fs,
    path::{Path, PathBuf},
};
use uuid::Uuid;
use walkdir::WalkDir;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentView {
    pub id: String,
    pub knowledge_base_id: String,
    pub file_path: String,
    pub file_name: String,
    pub file_hash: String,
    pub file_type: String,
    pub status: String,
    pub updated_at: String,
    pub chunk_count: usize,
    pub vector_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ScanResult {
    pub added: usize,
    pub updated: usize,
    pub unchanged: usize,
    pub removed: usize,
    pub chunks_created: usize,
    pub errors: Vec<String>,
}

#[derive(Clone)]
pub struct DocumentService {
    db: Database,
}
impl DocumentService {
    pub fn new(db: Database) -> Self {
        Self { db }
    }

    pub fn list(&self, kb_id: &str) -> AppResult<Vec<DocumentView>> {
        let conn = self.db.connection()?;
        let mut stmt = conn.prepare("SELECT d.id,d.knowledge_base_id,d.file_path,d.file_name,d.file_hash,d.file_type,d.status,d.updated_at,COUNT(DISTINCT c.id),COUNT(DISTINCT vr.chunk_id)
            FROM document d LEFT JOIN chunk c ON c.document_id=d.id LEFT JOIN vector_record vr ON vr.chunk_id=c.id WHERE d.knowledge_base_id=?1 GROUP BY d.id ORDER BY d.file_name")?;
        let rows = stmt.query_map([kb_id], |r| {
            Ok(DocumentView {
                id: r.get(0)?,
                knowledge_base_id: r.get(1)?,
                file_path: r.get(2)?,
                file_name: r.get(3)?,
                file_hash: r.get(4)?,
                file_type: r.get(5)?,
                status: r.get(6)?,
                updated_at: r.get(7)?,
                chunk_count: r.get::<_, i64>(8)? as usize,
                vector_count: r.get::<_, i64>(9)? as usize,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn scan(&self, kb_id: &str) -> AppResult<ScanResult> {
        let kb = KnowledgeBaseService::new(self.db.clone()).get(kb_id)?;
        let mut paths = Vec::new();
        for entry in WalkDir::new(&kb.root_path)
            .follow_links(false)
            .into_iter()
            .filter_map(Result::ok)
        {
            if entry.file_type().is_file() && Self::supported(entry.path()) {
                paths.push(entry.path().to_path_buf());
            }
        }
        self.sync_paths(kb_id, &paths, kb.chunk_size, kb.chunk_overlap)
    }

    pub fn add_file(&self, kb_id: &str, file_path: &str) -> AppResult<ScanResult> {
        let kb = KnowledgeBaseService::new(self.db.clone()).get(kb_id)?;
        let path = PathBuf::from(file_path)
            .canonicalize()
            .map_err(|e| AppError::InvalidInput(format!("invalid file: {e}")))?;
        if !Self::supported(&path) {
            return Err(AppError::InvalidInput(
                "only .md and .txt files are supported".into(),
            ));
        }
        self.upsert_paths(kb_id, &[path], kb.chunk_size, kb.chunk_overlap)
    }

    pub fn reparse(&self, document_id: &str) -> AppResult<ScanResult> {
        let conn = self.db.connection()?;
        let row: Option<(String,String,usize,usize)> = conn.query_row("SELECT d.knowledge_base_id,d.file_path,k.chunk_size,k.chunk_overlap FROM document d JOIN knowledge_base k ON k.id=d.knowledge_base_id WHERE d.id=?1", [document_id], |r| Ok((r.get(0)?,r.get(1)?,r.get::<_,i64>(2)? as usize,r.get::<_,i64>(3)? as usize))).optional()?;
        drop(conn);
        let (kb_id, path, size, overlap) =
            row.ok_or_else(|| AppError::NotFound(format!("document {document_id}")))?;
        self.upsert_paths_force(&kb_id, &[PathBuf::from(path)], size, overlap, true)
    }

    pub fn delete(&self, document_id: &str) -> AppResult<()> {
        if self
            .db
            .connection()?
            .execute("DELETE FROM document WHERE id=?1", [document_id])?
            == 0
        {
            return Err(AppError::NotFound(format!("document {document_id}")));
        }
        Ok(())
    }

    fn sync_paths(
        &self,
        kb_id: &str,
        paths: &[PathBuf],
        size: usize,
        overlap: usize,
    ) -> AppResult<ScanResult> {
        let mut result = self.upsert_paths(kb_id, paths, size, overlap)?;
        let current: HashSet<String> = paths
            .iter()
            .filter_map(|p| p.canonicalize().ok())
            .map(|p| p.to_string_lossy().into_owned())
            .collect();
        let existing: Vec<(String, String)> = {
            let conn = self.db.connection()?;
            let mut stmt =
                conn.prepare("SELECT id,file_path FROM document WHERE knowledge_base_id=?1")?;
            let rows = stmt.query_map([kb_id], |r| Ok((r.get(0)?, r.get(1)?)))?;
            rows.collect::<Result<Vec<_>, _>>()?
        };
        let conn = self.db.connection()?;
        for (id, path) in existing {
            if !current.contains(&path) {
                conn.execute("DELETE FROM document WHERE id=?1", [id])?;
                result.removed += 1;
            }
        }
        Ok(result)
    }
    fn upsert_paths(
        &self,
        kb_id: &str,
        paths: &[PathBuf],
        size: usize,
        overlap: usize,
    ) -> AppResult<ScanResult> {
        self.upsert_paths_force(kb_id, paths, size, overlap, false)
    }
    fn upsert_paths_force(
        &self,
        kb_id: &str,
        paths: &[PathBuf],
        size: usize,
        overlap: usize,
        force: bool,
    ) -> AppResult<ScanResult> {
        let chunker = FixedSizeChunker {
            chunk_size: size,
            chunk_overlap: overlap,
        };
        let mut result = ScanResult::default();
        for source in paths {
            let outcome = (|| -> AppResult<()> {
                let canonical = source.canonicalize()?;
                let path = canonical.to_string_lossy().into_owned();
                let bytes = fs::read(&canonical)?;
                let text = String::from_utf8(bytes.clone()).map_err(|e| {
                    AppError::InvalidInput(format!("{} is not UTF-8: {e}", canonical.display()))
                })?;
                let hash = format!("{:x}", Sha256::digest(&bytes));
                let existing:Option<(String,String)>=self.db.connection()?.query_row("SELECT id,file_hash FROM document WHERE knowledge_base_id=?1 AND file_path=?2",params![kb_id,path],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
                if !force && existing.as_ref().is_some_and(|(_, h)| h == &hash) {
                    result.unchanged += 1;
                    return Ok(());
                }
                let id = existing
                    .as_ref()
                    .map(|v| v.0.clone())
                    .unwrap_or_else(|| Uuid::new_v4().to_string());
                let is_new = existing.is_none();
                let now = Utc::now().to_rfc3339();
                let file_name = canonical
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned();
                let file_type = canonical
                    .extension()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_lowercase();
                let chunks = chunker.chunk(&text);
                let mut conn = self.db.connection()?;
                let tx = conn.transaction()?;
                tx.execute("INSERT INTO document(id,knowledge_base_id,file_path,file_name,file_hash,file_type,status,created_at,updated_at) VALUES(?1,?2,?3,?4,?5,?6,'WAITING_EMBEDDING',?7,?7)
                    ON CONFLICT(knowledge_base_id,file_path) DO UPDATE SET file_name=excluded.file_name,file_hash=excluded.file_hash,file_type=excluded.file_type,status='WAITING_EMBEDDING',updated_at=excluded.updated_at",params![id,kb_id,path,file_name,hash,file_type,now])?;
                tx.execute("DELETE FROM chunk WHERE document_id=?1", [&id])?;
                for (index, value) in chunks.iter().enumerate() {
                    tx.execute("INSERT INTO chunk(id,document_id,chunk_index,text,metadata_json,created_at) VALUES(?1,?2,?3,?4,?5,?6)",params![Uuid::new_v4().to_string(),id,index as i64,value,serde_json::json!({"source":path}).to_string(),now])?;
                }
                tx.execute("UPDATE index_state SET status='STALE',detail='document content changed',updated_at=?2 WHERE knowledge_base_id=?1",params![kb_id,now])?;
                tx.commit()?;
                if is_new {
                    result.added += 1
                } else {
                    result.updated += 1
                };
                result.chunks_created += chunks.len();
                Ok(())
            })();
            if let Err(error) = outcome {
                result.errors.push(format!("{}: {error}", source.display()));
            }
        }
        Ok(result)
    }
    fn supported(path: &Path) -> bool {
        path.extension()
            .and_then(|v| v.to_str())
            .is_some_and(|v| matches!(v.to_ascii_lowercase().as_str(), "md" | "txt"))
    }
}
