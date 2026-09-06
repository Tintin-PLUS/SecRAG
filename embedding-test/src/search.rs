use rusqlite::Connection;
use serde::{Serialize, Deserialize};
use std::collections::HashMap;
use jieba_rs::Jieba;

#[derive(Serialize, Deserialize, Clone)]
pub struct SearchResult {
    pub doc_id: String,
    pub position: usize,
    pub content: String,
    pub score: f32,
    pub title: String,
    pub source: String,
}

static JIEBA: std::sync::OnceLock<Jieba> = std::sync::OnceLock::new();

fn get_jieba() -> &'static Jieba {
    JIEBA.get_or_init(Jieba::new)
}

fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let dot: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm_a == 0.0 || norm_b == 0.0 { return 0.0; }
    dot / (norm_a * norm_b)
}

fn segment_query(query: &str) -> Vec<String> {
    let words = get_jieba().cut(query, true);
    let stop_words = ["的", "了", "是", "在", "有", "和", "与", "及", "或",
                      "什么", "怎么", "如何", "多少", "请问", "请",
                      "方面", "情况", "一个", "这个", "那个"];
    words.iter()
        .filter(|w| w.chars().count() > 1 && !stop_words.contains(w))
        .map(|w| w.to_string())
        .collect()
}

fn load_all_chunks(conn: &Connection) -> Vec<(String, usize, String, String, String)> {
    let mut stmt = match conn.prepare(
        "SELECT c.doc_id, c.position, c.content, d.title, d.file_path
         FROM chunks c
         JOIN documents d ON c.doc_id = d.doc_id
         WHERE d.status = 'active'"
    ) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };

    stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, i64>(1)? as usize,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
        ))
    }).ok()
    .into_iter()
    .flatten()
    .filter_map(|r| r.ok())
    .collect()
}

fn compute_idf(term: &str, chunks: &[(String, usize, String, String, String)]) -> f32 {
    let n = chunks.len() as f32;
    let df = chunks.iter().filter(|(_, _, content, _, _)| content.contains(term)).count() as f32;
    ((n - df + 0.5) / (df + 0.5) + 1.0).ln()
}

fn bm25_score(
    query_terms: &[String],
    chunk_content: &str,
    chunk_length: usize,
    avg_length: f32,
    idf_map: &HashMap<String, f32>,
) -> f32 {
    const K1: f32 = 1.2;
    const B: f32 = 0.75;

    let norm_length = if avg_length > 0.0 {
        chunk_length as f32 / avg_length
    } else {
        1.0
    };

    let mut score = 0.0;
    for term in query_terms {
        let tf = chunk_content.matches(term).count() as f32;
        if tf == 0.0 { continue; }

        let idf = idf_map.get(term).copied().unwrap_or(0.0);
        let tf_component = (tf * (K1 + 1.0)) / (tf + K1 * (1.0 - B + B * norm_length));
        score += idf * tf_component;
    }
    score
}

fn query_specificity(query_terms: &[String], idf_map: &HashMap<String, f32>) -> f32 {
    if query_terms.is_empty() {
        return 0.5;
    }
    let avg_idf = query_terms.iter()
        .map(|t| idf_map.get(t).copied().unwrap_or(0.0))
        .sum::<f32>() / query_terms.len() as f32;

    (avg_idf / 3.0).min(1.0)
}

pub fn vector_search(
    conn: &Connection,
    query_vector: &[f32],
    top_k: usize,
) -> Vec<SearchResult> {
    let mut stmt = match conn.prepare(
        "SELECT c.doc_id, c.position, c.content, d.title, d.file_path, c.vector
         FROM chunks c
         JOIN documents d ON c.doc_id = d.doc_id
         WHERE d.status = 'active' AND c.vector IS NOT NULL"
    ) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };

    let mut results: Vec<SearchResult> = match stmt.query_map([], |row| {
        let vector_json: String = row.get(5)?;
        let vector: Vec<f32> = serde_json::from_str(&vector_json).unwrap_or_default();
        let score = cosine_similarity(query_vector, &vector);

        Ok(SearchResult {
            doc_id: row.get(0)?,
            position: row.get::<_, i64>(1)? as usize,
            content: row.get(2)?,
            title: row.get(3)?,
            source: row.get(4)?,
            score,
        })
    }) {
        Ok(rows) => rows.filter_map(|r| r.ok()).collect(),
        Err(_) => return Vec::new(),
    };

    results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
    results.truncate(top_k);
    results
}

pub fn bm25_search(
    conn: &Connection,
    query: &str,
    top_k: usize,
) -> Vec<SearchResult> {
    let query_terms = segment_query(query);
    if query_terms.is_empty() {
        return Vec::new();
    }

    let chunks = load_all_chunks(conn);
    if chunks.is_empty() {
        return Vec::new();
    }

    let idf_map: HashMap<String, f32> = query_terms.iter()
        .map(|t| (t.clone(), compute_idf(t, &chunks)))
        .collect();

    let avg_length: f32 = chunks.iter()
        .map(|(_, _, content, _, _)| content.chars().count())
        .sum::<usize>() as f32 / chunks.len() as f32;

    let mut results: Vec<SearchResult> = chunks.iter()
        .map(|(doc_id, position, content, title, source)| {
            let score = bm25_score(
                &query_terms,
                content,
                content.chars().count(),
                avg_length,
                &idf_map,
            );
            SearchResult {
                doc_id: doc_id.clone(),
                position: *position,
                content: content.clone(),
                score,
                title: title.clone(),
                source: source.clone(),
            }
        })
        .filter(|r| r.score > 0.0)
        .collect();

    results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
    results.truncate(top_k);
    results
}

pub fn hybrid_search(
    conn: &Connection,
    query: &str,
    query_vector: &[f32],
    top_k: usize,
) -> Vec<SearchResult> {
    const RRF_K: f32 = 60.0;

    let query_terms = segment_query(query);
    let chunks = load_all_chunks(conn);

    let idf_map: HashMap<String, f32> = query_terms.iter()
        .map(|t| (t.clone(), compute_idf(t, &chunks)))
        .collect();
    let specificity = query_specificity(&query_terms, &idf_map);

    let vector_weight = 1.0 - 0.6 * specificity;
    let bm25_weight = 0.4 + 0.8 * specificity;

    let vec_results = vector_search(conn, query_vector, top_k * 3);
    let bm25_results = bm25_search(conn, query, top_k * 3);

    let mut fused_map: HashMap<String, (SearchResult, f32)> = HashMap::new();

    for (rank, r) in vec_results.iter().enumerate() {
        let key = format!("{}_{}", r.doc_id, r.position);
        let rrf_score = vector_weight / (RRF_K + (rank + 1) as f32);
        let entry = fused_map.entry(key).or_insert((r.clone(), 0.0));
        entry.1 += rrf_score;
    }

    for (rank, r) in bm25_results.iter().enumerate() {
        let key = format!("{}_{}", r.doc_id, r.position);
        let rrf_score = bm25_weight / (RRF_K + (rank + 1) as f32);
        let entry = fused_map.entry(key).or_insert((r.clone(), 0.0));
        entry.1 += rrf_score;
    }

    let mut results: Vec<SearchResult> = fused_map
        .into_iter()
        .map(|(_, (r, score))| SearchResult { score, ..r })
        .collect();

    results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
    results.truncate(top_k);
    results
}

pub fn analyze_query(query: &str, conn: &Connection) -> serde_json::Value {
    let terms = segment_query(query);
    let chunks = load_all_chunks(conn);

    let term_analysis: Vec<serde_json::Value> = terms.iter().map(|t| {
        let df = chunks.iter().filter(|(_, _, content, _, _)| content.contains(t)).count();
        let idf = compute_idf(t, &chunks);
        serde_json::json!({
            "term": t,
            "doc_freq": df,
            "idf": format!("{:.3}", idf),
        })
    }).collect();

    let idf_map: HashMap<String, f32> = terms.iter()
        .map(|t| (t.clone(), compute_idf(t, &chunks)))
        .collect();
    let specificity = query_specificity(&terms, &idf_map);

    serde_json::json!({
        "query": query,
        "terms": term_analysis,
        "specificity": format!("{:.3}", specificity),
        "vector_weight": format!("{:.3}", 1.0 - 0.6 * specificity),
        "bm25_weight": format!("{:.3}", 0.4 + 0.8 * specificity),
    })
}
