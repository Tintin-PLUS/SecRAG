use tiny_http::{Server, Method, Response, Header};
use std::sync::{Arc, Mutex};
use rusqlite::{Connection, params};
use crate::{search, parser, chunker, embedding};
use uuid::Uuid;

pub fn start_server(port: u16, conn: Arc<Mutex<Connection>>) {
    let server = match Server::http(format!("127.0.0.1:{}", port)) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[ERROR] 启动HTTP服务失败: {}", e);
            return;
        }
    };

    for request in server.incoming_requests() {
        handle_request(request, &conn);
    }
}

fn url_decode(s: &str) -> String {
    let mut result = String::new();
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '%' {
            let h1 = chars.next();
            let h2 = chars.next();
            if let (Some(h1), Some(h2)) = (h1, h2) {
                let hex = format!("{}{}", h1, h2);
                if let Ok(byte) = u8::from_str_radix(&hex, 16) {
                    result.push(byte as char);
                    continue;
                }
            }
        } else if c == '+' {
            result.push(' ');
        } else {
            result.push(c);
        }
    }
    result
}

fn handle_request(mut request: tiny_http::Request, conn: &Arc<Mutex<Connection>>) {
    let url = request.url().to_string();
    let method = request.method().clone();

    let cors_header = Header::from_bytes(&b"Access-Control-Allow-Origin"[..], &b"*"[..]).unwrap();
    let json_header = Header::from_bytes(&b"Content-Type"[..], &b"application/json"[..]).unwrap();

    if method == Method::Options {
        request.respond(Response::empty(204).with_header(cors_header)).ok();
        return;
    }

    let body = if method == Method::Post {
        use std::io::Read;
        let mut buf = String::new();
        let _ = request.as_reader().take(10 * 1024 * 1024).read_to_string(&mut buf);
        Some(buf)
    } else {
        None
    };

    let resp_json = match (&method, url.as_str()) {
        (Method::Post, "/api/ingest") => Some(handle_ingest(&body.unwrap_or_default(), conn)),
        (Method::Post, "/api/search") => Some(handle_search(&body.unwrap_or_default(), conn)),
        (Method::Get, path) if path.starts_with("/api/documents") => Some(handle_list_documents(conn)),
        (Method::Get, path) if path.starts_with("/api/analyze") => {
            let query_str = path.split("?q=").nth(1).unwrap_or("");
            let decoded = url_decode(query_str);
            let conn_lock = conn.lock().unwrap();
            let analysis = search::analyze_query(&decoded, &conn_lock);
            request.respond(
                Response::from_data(analysis.to_string().into_bytes())
                    .with_header(cors_header)
                    .with_header(json_header)
            ).ok();
            return;
        }
        (Method::Post, "/api/recall") => Some(handle_recall(&body.unwrap_or_default(), conn)),
        (Method::Get, "/api/health") => {
            request.respond(Response::from_string(r#"{"status":"ok"}"#)
                .with_header(cors_header)
                .with_header(json_header)).ok();
            return;
        }
        (Method::Get, "/api/stats") => Some(handle_stats(conn)),
        (Method::Get, "/api/models") => {
            request.respond(Response::from_string(
                serde_json::json!({
                    "models": embedding::available_models().iter().map(|(k, v)| {
                        serde_json::json!({"key": k, "desc": v})
                    }).collect::<Vec<_>>()
                }).to_string()
            ).with_header(cors_header).with_header(json_header)).ok();
            return;
        }
        _ => {
            request.respond(Response::from_string(r#"{"error":"not found"}"#)
                .with_status_code(404)
                .with_header(cors_header)
                .with_header(json_header)).ok();
            return;
        }
    };

    if let Some(json) = resp_json {
        request.respond(
            Response::from_data(json.into_bytes())
                .with_header(cors_header)
                .with_header(json_header)
        ).ok();
    }
}

fn handle_ingest(body: &str, conn: &Arc<Mutex<Connection>>) -> String {
    let req: serde_json::Value = match serde_json::from_str(body) {
        Ok(v) => v,
        Err(_) => return r#"{"error":"无效的JSON"}"#.into(),
    };

    let file_path = req["file_path"].as_str().unwrap_or("");
    let model = req["model"].as_str().unwrap_or("bge-small");
    if file_path.is_empty() {
        return r#"{"error":"缺少file_path参数"}"#.into();
    }

    let parsed = match parser::parse_file(file_path) {
        Ok(d) => d,
        Err(e) => return format!(r#"{{"error":"解析失败: {}"}}"#, e),
    };

    let conn = conn.lock().unwrap();
    let doc_id = Uuid::new_v4().to_string();

    if conn.execute(
        "INSERT INTO documents (doc_id, title, doc_type, file_path, content)
         VALUES (?1, ?2, ?3, ?4, ?5)",
        params![doc_id, parsed.title, parsed.doc_type, parsed.file_path, parsed.content],
    ).is_err() {
        return r#"{"error":"数据库写入失败"}"#.into();
    }

    let chunks = chunker::chunk_by_structure(&parsed.content, 800, 100);
    let texts: Vec<String> = chunks.iter().map(|c| c.content.clone()).collect();
    let vectors = embedding::embed_with_model(&texts, model).unwrap_or_default();

    for (i, chunk) in chunks.iter().enumerate() {
        let vector_json = vectors.get(i)
            .map(|v| serde_json::to_string(v).unwrap_or_default())
            .unwrap_or("null".to_string());

        let _ = conn.execute(
            "INSERT INTO chunks (doc_id, position, content, vector)
             VALUES (?1, ?2, ?3, ?4)",
            params![doc_id, chunk.position, chunk.content, vector_json],
        );
    }

    serde_json::json!({
        "doc_id": doc_id,
        "title": parsed.title,
        "model": model,
        "chunk_count": chunks.len(),
        "status": "success"
    }).to_string()
}

fn handle_search(body: &str, conn: &Arc<Mutex<Connection>>) -> String {
    let req: serde_json::Value = match serde_json::from_str(body) {
        Ok(v) => v,
        Err(_) => return r#"{"error":"无效的JSON"}"#.into(),
    };

    let query = req["query"].as_str().unwrap_or("");
    let model = req["model"].as_str().unwrap_or("bge-small");
    let top_k = req["top_k"].as_u64().unwrap_or(5) as usize;

    if query.is_empty() {
        return r#"{"error":"缺少query参数"}"#.into();
    }

    let query_vector = match embedding::embed_single_with_model(query, model) {
        Ok(v) => v,
        Err(e) => return format!(r#"{{"error":"向量化失败: {}"}}"#, e),
    };

    let conn = conn.lock().unwrap();
    let results = search::hybrid_search(&conn, query, &query_vector, top_k);

    serde_json::json!({
        "chunks": results,
        "query": query,
        "model": model,
        "count": results.len()
    }).to_string()
}

fn handle_recall(body: &str, conn: &Arc<Mutex<Connection>>) -> String {
    let req: serde_json::Value = match serde_json::from_str(body) {
        Ok(v) => v,
        Err(_) => return r#"{"error":"无效的JSON"}"#.into(),
    };

    let signal_type = req["signal_type"].as_str().unwrap_or("unknown");
    let symbol = req["symbol"].as_str().unwrap_or("");
    let name = req["name"].as_str().unwrap_or("");
    let top_k = req["top_k"].as_u64().unwrap_or(5) as usize;

    let query = match signal_type {
        "price_surge" => format!("{} 涨幅 原因 分析 利好", name),
        "price_drop" => format!("{} 下跌 风险 利空 跟踪", name),
        "volume_anomaly" => format!("{} 成交量 异动 资金", name),
        _ => format!("{} {} 分析", name, symbol),
    };

    let query_vector = match embedding::embed_single(&query) {
        Ok(v) => v,
        Err(e) => return format!(r#"{{"error":"向量化失败: {}"}}"#, e),
    };

    let conn = conn.lock().unwrap();
    let results = search::vector_search(&conn, &query_vector, top_k);

    serde_json::json!({
        "chunks": results,
        "recall_reason": signal_type,
        "symbol": symbol,
        "count": results.len()
    }).to_string()
}

fn handle_list_documents(conn: &Arc<Mutex<Connection>>) -> String {
    let conn = conn.lock().unwrap();

    let mut stmt = match conn.prepare(
        "SELECT doc_id, title, doc_type, file_path, created_at
         FROM documents WHERE status='active' ORDER BY created_at DESC"
    ) {
        Ok(s) => s,
        Err(e) => return format!(r#"{{"error":"{}"}}"#, e),
    };

    let docs: Vec<serde_json::Value> = stmt.query_map([], |row| {
        Ok(serde_json::json!({
            "doc_id": row.get::<_, String>(0)?,
            "title": row.get::<_, String>(1)?,
            "doc_type": row.get::<_, String>(2)?,
            "file_path": row.get::<_, String>(3)?,
            "created_at": row.get::<_, String>(4)?,
        }))
    }).ok()
    .into_iter()
    .flatten()
    .filter_map(|r| r.ok())
    .collect();

    serde_json::json!({ "documents": docs, "total": docs.len() }).to_string()
}

fn handle_stats(conn: &Arc<Mutex<Connection>>) -> String {
    let conn = conn.lock().unwrap();

    let doc_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM documents WHERE status='active'", [], |r| r.get(0)
    ).unwrap_or(0);

    let chunk_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM chunks", [], |r| r.get(0)
    ).unwrap_or(0);

    let vector_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM chunks WHERE vector IS NOT NULL", [], |r| r.get(0)
    ).unwrap_or(0);

    serde_json::json!({
        "document_count": doc_count,
        "chunk_count": chunk_count,
        "vector_count": vector_count,
        "database": "data/knowledge.db"
    }).to_string()
}
