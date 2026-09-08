use local_kb_lib::{
    database::Database,
    document::DocumentService,
    embedding::{
        DeterministicEmbeddingProvider, EmbeddingInput, EmbeddingInputType, EmbeddingProvider,
        VectorIngestService,
    },
    knowledge_base::KnowledgeBaseService,
    retrieval::RetrievalService,
    watcher,
};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    env, fs,
    path::{Path, PathBuf},
    thread,
    time::{Duration, Instant},
};
use uuid::Uuid;

fn work_dir_from_args() -> Result<PathBuf, String> {
    let mut args = env::args().skip(1);
    match (args.next().as_deref(), args.next(), args.next()) {
        (Some("--work-dir"), Some(path), None) => Ok(PathBuf::from(path)),
        _ => Err("usage: functional_verification --work-dir <path>".into()),
    }
}

fn pass(case_id: &str, category: &str, started: Instant, actual: Value) -> Value {
    json!({
        "case_id": case_id,
        "category": category,
        "status": "PASS",
        "duration_ms": started.elapsed().as_secs_f64() * 1000.0,
        "actual": actual,
    })
}

fn require(condition: bool, message: &str) -> Result<(), Box<dyn std::error::Error>> {
    if condition {
        Ok(())
    } else {
        Err(message.into())
    }
}

fn count(db: &Database, table: &str) -> Result<i64, Box<dyn std::error::Error>> {
    let allowed = ["knowledge_base", "document", "chunk", "vector_record"];
    require(allowed.contains(&table), "unsupported table")?;
    Ok(db
        .connection()?
        .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
            row.get(0)
        })?)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let work_dir = work_dir_from_args().map_err(std::io::Error::other)?;
    let docs_dir = work_dir.join("documents");
    fs::create_dir_all(&docs_dir)?;
    let alpha = docs_dir.join("alpha.md");
    let beta = docs_dir.join("beta.txt");
    fs::write(&alpha, "# 宁德时代\n毛利率改善，海外产能稳步推进。\n")?;
    fs::write(&beta, "比亚迪销量增长，海外出口继续扩张。\n")?;

    let database_path = work_dir.join("local-kb-functional.db");
    let db = Database::open(&database_path)?;
    let knowledge_bases = KnowledgeBaseService::new(db.clone());
    let documents = DocumentService::new(db.clone());
    let mut cases = Vec::new();

    let started = Instant::now();
    let kb = knowledge_bases.create(
        "functional-verification",
        docs_dir.to_string_lossy().as_ref(),
        80,
        10,
    )?;
    require(
        knowledge_bases.list()?.len() == 1,
        "knowledge base was not created",
    )?;
    cases.push(pass(
        "L01",
        "closed_loop",
        started,
        json!({"knowledge_base_id": kb.id, "database": database_path}),
    ));

    let started = Instant::now();
    let initial = documents.scan(&kb.id)?;
    require(
        initial.added == 2 && initial.errors.is_empty(),
        "initial scan mismatch",
    )?;
    require(
        documents.list(&kb.id)?.len() == 2,
        "document count mismatch",
    )?;
    cases.push(pass("U01", "incremental_update", started, json!(initial)));

    let started = Instant::now();
    let unchanged = documents.scan(&kb.id)?;
    require(unchanged.unchanged == 2, "unchanged scan mismatch")?;
    cases.push(pass("I01", "incremental_update", started, json!(unchanged)));

    let started = Instant::now();
    fs::write(
        &alpha,
        "# 宁德时代\n毛利率改善，海外产能与研发投入同步推进。\n",
    )?;
    let updated = documents.scan(&kb.id)?;
    require(
        updated.updated == 1 && updated.unchanged == 1,
        "update scan mismatch",
    )?;
    cases.push(pass("U02", "incremental_update", started, json!(updated)));

    let started = Instant::now();
    let chunks: Vec<(String, String, String)> = {
        let conn = db.connection()?;
        let mut stmt = conn.prepare(
            "SELECT c.id,c.document_id,c.text FROM chunk c JOIN document d ON d.id=c.document_id WHERE d.knowledge_base_id=?1 ORDER BY c.id",
        )?;
        let rows = stmt.query_map([&kb.id], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)))?;
        rows.collect::<Result<Vec<_>, _>>()?
    };
    let provider = DeterministicEmbeddingProvider::new(64);
    let outputs = chunks
        .iter()
        .map(|(chunk_id, document_id, text)| {
            provider.embed(EmbeddingInput {
                request_id: Uuid::new_v4().to_string(),
                input_type: EmbeddingInputType::Document,
                text: text.clone(),
                document_id: Some(document_id.clone()),
                chunk_id: Some(chunk_id.clone()),
                metadata: HashMap::new(),
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    let indexed = VectorIngestService::new(db.clone()).ingest_embeddings(&kb.id, outputs, true)?;
    let hits = RetrievalService::new(db.clone()).search_text(
        &kb.id,
        "宁德时代 毛利率",
        3,
        std::sync::Arc::new(provider),
    )?;
    require(indexed.inserted == chunks.len(), "vector count mismatch")?;
    require(!hits.is_empty(), "local retrieval returned no results")?;
    cases.push(pass(
        "L02",
        "closed_loop",
        started,
        json!({"vectors": indexed.inserted, "hits": hits.len(), "runtime": "rust-mock"}),
    ));

    let started = Instant::now();
    let alpha_doc = documents
        .list(&kb.id)?
        .into_iter()
        .find(|document| document.file_name == "alpha.md")
        .ok_or("alpha document missing")?;
    documents.delete(&alpha_doc.id)?;
    fs::remove_file(&alpha)?;
    let remaining_alpha_chunks: i64 = db.connection()?.query_row(
        "SELECT COUNT(*) FROM chunk WHERE document_id=?1",
        [&alpha_doc.id],
        |row| row.get(0),
    )?;
    require(
        remaining_alpha_chunks == 0,
        "document delete did not cascade",
    )?;
    cases.push(pass(
        "U03",
        "incremental_update",
        started,
        json!({"remaining_chunks": remaining_alpha_chunks}),
    ));

    let started = Instant::now();
    let registration = watcher::start(kb.id.clone(), Path::new(&kb.root_path), db.clone())?;
    let watched = docs_dir.join("watched.md");
    for revision in 1..=3 {
        fs::write(
            &watched,
            format!("# 招商银行\n净息差与财富管理 AUM，连续修改版本{revision}。\n"),
        )?;
        thread::sleep(Duration::from_millis(20));
    }
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut watcher_detected = false;
    while Instant::now() < deadline {
        if documents
            .list(&kb.id)?
            .iter()
            .any(|document| document.file_name == "watched.md")
        {
            watcher_detected = true;
            break;
        }
        thread::sleep(Duration::from_millis(100));
    }
    drop(registration);
    require(
        watcher_detected,
        "file watcher did not trigger incremental scan",
    )?;
    let watched_documents = documents
        .list(&kb.id)?
        .into_iter()
        .filter(|document| document.file_name == "watched.md")
        .collect::<Vec<_>>();
    require(watched_documents.len() == 1, "watcher created duplicate documents")?;
    cases.push(pass(
        "U04",
        "incremental_update",
        started,
        json!({"detected": watcher_detected, "writes": 3, "document_rows": watched_documents.len()}),
    ));

    let started = Instant::now();
    fs::remove_file(&beta)?;
    let removed = documents.scan(&kb.id)?;
    require(removed.removed == 1, "removed source was not synchronized")?;
    cases.push(pass("I02", "incremental_update", started, json!(removed)));

    let started = Instant::now();
    let before_corrupt = documents.list(&kb.id)?.len();
    let corrupt = docs_dir.join("corrupt.md");
    fs::write(&corrupt, [0xff, 0xfe, 0xfd])?;
    let corrupt_result = documents.scan(&kb.id)?;
    let after_corrupt = documents.list(&kb.id)?.len();
    require(!corrupt_result.errors.is_empty(), "corrupt file did not report an error")?;
    require(before_corrupt == after_corrupt, "corrupt file polluted document index")?;
    fs::remove_file(&corrupt)?;
    cases.push(pass(
        "U05",
        "incremental_update",
        started,
        json!({"errors": corrupt_result.errors, "before_documents": before_corrupt, "after_documents": after_corrupt}),
    ));

    let started = Instant::now();
    let before_reopen = count(&db, "document")?;
    let reopened = Database::open(&database_path)?;
    let after_reopen = count(&reopened, "document")?;
    require(before_reopen == after_reopen, "database state changed after reopen")?;
    cases.push(pass(
        "U06",
        "incremental_update",
        started,
        json!({"before_documents": before_reopen, "after_documents": after_reopen}),
    ));

    let started = Instant::now();
    fs::write(&watched, "# 招商银行\n监听已暂停，手动扫描恢复最终内容。\n")?;
    let manual_scan = documents.scan(&kb.id)?;
    require(manual_scan.updated == 1, "manual scan did not repair watcher gap")?;
    cases.push(pass("U07", "incremental_update", started, json!(manual_scan)));

    let started = Instant::now();
    require(
        database_path.starts_with(&work_dir),
        "database is not inside local work directory",
    )?;
    cases.push(pass(
        "L04",
        "closed_loop",
        started,
        json!({"external_service_used": false, "database_local": true}),
    ));

    let started = Instant::now();
    knowledge_bases.delete(&kb.id)?;
    let final_counts = json!({
        "knowledge_bases": count(&db, "knowledge_base")?,
        "documents": count(&db, "document")?,
        "chunks": count(&db, "chunk")?,
        "vectors": count(&db, "vector_record")?,
    });
    require(
        final_counts["knowledge_bases"] == 0
            && final_counts["documents"] == 0
            && final_counts["chunks"] == 0
            && final_counts["vectors"] == 0,
        "knowledge base delete did not cascade",
    )?;
    cases.push(pass("L05", "closed_loop", started, final_counts));

    println!(
        "{}",
        serde_json::to_string(&json!({
            "status": "PASS",
            "database_path": database_path,
            "case_results": cases,
        }))?
    );
    Ok(())
}
