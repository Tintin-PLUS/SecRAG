use crate::{
    database::Database,
    error::AppResult,
    vector_store::{SqliteVectorStore, VectorRecordInput, VectorStore},
};
use chrono::Utc;
use rusqlite::params;
use serde::{Deserialize, Serialize};
use std::time::Instant;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BenchmarkResult {
    pub chunk_count: usize,
    pub dimension: usize,
    pub insert_ms: f64,
    pub search_top5_ms: f64,
    pub search_top10_ms: f64,
    pub sqlite_read_ms: f64,
}

pub fn run(chunk_count: usize, dimension: usize) -> AppResult<BenchmarkResult> {
    let chunk_count = chunk_count.clamp(1, 10_000);
    let dimension = dimension.clamp(1, 4096);
    let db = Database::open_in_memory()?;
    let now = Utc::now().to_rfc3339();
    {
        let mut conn = db.connection()?;
        let tx = conn.transaction()?;
        tx.execute(
            "INSERT INTO knowledge_base VALUES('kb','bench','bench',500,80,?1,?1)",
            [&now],
        )?;
        tx.execute("INSERT INTO document VALUES('doc','kb','bench.md','bench.md','hash','md','WAITING_EMBEDDING',?1,?1)",[&now])?;
        tx.execute("INSERT INTO embedding_profile VALUES('profile','kb','bench','bench','1',?1,'bench','mock','f32',1,'none',NULL,NULL,NULL,?2)",params![dimension as i64,now])?;
        for i in 0..chunk_count {
            tx.execute(
                "INSERT INTO chunk VALUES(?1,'doc',?2,?3,'{}',?4)",
                params![
                    format!("c{i}"),
                    i as i64,
                    format!("benchmark chunk {i}"),
                    now
                ],
            )?;
        }
        tx.commit()?;
    }
    let store = SqliteVectorStore::new(db.clone());
    let records = (0..chunk_count)
        .map(|i| {
            let mut vector = vec![0.0; dimension];
            for (j, v) in vector.iter_mut().enumerate() {
                *v = (((i + 1) * (j + 3)) % 97) as f32 / 97.0;
            }
            VectorRecordInput {
                chunk_id: format!("c{i}"),
                embedding_profile_id: "profile".into(),
                vector,
            }
        })
        .collect();
    let start = Instant::now();
    store.insert_batch(records)?;
    let insert_ms = start.elapsed().as_secs_f64() * 1000.0;
    let query = vec![0.5; dimension];
    let start = Instant::now();
    store.search("profile", &query, 5)?;
    let search_top5_ms = start.elapsed().as_secs_f64() * 1000.0;
    let start = Instant::now();
    store.search("profile", &query, 10)?;
    let search_top10_ms = start.elapsed().as_secs_f64() * 1000.0;
    let start = Instant::now();
    let _: String =
        db.connection()?
            .query_row("SELECT text FROM chunk WHERE id='c0'", [], |r| r.get(0))?;
    let sqlite_read_ms = start.elapsed().as_secs_f64() * 1000.0;
    Ok(BenchmarkResult {
        chunk_count,
        dimension,
        insert_ms,
        search_top5_ms,
        search_top10_ms,
        sqlite_read_ms,
    })
}
