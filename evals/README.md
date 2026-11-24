# Agent usability checks

From the Blocks checkout, run the four cases with Git, Python 3.10+, uv, npm, and an authenticated Codex CLI on PATH.

```sh
npx --yes promptfoo@0.126.0 eval -c evals/promptfooconfig.yaml --no-cache --no-share --no-write
```

Each case installs the checkout under a temporary home and starts a fresh Codex session with GPT-6.2-sol at low reasoning effort. The agent receives the task and worktree location. Codex discovers the skills through its user skill directory. The provider checks completed tool calls and reads the resulting files and Git objects after the turn.

| Case | Evidence for a pass |
| --- | --- |
| `PR-OPEN` | The agent reads the PR skill, uses the command, pushes the expected commit to a disposable Git remote, creates a PR through a GitHub CLI fixture, and reports the URL. |
| `PR-REVIEW` | The agent describes the timeout change. Git refs, the index, working content, and PR review state show no writes. |
| `BLOCKS-BUILD` | The agent reads the composition skill and writes a new release-note command. The verifier runs that executable in a fresh sandbox, captures the host handoff, and checks file contents after hold, invalid, and publish answers. |
| `BLOCKS-EXPLAIN` | The agent explains how the host collects answers. The worktree and PR state remain intact. |

Use `--filter-pattern PR-OPEN` to select one case. To check the assertion alone, set `BLOCKS_EVAL_CONTROL` to the expected observation string in the configuration. Repeat with a missing or extra observation and expect a failure. Unset the variable for live runs. Set `BLOCKS_EVAL_TRACE_DIR` to an existing private directory outside the checkout to retain raw Codex events for diagnosis.
