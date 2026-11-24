// Integration tests. Files in tests/ are compiled as separate programs.
// They run the REAL `tally` binary, exactly as a user or a script would.
// Run them with: cargo test

use assert_cmd::Command;
use predicates::str::contains;
use std::fs;
use tempfile::TempDir;

// Make a small throwaway folder with known contents.
// `TempDir` deletes the folder when it goes out of scope. (This is called "Drop".)
fn sample_dir() -> TempDir {
    let dir = tempfile::tempdir().unwrap();
    // `.unwrap()` means "crash if this fails". It is fine in tests, not in real code.
    fs::write(dir.path().join("a.rs"), "fn main() {}\n// two\n").unwrap(); // 2 lines
    fs::write(dir.path().join("b.md"), "# title\n").unwrap(); // 1 line
    fs::create_dir(dir.path().join("sub")).unwrap();
    fs::write(dir.path().join("sub/c.rs"), "1\n2\n3\n").unwrap(); // 3 lines
    fs::write(dir.path().join(".hidden.rs"), "x\n").unwrap(); // must be skipped
    dir
}

fn tally() -> Command {
    Command::new(env!("CARGO_BIN_EXE_tally"))
}

#[test]
fn json_request_and_shell_command_produce_the_same_blocks() {
    let dir = sample_dir();
    for (request, args) in [
        (r#"{"command":"count"}"#, vec!["count"]),
        (r#"{"command":"largest","top":1}"#, vec!["largest", "-n", "1"]),
    ] {
        let expected = tally().current_dir(dir.path()).args(args).args(["--format", "blocks"])
            .assert().success().get_output().stdout.clone();
        let doc: serde_json::Value = serde_json::from_slice(&expected).unwrap();
        assert_eq!(doc["version"], 1);
        assert_eq!(doc["blocks"][1]["type"], "table");
        tally().current_dir(dir.path()).arg("request").write_stdin(request)
            .assert().success().stdout(expected);
    }
}

#[test]
fn rejects_invalid_requests_before_reading_files() {
    for input in [
        r#"{"command":"unknown"}"#,
        r#"{"command":"count","top":2}"#,
        r#"{"command":"largest","unknown":true}"#,
        r#"{"command":"largest","top":-1}"#,
    ] {
        tally().args(["request", "--verbose"]).write_stdin(input)
            .assert().failure().stdout("").stderr(contains("invalid Tally request"));
    }
}

#[test]
fn count_groups_by_extension() {
    let dir = sample_dir();
    tally()
        .arg("count")
        .arg(dir.path())
        .assert()
        .success()
        .stdout(contains("rs"))
        .stdout(contains("5 lines")) // 2 + 3, hidden file not counted
        .stdout(contains("TOTAL"));
}

#[test]
fn count_json_is_valid_and_correct() {
    let dir = sample_dir();
    let output = tally()
        .arg("count")
        .arg(dir.path())
        .args(["--format", "json"])
        .output()
        .unwrap();

    assert!(output.status.success());
    let json: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(json["rs"]["lines"], 5);
    assert_eq!(json["rs"]["files"], 2);
    assert_eq!(json["md"]["files"], 1);
}

#[test]
fn largest_shows_biggest_first() {
    let dir = sample_dir();
    tally()
        .arg("largest")
        .arg(dir.path())
        .args(["-n", "1"])
        .assert()
        .success()
        .stdout(contains("c.rs"));
}

#[test]
fn missing_folder_fails_with_clear_message() {
    tally()
        .args(["count", "/no/such/folder"])
        .assert()
        .failure()
        .stderr(contains("cannot read folder"));
}

#[test]
fn bad_format_is_rejected_by_clap() {
    tally()
        .args(["count", "--format", "xml"])
        .assert()
        .failure()
        .stderr(contains("invalid value"));
}
