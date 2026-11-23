"""Build the small C estimator library used by the Python backend."""
from __future__ import annotations

import os
import pathlib
import shlex
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE = ROOT / "native" / "pricing.c"
OUT_DIR = ROOT / "instance"
OUT_DIR.mkdir(exist_ok=True)

if sys.platform == "win32":
    output = OUT_DIR / "scenesnap_pricing.dll"
else:
    output = OUT_DIR / "libscenesnap_pricing.so"

compiler = shlex.split(os.environ.get("CC", "cc"))
args = compiler + ["-O2", "-fPIC", "-shared", str(SOURCE), "-o", str(output), "-lm"]
if sys.platform == "darwin":
    args = compiler + ["-O2", "-dynamiclib", str(SOURCE), "-o", str(OUT_DIR / "libscenesnap_pricing.dylib"), "-lm"]
    output = OUT_DIR / "libscenesnap_pricing.dylib"

subprocess.run(args, check=True)
print(f"Built {output}")
