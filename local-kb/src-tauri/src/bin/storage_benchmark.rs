use local_kb_lib::benchmark;
use serde_json::json;
use std::{env, process};

fn value_after(args: &[String], name: &str, default: usize) -> Result<usize, String> {
    let Some(index) = args.iter().position(|arg| arg == name) else {
        return Ok(default);
    };
    let raw = args
        .get(index + 1)
        .ok_or_else(|| format!("missing value after {name}"))?;
    raw.parse::<usize>()
        .map_err(|_| format!("invalid positive integer for {name}: {raw}"))
        .and_then(|value| {
            (value > 0)
                .then_some(value)
                .ok_or_else(|| format!("{name} must be greater than zero"))
        })
}

fn main() {
    if let Err(message) = run() {
        eprintln!("{message}");
        process::exit(2);
    }
}

fn run() -> Result<(), String> {
    let args: Vec<String> = env::args().skip(1).collect();
    let chunk_count = value_after(&args, "--chunks", 1_000)?;
    let dimension = value_after(&args, "--dimension", 512)?;
    let repetitions = value_after(&args, "--repetitions", 10)?;
    let mut samples = Vec::with_capacity(repetitions);

    for repetition in 1..=repetitions {
        let result = benchmark::run(chunk_count, dimension).map_err(|error| error.to_string())?;
        samples.push(json!({
            "sample_id": repetition,
            "insert_ms": result.insert_ms,
            "search_top5_ms": result.search_top5_ms,
            "search_top10_ms": result.search_top10_ms,
            "sqlite_read_ms": result.sqlite_read_ms
        }));
    }

    println!(
        "{}",
        json!({
            "schema_version": "1.0",
            "chunk_count": chunk_count.clamp(1, 10_000),
            "dimension": dimension.clamp(1, 4_096),
            "repetitions": repetitions,
            "samples": samples
        })
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::value_after;

    #[test]
    fn parses_named_positive_integer() {
        let args = vec!["--chunks".to_string(), "25".to_string()];
        assert_eq!(value_after(&args, "--chunks", 10).unwrap(), 25);
    }

    #[test]
    fn rejects_zero() {
        let args = vec!["--chunks".to_string(), "0".to_string()];
        assert!(value_after(&args, "--chunks", 10).is_err());
    }
}
