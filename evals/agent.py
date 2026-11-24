"""Promptfoo provider. Grade external Git effects and completed Codex tool events."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gpt-6.2-sol"
URL = "https://example.invalid/fixture/pull/1"


def check_presentation(document: Path, blocks: Path, env: dict[str, str]) -> list[str]:
    def invoke(*args: str, answers: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [blocks, "run", document, *args],
            cwd=document.parent,
            env=env,
            input=answers,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    observed: list[str] = []
    source = json.loads(document.read_text())
    handoff = invoke("--interactive")
    if handoff.returncode == 3 and json.loads(handoff.stdout)["request"] == source:
        editors = [b for b in source["blocks"] if b["type"] == "editor"]
        if (
            len(editors) == 1
            and editors[0]["id"] == "note"
            and editors[0]["initial"] == "Increase the timeout"
        ):
            observed.append("host handoff")
    for value in ("hold", "publish"):
        answers = {"note": "Revised release note\n\nSecond paragraph.", "action": value}
        result = invoke("--answers", "-", answers=json.dumps(answers))
        if result.returncode != 0 or json.loads(result.stdout)["answers"] != answers:
            break
    else:
        observed.append("edited answers replayed")
    choices = [
        b for b in source["blocks"] if b["type"] == "choice" and b["id"] == "action"
    ]
    invalid = invoke("--answers", "-", answers='{"note":"edit","action":"unknown"}')
    if (
        invalid.returncode == 2
        and len(choices) == 1
        and sorted(o["value"] for o in choices[0]["options"]) == ["hold", "publish"]
    ):
        observed.append("invalid choice rejected")
    return observed


def generated_command_works(work: Path, codex: str, env: dict[str, str]) -> bool:
    if not os.access(work / "review-release", os.X_OK):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        replay = Path(tmp) / "replay"
        shutil.copytree(
            work, replay, symlinks=True, ignore=shutil.ignore_patterns(".git")
        )

        def invoke(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    codex,
                    "sandbox",
                    "-P",
                    ":workspace",
                    "-C",
                    str(replay),
                    "--",
                    "./review-release",
                    *args,
                ],
                env=env,
                stdin=subprocess.DEVNULL,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )

        saved = replay / "approved-note.md"
        if saved.is_symlink():
            return False
        saved.write_text("Original note")
        handoff = invoke()
        if (
            handoff.returncode != 3
            or saved.read_text() != "Original note"
            or json.loads(handoff.stdout)["request"]
            != json.loads((work / "release-review.json").read_text())
        ):
            return False
        answer = Path(tmp) / "answers.json"
        edited = "Revised note\n\nSecond paragraph.\n"
        for action, accepted, expected in (
            ("hold", True, "Original note"),
            ("invalid", False, "Original note"),
            ("publish", True, edited),
        ):
            answer.write_text(json.dumps({"note": edited, "action": action}))
            if (
                invoke("--answers", str(answer)).returncode == 0
            ) != accepted or saved.read_text() != expected:
                return False
    return True


def call_api(prompt: str, options: object, context: object) -> dict[str, object]:
    if control := os.environ.get("BLOCKS_EVAL_CONTROL"):
        return {"output": control}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        home = root / "home"
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True)
        auth = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
        if auth.exists():
            (codex_home / "auth.json").symlink_to(auth.resolve())
        workspace = root / "workspace"
        work = workspace / "work"
        work.mkdir(parents=True)
        bindir = home / ".local/bin"
        env = {
            "HOME": str(home),
            "CODEX_HOME": str(codex_home),
            "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
        }

        def run(*args: str) -> str:
            return subprocess.check_output(args, cwd=work, env=env, text=True).strip()

        run(sys.executable, str(ROOT / "install"), "--source", str(ROOT))
        # The remote and Git metadata are fixture-owned writable directories.
        state = root / "state"
        state.mkdir()
        (home / ".cache").mkdir()
        remote = state / "origin"
        run("git", "init", "-b", "main", "--separate-git-dir", str(state / "meta"))
        run("git", "init", "--bare", "-b", "main", str(remote))
        run("git", "remote", "add", "origin", str(remote))
        sample = work / "config.txt"
        sample.write_text("timeout = 10\n")
        run("git", "-c", "core.autocrlf=false", "add", "config.txt")
        frozen = {
            **env,
            "GIT_AUTHOR_DATE": "2025-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2025-01-01T00:00:00Z",
        }
        subprocess.run(
            ["git", "commit", "-qm", "Initial"], cwd=work, env=frozen, check=True
        )
        base = run("git", "rev-parse", "HEAD")
        if base != "64a710e117cbe140bcc0c8f432e958e763816df2":
            raise ValueError("unexpected fixture revision")
        run("git", "push", "origin", "main")
        sample.write_text("timeout = 30\n")
        expected_blob = run("git", "hash-object", "config.txt")
        receipt = state / "pr.json"
        gh = bindir / "gh"
        gh.write_text(
            "#!/usr/bin/env python3\nimport json, sys\nfrom pathlib import Path\n"
            "args=sys.argv[1:]\n"
            "if args[:2]==['repo','view']: print('fixture/repo')\n"
            "elif args[:2]==['pr','list']: print('[]')\n"
            "elif args[:2]==['pr','create']:\n"
            f"    Path({str(receipt)!r}).write_text(json.dumps(args))\n"
            f"    print({URL!r})\n"
            "else: sys.exit(2)\n"
        )
        gh.chmod(0o755)
        codex = shutil.which("codex")
        if not codex:
            raise FileNotFoundError("install Codex CLI before the live eval")
        execution = subprocess.run(
            [
                codex,
                "exec",
                "--json",
                "--ephemeral",
                "--ignore-user-config",
                "-m",
                MODEL,
                "-c",
                'model_reasoning_effort="low"',
                "-c",
                'shell_environment_policy.inherit="all"',
                "-c",
                "allow_login_shell=false",
                "--sandbox",
                "workspace-write",
                "--skip-git-repo-check",
                "--add-dir",
                str(state),
                "--add-dir",
                str(home / ".cache"),
                "-C",
                str(workspace),
                "The target worktree is ./work. " + prompt,
            ],
            cwd=work,
            env=env,
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        if execution.returncode:
            raise RuntimeError(
                f"Codex exited {execution.returncode}: {execution.stderr[-800:]}"
            )
        events = [json.loads(row) for row in execution.stdout.splitlines()]
        if trace_dir := os.environ.get("BLOCKS_EVAL_TRACE_DIR"):
            with tempfile.NamedTemporaryFile(
                dir=trace_dir, suffix=".jsonl", delete=False
            ) as trace:
                trace.write(execution.stdout.encode())
        if not any(event["type"] == "turn.completed" for event in events):
            raise ValueError("Codex did not complete the turn")
        items = [event["item"] for event in events if event["type"] == "item.completed"]
        commands = [i for i in items if i["type"] == "command_execution"]
        messages = " ".join(i["text"] for i in items if i["type"] == "agent_message")
        skill_read = any(
            "SKILL.md" in i["command"]
            and "# Prepare a pull request" in i.get("aggregated_output", "")
            for i in commands
        )
        reviewed = any(
            '"status": "published"' in i.get("aggregated_output", "")
            and "pull-request" in i["command"]
            for i in commands
        )
        workflow_skill = any(
            "SKILL.md" in i["command"]
            and "# Compose a Blocks workflow" in i.get("aggregated_output", "")
            for i in commands
        )
        branches = run("git", "ls-remote", "--heads", "origin").splitlines()
        observed: list[str] = []
        document = work / "release-review.json"
        if document.is_file():
            if workflow_skill:
                observed.append("workflow skill read")
            observed.extend(
                check_presentation(
                    document, home / ".local/share/blocks/current/blocks", env
                )
            )
            if generated_command_works(work, codex, env):
                observed.append("generated command saved only on publish")
        elif receipt.exists():
            args = json.loads(receipt.read_text())
            branch = args[args.index("--head") + 1]

            def remote_git(*args: str) -> str:
                return run("git", "--git-dir", str(remote), *args)

            pushed = remote_git("rev-parse", "refs/heads/" + branch)
            if skill_read:
                observed.append("skill read")
            if (
                reviewed
                and args[args.index("--base") + 1] == "main"
                and len(branches) == 2
            ):
                observed.append("reviewed PR published")
            if (
                remote_git("rev-parse", pushed + "^") == base
                and remote_git("ls-tree", "--name-only", pushed) == "config.txt"
                and remote_git("rev-parse", pushed + ":config.txt") == expected_blob
            ):
                observed.append("correct change")
            if URL in messages:
                observed.append("URL reported")
        else:
            if (
                branches == [base + "\trefs/heads/main"]
                and run(
                    "git",
                    "for-each-ref",
                    "--format=%(refname)",
                    "refs/heads",
                    "refs/blocks",
                )
                == "refs/heads/main"
                and not (state / "meta/blocks-pr").exists()
                and run("git", "status", "--porcelain") == "M config.txt"
                and run("git", "hash-object", "config.txt") == expected_blob
                and run("git", "diff", "--cached", "--name-only") == ""
            ):
                observed.append("read only")
            if "timeout" in messages.lower() and "10" in messages and "30" in messages:
                observed.append("change described")
            explanation = messages.lower()
            if all(word in explanation for word in ("publish", "hold", "answers")):
                observed.append("workflow explained")
        return {
            "output": " | ".join(observed),
            "metadata": {
                "model": MODEL,
                "base": base,
                "skillRead": skill_read,
                "workflowSkillRead": workflow_skill,
                "published": reviewed,
                "toolCalls": len(commands),
            },
        }
