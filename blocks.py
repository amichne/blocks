#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# no-build = true
# [[tool.uv.index]]
# name = "pypi"
# url = "https://pypi.org/simple"
# default = true
# ///
"""Compose a terminal presentation from a versioned JSON document."""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, TypeGuard


class Invalid(ValueError):
    """A document or response violates the protocol."""


class Declined:
    """The person explicitly declined the whole request."""


ID = r"[A-Za-z][A-Za-z0-9_.-]*"
UNSAFE = r"[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]"
FIELDS = {
    "heading": {"text": "line"},
    "text": {"text": "line"},
    "list": {"items": "lines"},
    "table": {"columns": "columns", "rows": "rows"},
    "section": {"title": "line", "blocks": "blocks"},
    "choice": {"id": "id", "label": "line", "options": "options"},
    "input": {"id": "id", "label": "line"},
}


def record(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def schema() -> dict[str, object]:
    def ref(name: str) -> dict[str, str]:
        return {"$ref": f"#/$defs/{name}"}

    variants = [
        record({"type": {"const": kind}, **{k: ref(v) for k, v in fields.items()}})
        for kind, fields in FIELDS.items()
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Blocks presentation v1",
        **record({"version": {"const": 1}, "blocks": ref("blocks")}),
        "$defs": {
            "line": {"type": "string", "minLength": 1, "not": {"pattern": UNSAFE}},
            "id": {"type": "string", "pattern": f"^{ID}$", "allOf": [ref("line")]},
            "lines": {"type": "array", "items": ref("line")},
            "columns": {"type": "array", "minItems": 1, "items": ref("line")},
            "rows": {
                "type": "array",
                "items": ref("lines"),
                "description": "Each row has one cell per column, in column order.",
            },
            "options": {
                "type": "array",
                "minItems": 1,
                "items": record(
                    {
                        "value": ref("line"),
                        "label": ref("line"),
                    }
                ),
                "description": "Values must be unique within this choice.",
            },
            "blocks": {
                "type": "array",
                "items": {"oneOf": variants},
                "description": "Question IDs must be unique across the document.",
            },
        },
    }


def picker_schema() -> dict[str, object]:
    option = record(
        {
            "value": {"$ref": "#/$defs/line"},
            "label": {"$ref": "#/$defs/line"},
            "blocks": {"$ref": "#/$defs/blocks"},
            "request": {"type": "object"},
        }
    )
    option["required"] = ["value", "label"]
    option["anyOf"] = [{"required": ["blocks"]}, {"required": ["request"]}]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Blocks picker v1",
        "$defs": schema()["$defs"],
        **record(
            {
                "version": {"const": 1},
                "label": {"$ref": "#/$defs/line"},
                "options": {
                    "type": "array",
                    "minItems": 1,
                    "items": option,
                    "description": "Each option needs a unique value.",
                },
            }
        ),
    }


def result_schema() -> dict[str, object]:
    definition = schema()
    version = {"const": 1}
    answers = {
        "type": "object",
        "propertyNames": {"$ref": "#/$defs/id"},
        "additionalProperties": {"$ref": "#/$defs/line"},
        "description": "Exactly the question IDs and allowed values from this request.",
    }
    request = record({"version": version, "blocks": {"$ref": "#/$defs/blocks"}})
    return {
        "$schema": definition["$schema"],
        "$defs": definition["$defs"],
        "title": "Blocks run and ask stdout v1",
        "oneOf": [
            record({"version": version, "answers": answers}),
            record(
                {
                    "version": version,
                    "status": {"const": "input_required"},
                    "request": request,
                }
            ),
        ],
    }


def is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def is_object(value: object) -> TypeGuard[dict[str, object]]:
    # All keys from the JSON decoder are strings.
    return isinstance(value, dict)


def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise Invalid("duplicate JSON property")
    return result


def decode_json(raw: bytes, source: str) -> object:
    def invalid_number(token: str) -> object:
        raise Invalid(f"{source} contains invalid JSON number {token}")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_keys,
            parse_constant=invalid_number,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Invalid(f"invalid UTF-8 JSON in {source}: {error}") from error


def read_json(path: str) -> object:
    raw = sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()
    return decode_json(raw, ascii(path))


def line(value: object, path: str) -> str:
    if not isinstance(value, str) or not value or re.search(UNSAFE, value):
        raise Invalid(
            f"{path} needs nonempty, single-line text without control characters"
        )
    return value


def identifier(value: object, path: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(ID, value):
        raise Invalid(f"{path} needs an identifier matching {ID}")
    return value


@dataclass(frozen=True)
class Question:
    id: str
    options: tuple[str, ...]  # Empty for free text.

    def answer(self, value: object) -> str:
        answer = line(value, f"answer {self.id}")
        if self.options and answer not in self.options:
            raise Invalid(f"answer {self.id} needs one of: {', '.join(self.options)}")
        return answer


Part = str | Question


def ink(text: str, rendition: str) -> str:
    return f"\x1b[{rendition}m{text}\x1b[0m"


TITLE = "1;7;36"
ACCENT = "36"
STRONG = "1"
SECONDARY = "34"
KEY = "1;33"


def table_lines(
    block: dict[str, object], at: str, available: int | None, styled: bool = False
) -> list[str]:
    def cells(value: object, path: str) -> list[str]:
        if not is_list(value):
            raise Invalid(f"{path} needs an array")
        return [line(cell, f"{path}[{i}]") for i, cell in enumerate(value)]

    columns = cells(block["columns"], at + ".columns")
    if not columns:
        raise Invalid(f"{at}.columns needs at least one label")
    raw_rows = block["rows"]
    if not is_list(raw_rows):
        raise Invalid(f"{at}.rows needs an array")
    rows: list[list[str]] = []
    for i, raw in enumerate(raw_rows):
        row = cells(raw, f"{at}.rows[{i}]")
        if len(row) != len(columns):
            raise Invalid(f"{at}.rows[{i}] needs {len(columns)} cells")
        rows.append(row)

    def width(text: str) -> int:
        return sum(
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            for ch in text
            if not unicodedata.combining(ch)
        )

    grid = [columns, *rows]
    widths = [max(map(width, column)) for column in zip(*grid)]
    margin = "  " if styled else ""
    gap = "    " if styled else "  "
    if (
        rows
        and available is not None
        and len(margin) + sum(widths) + len(gap) * (len(columns) - 1) > available
    ):
        lines: list[str] = []
        for row in rows:
            if lines:
                lines.append("")
            for label, value in zip(columns, row):
                if styled:
                    lines.append(f"{margin}{ink(label, ACCENT)}  {value}")
                else:
                    lines.append(f"{label}: {value}")
        return lines

    numeric = [False] * len(columns)
    if styled and rows:
        numeric = [
            all(re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", v) for v in values)
            for values in zip(*rows)
        ]

    def aligned(row: list[str], header: bool) -> str:
        cells: list[str] = []
        for i, value in enumerate(row):
            padding = " " * (widths[i] - width(value))
            if styled and header:
                value = ink(value, ACCENT)
            elif numeric[i]:
                value = ink(value, KEY)
            if numeric[i]:
                value = padding + value
            elif i < len(columns) - 1:
                value += padding
            cells.append(value)
        return margin + gap.join(cells)

    lines = [aligned(columns, True)]
    if styled:
        lines.append(margin + ink(gap.join("─" * size for size in widths), SECONDARY))
    lines.extend(aligned(row, False) for row in rows)
    return lines


def document_blocks(doc: object) -> list[object]:
    if not is_object(doc) or doc.keys() != {"version", "blocks"}:
        raise Invalid("document needs exactly version and blocks")
    if type(doc["version"]) not in (int, float) or doc["version"] != 1:
        raise Invalid("unsupported version (expected 1)")
    blocks = doc["blocks"]
    if not is_list(blocks):
        raise Invalid("blocks needs an array")
    return blocks


def presentation(
    doc: object, width: int | None = None, styled: bool = False
) -> list[Part]:
    parts: list[Part] = []
    ids: set[str] = set()

    def visit(blocks: object, path: str, indent: str) -> None:
        if not is_list(blocks):
            raise Invalid(f"{path} needs an array")
        for index, block in enumerate(blocks):
            at = f"{path}[{index}]"
            if not is_object(block):
                raise Invalid(f"{at} needs a block object")
            kind = block.get("type")
            if not isinstance(kind, str) or kind not in FIELDS:
                raise Invalid(f"{at}.type needs one of: {', '.join(FIELDS)}")
            fields = FIELDS[kind]
            if block.keys() != {"type", *fields}:
                raise Invalid(f"{at} ({kind}) needs exactly: type, {', '.join(fields)}")
            if (
                styled
                and parts
                and kind in ("heading", "section", "input", "choice", "text")
            ):
                parts.append("")
            if kind == "heading":
                title = line(block["text"], at + ".text")
                parts.append(
                    indent + (ink(f" {title} ", TITLE) if styled else "# " + title)
                )
            elif kind == "text":
                parts.append(indent + line(block["text"], at + ".text"))
            elif kind == "section":
                title = line(block["title"], at + ".title")
                parts.append(indent + (ink(title, STRONG) if styled else title))
                visit(block["blocks"], at + ".blocks", indent + "  ")
            elif kind == "table":
                available = None if width is None else width - len(indent)
                parts.extend(
                    indent + text for text in table_lines(block, at, available, styled)
                )
            elif kind == "list":
                items = block["items"]
                if not is_list(items):
                    raise Invalid(f"{at}.items needs an array")
                for i, item in enumerate(items):
                    bullet = ink("•", ACCENT) + " " if styled else "- "
                    parts.append(indent + bullet + line(item, f"{at}.items[{i}]"))
            else:
                key = identifier(block["id"], at + ".id")
                if key in ids:
                    raise Invalid(f"{at}.id repeats question ID {key}")
                ids.add(key)
                label = line(block["label"], at + ".label")
                parts.append(
                    indent
                    + (ink("? ", ACCENT) + ink(label, STRONG) if styled else label)
                )
                values: dict[str, None] = {}
                if kind == "choice":
                    options = block["options"]
                    if not is_list(options) or not options:
                        raise Invalid(f"{at}.options needs at least one option")
                    for i, option in enumerate(options):
                        opt = f"{at}.options[{i}]"
                        if not is_object(option) or option.keys() != {"value", "label"}:
                            raise Invalid(f"{opt} needs exactly value and label")
                        value = line(option["value"], opt + ".value")
                        if value in values:
                            raise Invalid(f"{opt} repeats option value {value}")
                        values[value] = None
                        number = ink(f"[{i + 1}]", KEY) if styled else f"{i + 1}."
                        parts.append(
                            f"{indent}  {number} "
                            + line(option["label"], opt + ".label")
                        )
                parts.append(Question(key, tuple(values)))

    visit(document_blocks(doc), "blocks", "")
    return parts


def supplied_answers(parts: list[Part], supplied: object) -> dict[str, str]:
    questions = [part for part in parts if isinstance(part, Question)]
    if not is_object(supplied) or supplied.keys() != {q.id for q in questions}:
        raise Invalid(
            "answers must contain exactly the question IDs in the presentation"
        )
    return {q.id: q.answer(supplied[q.id]) for q in questions}


def interact(
    parts: list[Part], keyboard: TextIO, display: TextIO, styled: bool = False
) -> dict[str, str] | Declined:
    answers: dict[str, str] = {}
    for part in parts:
        if isinstance(part, str):
            print(part, file=display)
            continue
        choices = {str(i): v for i, v in enumerate(part.options, 1)}
        while True:
            prompt = (
                f"Select 1-{len(choices)} or d to decline"
                if choices
                else "Enter text (Ctrl+G then Enter to decline)"
            )
            hint = f"{prompt} [{part.id}]"
            cursor = ink(hint, ACCENT) + ink(" › ", KEY) if styled else f"{hint} > "
            print(cursor, end="", file=display, flush=True)
            reply = keyboard.readline()
            if not reply:
                raise EOFError
            value = reply.rstrip("\r\n")
            if value == "\x07" or (choices and value == "d"):
                return Declined()
            try:
                answers[part.id] = part.answer(choices.get(value) if choices else value)
                break
            except Invalid:
                message = (
                    "Enter a listed number." if choices else "Enter one line of text."
                )
                print(ink(message, KEY) if styled else message, file=display)
    return answers


@dataclass(frozen=True)
class Branch:
    value: str
    label: str
    blocks: list[object]
    request: dict[str, object] | None

    @classmethod
    def parse(cls, raw: object, path: str) -> Branch:
        if (
            not is_object(raw)
            or not {"value", "label"} <= raw.keys()
            or raw.keys() - {"value", "label", "blocks", "request"}
        ):
            raise Invalid(f"{path} needs value, label and blocks or request")
        if not raw.keys() & {"blocks", "request"}:
            raise Invalid(f"{path} needs blocks or request")
        blocks = raw.get("blocks", [])
        if not is_list(blocks):
            raise Invalid(f"{path}.blocks needs an array")
        presentation({"version": 1, "blocks": blocks})
        request = raw.get("request")
        if not is_object(request):
            if "request" in raw:
                raise Invalid(f"{path}.request needs a JSON object")
            request = None
        return cls(
            line(raw["value"], path + ".value"),
            line(raw["label"], path + ".label"),
            blocks,
            request,
        )

    def resolve(self, provider: list[str]) -> dict[str, object]:
        blocks = self.blocks
        if self.request is not None:
            if not provider:
                raise Invalid(
                    f"{self.value} needs --provider PROGRAM [ARG ...] or --request-only"
                )
            result = subprocess.run(
                provider,
                input=json.dumps(self.request).encode() + b"\n",
                capture_output=True,
                check=False,
            )
            if result.returncode:
                detail = ascii(result.stderr[:500].decode("utf-8", "replace").strip())
                raise Invalid(
                    f"provider exited {result.returncode} for {self.value}: {detail}"
                )
            reply = decode_json(result.stdout, "provider stdout")
            blocks = [*blocks, *document_blocks(reply)]
        doc: dict[str, object] = {"version": 1, "blocks": blocks}
        presentation(doc)
        return doc


def catalog(raw: object) -> tuple[str, dict[str, Branch]]:
    if not is_object(raw) or raw.keys() != {"version", "label", "options"}:
        raise Invalid("picker needs exactly version, label and options")
    if type(raw["version"]) not in (int, float) or raw["version"] != 1:
        raise Invalid("unsupported picker version (expected 1)")
    title = line(raw["label"], "label")
    options = raw["options"]
    if not is_list(options) or not options:
        raise Invalid("picker needs at least one option")
    branches: dict[str, Branch] = {}
    for i, option in enumerate(options):
        branch = Branch.parse(option, f"options[{i}]")
        if branch.value in branches:
            raise Invalid(f"duplicate option value {branch.value}")
        branches[branch.value] = branch
    return title, branches


def pick_preview(offset: int) -> None:
    # Offsets refer to the private snapshot for this invocation. Only the
    # focused record must be decoded as the user moves through a large menu.
    with Path(os.environ["BLOCKS_PICK_INDEX"]).open("rb") as index:
        provider = decode_json(index.readline(), "provider arguments")
        index.seek(offset)
        branch = Branch.parse(decode_json(index.readline(), "focused option"), "option")
    if not is_list(provider) or not all(isinstance(arg, str) for arg in provider):
        raise Invalid("invalid provider arguments")
    if os.environ.get("BLOCKS_PICK_REQUEST_ONLY") == "1":
        print(
            json.dumps(branch.request, indent=2)
            if branch.request is not None
            else "This option has no request."
        )
        return
    doc = branch.resolve([str(arg) for arg in provider])
    width = int(os.environ.get("FZF_PREVIEW_COLUMNS", "80"))
    for part in presentation(
        doc, width=width, styled=os.environ.get("BLOCKS_PICK_COLOR") == "1"
    ):
        if isinstance(part, str):
            print(part)


def browse(
    title: str,
    branches: dict[str, Branch],
    provider: list[str],
    request_only: bool,
    plain: bool,
) -> str:
    fzf = shutil.which("fzf")
    if not fzf:
        raise Invalid("interactive picking needs fzf on PATH; --value selects by ID")
    if not sys.stderr.isatty():
        raise Invalid(
            "interactive picking needs a terminal on stderr; use --value for automation"
        )
    with tempfile.TemporaryDirectory(prefix="blocks-pick-") as directory:
        snapshot = Path(directory) / "options.jsonl"
        entries: list[str] = []
        with snapshot.open("wb") as index:
            index.write(json.dumps(provider).encode() + b"\n")
            for branch in branches.values():
                entries.append(f"{index.tell()}\t{branch.value}\t{branch.label}\n")
                option: dict[str, object] = {
                    "value": branch.value,
                    "label": branch.label,
                    "blocks": branch.blocks,
                }
                if branch.request is not None:
                    option["request"] = branch.request
                index.write(json.dumps(option).encode() + b"\n")
        color = not (
            plain or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb"
        )
        env = {
            **os.environ,
            "FZF_DEFAULT_OPTS": "",
            "FZF_DEFAULT_OPTS_FILE": "",
            "BLOCKS_PICK_INDEX": str(snapshot),
            "BLOCKS_PICK_PYTHON": sys.executable,
            "BLOCKS_PICK_SCRIPT": str(Path(__file__).resolve()),
            "BLOCKS_PICK_COLOR": str(int(color)),
            "BLOCKS_PICK_REQUEST_ONLY": str(int(request_only)),
        }
        if os.name == "nt":
            preview = '"%BLOCKS_PICK_PYTHON%" "%BLOCKS_PICK_SCRIPT%" _pick-preview {1}'
            shell = "cmd.exe /d /s /c"
        else:
            preview = (
                'exec "$BLOCKS_PICK_PYTHON" "$BLOCKS_PICK_SCRIPT" _pick-preview {1}'
            )
            shell = "/bin/sh -c"
        args = [
            fzf,
            "--layout=reverse",
            "--delimiter=\t",
            "--with-nth=3..",
            "--prompt=Search > ",
            "--header",
            title,
            "--preview",
            preview,
            "--with-shell",
            shell,
            "--preview-window=right,55%,wrap,<70(down,55%,wrap)",
        ]
        if not color:
            args.append("--no-color")
        result = subprocess.run(
            args,
            input="".join(entries).encode(),
            stdout=subprocess.PIPE,
            env=env,
            check=False,
        )
        if result.returncode in (1, 130):
            raise EOFError
        if result.returncode:
            raise Invalid(f"fzf exited {result.returncode}")
        fields = result.stdout.decode().rstrip("\r\n").split("\t")
        if len(fields) != 3 or fields[1] not in branches:
            raise Invalid("fzf returned an unknown option")
        return fields[1]


def input_required(document: object) -> int:
    print(json.dumps({"version": 1, "status": "input_required", "request": document}))
    return 3


def main() -> int:
    if (
        len(sys.argv) == 3
        and sys.argv[1] == "_pick-preview"
        and "BLOCKS_PICK_INDEX" in os.environ
    ):
        pick_preview(int(sys.argv[2]))
        return 0
    parser = argparse.ArgumentParser(prog="blocks", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    schemas = commands.add_parser("schema", help="print a JSON protocol schema")
    schema_kinds = {
        "presentation": schema,
        "picker": picker_schema,
        "result": result_schema,
    }
    schemas.add_argument(
        "kind", choices=schema_kinds, nargs="?", default="presentation"
    )
    pick = commands.add_parser(
        "pick", help="resolve a searchable branch into a presentation"
    )
    pick.add_argument(
        "catalog", nargs="?", default="-", help="picker JSON file (default: stdin)"
    )
    selection = pick.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--interactive",
        action="store_true",
        help="browse with fzf and preview focused options",
    )
    selection.add_argument("--value", help="select an exact option ID")
    pick.add_argument(
        "--plain", action="store_true", help="disable picker and preview colors"
    )
    pick.add_argument(
        "--request-only",
        action="store_true",
        help="return the selected request directly to the caller",
    )
    pick.add_argument(
        "--provider",
        nargs=argparse.REMAINDER,
        metavar="ARG",
        help="last option: program and arguments that turn a request into a presentation",
    )
    render = commands.add_parser(
        "render", help="display a presentation in the terminal"
    )
    run = commands.add_parser("run", help="collect answers and print a JSON result")
    ask = commands.add_parser("ask", help="ask one question and print a JSON result")
    ask.add_argument("id", help="question ID used in the answer object")
    ask.add_argument("label", help="question shown to the person")
    ask.add_argument(
        "--options",
        metavar="FILE",
        help="JSON array of value/label pairs (- for stdin)",
    )
    for command in (render, run):
        command.add_argument(
            "document", nargs="?", default="-", help="JSON file (default: stdin)"
        )
    for command in (render, run, ask):
        command.add_argument(
            "--plain", action="store_true", help="use the plain text layout"
        )
    for command in (run, ask):
        mode = command.add_mutually_exclusive_group(required=command is run)
        mode.add_argument(
            "--answers", metavar="FILE", help="read a JSON answer object (- for stdin)"
        )
        mode.add_argument(
            "--interactive",
            action="store_true",
            help="prompt if visible, otherwise return input_required (default for ask)",
        )
    args = parser.parse_args()
    if args.command == "schema":
        print(json.dumps(schema_kinds[args.kind](), indent=2))
        return 0
    if args.command == "pick":
        if args.provider == [] or (args.provider and args.request_only):
            parser.error(
                "--provider needs a program and cannot accompany --request-only"
            )
        title, branches = catalog(read_json(args.catalog))
        provider: list[str] = args.provider or []
        value = (
            browse(title, branches, provider, args.request_only, args.plain)
            if args.interactive
            else args.value
        )
        if value not in branches:
            raise Invalid(f"unknown picker value {value!a}")
        branch = branches[value]
        if args.request_only and branch.request is None:
            raise Invalid(f"{value} has no request")
        print(
            json.dumps(
                branch.request if args.request_only else branch.resolve(provider)
            )
        )
        return 0
    source = args.options if args.command == "ask" else args.document
    if args.command != "render" and args.answers == source == "-":
        parser.error("only one input can use stdin")
    if args.command == "ask":
        block: dict[str, object] = {"type": "input", "id": args.id, "label": args.label}
        if source is not None:
            block.update(type="choice", options=read_json(source))
        document = {"version": 1, "blocks": [block]}
    else:
        document = read_json(source)
    stream = sys.stdout if args.command == "render" else sys.stderr
    width = os.get_terminal_size(stream.fileno()).columns if stream.isatty() else None
    styled = (
        width is not None
        and not args.plain
        and not os.environ.get("NO_COLOR")
        and os.environ.get("TERM") != "dumb"
        and stream.encoding.lower().replace("-", "") == "utf8"
    )
    parts = presentation(document, width, styled)
    if args.command == "render":
        for part in parts:
            if isinstance(part, str):
                print(part)
        return 0
    if args.answers is not None:
        answers = supplied_answers(parts, read_json(args.answers))
    elif not any(isinstance(part, Question) for part in parts) or (
        sys.stderr.isatty() and sys.stdin.isatty() and source != "-"
    ):
        answers = interact(parts, sys.stdin, sys.stderr, styled)
    elif not sys.stderr.isatty():
        return input_required(document)
    else:
        # A piped document leaves stdin at EOF. Read keys from the terminal.
        terminal = "CONIN$" if os.name == "nt" else "/dev/tty"
        with ExitStack() as stack:
            try:
                keyboard = stack.enter_context(open(terminal, encoding="utf-8"))
            except OSError as error:
                if error.errno in (
                    errno.ENXIO,
                    errno.ENODEV,
                    errno.ENOENT,
                    errno.ENOTTY,
                ):
                    return input_required(document)
                raise
            answers = interact(parts, keyboard, sys.stderr, styled)
    if isinstance(answers, Declined):
        print("blocks: declined", file=sys.stderr)
        return 4
    print(json.dumps({"version": 1, "answers": answers}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        sys.stderr.write("\nblocks: cancelled\n")
        raise SystemExit(130)
    except (OSError, ValueError, RecursionError) as error:
        sys.stderr.write(f"blocks: {error}\n")
        raise SystemExit(2)
