#!/usr/bin/env python3
"""Install the freshly built wheel into a throwaway venv and smoke it.

Run from the repo root after `python -m build`; expects exactly one wheel in
dist/. Verifies: clean-venv install resolves, package imports, the knowledge
base ships inside the wheel, the cost matrix loads from it, the MCP server
module imports, and the CLI entry point is functional.
"""

from __future__ import annotations

import glob
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DIST = REPO / "dist"


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def main() -> int:
    wheels = sorted(glob.glob(str(DIST / "*.whl")))
    if len(wheels) != 1:
        print(f"expected exactly one wheel in dist/, found: {wheels}")
        return 1
    wheel = wheels[0]

    with tempfile.TemporaryDirectory(prefix="costmodel-smoke-") as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.create(venv_dir, with_pip=True)
        py = str(venv_dir / "bin" / "python")

        run([py, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
        run([py, "-m", "pip", "install", "--quiet", wheel])

        # Imports + version
        run([py, "-c",
             "import plat_costmodel; "
             "from plat_costmodel.estimator import estimate_unit; "
             "from plat_costmodel import server; "
             "print('import-ok', plat_costmodel.__version__)"])

        # Knowledge base ships in the wheel and the matrix reads it
        run([py, "-c",
             "from plat_costmodel.matrix import _KB_PATH; "
             "assert _KB_PATH.exists(), f'missing {_KB_PATH}'; "
             "print('kb-ok', _KB_PATH)"])

        # Deterministic cost lookup works end to end
        run([py, "-c",
             "from plat_costmodel.matrix import lookup_range; "
             "r = lookup_range('standard_value_add', 'medium', 'basic'); "
             "print('matrix-ok', r)"])

        # CLI entry point
        run([str(venv_dir / "bin" / "plat-cost"), "--help"])

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())