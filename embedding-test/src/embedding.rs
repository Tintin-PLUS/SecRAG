use serde_json::Value;

const EMBED_SERVER: &str = "http://127.0.0.1:8902";
const DEFAULT_MODEL: &str = "bge-small";

pub fn is_server_alive() -> bool {
    ureq::get(&format!("{}/health", EMBED_SERVER))
        .timeout(std::time::Duration::from_secs(2))
        .call()
        .is_ok()
}

pub fn wait_for_server() -> bool {
    for _ in 0..60 {
        if is_server_alive() {
            return true;
        }
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
    false
}

pub fn start_embed_server() -> Option<std::process::Child> {
    if is_server_alive() {
        println!("[OK] Embedding服务已在运行");
        return None;
    }

    println!("[..] 启动Embedding常驻服务...");
    let child = std::process::Command::new("python3")
        .arg("scripts/embed_server.py")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .ok()?;

    if wait_for_server() {
        println!("[OK] Embedding服务就绪");
        Some(child)
    } else {
        println!("[ERROR] Embedding服务启动失败");
        None
    }
}

pub fn embed_with_model(texts: &[String], model: &str) -> Result<Vec<Vec<f32>>, String> {
    if texts.is_empty() {
        return Ok(Vec::new());
    }

    let input = serde_json::json!({ "texts": texts, "model": model }).to_string();

    let resp = ureq::post(&format!("{}/embed", EMBED_SERVER))
        .timeout(std::time::Duration::from_secs(120))
        .set("Content-Type", "application/json")
        .send_string(&input)
        .map_err(|e| format!("Embedding服务请求失败: {}", e))?;

    let body = resp.into_string().map_err(|e| format!("读取响应失败: {}", e))?;

    let result: Value = serde_json::from_str(&body)
        .map_err(|e| format!("解析JSON失败: {} | body: {}", e, &body[..200.min(body.len())]))?;

    if let Some(err) = result.get("error") {
        return Err(format!("Embedding服务报错: {}", err));
    }

    let vectors = result["vectors"]
        .as_array()
        .ok_or("返回格式错误: 缺少vectors字段")?
        .iter()
        .map(|v| {
            v.as_array().unwrap()
                .iter()
                .map(|n| n.as_f64().unwrap_or(0.0) as f32)
                .collect()
        })
        .collect();

    Ok(vectors)
}

pub fn embed_single(text: &str) -> Result<Vec<f32>, String> {
    let vectors = embed_with_model(&[text.to_string()], DEFAULT_MODEL)?;
    vectors.into_iter().next().ok_or("向量列表为空".into())
}

pub fn embed_single_with_model(text: &str, model: &str) -> Result<Vec<f32>, String> {
    let vectors = embed_with_model(&[text.to_string()], model)?;
    vectors.into_iter().next().ok_or("向量列表为空".into())
}

pub fn available_models() -> Vec<(&'static str, &'static str)> {
    vec![
        ("bge-small", "BAAI/bge-small-zh-v1.5 (~100MB, 512维)"),
        ("m3e-base",  "moka-ai/m3e-base (~400MB, 768维)"),
        ("bge-m3",    "BAAI/bge-m3 (~2.3GB, 1024维)"),
    ]
}
