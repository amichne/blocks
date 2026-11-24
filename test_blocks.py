import json
import re
import subprocess
import sys
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from blocks import Declined, interact, presentation

ROOT = Path(__file__).resolve().parent
EXAMPLE = ROOT / "example.json"


def cli(*args: str, data: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ROOT / "blocks", *args],
        input=data,
        cwd=ROOT.parent,
        capture_output=True,
        text=True,
        check=False,
    )


class BlocksTests(TestCase):
    def test_picker_static_branch_feeds_an_interaction(self) -> None:
        picked = cli("pick", str(ROOT / "picker.json"), "--value", "review")
        self.assertEqual(picked.returncode, 0, picked.stderr)
        self.assertEqual(json.loads(picked.stdout)["blocks"][1]["id"], "focus")
        self.assertEqual(cli("render", data=picked.stdout).returncode, 0)

    def test_picker_composes_provider_and_local_blocks(self) -> None:
        prefix = {"type": "text", "text": "Current report"}
        request = {"name": "a 'literal' $(value)"}
        option = {
            "value": "src/a b",
            "label": "Read file",
            "blocks": [prefix],
            "request": request,
        }
        menu = json.dumps({"version": 1, "label": "Choose", "options": [option]})
        provider = (
            "import json,sys; name=json.load(sys.stdin)['name']; "
            "print(json.dumps({'version':1,'blocks':[{'type':'text','text':name}]}))"
        )
        arg = ["pick", "--value", "src/a b"]
        picked = cli(*arg, "--provider", sys.executable, "-c", provider, data=menu)
        self.assertEqual(picked.returncode, 0, picked.stderr)
        self.assertEqual(
            json.loads(picked.stdout),
            {
                "version": 1,
                "blocks": [prefix, {"type": "text", "text": request["name"]}],
            },
        )
        raw = cli(*arg, "--request-only", data=menu)
        self.assertEqual(json.loads(raw.stdout), request)

    def test_picker_failures_have_no_partial_document(self) -> None:
        question = {"type": "input", "id": "q", "label": "Question"}
        option: dict[str, object] = {
            "value": "a",
            "label": "Run",
            "blocks": [question],
            "request": {},
        }
        menu = {"version": 1, "label": "Select", "options": [option]}
        duplicate = json.dumps({"version": 1, "blocks": [question]})
        for selected, tail, doc in [
            ("missing", [], menu),
            ("a", [], menu),
            ("a", ["--request-only"], {**menu, "options": [option, option]}),
            ("a", ["--provider", sys.executable, "-c", "print('broken')"], menu),
            ("a", ["--provider", sys.executable, "-c", "raise SystemExit(3)"], menu),
            ("a", ["--provider", sys.executable, "-c", f"print({duplicate!r})"], menu),
        ]:
            with self.subTest(selected=selected, tail=tail):
                result = cli("pick", "--value", selected, *tail, data=json.dumps(doc))
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertIn("blocks:", result.stderr)

    def test_styled_table_alignment_and_narrow_layout(self) -> None:
        table = {
            "type": "table",
            "columns": ["File", "N"],
            "rows": [["文", "2"], ["a", "10"]],
        }
        doc = {"version": 1, "blocks": [table]}

        def visible(width: int) -> list[str]:
            return [
                re.sub(r"\x1b\[[0-9;]+m", "", s)
                for s in presentation(doc, width, styled=True)
                if isinstance(s, str)
            ]

        self.assertEqual(
            visible(12),
            ["  File     N", "  ────    ──", "  文       2", "  a       10"],
        )
        self.assertEqual(visible(11)[:2], ["  File  文", "  N  2"])

    def test_table_layout_and_bad_row(self) -> None:
        table = {
            "type": "table",
            "columns": ["File", "Lines"],
            "rows": [["文", "2"], ["a", "1"]],
        }
        doc = {
            "version": 1,
            "blocks": [{"type": "section", "title": "Count", "blocks": [table]}],
        }
        self.assertEqual(
            presentation(doc), ["Count", "  File  Lines", "  文    2", "  a     1"]
        )
        self.assertEqual(
            presentation(doc, width=10),
            ["Count", "  File: 文", "  Lines: 2", "  ", "  File: a", "  Lines: 1"],
        )
        invalid = {"version": 1, "blocks": [{**table, "rows": [["only one cell"]]}]}
        result = cli("render", data=json.dumps(invalid))
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn("needs 2 cells", result.stderr)

    def test_example_preview(self) -> None:
        result = cli("render", data=EXAMPLE.read_text())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "# Review the change",
                "Changed files",
                "  - cli.py",
                "  - README.md",
                "Choose the next review step.",
                "What needs review?",
                "  1. Implementation",
                "  2. Documentation",
                "What should the reviewer look for?",
            ],
        )

    def test_answers_by_stable_value(self) -> None:
        reply = {"next": "docs", "focus": "Check the examples"}
        result = cli("run", str(EXAMPLE), "--answers", "-", data=json.dumps(reply))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {"version": 1, "answers": reply})
        self.assertEqual(result.stderr, "")

    def test_interactive_retry_and_cancel(self) -> None:
        parts = presentation(json.loads(EXAMPLE.read_text()))
        display = StringIO()
        self.assertEqual(
            interact(parts, StringIO("0\n2\n\nExamples\n"), display),
            {"next": "docs", "focus": "Examples"},
        )
        self.assertIn("Enter a listed number.", display.getvalue())
        self.assertIn("Enter one line of text.", display.getvalue())
        with self.assertRaises(EOFError):
            interact(parts, StringIO("1\n"), StringIO())

    def test_host_can_replay_the_exact_choice_document(self) -> None:
        path = "src/1 $(literal) 文.rs"
        options = [{"value": path, "label": "Review source"}]
        handoff = cli(
            "ask", "file", "Which file?", "--options", "-", data=json.dumps(options)
        )
        self.assertEqual((handoff.returncode, handoff.stderr), (3, ""))
        doc = {
            "version": 1,
            "blocks": [
                {
                    "type": "choice",
                    "id": "file",
                    "label": "Which file?",
                    "options": options,
                }
            ],
        }
        self.assertEqual(
            json.loads(handoff.stdout),
            {"version": 1, "status": "input_required", "request": doc},
        )
        with TemporaryDirectory() as directory:
            snapshot = Path(directory) / "request.json"
            snapshot.write_text(json.dumps(doc))
            for value, status in [(path, 0), ("Review source", 2)]:
                answers = {"file": value}
                replay = cli(
                    "run", str(snapshot), "--answers", "-", data=json.dumps(answers)
                )
                self.assertEqual(replay.returncode, status, replay.stderr)
                if status == 0:
                    self.assertEqual(
                        json.loads(replay.stdout), {"version": 1, "answers": answers}
                    )
                else:
                    self.assertEqual(replay.stdout, "")

    def test_ask_and_run_share_input_validation(self) -> None:
        reply = cli("ask", "focus", "Why?", "--answers", "-", data='{"focus":"d"}')
        self.assertEqual(
            (reply.returncode, json.loads(reply.stdout)["answers"]), (0, {"focus": "d"})
        )
        for argv, data in [
            (["ask", "bad/id", "Why?"], ""),
            (["ask", "ok", "Why?", "--options", "-"], '[{"value":"x\\n","label":"X"}]'),
            (["ask", "ok", "Why?", "--options", "-", "--answers", "-"], "[]"),
        ]:
            with self.subTest(argv=argv):
                failure = cli(*argv, data=data)
                self.assertEqual((failure.returncode, failure.stdout), (2, ""))
        empty = cli("run", "--interactive", data='{"version":1,"blocks":[]}')
        self.assertEqual(
            (empty.returncode, json.loads(empty.stdout)["answers"]), (0, {})
        )

    def test_decline_discards_the_whole_request(self) -> None:
        parts = presentation(json.loads(EXAMPLE.read_text()))
        for keys in ["d\n", "2\n\x07\n"]:
            self.assertIsInstance(interact(parts, StringIO(keys), StringIO()), Declined)

    def test_invalid_answers_never_emit_a_result(self) -> None:
        for reply in (
            {},
            {"next": "1", "focus": "examples"},
            {"next": "docs", "focus": "a", "extra": "b"},
        ):
            with self.subTest(reply=reply):
                result = cli(
                    "run", str(EXAMPLE), "--answers", "-", data=json.dumps(reply)
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")

    def test_invalid_document_never_emits_partial_output(self) -> None:
        question = {"type": "input", "id": "name", "label": "Name?"}
        cases: list[object] = [
            {"version": True, "blocks": []},
            {"version": 2, "blocks": []},
            {"version": 1, "blocks": [question, {"type": "unknown"}]},
            {"version": 1, "blocks": [{"type": "text", "text": "\x1b[2J"}]},
            {
                "version": 1,
                "blocks": [
                    question,
                    {"type": "section", "title": "More", "blocks": [question]},
                ],
            },
            {
                "version": 1,
                "blocks": [
                    {
                        "type": "choice",
                        "id": "a",
                        "label": "A?",
                        "options": [{"value": "x", "label": "X"}] * 2,
                    }
                ],
            },
        ]
        for document in cases:
            with self.subTest(document=document):
                result = cli("render", data=json.dumps(document))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("blocks:", result.stderr)

    def test_empty_document_and_duplicate_json_keys(self) -> None:
        empty = cli("render", data='{"version":1,"blocks":[]}')
        self.assertEqual((empty.returncode, empty.stdout), (0, ""))
        duplicate = cli("render", data='{"version":1,"version":1,"blocks":[]}')
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("duplicate JSON property", duplicate.stderr)
