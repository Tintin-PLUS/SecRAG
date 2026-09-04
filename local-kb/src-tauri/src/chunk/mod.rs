pub trait Chunker: Send + Sync {
    fn chunk(&self, text: &str) -> Vec<String>;
}

#[derive(Debug, Clone)]
pub struct FixedSizeChunker {
    pub chunk_size: usize,
    pub chunk_overlap: usize,
}

impl Chunker for FixedSizeChunker {
    fn chunk(&self, text: &str) -> Vec<String> {
        if text.is_empty() || self.chunk_size == 0 {
            return vec![];
        }
        let chars: Vec<char> = text.chars().collect();
        let mut chunks = Vec::new();
        let mut start = 0;
        while start < chars.len() {
            let end = (start + self.chunk_size).min(chars.len());
            let value: String = chars[start..end]
                .iter()
                .collect::<String>()
                .trim()
                .to_string();
            if !value.is_empty() {
                chunks.push(value);
            }
            if end == chars.len() {
                break;
            }
            let advance = self.chunk_size.saturating_sub(self.chunk_overlap).max(1);
            start += advance;
        }
        chunks
    }
}
