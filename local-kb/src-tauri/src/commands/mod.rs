use crate::{
    app::AppState,
    benchmark::{self, BenchmarkResult},
    document::{DocumentService, DocumentView, ScanResult},
    embedding::{
        EmbeddingInput, EmbeddingInputType, EmbeddingModelInfo, EmbeddingOutput,
        EmbeddingServiceStatus, ExternalVectorBatch, VectorIngestService,
    },
    error::AppError,
    knowledge_base::{KnowledgeBase, KnowledgeBaseService},
    rag::{RagResponse, RagService},
    retrieval::RetrievalService,
    vector_store::SearchHit,
    watcher,
};
use rusqlite::OptionalExtension;
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, path::Path};
use tauri::State;
use uuid::Uuid;

type CommandResult<T> = Result<T, String>;
fn command<T>(result: Result<T, AppError>) -> CommandResult<T> {
    result.map_err(|e| e.to_string())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Dashboard {
    pub knowledge_bases: usize,
    pub documents: usize,
    pub chunks: usize,
    pub vectors: usize,
    pub vector_store: String,
    pub embedding_status: String,
    pub index_status: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProfileView {
    pub id: String,
    pub knowledge_base_id: String,
    pub model_id: String,
    pub model_name: String,
    pub model_version: String,
    pub dimension: usize,
    pub config_hash: String,
    pub runtime: String,
    pub normalize: bool,
    pub pooling: String,
    pub status: String,
    pub vector_count: usize,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SettingsView {
    pub database_path: String,
    pub chunk_size: usize,
    pub chunk_overlap: usize,
    pub llm_base_url: String,
    pub llm_model: String,
    pub llm_api_key_configured: bool,
    pub llm_provider: String,
    pub llm_thinking: bool,
    pub llm_reasoning_effort: String,
    pub llm_timeout_secs: u64,
    pub vector_store: String,
    pub registered_providers: Vec<String>,
    pub embedding_base_url: String,
    pub embedding_python: String,
    pub embedding_script: String,
    pub embedding_batch_size: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingIndexResult {
    pub model_id: String,
    pub chunks_embedded: usize,
    pub batches: usize,
    pub profile_id: String,
    pub status: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkView {
    pub id: String,
    pub document_id: String,
    pub file_name: String,
    pub chunk_index: usize,
    pub text: String,
}

#[tauri::command]
pub fn get_dashboard(state: State<'_, AppState>) -> CommandResult<Dashboard> {
    command((|| {
        let conn = state.db.connection()?;
        let count = |table: &str| -> Result<usize, AppError> {
            Ok(
                conn.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| {
                    r.get::<_, i64>(0)
                })? as usize,
            )
        };
        let real_profiles: i64 = conn.query_row(
            "SELECT COUNT(*) FROM embedding_profile WHERE runtime='python-sentence-transformers'",
            [],
            |row| row.get(0),
        )?;
        let embedding_status = if real_profiles > 0 {
            "REAL_INDEX_AVAILABLE"
        } else {
            "SIDECAR_CONFIGURED"
        }
        .into();
        let index_status: Option<String> = conn
            .query_row(
                "SELECT status FROM index_state ORDER BY updated_at DESC LIMIT 1",
                [],
                |r| r.get(0),
            )
            .optional()?;
        Ok(Dashboard {
            knowledge_bases: count("knowledge_base")?,
            documents: count("document")?,
            chunks: count("chunk")?,
            vectors: count("vector_record")?,
            vector_store: "SQLite BLOB + Rust cosine (fallback)".into(),
            embedding_status,
            index_status: index_status.unwrap_or_else(|| "EMPTY".into()),
        })
    })())
}

#[tauri::command]
pub fn list_knowledge_bases(state: State<'_, AppState>) -> CommandResult<Vec<KnowledgeBase>> {
    command(KnowledgeBaseService::new(state.db.clone()).list())
}
#[tauri::command]
pub fn create_knowledge_base(
    state: State<'_, AppState>,
    name: String,
    root_path: String,
    chunk_size: Option<usize>,
    chunk_overlap: Option<usize>,
) -> CommandResult<KnowledgeBase> {
    let size = chunk_size.unwrap_or(state.config.chunk_size);
    let overlap = chunk_overlap.unwrap_or(state.config.chunk_overlap);
    command(KnowledgeBaseService::new(state.db.clone()).create(&name, &root_path, size, overlap))
}
#[tauri::command]
pub fn delete_knowledge_base(
    state: State<'_, AppState>,
    knowledge_base_id: String,
) -> CommandResult<()> {
    if let Ok(mut map) = state.watchers.lock() {
        map.remove(&knowledge_base_id);
    }
    command(KnowledgeBaseService::new(state.db.clone()).delete(&knowledge_base_id))
}
#[tauri::command]
pub fn scan_knowledge_base(
    state: State<'_, AppState>,
    knowledge_base_id: String,
) -> CommandResult<ScanResult> {
    command(DocumentService::new(state.db.clone()).scan(&knowledge_base_id))
}
#[tauri::command]
pub fn list_documents(
    state: State<'_, AppState>,
    knowledge_base_id: String,
) -> CommandResult<Vec<DocumentView>> {
    command(DocumentService::new(state.db.clone()).list(&knowledge_base_id))
}
#[tauri::command]
pub fn list_chunks(
    state: State<'_, AppState>,
    knowledge_base_id: String,
) -> CommandResult<Vec<ChunkView>> {
    command((|| {
        let conn = state.db.connection()?;
        let mut stmt=conn.prepare("SELECT c.id,c.document_id,d.file_name,c.chunk_index,c.text FROM chunk c JOIN document d ON d.id=c.document_id WHERE d.knowledge_base_id=?1 ORDER BY d.file_name,c.chunk_index")?;
        let rows = stmt.query_map([knowledge_base_id], |r| {
            Ok(ChunkView {
                id: r.get(0)?,
                document_id: r.get(1)?,
                file_name: r.get(2)?,
                chunk_index: r.get::<_, i64>(3)? as usize,
                text: r.get(4)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    })())
}
#[tauri::command]
pub fn add_file(
    state: State<'_, AppState>,
    knowledge_base_id: String,
    file_path: String,
) -> CommandResult<ScanResult> {
    command(DocumentService::new(state.db.clone()).add_file(&knowledge_base_id, &file_path))
}
#[tauri::command]
pub fn reparse_document(
    state: State<'_, AppState>,
    document_id: String,
) -> CommandResult<ScanResult> {
    command(DocumentService::new(state.db.clone()).reparse(&document_id))
}
#[tauri::command]
pub fn delete_document(state: State<'_, AppState>, document_id: String) -> CommandResult<()> {
    command(DocumentService::new(state.db.clone()).delete(&document_id))
}

#[tauri::command]
pub fn mock_index(
    state: State<'_, AppState>,
    knowledge_base_id: String,
) -> CommandResult<crate::embedding::integration::IngestResult> {
    command((|| {
        let provider = state.embeddings.get("deterministic-mock-v1")?;
        let chunks = {
            let conn = state.db.connection()?;
            let mut stmt=conn.prepare("SELECT c.id,c.document_id,c.text FROM chunk c JOIN document d ON d.id=c.document_id WHERE d.knowledge_base_id=?1 ORDER BY d.id,c.chunk_index")?;
            let rows = stmt.query_map([&knowledge_base_id], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })?;
            rows.collect::<Result<Vec<_>, _>>()?
        };
        if chunks.is_empty() {
            return Err(AppError::InvalidInput(
                "scan documents before creating mock vectors".into(),
            ));
        }
        let outputs = chunks
            .into_iter()
            .map(|(chunk_id, document_id, text)| {
                provider.embed(EmbeddingInput {
                    request_id: Uuid::new_v4().to_string(),
                    input_type: EmbeddingInputType::Document,
                    text,
                    document_id: Some(document_id),
                    chunk_id: Some(chunk_id),
                    metadata: HashMap::new(),
                })
            })
            .collect::<Result<Vec<EmbeddingOutput>, _>>()?;
        let result = VectorIngestService::new(state.db.clone()).ingest_embeddings(
            &knowledge_base_id,
            outputs,
            true,
        )?;
        state.db.connection()?.execute("UPDATE document SET status='MOCK_INDEXED',updated_at=datetime('now') WHERE knowledge_base_id=?1",[knowledge_base_id])?;
        Ok(result)
    })())
}

#[tauri::command]
pub fn get_embedding_service_status(
    state: State<'_, AppState>,
) -> CommandResult<EmbeddingServiceStatus> {
    Ok(state.embedding_service.status())
}

#[tauri::command]
pub fn start_embedding_service(
    state: State<'_, AppState>,
) -> CommandResult<EmbeddingServiceStatus> {
    command(state.embedding_service.start())
}

#[tauri::command]
pub fn stop_embedding_service(state: State<'_, AppState>) -> CommandResult<EmbeddingServiceStatus> {
    command(state.embedding_service.stop())
}

#[tauri::command]
pub fn list_embedding_models(state: State<'_, AppState>) -> CommandResult<Vec<EmbeddingModelInfo>> {
    command(state.embeddings.model_infos())
}

#[tauri::command]
pub async fn index_with_embedding(
    state: State<'_, AppState>,
    knowledge_base_id: String,
    model_id: String,
) -> CommandResult<EmbeddingIndexResult> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        command((|| {
            if model_id == "deterministic-mock-v1" {
                return Err(AppError::InvalidInput(
                    "use Mock Index for the deterministic mock provider".into(),
                ));
            }
            let provider = state.embeddings.get(&model_id)?;
            let chunks = {
                let conn = state.db.connection()?;
                let mut stmt=conn.prepare("SELECT c.id,c.document_id,c.text FROM chunk c JOIN document d ON d.id=c.document_id WHERE d.knowledge_base_id=?1 ORDER BY d.id,c.chunk_index")?;
                let rows = stmt.query_map([&knowledge_base_id], |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                })?;
                rows.collect::<Result<Vec<_>, _>>()?
            };
            if chunks.is_empty() {
                return Err(AppError::InvalidInput(
                    "scan documents before creating vectors".into(),
                ));
            }
            let mut outputs = Vec::with_capacity(chunks.len());
            let mut batches = 0;
            for batch in chunks.chunks(state.config.embedding_batch_size) {
                let inputs = batch
                    .iter()
                    .map(|(chunk_id, document_id, text)| EmbeddingInput {
                        request_id: Uuid::new_v4().to_string(),
                        input_type: EmbeddingInputType::Document,
                        text: text.clone(),
                        document_id: Some(document_id.clone()),
                        chunk_id: Some(chunk_id.clone()),
                        metadata: HashMap::new(),
                    })
                    .collect();
                outputs.extend(provider.embed_batch(inputs)?);
                batches += 1;
            }
            let chunks_embedded = outputs.len();
            let result = VectorIngestService::new(state.db.clone()).ingest_embeddings(
                &knowledge_base_id,
                outputs,
                false,
            )?;
            Ok(EmbeddingIndexResult {
                model_id,
                chunks_embedded,
                batches,
                profile_id: result.profile_id,
                status: result.status,
            })
        })())
    })
    .await
    .map_err(|error| format!("embedding task failed: {error}"))?
}

#[tauri::command]
pub fn import_embedding_vectors(
    state: State<'_, AppState>,
    json: String,
) -> CommandResult<crate::embedding::integration::IngestResult> {
    command((|| {
        let batch: ExternalVectorBatch = serde_json::from_str(&json)?;
        VectorIngestService::new(state.db.clone()).ingest_external(batch)
    })())
}

#[tauri::command]
pub fn list_embedding_profiles(
    state: State<'_, AppState>,
    knowledge_base_id: Option<String>,
) -> CommandResult<Vec<ProfileView>> {
    command((|| {
        let conn = state.db.connection()?;
        let sql = "SELECT p.id,p.knowledge_base_id,p.model_id,p.model_name,p.model_version,p.dimension,p.config_hash,p.runtime,p.normalize,p.pooling,COALESCE(s.status,'EMPTY'),COUNT(v.chunk_id) FROM embedding_profile p LEFT JOIN index_state s ON s.embedding_profile_id=p.id LEFT JOIN vector_record v ON v.embedding_profile_id=p.id WHERE (?1 IS NULL OR p.knowledge_base_id=?1) GROUP BY p.id ORDER BY p.created_at DESC";
        let mut stmt = conn.prepare(sql)?;
        let rows = stmt.query_map([knowledge_base_id], |r| {
            Ok(ProfileView {
                id: r.get(0)?,
                knowledge_base_id: r.get(1)?,
                model_id: r.get(2)?,
                model_name: r.get(3)?,
                model_version: r.get(4)?,
                dimension: r.get::<_, i64>(5)? as usize,
                config_hash: r.get(6)?,
                runtime: r.get(7)?,
                normalize: r.get::<_, i64>(8)? != 0,
                pooling: r.get(9)?,
                status: r.get(10)?,
                vector_count: r.get::<_, i64>(11)? as usize,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    })())
}

#[tauri::command]
pub fn search_mock(
    state: State<'_, AppState>,
    knowledge_base_id: String,
    query: String,
    top_k: usize,
) -> CommandResult<Vec<SearchHit>> {
    command((|| {
        let provider = state.embeddings.get("deterministic-mock-v1")?;
        RetrievalService::new(state.db.clone()).search_text(
            &knowledge_base_id,
            &query,
            top_k,
            provider,
        )
    })())
}

#[tauri::command]
pub async fn search_with_embedding(
    state: State<'_, AppState>,
    knowledge_base_id: String,
    model_id: String,
    query: String,
    top_k: usize,
) -> CommandResult<Vec<SearchHit>> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        command((|| {
            let provider = state.embeddings.get(&model_id)?;
            RetrievalService::new(state.db.clone()).search_text(
                &knowledge_base_id,
                &query,
                top_k,
                provider,
            )
        })())
    })
    .await
    .map_err(|error| format!("embedding search task failed: {error}"))?
}
#[tauri::command]
pub fn search_by_vector(
    state: State<'_, AppState>,
    knowledge_base_id: String,
    embedding_profile_id: String,
    query_vector: Vec<f32>,
    top_k: usize,
) -> CommandResult<Vec<SearchHit>> {
    command(RetrievalService::new(state.db.clone()).search_by_vector(
        &knowledge_base_id,
        &embedding_profile_id,
        &query_vector,
        top_k,
    ))
}
#[tauri::command]
pub fn search_local_knowledge(
    state: State<'_, AppState>,
    knowledge_base_id: String,
    query: String,
    top_k: usize,
) -> CommandResult<Vec<SearchHit>> {
    search_mock(state, knowledge_base_id, query, top_k)
}
#[tauri::command]
pub fn search_local_knowledge_by_vector(
    state: State<'_, AppState>,
    knowledge_base_id: String,
    embedding_profile_id: String,
    query_vector: Vec<f32>,
    top_k: usize,
) -> CommandResult<Vec<SearchHit>> {
    search_by_vector(
        state,
        knowledge_base_id,
        embedding_profile_id,
        query_vector,
        top_k,
    )
}

#[tauri::command]
pub async fn rag_query(
    state: State<'_, AppState>,
    knowledge_base_id: String,
    question: String,
    top_k: usize,
) -> CommandResult<RagResponse> {
    let provider = command(state.embeddings.get("deterministic-mock-v1"))?;
    command(
        RagService::new(
            RetrievalService::new(state.db.clone()),
            state.config.clone(),
        )
        .answer(&knowledge_base_id, &question, top_k, provider)
        .await,
    )
}

#[tauri::command]
pub async fn rag_query_with_embedding(
    state: State<'_, AppState>,
    knowledge_base_id: String,
    question: String,
    top_k: usize,
    model_id: String,
) -> CommandResult<RagResponse> {
    let provider = command(state.embeddings.get(&model_id))?;
    command(
        RagService::new(
            RetrievalService::new(state.db.clone()),
            state.config.clone(),
        )
        .answer(&knowledge_base_id, &question, top_k, provider)
        .await,
    )
}

#[tauri::command]
pub fn get_settings(state: State<'_, AppState>) -> CommandResult<SettingsView> {
    command((|| {
        Ok(SettingsView {
            database_path: state.db.path().to_string_lossy().into_owned(),
            chunk_size: state.config.chunk_size,
            chunk_overlap: state.config.chunk_overlap,
            llm_base_url: state.config.llm_base_url.clone(),
            llm_model: state.config.llm_model.clone(),
            llm_api_key_configured: state.config.llm_api_key.is_some(),
            llm_provider: "DeepSeek Chat Completions".into(),
            llm_thinking: state.config.llm_thinking,
            llm_reasoning_effort: state.config.llm_reasoning_effort.clone(),
            llm_timeout_secs: state.config.llm_timeout_secs,
            vector_store:
                "SQLite BLOB + Rust cosine (sqlite-vec replacement boundary: VectorStore)".into(),
            registered_providers: state.embeddings.model_ids()?,
            embedding_base_url: state.config.embedding_base_url.clone(),
            embedding_python: state.config.embedding_python.to_string_lossy().into_owned(),
            embedding_script: state.config.embedding_script.to_string_lossy().into_owned(),
            embedding_batch_size: state.config.embedding_batch_size,
        })
    })())
}

#[tauri::command]
pub fn start_watcher(
    state: State<'_, AppState>,
    knowledge_base_id: String,
) -> CommandResult<String> {
    command((|| {
        let kb = KnowledgeBaseService::new(state.db.clone()).get(&knowledge_base_id)?;
        let registration = watcher::start(
            knowledge_base_id.clone(),
            Path::new(&kb.root_path),
            state.db.clone(),
        )?;
        state
            .watchers
            .lock()
            .map_err(|_| AppError::Internal("watcher map poisoned".into()))?
            .insert(knowledge_base_id, registration);
        Ok("WATCHING".into())
    })())
}
#[tauri::command]
pub fn stop_watcher(
    state: State<'_, AppState>,
    knowledge_base_id: String,
) -> CommandResult<String> {
    command((|| {
        state
            .watchers
            .lock()
            .map_err(|_| AppError::Internal("watcher map poisoned".into()))?
            .remove(&knowledge_base_id);
        Ok("STOPPED".into())
    })())
}
#[tauri::command]
pub fn open_directory(path: String) -> CommandResult<()> {
    let target = Path::new(&path);
    if !target.is_dir() {
        return Err("directory does not exist".into());
    }
    std::process::Command::new("explorer.exe")
        .arg(target)
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("failed to open directory: {e}"))
}
#[tauri::command]
pub fn run_benchmark(chunk_count: usize, dimension: usize) -> CommandResult<BenchmarkResult> {
    command(benchmark::run(chunk_count, dimension))
}
