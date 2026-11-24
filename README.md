# Blocks

Blocks is an early proof of concept for agents and CLI tools that need to ask someone a question in the terminal.
Everything is open to change, including the commands, JSON formats, terminal interactions, and the overall direction.
The examples describe what works today.

Give an agent the output of `blocks schema`. The agent can compose a JSON presentation and send it directly to `blocks render`.
Use `blocks run` when the caller needs answers. The caller decides what each answer does.

From this directory, put the command on your shell's search path. It uses Python 3.10 or later and its standard library.

```sh
export PATH="$PWD:$PATH"
blocks schema
blocks render example.json
blocks run example.json --interactive
```

In a UTF-8 color terminal, Blocks highlights titles, aligns numeric columns on the right, and marks each choice with its number.
Use `blocks render --plain` or `blocks run --plain --interactive` for the plain layout.
Redirected output, a nonempty `NO_COLOR`, and `TERM=dumb` also select plain text.

### Ask one question

Use `blocks ask focus 'What needs a closer look?'` for a line of text. For a choice, pass a JSON array of labels and values.
For example, let Tally find the three largest files in a crate. Show their line counts and return the selected path.

```sh
cargo build --locked --release -p tally
target/release/tally largest tally/src -n 3 --format json |
  jq 'map({label:"\(.path) (\(.lines) lines)", value:.path})' |
  ./blocks ask file 'Which file needs review?' --options -
```

In a terminal, select a number. The caller gets an answer such as `{"version":1,"answers":{"file":"tally/src/scan.rs"}}`.
It can open that path or use what it finds to compose the next question.

### Ask through an agent host

Capture stdout and stderr when the host owns the conversation. For `ask` and `run --interactive`, inspect the exit status before reading stdout.

| Exit | Meaning | Caller action |
| --- | --- | --- |
| 0 | All questions have answers | Read the `answers` object from stdout. |
| 2 | Command, input, or I/O error | Read the diagnostic on stderr. |
| 3 | Input required | Read `request` from stdout and present it to the person. |
| 4 | The person declined | Stop this request. Stdout is empty. |
| 130 | The person interrupted or dismissed the prompt | Stop this request. Stdout is empty. |

Exit 3 carries one JSON object with `version: 1`, `status: "input_required"`, and the full presentation in `request`.
Blocks returns it when stderr is captured or the terminal has no keyboard available. It emits the request before it reads an answer.
Keep that exact document while the person decides. Save it as `request.json`, then pass their answers to `blocks run request.json --answers -` on stdin.
Supply option values under their question IDs. Blocks checks them against the choices the person saw, even if the data source has since changed.
If the person declines or dismisses the host's prompt, stop there. Use `blocks schema result` to inspect both stdout shapes.

### Prepare a pull request with an agent

The separate `pr` executable composes Git, Blocks, and GitHub CLI. Run it from the target worktree on macOS or Linux.
Use its absolute path if the worktree belongs to another project. The workflow needs Git, uv, an `origin` remote, and an authenticated `gh` for publication.

1. **Capture the changes.** Give the agent the JSON from this command.

   ```sh
   ./pr plan feature/retry --base main --scope staged
   ```

   The result contains a plan ID, the selected diff against the remote base, and the first standard PR template found in the selected tree.
   Staged scope preserves partial hunks. Use repeated `--path` arguments for literal working-tree paths relative to the repo root, or `--scope all` for all working changes.
   With unspecified scope, the command asks when unstaged changes exist. If a host captures that question, present it and repeat the plan with the selected scope.

2. **Create the local commit.** The calling agent writes a JSON object with the plan ID in `plan`, its `commit_message`, a PR `title`, and a Markdown `body`.
   Use the template and report checks the agent actually ran. Pass that object through stdin or a file outside the target worktree.

   ```sh
   ./pr prepare feature/retry --draft /tmp/agent-draft.json
   ```

   The command creates one commit on a new task branch from the captured base. It runs Git commit hooks in a temporary worktree and checks the resulting tree and parent.
   Your original checkout keeps its branch, staged hunks, and working files. If selected changes conflict with the base, planning stops.

3. **Edit the description in place.** The review shows the branch, commit, change counts, and title above the prefilled editor.
   Enter adds a newline. Esc then Enter accepts the text and moves to **Push and open PR** or **Keep local**.
   Keep local saves the edited description in the repository's Git metadata. Reopen it with `./pr review feature/retry`.
   Ctrl+C dismisses the review and preserves the last saved draft.

4. **Publish from the terminal or a host.** The terminal pushes only after the publish choice. In a host, exit 3 returns the Blocks `request` and a `review` ID.
   Present the request, then replay the person's exact `{"body":"…","action":"publish"}` or `local` choice.

   ```sh
   ./pr review feature/retry --for-review "$review_id" --answers /tmp/answers.json
   ```

   A changed draft invalidates an old review ID. If PR creation fails after the push, reopen the saved draft and retry.
   The command checks the reviewed commit and remote branch and recognizes an existing matching PR. If the base advances, prepare a new plan on a new branch.

### Request a Tally report

Tally counts files and lines by extension or ranks files by line count. The local Apple Silicon executable is `./bin/tally`.
From the workspace root, request a report and pipe the resulting presentation to the renderer.

```sh
echo '{"command":"largest","path":"tally/src","top":3}' | ./bin/tally request | ./blocks render
```

An agent can inspect `./bin/tally request --schema` to discover the operations.
Use `./blocks schema` for the presentation format. A caller can insert questions or combine reports before it renders the document.
This example adds a review question to a live report and returns the person's answer as JSON.

```sh
./bin/tally count tally/src --format blocks |
  jq '.blocks += [{"type":"input","id":"focus","label":"Which file needs review?"}]' |
  ./blocks run --interactive
```

For shell scripts, `./bin/tally count . --format json` returns the extension map.
`./bin/tally largest . -n 3 --format json` returns file records. Both commands default to text.
`--verbose` sends progress to stderr. The scan skips hidden entries, symlinks, and files it cannot read as UTF-8.
Use `./bin/tally completions zsh` to print shell completions.

### Search and evaluate a branch

Run the included picker from the workspace root. Type `lrg` to filter for “Largest source files.”
The preview shows the current line counts. Use the arrow keys to change focus, Enter to select, or Esc to cancel.

```sh
./blocks pick picker.json --interactive --provider ./bin/tally request | ./blocks render
```

The picker reads a catalog from a file or stdin. Each option has a unique single-line `value` and a display `label`.
An option can supply `blocks`, a JSON `request`, or both. Local blocks appear first, followed by the provider's blocks.
The selected presentation goes to stdout. Pipe it to `blocks run --interactive` when the branch contains questions.

The caller supplies the provider as the last CLI option, followed by its executable and arguments.
Blocks sends the request to the program's stdin and expects one version 1 presentation on stdout.
Use a read-only provider. Focus changes can run it repeatedly, and Enter requests a fresh result.
An invalid reply or failed provider on selection exits with status 2. Cancellation exits with status 130. Both leave stdout empty.

Agents can use the same catalog without a terminal. Inspect `blocks schema picker` for the input shape.

```sh
# Resolve the branch by ID and add live data.
./blocks pick picker.json --value counts --provider ./bin/tally request | ./blocks render

# Hand the selected request to the caller for its own dispatch.
./blocks pick picker.json --value largest --request-only | ./bin/tally request | ./blocks render
```

Generate the options on demand when the available items come from another tool.
This example uses each file path as its stable value and attaches its line count as a preview.

```sh
./bin/tally largest tally/src --format json |
  jq '{version:1, label:"Inspect a source file", options:map({
    value:.path, label:.path, blocks:[{type:"text",text:"\(.path) has \(.lines) lines"}]
  })}' |
  ./blocks pick --interactive | ./blocks render
```

Interactive search uses `fzf` on `PATH`. Exact-value selection uses the Python standard library.

### Reuse the Rust components

The `cli-blocks` crate owns the shared clap arguments and serializable presentation types.
Add it as a Cargo path dependency in another CLI. Flatten `GlobalOpts` or `PathArgs` into that CLI's clap parser.
Construct a `Presentation` from `Block` values and serialize it to stdout. Tally's [report implementation](tally/src/report.rs) covers both report shapes.

To rebuild from source on a machine with Rust, run `cargo build --locked --release -p tally`.
The binary is at `target/release/tally`. Run `cargo test --locked --release --workspace` to exercise the Rust commands.

### Compose a presentation

The document specifies version 1 and an ordered array of blocks. A section can contain other sections.

```sh
echo '{"version":1,"blocks":[{"type":"heading","text":"Build"},{"type":"list","items":["Tests passed","Package ready"]}]}' | blocks render --plain
```

```text
# Build
- Tests passed
- Package ready
```

| Block type | Fields | Presentation |
| --- | --- | --- |
| `heading` | `text` | Highlighted title, or a `#` prefix in plain text |
| `text` | `text` | One line |
| `list` | `items` | One bullet per string |
| `table` | `columns`, `rows` | Aligned columns, or labeled values in a narrow terminal |
| `section` | `title`, `blocks` | Title with indented children |
| `choice` | `id`, `label`, `options` | Numbered options with stable values |
| `input` | `id`, `label` | Single-line text prompt |
| `editor` | `id`, `label`, `initial` | Prefilled multiline text with inline cursor editing |

Each option has a display `label` and a unique `value` within its choice. Each question needs a unique `id` across the document.
Question IDs start with an ASCII letter and can contain letters, digits, underscores, periods, and hyphens.
Option values accept nonempty single-line text, including paths, spaces, and Unicode. Blocks returns each value verbatim.
Use separate text blocks for separate display lines. The editor accepts empty text, tabs, and LF newlines, including the final newline.
Only interactive editing uses the locked prompt-toolkit helper through uv. Rendering and host replay use the Python standard library.

### Collect answers

For a person, use `--interactive`. The terminal displays the questions on stderr. The caller receives one JSON object on stdout after the last answer.
The person selects a number. The caller receives the corresponding option value, even if the display order changes.
At a choice, enter `d` to decline. At a text prompt, press Ctrl+G and then Enter to decline. Both discard earlier answers in that request.

For an agent or CI job, pass an answer object by file or stdin. Supply exactly one answer per question.

```sh
echo '{"next":"docs","focus":"Check the installation example"}' | blocks run example.json --answers -
```

```json
{"version":1,"answers":{"next":"docs","focus":"Check the installation example"}}
```

The document can also come from stdin, with answers from a named file or the terminal.
`render` displays the document without prompts. A presentation with zero blocks renders zero bytes.
Invalid input exits with status 2 and a diagnostic on stderr. Cancellation exits with status 130 and discards partial answers.
