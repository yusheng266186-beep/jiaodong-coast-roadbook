#!/usr/bin/env python3
"""Build the Jiaodong field guide as one offline HTML file."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parent
PROJECT = SOURCE.parent


def roadbook_directory():
    candidates = (
        os.environ.get("ROADBOOK_SKILL"),
        SOURCE,
        PROJECT.parent / ".agents" / "skills" / "travel-roadbook",
        Path.home() / ".codex" / "skills" / "travel-roadbook",
    )
    for candidate in candidates:
        if candidate and (Path(candidate) / "scripts" / "roadbook.py").is_file():
            return Path(candidate)
    raise SystemExit("找不到 travel-roadbook 构建器，请把 ROADBOOK_SKILL 设为技能文件夹。")


def build(output):
    sys.path.insert(0, str(roadbook_directory() / "scripts"))
    from roadbook import PageCheck, load_spec

    sys.path.insert(0, str(SOURCE / "folio"))
    from render_folio import FieldGuide

    folder = SOURCE / "folio"
    spec = load_spec(SOURCE / "itinerary.json")
    art = json.loads((folder / "art.json").read_text(encoding="utf-8"))
    coastline = json.loads((folder / "shoreline.json").read_text(encoding="utf-8"))
    document = FieldGuide(spec, art, coastline["rings"], folder).render()
    PageCheck().check(document)
    output.mkdir(parents=True, exist_ok=True)
    article = output / "index.html"
    article.write_text(document, encoding="utf-8")
    return article


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "dist")
    args = parser.parse_args()
    print(build(args.output.resolve()))
