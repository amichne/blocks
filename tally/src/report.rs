use crate::scan::Scan;
use anyhow::Result;
use cli_blocks::{Block, Format, Presentation};
use serde::Serialize;
use std::io::{self, Write};

fn json(value: &impl Serialize) -> Result<()> {
    let mut out = io::stdout().lock();
    serde_json::to_writer_pretty(&mut out, value)?;
    writeln!(out)?;
    Ok(())
}

fn table(title: &str, columns: &[&str], rows: Vec<Vec<String>>) -> Result<()> {
    json(&Presentation::new(vec![
        Block::Heading { text: title.to_owned() },
        Block::Table {
            columns: columns.iter().map(|s| s.to_string()).collect(),
            rows,
        },
    ]))
}

// File names can contain line breaks and terminal controls. Preserve their
// identity in raw JSON and escape those characters in terminal presentations.
fn cell(value: &str) -> String {
    if value.is_empty() {
        return "\"\"".to_owned();
    }
    let mut display = String::new();
    for ch in value.chars() {
        if ch.is_control() || matches!(ch, '\u{2028}' | '\u{2029}') {
            display.extend(ch.escape_default());
        } else {
            display.push(ch);
        }
    }
    display
}

pub fn counts(scan: &Scan, format: Format) -> Result<()> {
    let total: usize = scan.by_ext.values().map(|stats| stats.lines).sum();
    match format {
        Format::Json => json(&scan.by_ext),
        Format::Text => {
            let mut out = io::stdout().lock();
            for (ext, stats) in &scan.by_ext {
                writeln!(out, "{:<10} {:>6} files {:>8} lines", cell(ext), stats.files, stats.lines)?;
            }
            writeln!(out, "{:<10} {:>6} files {:>8} lines", "TOTAL", scan.files.len(), total)?;
            Ok(())
        }
        Format::Blocks => {
            let mut rows: Vec<_> = scan.by_ext.iter().map(|(ext, stats)| {
                vec![cell(ext), stats.files.to_string(), stats.lines.to_string()]
            }).collect();
            rows.push(vec!["TOTAL".into(), scan.files.len().to_string(), total.to_string()]);
            table("Files by extension", &["Extension", "Files", "Lines"], rows)
        }
    }
}

pub fn largest(mut scan: Scan, top: usize, format: Format) -> Result<()> {
    scan.files.sort_by(|a, b| b.lines.cmp(&a.lines).then_with(|| a.path.cmp(&b.path)));
    scan.files.truncate(top);
    match format {
        Format::Json => json(&scan.files),
        Format::Text => {
            let mut out = io::stdout().lock();
            for file in &scan.files {
                writeln!(out, "{:>8}  {}", file.lines, cell(&file.path.to_string_lossy()))?;
            }
            Ok(())
        }
        Format::Blocks => {
            let rows = scan.files.iter().map(|f| vec![f.lines.to_string(), cell(&f.path.to_string_lossy())]).collect();
            table("Largest files by line count", &["Lines", "Path"], rows)
        }
    }
}
