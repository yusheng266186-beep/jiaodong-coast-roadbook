#!/usr/bin/env python3
"""Validate, build, or recover a self-contained travel roadbook."""

import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from urllib.parse import unquote

sys.dont_write_bytecode = True

from exports import budget_csv, calendars, export_markdown, json_text, waypoint_files
from model import Validator
from render import Renderer, labels_for, load_presentation, stylesheet_resources


class ItineraryBlock(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.reading = False
        self.count = 0
        self.fragments = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "script" and fields.get("id") == "itinerary-data" and fields.get("type") == "application/json":
            self.count += 1
            self.reading = True

    def handle_data(self, content):
        if self.reading:
            self.fragments.append(content)

    def handle_endtag(self, tag):
        if tag == "script":
            self.reading = False


def source_candidates(value):
    """Read srcset URLs while keeping the comma inside a data URL."""
    while value := value.lstrip(" ,\t\n\r\f"):
        parts = value.split(None, 1)
        url, tail = parts[0], parts[1] if len(parts) > 1 else ""
        yield url.rstrip(",")
        value = tail if url.endswith(",") else tail.partition(",")[2]


class PageCheck(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = Counter()
        self.references = set()
        self.resources = set()
        self.in_style = False

    def asset(self, tag, attribute, url, inline=False):
        url = url.strip()
        if url and not (inline and url.lower().startswith("data:")):
            self.resources.add(f"<{tag}> {attribute}={url[:100]}")

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "style":
            self.in_style = True
        if fields.get("id"):
            self.ids[fields["id"]] += 1
        href = (fields.get("href") or fields.get("xlink:href") or "").strip()
        if href.startswith("#") and href != "#":
            self.references.add(unquote(href[1:].partition("?")[0]))
        for attr in ("aria-labelledby", "aria-describedby", "aria-controls", "for"):
            self.references.update((fields.get(attr) or "").split())
        if fields.get("src"):
            self.asset(tag, "src", fields["src"], inline=tag in ("img", "source", "input"))
        for url in source_candidates(fields.get("srcset") or ""):
            self.asset(tag, "srcset", url, inline=True)
        if fields.get("poster"):
            self.asset(tag, "poster", fields["poster"], inline=True)
        if tag in ("use", "image", "link") and href and not href.startswith("#"):
            self.asset(tag, "href", href, inline=tag == "image")
        self.resources.update(f"<{tag}> style {resource}" for resource in stylesheet_resources(fields.get("style") or ""))

    def handle_data(self, data):
        if self.in_style:
            self.resources.update(f"<style> {resource}" for resource in stylesheet_resources(data))

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def check(self, html):
        self.feed(html)
        self.close()
        duplicate = [key for key, count in self.ids.items() if count > 1]
        missing = self.references.difference(self.ids)
        findings = [
            *(f"重复锚点 #{key}" for key in sorted(duplicate)),
            *(f"找不到锚点 #{key}" for key in sorted(missing)),
            *(f"需要内嵌的资源 {resource}" for resource in sorted(self.resources)),
        ]
        if findings:
            raise ValueError("生成网页需要修正，请检查版式与链接\n" + "\n".join(f"- {finding}" for finding in findings))


def reject_constant(value):
    raise ValueError(f"JSON 中不支持 {value}")


def load_json(source):
    return json.loads(source, parse_constant=reject_constant)


def validated(spec, directory):
    findings = Validator().validate(spec, directory)
    if findings:
        raise ValueError("路书数据需要修正\n" + "\n".join(f"- {finding}" for finding in findings))
    return spec


def load_spec(path):
    return validated(load_json(path.read_text(encoding="utf-8-sig")), path.parent)


def build_files(spec, presentation=None, *, reader=False):
    places = {place["id"]: place for place in spec.get("places", [])}
    files = {
        "itinerary.json": json_text(spec),
        "roadbook.md": export_markdown(spec, places, labels_for(spec)),
        "budget.csv": budget_csv(spec),
        **waypoint_files(spec),
        **calendars(spec, places),
    }
    html = Renderer(spec, files, presentation, reader=reader).render()
    PageCheck().check(html)
    files["roadbook.html"] = html
    return files


def generated_filename(name):
    return name in {"roadbook.html", "roadbook.md", "itinerary.json", "budget.csv", "places.gpx", "places.geojson"} or (
        name.startswith("calendar-") and name.endswith(".ics")
    )


def require_generated_dir(destination, trip_id):
    paths = list(destination.iterdir())
    if not paths:
        return
    if any(not path.is_file() or path.is_symlink() or not generated_filename(path.name) for path in paths):
        raise ValueError("成品目录中含其他文件，请选择新目录")
    try:
        old = load_json((destination / "itinerary.json").read_text(encoding="utf-8"))
        same_trip = old.get("schema_version") == 1 and old["trip"]["id"] == trip_id
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        same_trip = False
    if not same_trip or not (destination / "roadbook.html").is_file():
        raise ValueError("覆盖适用于由此 Skill 构建的同一趟路书")


def publish_local(files, destination, replace, trip_id):
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.parent / ("." + destination.name + ".roadbook-lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError("该目录已有构建正在写入，请选另一成品目录") from error
    try:
        had_previous = destination.exists()
        if destination.is_symlink() or (had_previous and not destination.is_dir()):
            raise ValueError("请为成品选择普通目录")
        if had_previous:
            if not replace and any(destination.iterdir()):
                raise ValueError("成品目录已有内容，选择新目录或用 --replace 更新同一趟路书")
            require_generated_dir(destination, trip_id)
        with TemporaryDirectory(prefix=".roadbook-", dir=destination.parent) as tmp:
            scratch = Path(tmp)
            ready = scratch / "ready"
            backup = scratch / "previous"
            ready.mkdir()
            for filename, body in files.items():
                (ready / filename).write_bytes(body.encode("utf-8"))
            if had_previous:
                destination.rename(backup)
            try:
                ready.rename(destination)
            except OSError:
                if had_previous and not destination.exists():
                    backup.rename(destination)
                raise
    finally:
        lock.rmdir()


def recover(input_path, target):
    parser = ItineraryBlock()
    parser.feed(input_path.read_text(encoding="utf-8"))
    parser.close()
    if parser.count != 1 or not parser.fragments:
        raise ValueError("这份 HTML 中没有找到唯一的旅行路书数据")
    spec = validated(load_json("".join(parser.fragments)), input_path.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as output:
            output.write(json_text(spec))
    except FileExistsError as error:
        raise ValueError(f"提取路径已有文件，请为恢复的行程指定新文件：{target}") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate", help="check itinerary JSON")
    validate.add_argument("input", type=Path)
    validate.add_argument("--presentation", type=Path, help="also check the rendered layout without writing output")
    build = subcommands.add_parser("build", help="generate HTML and travel files")
    build.add_argument("input", type=Path)
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--presentation", type=Path, help="use a local, authored CSS and HTML layout directory")
    build.add_argument("--replace", action="store_true", help="replace generated files for the same trip")
    for command in (validate, build):
        command.add_argument("--reader", action="store_true", help="keep trip essentials in the HTML and export supporting files alongside it")
    extract = subcommands.add_parser("extract", help="recover editable JSON from a generated HTML file")
    extract.add_argument("input", type=Path)
    extract.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        if args.command == "extract":
            recover(args.input, args.output)
            print(args.output.absolute())
        else:
            spec = load_spec(args.input)
            presentation = load_presentation(args.presentation) if args.presentation else None
            if args.command == "validate":
                render_page = presentation is not None or args.reader
                if render_page:
                    build_files(spec, presentation, reader=args.reader)
                scope = "itinerary and presentation" if render_page else "itinerary"
                print(f"Valid {scope} · {len(spec['routes'])} route(s)")
            else:
                files = build_files(spec, presentation, reader=args.reader)
                publish_local(files, args.output.absolute(), args.replace, spec["trip"]["id"])
                for filename in files:
                    print(args.output.absolute() / filename)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
