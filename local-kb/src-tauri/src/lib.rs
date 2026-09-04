pub mod app;
pub mod benchmark;
pub mod chunk;
pub mod commands;
pub mod config;
pub mod database;
pub mod document;
pub mod embedding;
pub mod error;
pub mod knowledge_base;
pub mod llm;
pub mod rag;
pub mod retrieval;
pub mod vector_store;
pub mod watcher;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let state = app::AppState::initialize().expect("failed to initialize Local KB");
    tauri::Builder::default()
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            commands::get_dashboard,
            commands::list_knowledge_bases,
            commands::create_knowledge_base,
            commands::delete_knowledge_base,
            commands::scan_knowledge_base,
            commands::list_documents,
            commands::list_chunks,
            commands::add_file,
            commands::reparse_document,
            commands::delete_document,
            commands::mock_index,
            commands::get_embedding_service_status,
            commands::start_embedding_service,
            commands::stop_embedding_service,
            commands::list_embedding_models,
            commands::index_with_embedding,
            commands::import_embedding_vectors,
            commands::list_embedding_profiles,
            commands::search_mock,
            commands::search_with_embedding,
            commands::search_by_vector,
            commands::search_local_knowledge,
            commands::search_local_knowledge_by_vector,
            commands::rag_query,
            commands::rag_query_with_embedding,
            commands::get_settings,
            commands::start_watcher,
            commands::stop_watcher,
            commands::open_directory,
            commands::run_benchmark
        ])
        .run(tauri::generate_context!())
        .expect("error while running Local KB");
}
