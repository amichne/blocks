mod cli;
mod report;
mod scan;

use anyhow::{Context, Result};
use clap::{CommandFactory, Parser};
use cli::{Cli, Command, Report};
use cli_blocks::Format;
use std::io;

fn main() -> Result<()> {
    let Cli { global, command } = Cli::parse();
    let (report, default_format) = match command {
        Command::Report(report) => (report, Format::Text),
        Command::Request { schema: true } => {
            println!("{}", include_str!("../request.schema.json").trim_end());
            return Ok(());
        }
        Command::Request { schema: false } => {
            let request = serde_json::from_reader(io::stdin().lock())
                .context("invalid Tally request (see tally request --schema)")?;
            (request, Format::Blocks)
        }
        Command::Completions { shell } => {
            clap_complete::generate(shell, &mut Cli::command(), "tally", &mut io::stdout());
            return Ok(());
        }
    };
    let format = global.format.unwrap_or(default_format);
    match report {
        Report::Count(args) => report::counts(&scan::scan(&args.path, global.verbose)?, format),
        Report::Largest(args) => report::largest(scan::scan(&args.target.path, global.verbose)?, args.top, format),
    }
}
