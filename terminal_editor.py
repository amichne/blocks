# /// script
# requires-python = ">=3.10"
# dependencies = ["prompt-toolkit>=3.0.50,<4"]
# [tool.uv]
# no-build = true
# [[tool.uv.index]]
# name = "pypi"
# url = "https://pypi.org/simple"
# default = true
# ///
"""Edit a prefilled document on the terminal and emit its UTF-8 bytes."""

import asyncio
import selectors
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.output.defaults import create_output


def main() -> None:
    initial = Path(sys.argv[1]).read_bytes().decode("utf-8")
    session = PromptSession[str](output=create_output(stdout=sys.stderr))
    print(
        "Edit the draft. Enter inserts a line. Esc then Enter accepts. Ctrl+C cancels.",
        file=sys.stderr,
    )
    # Darwin's kqueue cannot watch /dev/tty when the document arrived on stdin.
    if sys.platform == "darwin":
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        try:
            value = loop.run_until_complete(
                session.prompt_async("> ", default=initial, multiline=True)
            )
        finally:
            loop.close()
    else:
        value = session.prompt("> ", default=initial, multiline=True)
    sys.stdout.buffer.write(value.encode("utf-8"))


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(130)
