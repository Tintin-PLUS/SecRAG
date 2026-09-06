use std::path::Path;
use std::fs;

pub struct ParsedDoc {
    pub title: String,
    pub content: String,
    pub doc_type: String,
    pub file_path: String,
}

pub fn parse_file(path: &str) -> Result<ParsedDoc, String> {
    let path_obj = Path::new(path);

    if !path_obj.exists() {
        return Err(format!("文件不存在: {}", path));
    }

    let ext = path_obj.extension()
        .and_then(|e| e.to_str())
        .unwrap_or("");

    let content = match ext.to_lowercase().as_str() {
        "pdf" => parse_pdf(path)?,
        "md" | "txt" => parse_text(path)?,
        "docx" => return Err("Word文档暂不支持，请转为PDF或MD".into()),
        _ => return Err(format!("不支持的格式: .{}", ext)),
    };

    let title = path_obj
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("未知")
        .to_string();

    let doc_type = match ext.to_lowercase().as_str() {
        "pdf" => "research_report",
        "md" => "markdown",
        _ => "text",
    }.to_string();

    Ok(ParsedDoc { title, content, doc_type, file_path: path.to_string() })
}

fn parse_pdf(path: &str) -> Result<String, String> {
    let bytes = fs::read(path).map_err(|e| format!("读取PDF失败: {}", e))?;
    let text = pdf_extract::extract_text_from_mem(&bytes)
        .map_err(|e| format!("解析PDF失败: {}", e))?;
    Ok(text.trim().to_string())
}

fn parse_text(path: &str) -> Result<String, String> {
    fs::read_to_string(path).map_err(|e| format!("读取文件失败: {}", e))
}
