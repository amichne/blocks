// scan.rs does the real work: it walks a folder and collects numbers.
// It prints nothing to stdout. Keeping work and output separate makes both easy to test.

use anyhow::{Context, Result};
use serde::Serialize;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

// CONCEPT: struct
// A struct groups related values under one name.
// `Serialize` (from serde) lets us turn it into JSON with one call.
#[derive(Debug, Serialize)]
pub struct FileInfo {
    pub path: PathBuf,
    pub lines: usize,
}

// `Default` gives a "zero" value: files = 0, lines = 0.
#[derive(Debug, Default, Serialize)]
pub struct ExtStats {
    pub files: usize,
    pub lines: usize,
}

#[derive(Debug, Default)]
pub struct Scan {
    // `Vec<T>` is a growable list of T.
    pub files: Vec<FileInfo>,
    // `BTreeMap` is a map that keeps keys sorted. Sorted output = stable test results.
    pub by_ext: BTreeMap<String, ExtStats>,
}

// CONCEPT: &Path vs PathBuf (borrowed vs owned)
// `PathBuf` OWNS its text, like `String`.
// `&Path` only BORROWS a path that someone else owns, like `&str`.
// Functions that only read a value should take the borrowed form.
pub fn scan(root: &Path, verbose: bool) -> Result<Scan> {
    // `let mut` makes the variable changeable. Variables are read-only by default.
    let mut result = Scan::default();

    // `&mut result` lends the value AND lets `walk` change it.
    // Rule: only one `&mut` borrow can exist at a time. This prevents data races.
    walk(root, verbose, &mut result)?;
    Ok(result)
}

// This function is not `pub`, so only code in this file can call it.
fn walk(dir: &Path, verbose: bool, out: &mut Scan) -> Result<()> {
    // `.with_context(...)` adds a human message to the error if `read_dir` fails.
    // The `|| ...` part is a closure: a small unnamed function that runs only on error.
    let entries = fs::read_dir(dir)
        .with_context(|| format!("cannot read folder {}", dir.display()))?;

    for entry in entries {
        // Each entry can also fail (for example, permission denied), so `?` again.
        let entry = entry?;
        let path = entry.path();

        if is_hidden(&path) {
            continue; // skip .git, .cache, and so on
        }

        let kind = entry.file_type()?;
        if kind.is_dir() {
            // A function can call itself. This is recursion.
            walk(&path, verbose, out)?;
        } else if kind.is_file() {
            // CONCEPT: Option and let-else
            // `count_lines` returns `Option<usize>`: `Some(n)` or `None`.
            // `let Some(x) = ... else { ... }` means: "if it is None, do the else part."
            let Some(lines) = count_lines(&path) else {
                continue; // not a text file, skip it
            };

            if verbose {
                // `eprintln!` writes to stderr, so it does not break JSON on stdout.
                eprintln!("read {:?}", path);
            }

            // Get the extension as owned text. A chain of small steps:
            //   extension()        -> Option<&OsStr>   (maybe no extension)
            //   .and_then(to_str)  -> Option<&str>     (maybe not valid UTF-8)
            //   .unwrap_or(...)    -> &str             (use a fallback if None)
            //   .to_string()       -> String           (owned copy, so the borrow of `path` ends)
            let ext = path
                .extension()
                .and_then(|e| e.to_str())
                .unwrap_or("(none)")
                .to_string();

            // `entry(...).or_default()` finds the key or inserts a zero `ExtStats`.
            let stats = out.by_ext.entry(ext).or_default();
            stats.files += 1;
            stats.lines += lines;

            // CONCEPT: move
            // `path` MOVES into the new FileInfo. After this line, we cannot use `path` here.
            // That is fine, because we do not need it again. The compiler checks this for you.
            out.files.push(FileInfo { path, lines });
        }
    }
    Ok(())
}

fn is_hidden(path: &Path) -> bool {
    path.file_name()
        .and_then(|n| n.to_str())
        .is_some_and(|n| n.starts_with('.'))
}

fn count_lines(path: &Path) -> Option<usize> {
    // `read_to_string` fails on binary files. `.ok()` turns that error into `None`.
    // `.map(...)` changes the value inside `Some`, and leaves `None` alone.
    fs::read_to_string(path).ok().map(|text| text.lines().count())
}

// CONCEPT: unit tests
// Code inside `#[cfg(test)]` is compiled only for `cargo test`.
// Unit tests live next to the code and can call private functions.
#[cfg(test)]
mod tests {
    use super::*; // bring everything from the parent module into scope

    #[test]
    fn hidden_files_start_with_a_dot() {
        assert!(is_hidden(Path::new("/x/.git")));
        assert!(!is_hidden(Path::new("/x/src")));
    }
}
