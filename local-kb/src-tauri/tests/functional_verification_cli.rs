use std::{path::PathBuf, process::Command};

#[test]
fn functional_verification_covers_local_lifecycle() {
    let executable = env!("CARGO_BIN_EXE_functional_verification");
    let work_dir =
        std::env::temp_dir().join(format!("local-kb-functional-test-{}", std::process::id()));
    let output = Command::new(executable)
        .arg("--work-dir")
        .arg(&work_dir)
        .output()
        .expect("functional verification should launch");

    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("stdout should be JSON");
    assert_eq!(value["status"], "PASS");
    assert!(value["case_results"].as_array().unwrap().len() >= 8);
    assert!(
        value["case_results"]
            .as_array()
            .unwrap()
            .iter()
            .all(|case| case["status"] == "PASS")
    );
    assert!(PathBuf::from(value["database_path"].as_str().unwrap()).exists());

    std::fs::remove_dir_all(work_dir).ok();
}
