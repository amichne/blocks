---
name: pull-request
description: Prepare or open a GitHub pull request from local changes when the user requests a PR. Use the installed pull-request command to select the diff, review the draft, and publish or keep it local.
---

# Prepare a pull request

For a read-only review, inspect the diff with Git. Start this workflow when the user wants a local PR draft or wants to open a PR.

1. Run `git status --short --branch` in the target worktree. For the whole current diff, run `pull-request` with no arguments. It targets the default branch on `origin` and includes branch commits and working files. If the command is absent from PATH, try `~/.local/bin/pull-request`.
2. For a narrower selection or an agent-written title and commit message, run `pull-request plan BRANCH --base BASE --scope staged`. Use repeated `--path PATH` for specific working files. Read the returned diff and template. Pass a JSON object with its exact `plan`, a `commit_message`, a `title`, and a Markdown `body` to `pull-request prepare BRANCH --draft -` on stdin.
3. In a host, exit 3 returns a question in `request.blocks`. For a branch question, collect the name and rerun with `--branch NAME`. For a ticket question, collect the ticket and supply it through `blocksPr.ticket` for this invocation. A review includes `branch`, `review`, the initial body in the editor, and the publication choices.
4. Apply the user's instructions to the review. An explicit request to open the PR authorizes `publish` for the requested diff. A local draft uses `local`. If the user reserved approval or the scope is unclear, show the branch, title, and body and wait for their choice. Keep the body from the review unless the user asked you to write or edit it.
5. Write `{"body":"<reviewed Markdown>","action":"publish"}` or its `local` counterpart to a temporary JSON file outside the worktree. Run `pull-request review BRANCH --for-review REVIEW_ID --answers FILE`. If the review expired, reopen it and inspect the new draft. A successful publish returns the URL. Report that URL or the saved local branch and commit. A declined or interrupted review ends the workflow.
