#[allow(dead_code)]
pub struct Chunk {
    pub position: usize,
    pub content: String,
    pub section: String,
}

pub fn chunk_by_structure(text: &str, max_size: usize, min_size: usize) -> Vec<Chunk> {
    let sections = split_by_headers(text);
    let mut chunks = Vec::new();
    let mut position = 0;

    for (header, body) in sections {
        let full_text = if header.is_empty() {
            body.clone()
        } else {
            format!("{}\n{}", header, body)
        };

        let trimmed = full_text.trim();
        if trimmed.is_empty() {
            continue;
        }

        if trimmed.chars().count() <= max_size {
            if trimmed.chars().count() >= min_size || chunks.is_empty() {
                chunks.push(Chunk {
                    position,
                    content: trimmed.to_string(),
                    section: header.trim_start_matches('#').trim().to_string(),
                });
                position += 1;
            } else if let Some(last) = chunks.last_mut() {
                last.content.push_str("\n\n");
                last.content.push_str(trimmed);
            }
        } else {
            for sc in split_long_section(&full_text, max_size, min_size) {
                let sc_trimmed = sc.trim();
                if sc_trimmed.is_empty() {
                    continue;
                }
                if sc_trimmed.chars().count() < min_size {
                    if let Some(last) = chunks.last_mut() {
                        last.content.push_str("\n\n");
                        last.content.push_str(sc_trimmed);
                    } else {
                        chunks.push(Chunk {
                            position,
                            content: sc_trimmed.to_string(),
                            section: header.trim_start_matches('#').trim().to_string(),
                        });
                        position += 1;
                    }
                } else {
                    chunks.push(Chunk {
                        position,
                        content: sc_trimmed.to_string(),
                        section: header.trim_start_matches('#').trim().to_string(),
                    });
                    position += 1;
                }
            }
        }
    }

    chunks
}

fn split_by_headers(text: &str) -> Vec<(String, String)> {
    let mut sections = Vec::new();
    let mut current_header = String::new();
    let mut current_body = String::new();

    for line in text.lines() {
        let trimmed = line.trim_start();
        if trimmed.starts_with('#') {
            if !current_body.trim().is_empty() || !current_header.is_empty() {
                sections.push((current_header.clone(), current_body.clone()));
            }
            current_header = trimmed.to_string();
            current_body.clear();
        } else {
            current_body.push_str(line);
            current_body.push('\n');
        }
    }

    if !current_body.trim().is_empty() || !current_header.is_empty() {
        sections.push((current_header, current_body));
    }

    sections
}

fn split_long_section(text: &str, max_size: usize, min_size: usize) -> Vec<String> {
    let paragraphs: Vec<&str> = text.split("\n\n").filter(|p| !p.trim().is_empty()).collect();

    if paragraphs.is_empty() {
        return vec![text.to_string()];
    }

    if paragraphs.len() == 1 {
        return split_by_char_count(text, max_size);
    }

    let mut chunks = Vec::new();
    let mut buffer = String::new();

    for para in paragraphs {
        if buffer.chars().count() + para.chars().count() > max_size && !buffer.is_empty() {
            chunks.push(buffer.trim().to_string());
            buffer.clear();
        }
        buffer.push_str(para);
        buffer.push_str("\n\n");
    }

    if !buffer.trim().is_empty() {
        let trimmed = buffer.trim();
        if trimmed.chars().count() < min_size {
            if let Some(last) = chunks.last_mut() {
                last.push_str("\n\n");
                last.push_str(trimmed);
            } else {
                chunks.push(trimmed.to_string());
            }
        } else {
            chunks.push(trimmed.to_string());
        }
    }

    chunks
}

fn split_by_char_count(text: &str, max_size: usize) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    let mut chunks = Vec::new();
    let mut start = 0;

    while start < chars.len() {
        let end = (start + max_size).min(chars.len());
        let mut split_at = end;

        if end < chars.len() {
            for i in (start + max_size / 2..end).rev() {
                if chars[i] == '。' || chars[i] == '\n' || chars[i] == '；' {
                    split_at = i + 1;
                    break;
                }
            }
        }

        let chunk: String = chars[start..split_at].iter().collect();
        let trimmed = chunk.trim();
        if !trimmed.is_empty() {
            chunks.push(trimmed.to_string());
        }

        if split_at >= chars.len() {
            break;
        }
        start = split_at;
    }

    chunks
}

#[allow(dead_code)]
pub fn chunk_by_paragraph(text: &str, max_size: usize) -> Vec<Chunk> {
    chunk_by_structure(text, max_size, 50)
}
