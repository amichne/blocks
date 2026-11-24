---
name: blocks-workflows
description: Build terminal questions, editable reviews, and agent-to-human approval workflows on demand with Blocks. Use when asked to compose a new presentation or integrate a CLI with interactive and host-supplied answers.
---

# Compose a Blocks workflow

For an explanation, describe the interaction. Create or change files when the user asks for an implementation. For the existing GitHub PR workflow, use the pull-request skill.

1. Inspect the producer's input and the decision the user needs to make. Run `~/.local/share/blocks/current/blocks schema` for the installed presentation contract. Reuse this executable from the calling tool.
2. Build a version 1 JSON document with a `blocks` array. Put the context first. Use an `editor` with `id`, `label`, and `initial` for editable Markdown. Use a `choice` with stable option values for the action. Let the caller own the effect of each answer.
3. Pass the document to `blocks run DOCUMENT --interactive` using the installed executable above. In a terminal it asks the person. When stderr is captured, exit 3 returns the exact `request` for the host to present. Preserve this document while the person decides.
4. Replay answers with `blocks run DOCUMENT --answers ANSWERS.json`. The answer file maps each question ID to its value. On exit 0, consume stdout's `answers` object. Apply a requested side effect only for the corresponding authorized action. Stop on a decline or dismissal.
5. Exercise the public entry point. Capture a host handoff, replay an edited answer, and try a value outside the choices. For a request to deliver a presentation, save the JSON and give the user its invocation.
