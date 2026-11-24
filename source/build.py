#!/usr/bin/env python3
"""Build the Jiaodong field guide for the web or for offline reading."""

import argparse
from functools import cache
from hashlib import sha256
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


def web_asset_writer(output):
    media = output / "media"
    media.mkdir(parents=True, exist_ok=True)

    @cache
    def asset_url(path):
        contents = path.read_bytes()
        digest = sha256(contents).hexdigest()[:20]
        target = media / f"{digest}{path.suffix}"
        if not target.is_file() or target.read_bytes() != contents:
            target.write_bytes(contents)
        return target.relative_to(output).as_posix()

    return asset_url


def build(output, web=False):
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
    if web:
        offline = output / "offline.html"
        offline.write_text(document, encoding="utf-8")
        document = FieldGuide(
            spec, art, coastline["rings"], folder, asset_url=web_asset_writer(output), offline_href=offline.name
        ).render()
    article = output / "index.html"
    article.write_text(document, encoding="utf-8")
    return article


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--web", action="store_true", help="publish cacheable images and an offline download")
    args = parser.parse_args()
    output = args.output or PROJECT / ("_site" if args.web else "dist")
    print(build(output.resolve(), web=args.web))
