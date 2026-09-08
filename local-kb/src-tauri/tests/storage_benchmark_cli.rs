use serde_json::Value;
use std::process::Command;

#[test]
fn storage_benchmark_emits_one_json_sample_per_repetition() {
    let executable = std::env::var("CARGO_BIN_EXE_storage_benchmark")
        .expect("Cargo provides the storage_benchmark binary path");
    let output = Command::new(executable)
        .args(["--chunks", "10", "--dimension", "4", "--repetitions", "2"])
        .output()
        .expect("run storage benchmark CLI");

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: Value = serde_json::from_slice(&output.stdout).expect("valid JSON output");
    assert_eq!(value["chunk_count"], 10);
    assert_eq!(value["dimension"], 4);
    assert_eq!(value["samples"].as_array().unwrap().len(), 2);
    assert!(value["samples"][0]["search_top5_ms"].as_f64().unwrap() >= 0.0);
}
