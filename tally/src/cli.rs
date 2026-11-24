use clap::{Args, Parser, Subcommand};
use cli_blocks::{GlobalOpts, PathArgs};
use serde::Deserialize;

#[derive(Debug, Parser)]
#[command(name = "tally", version, about = "Count files and lines in a folder.")]
pub struct Cli {
    #[command(flatten)]
    pub global: GlobalOpts,
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    #[command(flatten)]
    Report(Report),
    /// Read one JSON report request from stdin. Outputs a Blocks presentation by default.
    Request {
        /// Print the JSON request schema and exit.
        #[arg(long)]
        schema: bool,
    },
    /// Print a completion script for your shell.
    Completions { shell: clap_complete::Shell },
}

#[derive(Debug, Subcommand, Deserialize)]
#[serde(tag = "command", rename_all = "lowercase", deny_unknown_fields)]
pub enum Report {
    /// Count files and lines, grouped by file extension.
    Count(PathArgs),
    /// Show the files with the most lines.
    Largest(LargestArgs),
}

#[derive(Debug, Args, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LargestArgs {
    #[command(flatten)]
    #[serde(flatten)]
    pub target: PathArgs,
    /// How many files to show.
    #[arg(short = 'n', long, default_value_t = default_top())]
    #[serde(default = "default_top")]
    pub top: usize,
}

fn default_top() -> usize {
    5
}
