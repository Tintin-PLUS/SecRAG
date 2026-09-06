use rusqlite::Connection;
use std::path::Path;
use std::sync::{Arc, Mutex};

mod parser;
mod chunker;
mod embedding;
mod search;
mod server;

fn main() {
    println!("=======================================");
    println!("  证券端侧知识库模块 v0.1");
    println!("=======================================\n");

    if !Path::new("data").exists() {
        std::fs::create_dir("data").expect("创建data目录失败");
    }

    let conn = Connection::open("data/knowledge.db").expect("打开数据库失败");
    conn.pragma_update(None, "journal_mode", "WAL").unwrap();
    init_tables(&conn);

    println!("[OK] 数据库已就绪: data/knowledge.db");

    let _embed_child = embedding::start_embed_server();

    let doc_count: i64 = conn
        .query_row("SELECT COUNT(*) FROM documents WHERE status='active'", [], |r| r.get(0))
        .unwrap_or(0);
    let chunk_count: i64 = conn
        .query_row("SELECT COUNT(*) FROM chunks", [], |r| r.get(0))
        .unwrap_or(0);
    println!("[OK] 当前文档数: {}, 文本块数: {}\n", doc_count, chunk_count);

    let conn = Arc::new(Mutex::new(conn));

    let port = 8901;
    println!("[OK] 服务地址: http://127.0.0.1:{}", port);
    println!("\n等待请求中... (Ctrl+C 退出)\n");

    server::start_server(port, conn);
}

fn init_tables(conn: &Connection) {
    conn.execute_batch(r#"
        CREATE TABLE IF NOT EXISTS documents (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id      TEXT UNIQUE NOT NULL,
            title       TEXT NOT NULL,
            doc_type    TEXT,
            file_path   TEXT,
            content     TEXT,
            status      TEXT DEFAULT 'active',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id      TEXT NOT NULL,
            position    INTEGER NOT NULL,
            content     TEXT NOT NULL,
            vector      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
    "#).expect("建表失败");
}
