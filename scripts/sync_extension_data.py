#!/usr/bin/env python3
"""Copies the shared knowledge base into the extension bundle.

V1 and V2 must never disagree about what a field means, so the JSON files and the DOM
extraction script have exactly one source of truth: src/jobwrapper/data/. Run this after
editing any of them (or after scripts/build_field_catalog.py).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jobwrapper" / "data"
DEST = ROOT / "extension" / "shared" / "data"

FILES = ["field_catalog.json", "ats_maps.json", "question_patterns.json",
         "skill_taxonomy.json", "extract_fields.js"]

DEST.mkdir(parents=True, exist_ok=True)
manifest = {}
for name in FILES:
    source = SRC / name
    shutil.copy2(source, DEST / name)
    manifest[name] = source.stat().st_size
    print(f"  {name:24} {source.stat().st_size:>8,} bytes")

(DEST / "VERSION.json").write_text(json.dumps({
    "generated_from": "src/jobwrapper/data",
    "files": manifest,
    "catalog_version": json.loads((SRC / "field_catalog.json").read_text())["version"],
}, indent=2))
print(f"synced {len(FILES)} file(s) -> {DEST.relative_to(ROOT)}")
