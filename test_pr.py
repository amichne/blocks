import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parent


class PullRequestFlow(TestCase):
    def test_partial_index_review_and_publish_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            work = root / "work"
            work.mkdir()
            env = {
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
            }

            def run(*args: str, data: str = "", status: int = 0) -> str:
                proc = subprocess.run(
                    args,
                    cwd=work,
                    env=env,
                    input=data,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(proc.returncode, status, proc.stderr)
                return proc.stdout

            def git(*args: str) -> str:
                return run("git", *args)

            def pr(*args: str, data: str = "", status: int = 0) -> str:
                return run(str(ROOT / "pr"), *args, data=data, status=status)

            git("init", "-b", "main")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            git("init", "--bare", str(root / "remote"))
            git("remote", "add", "origin", str(root / "remote"))
            source = work / "file.txt"
            source.write_text("original\n")
            git("add", "file.txt")
            git("commit", "-m", "Initial")
            git("push", "origin", "main")
            base = git("rev-parse", "HEAD").strip()
            source.write_text("staged\n")
            git("add", "file.txt")
            source.write_text("staged\nunstaged\n")
            pending = json.loads(pr("plan", "topic", "--base", "main", status=3))
            self.assertEqual(pending["status"], "input_required")
            plan = json.loads(
                pr("plan", "topic", "--base", "main", "--scope", "staged")
            )
            self.assertIn("+staged", plan["diff"])
            self.assertNotIn("unstaged", plan["diff"])
            draft = {
                "plan": plan["plan"],
                "title": "A title",
                "commit_message": "Staged change",
                "body": "Summary\n\nOriginal paragraph\n",
            }
            pr(
                "prepare",
                "topic",
                "--draft",
                "-",
                data=json.dumps({**draft, "plan": "stale"}),
                status=2,
            )
            review = json.loads(
                pr("prepare", "topic", "--draft", "-", data=json.dumps(draft), status=3)
            )
            self.assertEqual(git("show", "-s", "--format=%P", "topic").strip(), base)
            self.assertEqual(git("show", "topic:file.txt"), "staged\n")
            self.assertEqual(git("show", ":file.txt"), "staged\n")
            self.assertEqual(source.read_text(), "staged\nunstaged\n")
            answers = root / "answers.json"
            edited = "Summary\n\nA human's edit with `literal` text.\n"
            answers.write_text(json.dumps({"body": edited, "action": "local"}))

            def reply(review_id: str, status: int = 0) -> str:
                return pr(
                    "review",
                    "topic",
                    "--for-review",
                    review_id,
                    "--answers",
                    str(answers),
                    status=status,
                )

            self.assertEqual(json.loads(reply(review["review"]))["status"], "local")
            self.assertEqual(git("ls-remote", "origin", "refs/heads/topic"), "")
            reopened = json.loads(pr("review", "topic", status=3))
            editor = next(
                b for b in reopened["request"]["blocks"] if b["type"] == "editor"
            )
            self.assertEqual(editor["initial"], edited)
            reply(review["review"], status=2)
            answers.write_text(json.dumps({"body": edited, "action": "publish"}))
            gh = root / "gh"
            gh.write_text("""#!/usr/bin/env python3
import json, sys
from pathlib import Path
store = Path(__file__).parent
args = sys.argv[1:]
if args[:2] == ['repo', 'view']:
    print('owner/repo')
elif args[:2] == ['pr', 'list']:
    print((store / 'prs').read_text() if (store / 'prs').exists() else '[]')
elif args[:2] == ['pr', 'create']:
    if not (store / 'allow').exists():
        sys.exit(1)
    (store / 'published').write_bytes(Path(args[args.index('--body-file')+1]).read_bytes())
    print('https://example.invalid/pr/1')
else:
    sys.exit(2)
""")
            gh.chmod(0o755)
            reply(reopened["review"], status=2)
            sha = git("rev-parse", "topic").strip()
            self.assertTrue(
                git("ls-remote", "origin", "refs/heads/topic").startswith(sha)
            )
            (root / "allow").touch()
            self.assertEqual(
                json.loads(reply(reopened["review"]))["status"], "published"
            )
            self.assertEqual((root / "published").read_bytes(), edited.encode())
            (root / "allow").unlink()
            (root / "prs").write_text(
                json.dumps(
                    [
                        {
                            "headRefOid": sha,
                            "state": "OPEN",
                            "isCrossRepository": False,
                            "title": "A title",
                            "body": edited,
                            "url": "https://example.invalid/pr/1",
                        }
                    ]
                )
            )
            self.assertEqual(
                json.loads(reply(reopened["review"]))["url"],
                "https://example.invalid/pr/1",
            )
            git("branch", "-f", "topic", base)
            reply(reopened["review"], status=2)
