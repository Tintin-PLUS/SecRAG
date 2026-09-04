use super::store::{SearchHit, VectorRecordInput, VectorStore};
use crate::{
    database::Database,
    error::{AppError, AppResult},
};
use chrono::Utc;
use rusqlite::params;

#[derive(Clone)]
pub struct SqliteVectorStore {
    db: Database,
}

impl SqliteVectorStore {
    pub fn new(db: Database) -> Self {
        Self { db }
    }
    pub fn encode(vector: &[f32]) -> Vec<u8> {
        vector.iter().flat_map(|v| v.to_le_bytes()).collect()
    }
    pub fn decode(blob: &[u8]) -> AppResult<Vec<f32>> {
        if blob.len() % 4 != 0 {
            return Err(AppError::InvalidInput("corrupt vector BLOB".into()));
        }
        Ok(blob
            .chunks_exact(4)
            .map(|b| f32::from_le_bytes(b.try_into().unwrap()))
            .collect())
    }
    fn cosine(a: &[f32], b: &[f32]) -> AppResult<f32> {
        if a.len() != b.len() {
            return Err(AppError::InvalidInput(format!(
                "query dimension {} does not match stored dimension {}",
                a.len(),
                b.len()
            )));
        }
        let dot = a.iter().zip(b).map(|(x, y)| x * y).sum::<f32>();
        let na = a.iter().map(|x| x * x).sum::<f32>().sqrt();
        let nb = b.iter().map(|x| x * x).sum::<f32>().sqrt();
        Ok(if na == 0.0 || nb == 0.0 {
            0.0
        } else {
            dot / (na * nb)
        })
    }
}

impl VectorStore for SqliteVectorStore {
    fn insert(&self, record: VectorRecordInput) -> AppResult<()> {
        self.insert_batch(vec![record]).map(|_| ())
    }

    fn insert_batch(&self, records: Vec<VectorRecordInput>) -> AppResult<usize> {
        if records.is_empty() {
            return Ok(0);
        }
        let mut conn = self.db.connection()?;
        let tx = conn.transaction()?;
        let now = Utc::now().to_rfc3339();
        for record in &records {
            tx.execute("INSERT INTO vector_record(chunk_id,embedding_profile_id,dimension,vector,created_at)
                VALUES(?1,?2,?3,?4,?5) ON CONFLICT(chunk_id,embedding_profile_id) DO UPDATE SET dimension=excluded.dimension,vector=excluded.vector,created_at=excluded.created_at",
                params![record.chunk_id, record.embedding_profile_id, record.vector.len() as i64, Self::encode(&record.vector), now])?;
        }
        tx.commit()?;
        Ok(records.len())
    }

    fn search(&self, profile_id: &str, query: &[f32], top_k: usize) -> AppResult<Vec<SearchHit>> {
        if query.is_empty() {
            return Err(AppError::InvalidInput("query vector is empty".into()));
        }
        if query.iter().any(|value| !value.is_finite()) {
            return Err(AppError::InvalidInput(
                "query vector contains NaN or infinity".into(),
            ));
        }
        let conn = self.db.connection()?;
        let dimension: i64 = conn
            .query_row(
                "SELECT dimension FROM embedding_profile WHERE id=?1",
                [profile_id],
                |r| r.get(0),
            )
            .map_err(|_| AppError::NotFound(format!("embedding profile {profile_id}")))?;
        if dimension as usize != query.len() {
            return Err(AppError::IncompatibleEmbedding(format!(
                "profile dimension {dimension}, query dimension {}",
                query.len()
            )));
        }
        let mut stmt = conn.prepare("SELECT vr.vector,c.id,c.document_id,d.file_name,d.file_path,c.chunk_index,c.text
            FROM vector_record vr JOIN chunk c ON c.id=vr.chunk_id JOIN document d ON d.id=c.document_id
            WHERE vr.embedding_profile_id=?1")?;
        let rows = stmt.query_map([profile_id], |row| {
            Ok((
                row.get::<_, Vec<u8>>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, i64>(5)?,
                row.get::<_, String>(6)?,
            ))
        })?;
        let mut hits = Vec::new();
        for row in rows {
            let (blob, chunk_id, document_id, file_name, file_path, chunk_index, text) = row?;
            let score = Self::cosine(query, &Self::decode(&blob)?)?;
            hits.push(SearchHit {
                score,
                chunk_id,
                document_id,
                file_name,
                file_path,
                chunk_index: chunk_index as usize,
                text,
            });
        }
        hits.sort_by(|a, b| b.score.total_cmp(&a.score));
        hits.truncate(top_k.max(1));
        Ok(hits)
    }

    fn delete_by_document(&self, document_id: &str) -> AppResult<usize> {
        Ok(self.db.connection()?.execute("DELETE FROM vector_record WHERE chunk_id IN (SELECT id FROM chunk WHERE document_id=?1)", [document_id])?)
    }
    fn delete_by_chunk(&self, chunk_id: &str) -> AppResult<usize> {
        Ok(self
            .db
            .connection()?
            .execute("DELETE FROM vector_record WHERE chunk_id=?1", [chunk_id])?)
    }
    fn delete_by_profile(&self, profile_id: &str) -> AppResult<usize> {
        Ok(self.db.connection()?.execute(
            "DELETE FROM vector_record WHERE embedding_profile_id=?1",
            [profile_id],
        )?)
    }
    fn count(&self, profile_id: Option<&str>) -> AppResult<usize> {
        let conn = self.db.connection()?;
        let value: i64 = if let Some(id) = profile_id {
            conn.query_row(
                "SELECT COUNT(*) FROM vector_record WHERE embedding_profile_id=?1",
                [id],
                |r| r.get(0),
            )?
        } else {
            conn.query_row("SELECT COUNT(*) FROM vector_record", [], |r| r.get(0))?
        };
        Ok(value as usize)
    }
    fn clear(&self) -> AppResult<usize> {
        Ok(self
            .db
            .connection()?
            .execute("DELETE FROM vector_record", [])?)
    }
}
