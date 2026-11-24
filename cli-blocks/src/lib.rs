//! Shared clap arguments and serializable Blocks v1 presentations.
use clap::{Args, ValueEnum};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Copy, ValueEnum)]
pub enum Format {
    Text,
    Json,
    Blocks,
}

#[derive(Debug, Args)]
pub struct GlobalOpts {
    /// Output format (text for shell commands, blocks for JSON requests).
    #[arg(long, value_enum, global = true)]
    pub format: Option<Format>,
    /// Report progress on stderr.
    #[arg(short, long, global = true)]
    pub verbose: bool,
}

#[derive(Debug, Args, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PathArgs {
    /// Folder to scan.
    #[arg(default_value = ".")]
    #[serde(default = "current_folder")]
    pub path: PathBuf,
}

fn current_folder() -> PathBuf {
    PathBuf::from(".")
}

#[derive(Debug, Serialize)]
pub struct Presentation {
    version: u8,
    pub blocks: Vec<Block>,
}

impl Presentation {
    pub fn new(blocks: Vec<Block>) -> Self {
        Self { version: 1, blocks }
    }
}

#[derive(Debug, Serialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Block {
    Heading { text: String },
    Text { text: String },
    List { items: Vec<String> },
    Section { title: String, blocks: Vec<Block> },
    Table { columns: Vec<String>, rows: Vec<Vec<String>> },
    Choice { id: String, label: String, options: Vec<ChoiceOption> },
    Input { id: String, label: String },
    Editor { id: String, label: String, initial: String },
}

#[derive(Debug, Serialize)]
pub struct ChoiceOption {
    pub value: String,
    pub label: String,
}
