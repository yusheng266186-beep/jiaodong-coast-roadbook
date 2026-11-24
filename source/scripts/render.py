"""Render the offline, progressively enhanced roadbook."""

from base64 import b64encode
from html import escape
import json
from pathlib import Path
import re
from string import Template

from exports import average, estimate
from model import CLOCK, budget_range, budget_totals, group_day_items, item_start, multiplier, offset_time, return_plan_values


ASSETS = Path(__file__).resolve().parents[1] / "assets"
FONT_URL = re.compile(r"""url\(\s*(["'])(fonts/[^/"'\\\x00-\x1f]+\.woff2)\1\s*\)""", re.IGNORECASE)
CSS_RESOURCES = re.compile(
    r"""/\*.*?\*/|(?P<import>@import\b)|\burl\(\s*(?P<url>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^)]*)\s*\)"""
    r"""|(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(?P<function>[-\w]+)\(|(?P<close>\))""",
    re.IGNORECASE | re.DOTALL,
)


def stylesheet_resources(css):
    functions = []
    for match in CSS_RESOURCES.finditer(css):
        if match["import"]:
            yield "@import"
        if match["function"]:
            functions.append(match["function"].lower())
        elif match["close"] and functions:
            functions.pop()
        resource = match["url"]
        if match["string"] and functions and functions[-1] in ("image-set", "-webkit-image-set"):
            resource = match["string"]
        if resource:
            url = resource.strip().strip("\"'").strip()
            if url and not url.lower().startswith(("data:", "#")):
                yield f"url({url[:100]})"


def embed_fonts(style, directory):
    """Inline local WOFF2 references for a single-file presentation."""
    embedded = {}

    def replace(match):
        relative = match[2]
        if relative not in embedded:
            data = (directory / relative).read_bytes()
            if data[:4] != b"wOF2":
                raise ValueError(f"版式字体需要为 WOFF2 文件：{relative}")
            embedded[relative] = b64encode(data).decode("ascii")
        return f'url("data:font/woff2;base64,{embedded[relative]}")'

    style = FONT_URL.sub(replace, style)
    notice = directory / "fonts" / "OFL.txt"
    if embedded and notice.is_file():
        text = notice.read_text(encoding="utf-8").replace("*/", "* /").rstrip()
        style = f"/*\n{text}\n*/\n{style}"
    return style


def load_presentation(directory):
    style = embed_fonts((directory / "style.css").read_text(encoding="utf-8"), directory)
    if "</style" in style.lower():
        raise ValueError("版式 style.css 需为单独的 CSS，无 HTML 标签")
    external = list(dict.fromkeys(stylesheet_resources(style)))
    if external:
        raise ValueError("版式 style.css 含未内嵌的资源 " + "、".join(external) +
                         "。把照片写入行程数据，字体用 url(\"fonts/文件.woff2\")，其他样式直接写在版式内。")
    templates = {}
    panels = ("cover", "story", "opening", "chapter", "day", "places", "field", "return")
    paths = [directory / (name + ".html") for name in panels]
    paths.extend(sorted(directory.glob("chapter-*.html")))
    paths.extend(sorted(directory.glob("day-*.html")))
    for path in paths:
        if path.is_file():
            templates[path.stem] = Template(path.read_text(encoding="utf-8"))
    if ("opening" in templates) != ("chapter" in templates):
        raise ValueError("长篇故事版式需同时提供 opening.html 和 chapter.html")
    if "opening" not in templates and ("story" in templates or any(name.startswith("chapter-") for name in templates)):
        raise ValueError("story.html 和独立章节需配合 opening.html 和 chapter.html 使用")
    if "cover" in templates and "opening" in templates:
        raise ValueError("封面版式与长篇故事开场使用同一个页面入口，请选用其中一种")
    required = {
        "cover": ("title",), "opening": ("title",), "chapter": ("title",), "day": ("agenda",),
        "story": ("opening", "chapters"), "places": ("heading", "controls", "cards"),
        "field": ("heading", "events"), "return": ("head",),
    }
    for name, template in templates.items():
        slots = template_slots(template)
        anchors = required[name.split("-", 1)[0]]
        changed = ["$" + anchor for anchor in anchors if slots.count(anchor) != 1]
        if changed:
            raise ValueError(f"版式 {name}.html 的 {', '.join(changed)} 需要各出现一次")
    return style, templates


CHINESE = {
    "traveler": "人同行", "routes": "行程", "route_choice": "选择路线",
    "places": "地点", "budget": "计划预算", "tasks": "预约与清单", "tips": "到当地怎么玩",
    "sources": "来源与核验", "search": "搜索路书", "search_example": "搜地点、车次、美食或待办",
    "results": "条结果", "no_results": "暂无匹配内容", "today": "今日", "overnight": "夜宿",
    "alternative": "临场备选", "replaces": "替换", "change_cost": "费用变化", "planned": "计划", "observed": "查询快照",
    "fallback_where": "备选去向", "fallback_resume": "接回原行程", "fallback_decision": "判断节点",
    "estimated": "估算", "pending": "待核验", "booked": "已订", "paid": "已付",
    "visit": "游览", "meal": "餐饮", "transport": "交通", "rest": "休息", "buffer": "机动",
    "stay": "住宿", "other": "其他", "food": "美食", "sight": "景点", "critical": "优先处理",
    "subtotal": "已列金额", "per_person": "人均", "group": "整组", "units": "按数量",
    "approximate": "大致位置", "copy": "复制地址", "copied": "已复制",
    "copy_error": "可选中地址后复制", "favorite": "收藏", "favorites": "只看收藏",
    "all_days": "全部日期", "all_categories": "全部类型",
    "map_note": "点位表示相对方位。按天查看时，虚线标出原定停留顺序。",
    "no_points": "当前筛选没有可画点位，地点卡仍可查看。",
    "due": "截止", "arrive_by": "最晚到达", "downloads": "导出", "calendar": "路线日历", "print": "打印当前路线",
    "calendar_tip": "日历选一条路线导入。改走其他路线时，先移除此前导入的日历条目。",
    "share": "复制当前位置", "share_file": "把 HTML 文件一起发给同行人。位置锚点为",
    "log": "旅途记录", "notes": "旅行笔记", "expenses": "实际开销与均摊",
    "placeholder": "把需要记住的事留在这里", "expense_name": "支出名称",
    "amount": "金额", "currency": "币种", "payer": "垫付人", "member": "同行者",
    "add": "添加", "remove": "移除", "record_export": "导出本地记录", "record_import": "恢复本地记录",
    "replace_records": "用文件里的记录替换当前浏览器的勾选、收藏、笔记和开销？",
    "invalid_records": "请选择这份路书导出的记录文件。", "restored": "记录已恢复。",
    "saved_locally": "记录只保存在当前浏览器。换设备时，先导出记录文件。",
    "storage_unavailable": "当前浏览器只能临时保留记录，请及时导出备份。",
    "trip_expense_error": "请填写有效币种及该币种支持的小数位数。", "receive": "应收",
    "owe": "应付", "balance": "已平", "updated": "更新", "go_to_content": "跳到行程",
}
ENGLISH = {
    "traveler": "travelers", "routes": "Itinerary", "route_choice": "Choose a route",
    "places": "Places", "budget": "Planned budget", "tasks": "Bookings and checklist", "tips": "Field notes",
    "sources": "Sources and checks", "search": "Search the roadbook", "search_example": "Find a place, train, dish or task",
    "results": "matches", "no_results": "No matches", "today": "Today", "overnight": "Overnight",
    "alternative": "Fallback", "replaces": "Replaces", "change_cost": "Cost change", "planned": "Planned", "observed": "Checked snapshot",
    "fallback_where": "Fallback destination", "fallback_resume": "Rejoin the itinerary", "fallback_decision": "Decision point",
    "estimated": "Estimate", "pending": "To check", "booked": "Booked", "paid": "Paid",
    "visit": "Visit", "meal": "Meal", "transport": "Transport", "rest": "Rest", "buffer": "Buffer",
    "stay": "Stay", "other": "Other", "food": "Food", "sight": "Sights", "critical": "Do first",
    "subtotal": "Known amounts", "per_person": "Per traveler", "group": "Group", "units": "Per unit",
    "approximate": "Approximate", "copy": "Copy address", "copied": "Copied",
    "copy_error": "Select the address to copy it", "favorite": "Favorite", "favorites": "Favorites only",
    "all_days": "All days", "all_categories": "All types",
    "map_note": "Pins show relative positions. In a day view, dashed lines show the planned stop order.",
    "no_points": "No plottable points match. The place cards are still available.",
    "due": "Due", "arrive_by": "Arrive by", "downloads": "Exports", "calendar": "Route calendar", "print": "Print selected route",
    "calendar_tip": "Import a single route calendar. Remove the previous import when changing routes.",
    "share": "Copy current location", "share_file": "Share the HTML file with your companions. Location anchor",
    "log": "Travel log", "notes": "Notes", "expenses": "Actual expenses and equal split",
    "placeholder": "Keep a note for the trip", "expense_name": "Description",
    "amount": "Amount", "currency": "Currency", "payer": "Paid by", "member": "Traveler",
    "add": "Add", "remove": "Remove", "record_export": "Export local records", "record_import": "Restore local records",
    "replace_records": "Replace this browser’s checklist, favorites, notes and expenses with the file?",
    "invalid_records": "Choose a records file exported from this roadbook.", "restored": "Records restored.",
    "saved_locally": "Records stay in this browser. Export them before switching devices.",
    "storage_unavailable": "Browser storage is unavailable. Export these records before closing.",
    "trip_expense_error": "Use a valid currency and its supported decimal precision.", "receive": "Receives",
    "owe": "Owes", "balance": "Settled", "updated": "Updated", "go_to_content": "Skip to itinerary",
}


def labels_for(spec):
    return ENGLISH if spec["trip"].get("language") == "en" else CHINESE


def quoted(text):
    return escape(text, quote=True)


def json_for_script(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")


def paragraph(value, style=""):
    return f'<p class="{style}">{quoted(value)}</p>' if value else ""


def heading_text(labels, day, index):
    if day.get("date"):
        return day["date"]
    return f"Day {index}" if labels is ENGLISH else f"第 {index} 天"


def icon(name):
    return f'<span class="icon icon-{name}" aria-hidden="true"></span>'


def template_slots(template):
    if template is None:
        return ()
    return tuple(match["named"] or match["braced"] for match in template.pattern.finditer(template.template)
                 if match["named"] or match["braced"])


def select_field(key, label, options, name=""):
    form_name = f' name="{name}"' if name else ""
    return (
        f'<div class="select-field"><label for="{key}" id="{key}-label">{label}</label>'
        f'<div class="select-shell"><select id="{key}"{form_name} data-select-menu aria-labelledby="{key}-label">'
        f'{options}</select></div></div>'
    )


def external_links(links):
    return "".join(
        f'<a class="chip" href="{quoted(link["url"])}" target="_blank" rel="noopener noreferrer">'
        f'{quoted(link["label"])}{icon("outward")}</a>'
        for link in links
    )


def copy_button(address, label):
    if not address:
        return ""
    return f'<button class="chip js-only" type="button" data-copy="{quoted(address)}">{icon("copy")}{label}</button>'


def evidence(item, sources):
    return "".join(
        f'<a class="evidence" href="#source-{key}">{quoted(sources[key]["title"])}{icon("outward")}</a>'
        for key in item.get("source_ids", [])
    )


def actions(item, sources, extra=""):
    content = external_links(item.get("links", [])) + extra + evidence(item, sources)
    return f'<div class="actions">{content}</div>' if content else ""


def download(filename, label):
    return f'<button class="chip" type="button" data-download="{quoted(filename)}">{icon("download")}{quoted(label)}</button>'


def clock_face(value):
    original = quoted(value)
    if CLOCK.fullmatch(value):
        return f'<time datetime="{original}" class="event-clock">{original}</time>'
    parsed = offset_time(value)
    offset = parsed.isoformat(timespec="seconds")[19:]
    return (
        f'<time datetime="{original}" class="event-clock">'
        f'<span class="clock-date">{parsed.date()}</span>'
        f'<strong>{parsed:%H:%M}</strong><span class="clock-offset">UTC{offset}</span></time>'
    )


def item_clocks(item, separator=""):
    start = item_start(item)
    if not start:
        return ""
    end = item.get("end")
    return clock_face(start) + (separator + clock_face(end) if end else "")


class Renderer:
    def __init__(self, spec, files, presentation=None, *, reader=False):
        self.spec = spec
        self.trip = spec["trip"]
        self.scenes = self.trip.get("scenes", [])
        self.reader = reader
        self.files = {} if reader else files
        self.labels = labels_for(spec)
        self.places = {place["id"]: place for place in spec.get("places", [])}
        self.activities = {
            route["id"]: {item["id"]: (day, item) for day in route["days"] for item in day["items"]}
            for route in spec["routes"]
        }
        self.has_map_points = any(place.get("point") for place in self.places.values())
        self.sources = {source["id"]: source for source in spec.get("sources", [])}
        self.english = self.labels is ENGLISH
        self.custom_style, self.layout = presentation or ("", {})
        self.cover_slots = template_slots(self.layout.get("cover") or self.layout.get("opening"))
        self.day_decisions = {}
        if "plans" not in self.cover_slots:
            targets = self.trip.get("decision", {}).get("days", {})
            for route in spec["routes"]:
                key = route["id"]
                if key in targets:
                    index = targets[key]
                    template = self.layout.get(self.day_variant(route["days"][index - 1]))
                    if "decision" in template_slots(template):
                        self.day_decisions[key] = f"route-{key}--day-{index}--decision"
            if len(self.day_decisions) != len(spec["routes"]):
                self.day_decisions.clear()
        if "opening" in self.layout and not self.scenes:
            raise ValueError("长篇故事版式需要具有封面和 trip.scenes 的驻地纪行")

    def day_variant(self, day):
        for item in day["items"]:
            name = f'day-{item["id"]}'
            if name in self.layout:
                return name
        return "day"

    def compose(self, kind, **slots):
        try:
            return self.layout[kind].substitute(slots)
        except (KeyError, ValueError) as error:
            raise ValueError(f"请检查版式 {kind}.html 的占位符：{error}") from error

    def local(self, chinese, english):
        return english if self.english else chinese

    def text(self, key):
        return self.labels[key]

    def cover_days(self):
        if "days" not in self.cover_slots:
            return ""
        routes = self.spec["routes"]
        return "".join(
            f'<div data-index-route="{route["id"]}">'
            f'{paragraph(route["name"], "cover-route-option") if len(routes) > 1 else ""}'
            f'{self.day_navigation(route, overview=True)}</div>'
            for route in routes
        )

    def photo_credit(self, record):
        credit = quoted(record["credit"])
        if record.get("url"):
            credit = f'<a class="text-link" href="{quoted(record["url"])}" rel="noopener noreferrer">{credit}{icon("outward")}</a>'
        return credit

    def photo_image(self, record, eager=False):
        loading = ' fetchpriority="high"' if eager else ' loading="lazy" decoding="async"'
        axes = (("focal", "--photo-focal"), ("mobile_focal", "--photo-mobile-focal"))
        positions = [
            f'{variable}:{record[field][0]}% {record[field][1]}%'
            for field, variable in axes if field in record
        ]
        position = f' style="{";".join(positions)}"' if positions else ""
        return f'<img src="{record["data"]}" alt="{quoted(record["alt"])}"{position}{loading}>'

    def photo(self, record, style, eager=False):
        image = self.photo_image(record, eager)
        if style == "day-photo":
            image = f'<div class="day-image">{image}</div>'
        if style == "story-photo":
            image = f'<div class="story-image">{image}</div>'
        return f'<figure class="{style}">{image}<figcaption>{self.photo_credit(record)}</figcaption></figure>'

    def hero(self):
        cover = self.trip.get("cover")
        days = [len(route["days"]) for route in self.spec["routes"]]
        count = str(days[0]) if min(days) == max(days) else f"{min(days)}–{max(days)}"
        meta = self.local(f'{count} 天 · {self.trip["travelers"]} 人同行',
                          f'{count} days · {self.trip["travelers"]} {self.text("traveler")}')
        journey = self.trip.get("theme") == "journey"
        start = self.local("查看每日行程", "Explore the itinerary")
        open_map = self.local("查看地图", "View map") if self.has_map_points else self.local("查看地点", "View places")
        secondary = f'<a class="hero-ghost button-link" href="#places" data-view="map">{open_map}{icon("outward")}</a>' if self.places else ""
        base = ""
        date_range = ""
        endpoints = {(route["days"][0].get("date"), route["days"][-1].get("date")) for route in self.spec["routes"]}
        if len(endpoints) == 1:
            first, last = endpoints.pop()
            if first and last:
                date_range = f'<time>{quoted(first)}</time>'
                if first != last:
                    date_range += f' <span class="date-range-end">— <time>{quoted(last)}</time></span>'
        start_link = f'<a class="hero-open button-link" href="#routes" data-view="journal">{start}{icon("down")}</a>'
        if journey:
            primary_id = self.spec["routes"][0]["id"]
            start_link = f'<a class="hero-open button-link" href="#route-{primary_id}" data-open-route>{start}{icon("down")}</a>'
            days_for_route = [route["days"] for route in self.spec["routes"]]
            overnight = {tuple(day["stay_id"] for day in route_days if day.get("stay_id")) for route_days in days_for_route}
            if len(overnight) == 1:
                nights = overnight.pop()
                if len(nights) > 1 and len(set(nights)) == 1:
                    label = self.local(f'{len(nights)} 晚同住', f'{len(nights)} nights based at')
                    base = f'<p class="hero-base">{label} {self.place_ref(nights[0])}</p>'
            if self.trip.get("decision") and not self.day_decisions:
                label = self.local("比较出行方案", "Compare routes")
                secondary = f'<a class="hero-ghost button-link" href="#route-decision">{label}{icon("down")}</a>'
        if "opening" in self.layout:
            start_link = f'<a class="hero-open button-link" href="#routes" data-view="journal">{start}{icon("down")}</a>'
            return self.story_hero(cover, meta, date_range, base, start_link, secondary)
        if "cover" in self.layout:
            intro = paragraph(self.trip.get("summary", ""), "intro")
            opening = self.compose(
                "cover", title=f'<h1 id="cover-title">{quoted(self.trip["title"])}</h1>',
                subtitle=paragraph(self.trip.get("subtitle", ""), "subtitle"),
                intro=intro, shared_start=self.shared_start() or intro,
                photo=self.photo(cover, "authored-photo", eager=True) if cover else "",
                meta=paragraph(meta, "hero-meta"),
                dates=f'<p class="cover-dates">{date_range}</p>' if date_range else "",
                base=base, actions=f'<div class="hero-actions">{start_link}{secondary}</div>',
                plans=self.route_decision(cover=True),
                return_preview=self.common_arrival() if "return_preview" in self.cover_slots else "",
                days=self.cover_days(), notice=paragraph(self.trip.get("notice", ""), "cover-notice"),
            )
            return f'<header class="hero authored-hero" id="top" aria-labelledby="cover-title">{opening}</header>'
        if date_range and journey:
            meta += f' · {date_range}'
        if self.scenes:
            return self.scene_hero(cover, meta, base, start, secondary)
        image = self.photo(cover, "cover", eager=True) if cover else ""
        title = f'<h1>{quoted(self.trip["title"])}</h1>'
        subtitle = paragraph(self.trip.get("subtitle", ""), "subtitle")
        intro = paragraph(self.trip.get("summary", ""), "intro")
        actions = f'<div class="hero-actions">{start_link}{secondary}</div>'
        cover_class = " with-cover" if cover else ""
        if not journey:
            return (
                f'<header class="hero folio-hero{cover_class}" id="top">'
                f'<div class="folio-heading">{subtitle}{title}</div>{image}'
                f'<div class="folio-details">{intro}<p class="hero-meta">{meta}</p>{actions}</div></header>'
            )
        return (
            f'<header class="hero{cover_class}" id="top">{image}<div class="hero-copy">{subtitle}{title}{intro}'
            f'<p class="hero-meta">{meta}</p>{base}{actions}</div></header>'
        )

    def scene_cards(self, chronological=False):
        targets = {}
        for route in self.spec["routes"]:
            for index, day in enumerate(route["days"], 1):
                if day.get("photo"):
                    for item in day["items"]:
                        targets.setdefault(item["id"], (route, index, day))
        def day_order(scene):
            route, index, _day = targets[scene["item_id"]]
            return route is not self.spec["routes"][0], index

        scenes = sorted(self.scenes, key=day_order) if chronological else self.scenes
        for scene in scenes:
            item_id = scene["item_id"]
            route, index, day = targets[item_id]
            route_id = route["id"]
            photo = day["photo"]
            date = day["date"][5:].replace("-", ".") if day.get("date") else heading_text(self.labels, day, index)
            stamp = date
            if route is not self.spec["routes"][0]:
                stamp = f'{route["name"]} · {stamp}'
            cta = self.local("查看当天安排", "View the day")
            link = (
                f'<a class="scene-link button-link" data-scene-item="{item_id}" data-scene-route="{route_id}" '
                f'href="#route-{route_id}--day-{index}"><span data-scene-date>{quoted(stamp)}</span>'
                f'<span>{cta}</span>{icon("down")}</a>'
            )
            yield scene, photo, date, link

    def story_hero(self, cover, meta, date_range, base, start_link, secondary):
        stops = []
        chapters = []
        schedule = self.local("逐日路书", "Day by day")
        dates = self.trip.get("decision", {}).get("days", {})
        targets = [
            {item["id"] for item in route["days"][dates[route["id"]] - 1]["items"]}
            for route in self.spec["routes"] if route["id"] in dates
        ]
        common_items = set.intersection(*targets) if len(targets) > 1 else set()
        decision_scene = next((scene["item_id"] for scene in self.scenes if scene["item_id"] in common_items), None)
        cards = list(self.scene_cards(chronological=True))
        for index, (scene, photo, date, link) in enumerate(cards):
            item_id = scene["item_id"]
            scene_id = "story-" + item_id
            label = quoted(scene["label"])
            stops.append(
                f'<a href="#{scene_id}" data-story-link>'
                f'<span class="story-index-date" id="story-date-{item_id}">{quoted(date)}</span>'
                f'<span>{label}</span></a>'
            )
            following = cards[index + 1][0] if index + 1 < len(cards) else None
            target, caption = "routes", schedule
            if following:
                target = "story-" + following["item_id"]
                caption = self.local(f'接着读 · {following["label"]}', f'Continue to {following["label"]}')
            next_link = (f'<a class="story-next button-link" data-story-next href="#{target}">'
                         f'<span>{quoted(caption)}</span>{icon("down")}</a>')
            variant = "chapter-" + item_id
            chapter = self.compose(
                variant if variant in self.layout else "chapter", label=label,
                title=f'<h2 class="story-title" id="{scene_id}-title">{quoted(scene["title"])}</h2>',
                intro=paragraph(scene["summary"], "story-intro"),
                photo=self.photo(photo, "story-photo"), day_link=link, next=next_link,
                compare=secondary if item_id == decision_scene and not self.day_decisions else "",
            )
            chapters.append(
                f'<section class="story-chapter" id="{scene_id}" data-chapter-label="{label}" '
                f'aria-labelledby="{scene_id}-title">{chapter}</section>'
            )
        nav_label = self.local("沿途章节", "Journey chapters")
        stops.append(f'<a href="#routes" class="story-to-route button-link" data-story-link>{schedule}{icon("down")}</a>')
        navigation = f'<nav class="story-index" aria-label="{nav_label}">{"".join(stops)}</nav>'
        lead = self.local("沿途阅读", "Read the journey")
        first_scene = "story-" + cards[0][0]["item_id"]
        opening = self.compose(
            "opening", subtitle=paragraph(self.trip.get("subtitle", ""), "story-label"),
            title=f'<h1 class="story-title" id="story-title">{quoted(self.trip["title"])}</h1>',
            intro=paragraph(self.trip.get("summary", ""), "story-intro"),
            photo=self.photo(cover, "story-photo", eager=True),
            dates=f'<p class="story-dates">{date_range}</p>' if date_range else "",
            meta=paragraph(meta, "story-meta"), base=base, days=self.cover_days(),
            actions=f'<div class="hero-actions">{start_link}{secondary}</div>', schedule=start_link,
            read=f'<a class="story-read button-link" data-story-start href="#{first_scene}">{lead}{icon("down")}</a>',
        )
        opening = f'<section class="story-opening" id="top" aria-labelledby="story-title">{opening}</section>'
        chapter_group = f'<div class="story-chapters">{"".join(chapters)}</div>'
        body = opening + navigation + chapter_group
        if "story" in self.layout:
            day_index = "" if "days" in self.cover_slots else self.trip_index()
            body = self.compose("story", opening=opening, chapters=chapter_group,
                                chapter_index=navigation, day_index=day_index)
        return f'<div class="story" data-story>{body}</div>'

    def scene_hero(self, cover, meta, base, start, secondary):
        start_link = f'<a class="hero-open button-link" href="#routes" data-view="journal">{start}{icon("down")}</a>'
        tabs = [(self.local("序章", "Opening"), cover)]
        panels = [
            '<div class="scene-panel scene-opening" id="scene-0" role="tabpanel" aria-labelledby="scene-tab-0">'
            '<div class="hero-copy"><div class="scene-premise">'
            f'{paragraph(self.trip.get("subtitle", ""), "subtitle")}'
            f'<h1>{quoted(self.trip["title"])}</h1>'
            f'<p class="sr-only">{quoted(cover["alt"])}</p>'
            f'{paragraph(self.trip.get("summary", ""), "intro")}</div>'
            f'<div class="scene-opening-foot"><div><p class="hero-meta">{meta}</p>{base}</div>'
            f'<div class="hero-actions">{start_link}{secondary}</div></div></div>'
            f'<p class="scene-caption">{self.photo_credit(cover)}</p></div>'
        ]
        for number, (scene, photo, _date, link) in enumerate(self.scene_cards(), 1):
            tabs.append((scene["label"], photo))
            panels.append(
                f'<div class="scene-panel scene-chapter" id="scene-{number}" role="tabpanel" '
                f'aria-labelledby="scene-tab-{number}" hidden>'
                f'<div class="hero-copy"><p class="subtitle">{quoted(scene["label"])}</p>'
                f'<h2>{quoted(scene["title"])}</h2><p class="sr-only">{quoted(photo["alt"])}</p>'
                f'{paragraph(scene["summary"], "intro")}'
                f'{link}</div>'
                f'<p class="scene-caption">{self.photo_credit(photo)}</p></div>'
            )
        controls, pictures = [], []
        for number, (label, photo) in enumerate(tabs):
            selected = ' aria-selected="true"' if number == 0 else ' aria-selected="false" tabindex="-1"'
            controls.append(
                f'<button type="button" role="tab" id="scene-tab-{number}" aria-controls="scene-{number}"{selected}>'
                f'<span class="scene-thumbnail" aria-hidden="true"></span><span>{quoted(label)}</span></button>'
            )
            active = ' data-current' if number == 0 else ''
            pictures.append(f'<div class="scene-image" data-scene-photo="{number}"{active}>'
                            f'{self.photo_image(photo, eager=number == 0)}</div>')
        group_label = self.local("旅行章节", "Journey chapters")
        return (
            '<header class="hero scene-hero" id="top">'
            f'<div class="scene-strip js-only"><div class="scene-tabs" role="tablist" aria-label="{group_label}">'
            f'{"".join(controls)}</div></div><div class="scene-stage">'
            f'<div class="scene-visuals" aria-hidden="true">{"".join(pictures)}</div>'
            f'{"".join(panels)}</div></header>'
        )

    def navigation(self):
        views = [("journal", "routes", self.local("图文路书", "Journal"), self.local("行程", "Trip"))]
        if self.places:
            label = self.local("地图", "Map") if self.has_map_points else self.text("places")
            views.append(("map", "places", label, label))
        views.append(("tools", "travel-tools", self.local("出行工具", "Travel tools"), self.local("工具", "Tools")))
        links = "".join(
            f'<a data-view="{view}" href="#{anchor}" aria-label="{quoted(label)}" data-short-label="{quoted(short)}">'
            f'<span class="nav-label">{quoted(label)}</span></a>'
            for view, anchor, label, short in views
        )
        first_return = next((route for route in self.spec["routes"] if route.get("return_item_id")), None)
        if first_return:
            links += (
                f'<a class="return-jump button-link" data-return-jump '
                f'href="#field-{first_return["id"]}--event-{first_return["return_item_id"]}">'
                f'{icon("clock")}{self.local("返程", "Return")}</a>'
            )
        search = self.local("搜索", "Search")
        brand = self.trip["title"]
        return (
            f'<a class="skip" href="#routes">{self.text("go_to_content")}</a>'
            f'<header class="mast"><a class="brand" href="#top">{quoted(brand)}</a>'
            f'<nav class="top-nav" aria-label="{self.local("路书视图", "Roadbook views")}">{links}</nav>'
            f'<a class="search-link button-link js-only" href="#roadbook-search" aria-haspopup="dialog" aria-label="{search}">'
            f'{icon("search")}<span class="nav-label">{search}</span></a></header>'
        )

    def route_navigation(self, view="journal"):
        if len(self.spec["routes"]) == 1:
            return ""
        sections = {"map": "places", "tools": "travel-tools"}
        links = "".join(
            f'<a class="route-tab" data-route-tab="{route["id"]}" href="#{sections.get(view, "route-" + route["id"])}">'
            f'{quoted(route["name"])}</a>'
            for route in self.spec["routes"]
        )
        return f'<nav class="route-tabs" aria-label="{self.text("route_choice")}">{links}</nav>'

    def common_arrival(self):
        routes = self.spec["routes"]
        arrivals = []
        for route in routes:
            event = route.get("return_item_id")
            arrival = next(
                ((item.get("to_id"), item.get("arrive_by"), day.get("date") or number, day.get("timezone"),
                  item.get("arrive_label"))
                 for number, day in enumerate(route["days"], 1) for item in day["items"] if item["id"] == event),
                None,
            )
            arrivals.append(arrival)
        first = arrivals[0]
        if not first or not all(first[:2]) or any(arrival != first for arrival in arrivals[1:]):
            return ""
        place_id, deadline, _day, _zone, cutoff = first
        first_route = routes[0]
        target = f'field-{first_route["id"]}--event-{first_route["return_item_id"]}'
        label = (self.local("共同的返程时限", "Shared return deadline") if len(routes) > 1 else
                 self.local("返程时限", "Return deadline"))
        place = quoted(self.places[place_id]["name"])
        action = quoted(cutoff or self.text("arrive_by"))
        return (
            f'<div class="cover-arrival"><span class="cover-arrival-title">{label}</span>'
            f'<a class="button-link cover-arrival-link" data-return-preview href="#{target}">'
            f'<span class="cover-arrival-copy"><span class="cover-arrival-place">{place}</span> '
            f'<span class="cover-arrival-action">{action}</span></span>{clock_face(deadline)}'
            f'{icon("right")}</a></div>'
        )

    def cover_plans(self):
        if len(self.spec["routes"]) == 1:
            return ""
        days = self.trip.get("decision", {}).get("days", {})
        links = []
        for route in self.spec["routes"]:
            key = route["id"]
            day_anchor = f'--day-{days[key]}' if key in days else ""
            links.append(
                f'<a class="button-link" data-route-tab="{key}" href="#route-{key}{day_anchor}">'
                f'<div><strong>{quoted(route["name"])}</strong>'
                f'{paragraph(route.get("summary", ""), "cover-plan-note")}{self.decision_activity(key)}</div>{icon("right")}</a>'
            )
        return f'<nav class="cover-plans" aria-label="{self.text("route_choice")}">{"".join(links)}</nav>{self.common_arrival()}'

    def shared_start(self):
        routes = self.spec["routes"]
        first = routes[0]["days"][0]
        if len(routes) < 2 or any(route["days"][0] != first for route in routes[1:]):
            return ""
        label = self.local("第一天", "Day 1")
        return (
            f'<section class="shared-start"><h2 class="shared-start-label">{label}</h2>'
            f'<a class="shared-start-link button-link" href="#route-{routes[0]["id"]}--day-1" '
            f'data-shared-start>{quoted(first["title"])}{icon("right")}</a>'
            f'{paragraph(first.get("focus", ""), "shared-start-note")}</section>'
        )

    def deadline(self, item, style):
        value = item.get("arrive_by")
        if not value:
            return ""
        label = quoted(item.get("arrive_label") or self.text("arrive_by"))
        return f'<p class="{style}"><span class="deadline-label">{label}</span> {clock_face(value)}</p>'

    def decision_activity(self, route_id):
        item_id = self.trip.get("decision", {}).get("item_ids", {}).get(route_id)
        if not item_id:
            return ""
        _, item = self.activities[route_id][item_id]
        time = self.deadline(item, "decision-limit")
        if not time and item_start(item):
            title = quoted(item["title"])
            time = f'<p class="decision-limit"><span>{title}</span> {clock_face(item_start(item))}</p>'
        place = self.places.get(item.get("to_id") or item.get("place_id") or item.get("from_id"))
        location = ""
        if place:
            location = " · ".join(value for value in (place["name"], place.get("address")) if value)
        details = time + paragraph(location, "decision-location")
        return f'<div class="decision-activity">{details}</div>' if details else ""

    def route_decision(self, cover=False, day_anchor=None):
        decision = self.trip.get("decision")
        if not decision:
            return self.cover_plans() if cover else self.route_navigation()
        level = "h2" if cover else "h4" if day_anchor else "h3"
        if cover:
            choices = self.cover_plans()
        else:
            options = []
            choose = self.local("查看此方案", "View this route")
            option_level = "h5" if day_anchor else "h3"
            for route in self.spec["routes"]:
                key = route["id"]
                day = decision.get("days", {}).get(key)
                target = self.day_decisions.get(key) or (f'route-{key}--day-{day}' if day else f'route-{key}')
                options.append(
                    f'<article class="decision-option"><{option_level}>{quoted(route["name"])}</{option_level}>'
                    f'{paragraph(route.get("summary", ""))}{paragraph(route.get("tradeoff", ""), "decision-condition")}'
                    f'{self.decision_activity(key)}'
                    f'<a class="chip decision-link" data-route-tab="{key}" href="#{target}">'
                    f'{choose}<span class="sr-only"> {quoted(route["name"])}</span>{icon("outward")}</a></article>'
                )
            choices = f'<div class="decision-options">{"".join(options)}</div>'
        return (
            f'<section class="route-decision" id="{day_anchor or "route-decision"}" '
            f'data-searchable data-search-title="{quoted(decision["title"])}">'
            f'<{level} class="decision-title">{quoted(decision["title"])}</{level}>'
            f'{paragraph(decision["when"], "decision-when")}{choices}'
            f'{paragraph(decision.get("stop", ""), "decision-stop")}{actions(decision, self.sources)}</section>'
        )

    def day_navigation(self, route, tools=False, overview=False):
        if not overview and len(route["days"]) <= 1:
            return ""
        key = route["id"]
        prefix, flag, style = ("field", "data-field-tab", "field-tabs") if tools else ("route", "data-journal-day", "day-links")
        label = self.local("速查日期", "Field guide days") if tools else self.text("routes")
        if overview:
            flag, style = "data-index-day", "trip-index-days"
        tabs = []
        for index, day in enumerate(route["days"], 1):
            date = heading_text(self.labels, day, index)
            area = day.get("area") if overview else ""
            description = " · ".join(filter(None, (date, day["title"], area)))
            compact = day["date"][5:].replace("-", ".") if day.get("date") and self.trip.get("theme") == "journey" else date
            context = f'<span class="day-tab-area">{quoted(area)}</span>' if area else ""
            tabs.append(
                f'<a class="day-tab" {flag} href="#{prefix}-{key}--day-{index}" aria-label="{quoted(description)}">'
                f'<small>{compact}</small><b>{quoted(day.get("label") or day["title"])}</b>{context}</a>'
            )
        return f'<nav class="{style}" aria-label="{label}">{"".join(tabs)}</nav>'

    def trip_index(self):
        if self.trip.get("theme") != "journey" or all(len(route["days"]) == 1 for route in self.spec["routes"]):
            return ""
        title = self.local("逐日路书", "Day by day") if self.scenes else self.local("按日期查看", "Browse by day")
        strips = []
        for route in self.spec["routes"]:
            context = paragraph(route["name"], "trip-index-route") if len(self.spec["routes"]) > 1 else ""
            strips.append(
                f'<div class="trip-index-panel" data-index-route="{route["id"]}">'
                f'<div class="trip-index-head"><h2>{title}</h2>{context}</div>{self.day_navigation(route, overview=True)}</div>'
            )
        return '<div class="trip-index">' + "".join(strips) + '</div>'

    def place_ref(self, place_id):
        return f'<a class="place-ref" href="#place-{place_id}">{icon("place")}{quoted(self.places[place_id]["name"])}</a>'

    def operation_steps(self, item, anchor):
        rows = []
        for number, step in enumerate(item.get("steps", []), 1):
            label = quoted(step["label"])
            links = "".join(self.place_ref(key) for key in step.get("places", []))
            locations = f'<div class="operation-places">{links}</div>' if links else ""
            rows.append(
                f'<li class="operation-step" id="{anchor}--step-{number}" data-reading-label="{label}">'
                f'<strong>{label}</strong>{paragraph(step["detail"])}{locations}</li>'
            )
        if not rows:
            return ""
        title = self.local("操作步骤", "What to do")
        return f'<details class="operation-steps"><summary>{title}</summary><ol>{"".join(rows)}</ol></details>'

    def connections(self, item):
        departure, arrival = item.get("from_id"), item.get("to_id")
        ids = (departure, arrival) if departure and arrival else filter(None, (item.get("place_id") or arrival or departure,))
        to = self.local("到", "to")
        separator = f'{icon("right")}<span class="sr-only"> {to} </span>'
        names = separator.join(self.place_ref(place_id) for place_id in ids)
        return f'<div class="connections">{names}</div>' if names else ""

    def day_fallbacks(self, day, route_id, anchor, separate, field=False):
        items = {item["id"]: item for item in day["items"]}
        nearby, collected = {}, []
        for number, option in enumerate(day.get("alternatives", []), 1):
            target = f"{anchor}--fallback-{number}"
            title = quoted(option["title"])
            heading = f'{self.text("alternative")} · {title}'
            decision = option.get("decision_item_id")
            inline = decision and not separate
            trigger = paragraph(option["trigger"], "trigger")
            body = "" if inline else trigger
            place = self.places.get(option.get("place_id"))
            if place:
                label = self.text("fallback_where")
                address = place.get("address", "")
                body += (f'<div class="fallback-destination"><span class="fallback-label">{label}</span>'
                         f'<a class="button-link fallback-place" href="#place-{place["id"]}">'
                         f'{icon("place")}{quoted(place["name"])}{icon("right")}</a>'
                         f'{paragraph(address, "address")}{copy_button(address, self.text("copy"))}</div>')
            resume = items.get(option.get("resume_item_id"))
            if resume:
                label = self.text("fallback_resume")
                start = item_start(resume)
                stamp = clock_face(start) if start else ""
                item_anchor = f"field-{route_id}--event-{resume['id']}" if field else f"event-{route_id}--{resume['id']}"
                body += (f'<a class="button-link fallback-resume" href="#{item_anchor}">'
                         f'<span class="fallback-label">{label}</span>{stamp}'
                         f'<span>{quoted(resume["title"])}</span>{icon("right")}</a>')
            replaced = " / ".join(items[key]["title"] for key in option["replace"])
            body += paragraph(option["detail"], "fallback-detail")
            body += self.operation_steps(option, target)
            body += paragraph(self.text("replaces") + " · " + replaced, "muted fallback-scope")
            if option.get("cost_note"):
                body += paragraph(self.text("change_cost") + " · " + option["cost_note"], "muted")
            body += actions(option, self.sources)
            attributes = f'data-reading-label="{title}"' if field else f'data-searchable data-search-title="{title}"'
            card_class = "field-fallback" if field else "fallback"
            if field or inline:
                summary = heading
                if inline:
                    card_class += " fallback-inline"
                    summary = (f'<span class="fallback-summary"><span class="fallback-label">{self.text("alternative")}</span>'
                               f'<span class="fallback-name">{title}</span>'
                               f'<small class="trigger">{quoted(option["trigger"])}</small></span>')
                body_class = "fallback-body field-fallback-body" if field else "fallback-body"
                card = (f'<details class="{card_class}" id="{target}" {attributes}>'
                        f'<summary>{summary}</summary><div class="{body_class}">{body}</div></details>')
            else:
                card = f'<aside class="fallback" id="{target}" {attributes}><h4>{heading}</h4>{body}</aside>'
            if inline:
                nearby[decision] = nearby.get(decision, "") + card
            else:
                collected.append(card)
                if decision:
                    cue = (f'<div class="fallback-cue"><a class="button-link" href="#{target}">'
                           f'<span>{heading}</span>{icon("right")}</a>{trigger}</div>')
                    nearby[decision] = nearby.get(decision, "") + cue
        return nearby, "".join(collected)

    def activity(self, item, route_id, fallback=""):
        boundary = self.deadline(item, "overnight event-deadline")
        title = quoted(item["title"])
        status = item.get("status", "planned")
        tag = "" if status == "planned" else f'<span class="state {status}">{self.text(status)}</span>'
        times = item_clocks(item)
        clock = f'<div class="event-time">{times}</div>' if times else ""
        anchor = f'event-{route_id}--{item["id"]}'
        return (
            f'<li id="{anchor}" class="activity" data-searchable data-search-title="{title}">'
            f'{clock}<div class="activity-body"><div class="activity-meta">{self.text(item["kind"])} {tag}</div>'
            f'<h4>{title}</h4>{self.connections(item)}{boundary}{paragraph(item.get("detail", ""))}'
            f'{self.operation_steps(item, anchor)}{actions(item, self.sources)}{fallback}</div></li>'
        )

    def day_schedule(self, day, route_id, anchor, nearby):
        links = []
        sections = []
        for number, (title, items) in enumerate(group_day_items(day), 1):
            events = "".join(self.activity(item, route_id, nearby.get(item["id"], "")) for item in items)
            timeline = f'<ol class="timeline">{events}</ol>'
            if title is None:
                return "", timeline
            stage_id = f"{anchor}--stage-{number}"
            heading = quoted(title)
            start = item_start(items[0])
            time = clock_face(start) if start else ""
            links.append(
                f'<li><a class="stage-link" href="#{stage_id}">{time}<span class="stage-name">{heading}</span>'
                f'{icon("down")}</a></li>'
            )
            sections.append(
                f'<section class="agenda-stage" id="{stage_id}" aria-labelledby="{stage_id}-title">'
                f'<h5 class="agenda-stage-title" id="{stage_id}-title">{heading}</h5>{timeline}</section>'
            )
        label = self.local("当天各段安排", "Sections of the day")
        navigation = f'<nav class="stage-nav" aria-label="{label}"><ol>{"".join(links)}</ol></nav>' if len(links) > 1 else ""
        return navigation, "".join(sections)

    def day_panel(self, day, route, index):
        anchor = f"route-{route['id']}--day-{index}"
        variant = self.day_variant(day)
        day_template = self.layout.get(variant)
        day_slots = template_slots(day_template)
        name = quoted(day["title"])
        date = heading_text(self.labels, day, index)
        short = " · ".join(quoted(day[key]) for key in ("area", "pace") if day.get(key))
        subtitle = f'<span class="day-meta">{short}</span>' if short else ""
        separate_fallbacks = "fallbacks" in day_slots
        nearby, alternatives = self.day_fallbacks(day, route["id"], anchor, separate_fallbacks)
        stages, events = self.day_schedule(day, route["id"], anchor, nearby)
        titles = {item["id"]: item["title"] for item in day["items"]}
        overnight = ""
        if day.get("stay_id"):
            overnight = f'<p class="overnight">{self.text("overnight")} · {self.place_ref(day["stay_id"])}</p>'
        photo = self.photo(day["photo"], "day-photo") if day.get("photo") else ""
        story = ""
        if day.get("story"):
            label = self.local("当天见闻", "Day notes")
            story = (f'<p id="{anchor}--story" class="day-story" data-reading-label="{label}">'
                     f'{quoted(day["story"])}</p>')
        notes = "".join(
            f'<details class="day-note" id="{anchor}--note-{number}" data-searchable data-search-title="{quoted(note["title"])}">'
            f'<summary>{quoted(note["title"])}</summary>{paragraph(note["text"])}{actions(note, self.sources)}</details>'
            for number, note in enumerate(day.get("notes", []), 1)
        )
        prev, next_day = self.local("上一天", "Previous day"), self.local("下一天", "Next day")
        pager = (
            '<div class="day-pager js-only">'
            f'<button class="chip" type="button" data-step="-1">{icon("left")}{prev}</button>'
            f'<button class="chip" type="button" data-step="1">{next_day}{icon("right")}</button></div>'
        ) if len(route["days"]) > 1 else ""
        time_link = self.local("到当天时间线", "Jump to the schedule")
        schedule_id = f"{anchor}--schedule"
        target = schedule_id if day.get("stages") else f'event-{route["id"]}--{day["items"][0]["id"]}'
        shortcuts = f'<a class="button-link schedule-jump" href="#{target}">{time_link}{icon("down")}</a>'
        if day.get("alternatives"):
            fallback_link = self.local("看天气与临场备选", "See fallbacks")
            shortcuts += f'<a class="button-link" href="#{anchor}--fallback-1">{fallback_link}{icon("down")}</a>'
        schedule = self.local("当天时间线", "Day schedule")
        focus = paragraph(day.get("focus", ""), "focus")
        main = self.local("当天怎么走", "Plan for the day")
        day_focus = f'<div class="day-brief-focus"><strong>{main}</strong>{focus}</div>' if focus else ""
        brief = f'<div class="day-brief">{day_focus}<div class="day-shortcuts">{shortcuts}</div></div>'
        separate_story = "story" in day_slots
        reading = ("" if separate_story else story) + actions(day, self.sources) + notes
        reading_panel = f'<div class="day-reading">{reading}</div>' if reading else ""
        inline_stages = stages if day_template is None else ""
        inline_alternatives = "" if separate_fallbacks else alternatives
        agenda = (
            f'<div class="day-agenda" id="{schedule_id}"><h4 class="timeline-heading">{schedule}</h4>'
            f'{inline_stages}{events}{overnight}{inline_alternatives}{pager}</div>'
        )
        if day_template is not None:
            story_link = ""
            if "opening" in self.layout:
                scene = next((entry for entry in self.scenes if entry["item_id"] in titles), None)
                if scene:
                    label = self.local(f'返回{scene["label"]}章节', f'Return to {scene["label"]}')
                    story_link = f'<a class="story-back button-link" href="#story-{scene["item_id"]}">{icon("up")}{quoted(label)}</a>'
            return_link = ""
            if "return_link" in day_slots and route.get("return_item_id") in titles:
                return_id = route["return_item_id"]
                label = self.local("打开返程速查", "Open return details")
                return_link = (f'<a class="button-link day-return-link" href="#field-{route["id"]}--event-{return_id}">'
                               f'{icon("clock")}{label}{icon("right")}</a>')
            decision_id = f"{anchor}--decision"
            decision = self.route_decision(day_anchor=decision_id) if self.day_decisions.get(route["id"]) == decision_id else ""
            body = self.compose(
                variant, brief=brief, photo=photo, agenda=agenda, reading=reading_panel, story_link=story_link,
                stages=stages, story=story, focus=focus, return_link=return_link, decision=decision, fallbacks=alternatives,
            )
        else:
            body = f'{brief}<div class="day-content">{photo}{agenda}{reading_panel}</div>'
        return (
            f'<details class="day-card" id="{anchor}" data-day-index="{index - 1}" open>'
            f'<summary><span class="day-date">{date}</span><span class="day-title">{name}</span>{subtitle}</summary>'
            f'{body}</details>'
        )

    def task_panel(self, route):
        lines = []
        for item in sorted(route.get("tasks", []), key=lambda record: (not record.get("critical"), record.get("due", "9999"))):
            task_id = f'{route["id"]}--{item["id"]}'
            check_key = f'shared:{item["id"]}' if item.get("shared") else task_id
            previous_key = f' data-previous-check="{task_id}"' if item.get("shared") else ""
            label = quoted(item["label"])
            due = f'<span class="state">{self.text("due")} · {quoted(item["due"].replace("T", " "))}</span>' if item.get("due") else ""
            anchor = f"task-{task_id}"
            lines.append(
                f'<li class="task" id="{anchor}" data-searchable data-search-title="{label}">'
                f'<label><input type="checkbox" data-check="{check_key}"{previous_key}><span>{label}</span></label>'
                f'<div class="task-meta">{quoted(item.get("category", ""))} {due}</div>'
                f'{paragraph(item.get("detail", ""))}{self.operation_steps(item, anchor)}{actions(item, self.sources)}</li>'
            )
        if not lines:
            return ""
        return (f'<section class="route-detail" id="route-{route["id"]}--tasks">'
                f'<h3>{self.text("tasks")}</h3><ul class="task-list">{"".join(lines)}</ul></section>')

    def budget_panel(self, route):
        rows = route.get("budget", [])
        if not rows:
            return ""
        travelers = self.trip["travelers"]
        cards = []
        for currency, total in budget_totals(rows, travelers).items():
            content = ""
            if any(row["currency"] == currency and row["status"] != "pending" for row in rows):
                span = estimate(total["low"], total["high"])
                per_person = average(total["low"], total["high"], travelers)
                content = f'<strong>{span}</strong><span>{self.text("per_person")} {per_person}</span>'
            if any(row["currency"] == currency and row["status"] == "paid" for row in rows):
                content += f'<span>{self.text("paid")} {estimate(total["paid_low"], total["paid_high"])}</span>'
            if total["pending"]:
                content += f'<span>{self.text("pending")} {total["pending"]}</span>'
            cards.append(f'<div><span>{currency} · {self.text("subtotal")}</span>{content}</div>')
        lines = []
        for item in rows:
            value = self.text("pending")
            if item["status"] != "pending":
                value = estimate(*budget_range(item, travelers)) + " " + item["currency"]
            basis = self.text(item["basis"])
            if multiplier(item, travelers) > 1:
                basis += f' × {multiplier(item, travelers)}'
            title = quoted(item["label"])
            lines.append(
                f'<li id="budget-{route["id"]}--{item["id"]}" data-searchable data-search-title="{title}">'
                f'<div><strong>{title}</strong>'
                f'<span class="budget-amount">{value}</span></div><small>{basis} · {self.text(item["status"])}</small>'
                f'{paragraph(item.get("note", ""))}{actions(item, self.sources)}</li>'
            )
        return (
            f'<section class="route-detail" id="route-{route["id"]}--budget"><h3>{self.text("budget")}</h3>'
            f'<div class="budget-totals">{"".join(cards)}</div><ul class="budget-list">{"".join(lines)}</ul></section>'
        )

    def route_panel(self, route):
        key = route["id"]
        days = "".join(self.day_panel(day, route, index) for index, day in enumerate(route["days"], 1))
        urgent = [
            f'<li><a class="text-link" href="#task-{key}--{task["id"]}">{quoted(task["label"])}{icon("outward")}</a>'
            f'{paragraph(task.get("due", "").replace("T", " "), "muted")}</li>'
            for task in route.get("tasks", []) if task.get("critical")
        ]
        priority = (
            f'<aside class="priority"><strong>{self.text("critical")}</strong><ul>{"".join(urgent)}</ul></aside>'
            if urgent else ""
        )
        all_days = self.local("展开整段行程", "Show full itinerary")
        reading_mode = (
            '<div class="reading-mode js-only"><span data-page-indicator></span>'
            f'<button class="reader-toggle" type="button" data-all-days aria-pressed="false">'
            f'{icon("list")}<span data-all-days-label>{all_days}</span></button></div>'
            if len(route["days"]) > 1 else ""
        )
        compare = ""
        if self.trip.get("decision"):
            label = self.local("比较出行方案", "Compare routes")
            target = self.day_decisions.get(key, "route-decision")
            direction = "down" if self.day_decisions else "up"
            compare = f'<a class="route-compare-link button-link" href="#{target}">{label}{icon(direction)}</a>'
        return (
            f'<article class="route" id="route-{key}" data-route-panel="{key}">'
            f'<div class="route-intro"><div><h3>{quoted(route["name"])}</h3>'
            f'{paragraph(route.get("summary", ""))}{paragraph(route.get("tradeoff", ""), "muted")}{compare}</div>{priority}</div>'
            f'{reading_mode}{self.day_navigation(route)}'
            f'<div class="day-pages">{days}</div></article>'
        )

    def route_tools(self, route):
        key = route["id"]
        calendar = f"calendar-{key}.ics"
        control = (
            '<div class="route-download js-only">'
            f'{download(calendar, self.text("calendar"))}{paragraph(self.text("calendar_tip"), "muted")}</div>'
            if calendar in self.files else ""
        )
        shortcuts = []
        if route.get("tasks"):
            shortcuts.append(f'<a class="chip" href="#route-{key}--tasks">{self.text("tasks")}{icon("down")}</a>')
        if route.get("budget"):
            shortcuts.append(f'<a class="chip" href="#route-{key}--budget">{self.text("budget")}{icon("down")}</a>')
        quick_links = f'<div class="tool-shortcuts actions">{"".join(shortcuts)}</div>' if shortcuts else ""
        days = "".join(self.field_day(day, route, index) for index, day in enumerate(route["days"]))
        body = quick_links + self.day_navigation(route, tools=True) + days + control + self.task_panel(route) + self.budget_panel(route)
        return f'<div data-tools-route="{key}"><h3 class="tools-route-name">{quoted(route["name"])}</h3>{body}</div>'

    def return_endpoints(self, item):
        endpoints = []
        for field, title in (("from_id", self.local("上车点", "From")), ("to_id", self.local("到达点", "To"))):
            if not item.get(field):
                endpoints.append("")
                continue
            place = self.places[item[field]]
            address = place.get("address", "")
            operation = copy_button(address, self.text("copy")) + external_links(place.get("links", []))
            buttons = f'<div class="actions">{operation}</div>' if operation else ""
            endpoints.append(
                f'<div class="field-endpoint"><p><span>{title}</span> {self.place_ref(place["id"])}</p>'
                f'{paragraph(address, "address")}{buttons}{paragraph(place.get("note", ""), "muted")}</div>'
            )
        return endpoints

    def return_places(self, item):
        endpoints = "".join(self.return_endpoints(item))
        return f'<div class="field-endpoints">{endpoints}</div>' if endpoints else self.connections(item)

    def return_milestones(self, route):
        setup = route["return_plan"]
        route_id = route["id"]
        references = (
            (setup.get("luggage_item_id"), None),
            (route["return_item_id"], self.local("开始接驳", "Start the transfer")),
            (setup["departure_item_id"], self.local("票面出发", "Ticket departure")),
        )
        moments = [(key, label, *self.activities[route_id][key]) for key, label in references if key]
        spans_days = len({id(day) for _, _, day, _ in moments}) > 1
        steps = []
        for key, label, day, item in moments:
            stamp = item_start(item)
            label = quoted(label or item["title"])
            date = ""
            if spans_days and CLOCK.fullmatch(stamp):
                date = f'<small>{heading_text(self.labels, day, route["days"].index(day) + 1)}</small>'
            steps.append(
                f'<li><a class="return-milestone button-link" href="#event-{route_id}--{key}">'
                f'{date}{clock_face(stamp)}<span>{label}</span>{icon("right")}</a></li>'
            )
        heading = self.local("原计划", "Original plan")
        return (f'<div class="return-reference"><p>{heading}</p>'
                f'<ol class="return-milestones" aria-label="{heading}">{"".join(steps)}</ol></div>')

    def departure_planner(self, defaults=None, collection=""):
        title = self.local("按自己的车票倒推", "Work back from my ticket")
        help_text = self.local("填入出发地当地的票面时间和你为各环节预留的分钟数。",
                               "Use the departure time at the terminal and the minutes you want to allow.")
        reset = ""
        if defaults:
            help_text = self.local(
                "已填入能从原计划推得的时间和预留，含原安排的机动时间。可修改后在此试算。",
                "Available times and buffers come from the original plan, including its margins. Edit them to try a different plan.",
            )
            reset_label = self.local("恢复原计划值", "Restore original values")
            reset = f'<button class="chip" type="reset">{reset_label}</button>'
        defaults = defaults or {}
        time = defaults.get("departure", "")
        collect_label = self.local(f"预留 · {collection}", f"Buffer · {collection}") if collection else self.local("取行李预留", "Luggage collection buffer")
        action = f' data-collection-action="{quoted(collection)}"' if collection else ""
        fields = (
            ("entry", self.local("进站或值机预留", "Entry or check-in buffer")),
            ("ride", self.local("去车站或航站楼", "Ride to terminal")),
            ("bags", collect_label),
        )
        unit = self.local("分钟", "min")
        buffers = "".join(
            f'<label>{quoted(label)}<span class="input-unit">'
            f'<input type="number" min="0" max="1439" step="1" inputmode="numeric" name="{name}" '
            f'value="{defaults.get(name, "")}" required>'
            f'<span>{unit}</span></span></label>'
            for name, label in fields
        )
        return (
            f'<details class="departure-planner js-only"><summary>{title}</summary>{paragraph(help_text, "muted")}'
            f'<form data-departure-plan{action}><div class="departure-fields">'
            f'<label>{self.local("票面出发时间", "Departure time")}<span class="input-clock">'
            f'<input type="time" step="60" name="departure" value="{time}" required>'
            f'<span data-time-face aria-hidden="true">{time or "HH:MM"}</span>{icon("clock")}</span></label>'
            f'{buffers}</div><div class="actions departure-actions">'
            f'<button class="chip primary" type="submit">{self.local("计算时间", "Calculate times")}</button>{reset}</div>'
            '<output class="departure-result" aria-live="polite"></output></form></details>'
        )

    def transfer_times(self, item):
        if not item.get("end") or not item.get("arrive_by"):
            return item_clocks(item, "<span>–</span>")
        departure = self.local("接驳出发", "Transfer leaves")
        arrival = self.local("预计到达", "Expected arrival")
        return "".join(
            f'<span class="field-transfer-time"><span>{label}</span>{clock_face(moment)}</span>'
            for label, moment in ((departure, item["start"]), (arrival, item["end"]))
        )

    def field_day(self, day, route, index):
        route_id = route["id"]
        anchor = f"field-{route_id}--day-{index + 1}"
        authored = "field" in self.layout
        separate_fallbacks = "fallbacks" in template_slots(self.layout.get("field"))
        nearby, fallbacks = self.day_fallbacks(day, route_id, anchor, separate_fallbacks, field=True)
        rows = []
        for item in day["items"]:
            is_return = item["id"] == route.get("return_item_id")
            event_anchor = f'field-{route_id}--event-{item["id"]}'
            times = self.transfer_times(item) if is_return else item_clocks(item, "<span>–</span>")
            when = f'<div class="field-time">{times}</div>' if times else ""
            limit = self.deadline(item, "field-limit")
            authored_return = is_return and "return" in self.layout
            detail = paragraph(item.get("detail", ""), "field-detail")
            detail += self.operation_steps(item, event_anchor)
            planner, reference = "", ""
            if is_return:
                if route.get("return_plan"):
                    defaults = return_plan_values(route, self.activities[route_id])
                    reference = self.return_milestones(route)
                    collection = self.activities[route_id].get(route["return_plan"].get("luggage_item_id"))
                    planner = self.departure_planner(defaults, collection[1]["title"] if collection else "")
                else:
                    planner = self.departure_planner()
            notice = paragraph(self.trip.get("notice", ""), "muted") if is_return else ""
            day_link = (
                f'<a class="chip" href="#field-{route_id}--day-{index + 1}">'
                f'{self.local("查看当天时间表", "See the day’s schedule")}</a>' if is_return else ""
            )
            link_style = "field-event-link button-link" if authored or authored_return else "text-link"
            title = (f'<h5><a class="{link_style}" href="#event-{route_id}--{item["id"]}">'
                     f'{quoted(item["title"])}{icon("outward")}</a></h5>')
            header = limit + title + when if is_return and (authored or authored_return) else title + when + limit
            head = f'<div class="field-event-head">{header}</div>'
            operations = actions(item, self.sources, day_link)
            if authored_return:
                origin, destination = self.return_endpoints(item)
                body = self.compose("return", head=head, notice=notice, reference=reference, origin=origin,
                                    destination=destination, detail=detail, actions=operations, planner=planner)
            else:
                locations = self.return_places(item) if is_return else self.connections(item)
                description = detail + locations if is_return and not authored else locations + detail
                body = head + notice + reference + description + operations + planner
            rows.append(
                f'<li class="field-event{" field-return" if is_return else ""}" id="{event_anchor}">'
                f'{body}{nearby.get(item["id"], "")}</li>'
            )
        back = self.local("阅读当天图文", "Read the full day")
        date = heading_text(self.labels, day, index + 1)
        heading = (f'<h4 class="field-day-title"><span class="field-date">{date}</span>'
                   f'<span class="field-day-divider"> · </span>'
                   f'<span class="field-day-name">{quoted(day["title"])}</span></h4>')
        focus = paragraph(day.get("focus", ""), "field-focus")
        events = f'<ol class="field-schedule">{"".join(rows)}</ol>'
        day_link = (f'<a class="field-reading-link button-link" href="#route-{route_id}--day-{index + 1}">'
                    f'{back}{icon("outward")}</a>')
        if authored:
            if not separate_fallbacks:
                events += fallbacks
            body = self.compose("field", heading=heading, focus=focus, events=events, fallbacks=fallbacks, day_link=day_link)
        else:
            body = f'{heading}{focus}{events}{fallbacks}{day_link}'
        return (f'<section class="field-day" id="{anchor}" data-field-day="{index}">'
                f'{body}</section>')

    def places_panel(self):
        if not self.places:
            return ""
        options = f'<option value="">{self.text("all_categories")}</option>' + "".join(
            f'<option value="{key}">{self.text(key)}</option>' for key in ("sight", "food", "stay", "transport", "other")
        )
        day_filter = select_field("map-day", self.local("按天查看", "Show day"), "")
        type_filter = select_field("map-kind", self.local("地点类型", "Place type"), options)
        cards = []
        for key, place in self.places.items():
            name = quoted(place["name"])
            address = place.get("address", "")
            area = " · ".join(filter(None, (self.text(place["category"]), place.get("area", ""))))
            point = place.get("point") or {}
            if point.get("accuracy") == "approximate":
                area += " · " + self.text("approximate")
            copy = copy_button(address, self.text("copy"))
            cards.append(
                f'<article class="place-card" id="place-{key}" data-place="{key}" data-searchable data-search-title="{name}">'
                f'<div class="place-header"><div><p class="muted"><span data-map-order></span>{quoted(area)}</p><h3>{name}</h3></div>'
                f'<button class="favorite js-only" type="button" data-favorite="{key}" aria-label="{self.text("favorite")} {name}" '
                f'aria-pressed="false">{icon("bookmark")}</button></div>{paragraph(address, "address")}'
                f'{paragraph(place.get("note", ""))}{actions(place, self.sources, copy)}</article>'
            )
        canvas = ""
        hint = self.local("按天查看停留顺序与地点信息。", "Browse stops and place details by day.")
        if self.has_map_points:
            hint = self.local("按天筛选，查看点位和地点卡。", "Filter by day to browse pins and place cards.")
            north = self.local("北", "North")
            offset = self.local("近邻标记用短线连回原位置。", "Short guide lines connect nearby pins to their positions.")
            mixed = self.local("其余坐标系的地点可从列表打开。", "Places in other coordinate systems are available in the list.")
            alternative = self.local("带「备」字的点位是临场备选地点。", "Pins marked Alt are fallback stops.")
            canvas = (
                f'<figure class="map js-only"><div class="map-surface" id="map-surface">'
                f'<canvas id="map-lines" aria-hidden="true"></canvas><div id="map-points"></div>'
                f'<span class="map-north">{icon("up")}{north}</span></div><figcaption>{self.text("map_note")} '
                f'<span id="map-fallback-note" hidden>{alternative}</span> '
                f'<span id="map-offset-note" hidden>{offset}</span> <span id="map-mixed-note" hidden>{mixed}</span></figcaption></figure>'
            )
        heading = (
            f'<div class="section-title"><h2>{self.local("沿着路线找地点", "Find places along the route")}</h2></div>'
        )
        controls = (
            f'{paragraph(self.trip.get("notice", ""), "trip-notice")}'
            f'{self.route_navigation("map")}'
            f'<div class="filters js-only">{day_filter}{type_filter}'
            f'<label class="favorites-only"><input type="checkbox" id="favorites-only">{self.text("favorites")}</label></div>'
            f'<div class="places-empty js-only" id="places-empty" hidden><p role="status">'
            f'{self.local("没有符合筛选的地点。", "No places match the filters.")}</p>'
            f'<button type="button" class="chip" data-reset-map>{self.local("清除筛选", "Clear filters")}</button></div>'
        )
        selection = (
            f'<aside id="map-selection" class="map-selection js-only" '
            f'aria-live="polite">{hint}</aside>'
        )
        sequence = '<div class="map-sequence js-only" id="map-sequence" hidden></div>'
        directory = f'<div class="places-grid">{"".join(cards)}</div>'
        if "places" in self.layout:
            body = self.compose("places", heading=heading, controls=controls, plot=canvas,
                                selection=selection, sequence=sequence, cards=directory)
        else:
            body = (f'{heading}{controls}<div class="map-layout">{canvas}'
                    f'<div class="atlas-sidebar">{selection}{sequence}</div></div>{directory}')
        return f'<section class="chapter stage" id="places" data-view-panel="map">{body}</section>'

    def tips_panel(self):
        rows = []
        for index, item in enumerate(self.spec.get("tips", []), 1):
            name = quoted(item["title"])
            rows.append(
                f'<article class="tip" id="tip-{index}" data-searchable data-search-title="{name}">'
                f'{paragraph(item.get("category", ""), "muted")}<h3>{name}</h3>'
                f'{paragraph(item["text"])}{actions(item, self.sources)}</article>'
            )
        return f'<section class="chapter" id="tips"><h2>{self.text("tips")}</h2><div class="tip-grid">{"".join(rows)}</div></section>' if rows else ""

    def sources_panel(self):
        rows = []
        for key, source in self.sources.items():
            title = quoted(source["title"])
            content = title
            if source.get("url"):
                content = f'<a class="text-link" href="{quoted(source["url"])}" rel="noopener noreferrer">{title}{icon("outward")}</a>'
            when = paragraph(source.get("checked_at", "").replace("T", " "), "muted")
            rows.append(
                f'<li id="source-{key}" data-searchable data-search-title="{title}"><strong>{content}</strong>'
                f'{when}{paragraph(source.get("note", ""))}</li>'
            )
        return f'<section class="chapter" id="sources"><h2>{self.text("sources")}</h2><ol class="source-list">{"".join(rows)}</ol></section>' if rows else ""

    def search_panel(self):
        close = self.local("关闭", "Close")
        clear = self.local("清空搜索", "Clear search")
        return (
            f'<dialog id="roadbook-search" class="search js-only" aria-labelledby="search-title">'
            f'<div class="search-heading"><h2 id="search-title">{self.text("search")}</h2>'
            f'<button type="button" class="icon-button" data-close-search aria-label="{close}">{icon("close")}</button></div>'
            f'<label for="query" class="sr-only">{self.text("search")}</label>'
            f'<div class="search-field">{icon("search")}'
            f'<input id="query" type="search" autofocus placeholder="{self.text("search_example")}">'
            f'<button type="button" class="icon-button" data-clear-search aria-label="{clear}" hidden>{icon("close")}</button></div>'
            f'<p class="muted" id="search-count" aria-live="polite"></p><ol id="search-results"></ol></dialog>'
        )

    def travel_log(self):
        people = self.trip["travelers"]
        members = "".join(f'<option value="{index}">{self.text("member")} {index + 1}</option>' for index in range(people))
        default_currency = next(
            (item["currency"] for route in self.spec["routes"] for item in route.get("budget", [])),
            "CNY" if self.labels is CHINESE else "USD",
        )
        payer = select_field("expense-payer", self.text("payer"), members, "payer")
        cancel = self.local("取消", "Cancel")
        return (
            f'<section class="chapter js-only" id="travel-log"><h2>{self.text("log")}</h2>'
            f'<p id="storage-notice" class="muted">{self.text("saved_locally")}</p>'
            f'<label class="notes">{self.text("notes")}<textarea id="notes" rows="4" maxlength="50000" '
            f'placeholder="{self.text("placeholder")}"></textarea></label>'
            f'<h3>{self.text("expenses")}</h3><form id="expense-form" class="expense-form">'
            f'<label>{self.text("expense_name")}<input name="label" required maxlength="100"></label>'
            f'<label>{self.text("amount")}<input name="amount" inputmode="decimal" maxlength="16" required></label>'
            f'<label>{self.text("currency")}<input name="currency" value="{default_currency}" pattern="[A-Za-z]{{3}}" required></label>'
            f'{payer}'
            f'<button class="chip primary" type="submit">{self.text("add")}</button></form>'
            f'<ul id="expense-list" class="expense-list"></ul><div id="balances"></div>'
            f'<div class="actions"><button class="chip" id="record-export" type="button">'
            f'{icon("download")}{self.text("record_export")}</button>'
            f'<label class="chip upload">{icon("upload")}{self.text("record_import")}<input type="file" id="record-import" '
            f'accept=".json,application/json"></label></div></section>'
            f'<dialog class="search record-dialog js-only" id="record-confirm" aria-labelledby="record-confirm-title" '
            f'aria-describedby="record-confirm-body"><h2 id="record-confirm-title">{self.text("record_import")}</h2>'
            f'<p id="record-confirm-body">{self.text("replace_records")}</p>'
            f'<form method="dialog" class="actions"><button class="chip" value="cancel" autofocus>{cancel}</button>'
            f'<button class="chip primary" value="restore">{self.text("record_import")}</button></form></dialog>'
        )

    def tool_panel(self):
        keys = {"itinerary.json": "JSON", "roadbook.md": "Markdown", "budget.csv": "CSV",
                "places.gpx": "GPX", "places.geojson": "GeoJSON"}
        exports = "".join(download(filename, label) for filename, label in keys.items() if filename in self.files)
        motion_label = self.local("减少页面切换动效", "Reduce page transitions")
        return (
            f'<footer class="chapter js-only" id="exports"><h2>{self.text("downloads")}</h2><div class="actions">'
            f'{exports}<button class="chip" id="print-roadbook" type="button">{self.text("print")}</button>'
            f'<button class="chip" id="share-roadbook" type="button">{icon("copy")}{self.text("share")}</button></div>'
            f'<label class="motion-setting"><input type="checkbox" id="reduce-motion">{motion_label}</label></footer>'
        )

    def render(self):
        template = Template((ASSETS / "template.html").read_text(encoding="utf-8"))
        routes = "".join(self.route_panel(route) for route in self.spec["routes"])
        notice = paragraph(self.trip.get("notice", ""), "trip-notice")
        theme = self.trip.get("theme", "landscape")
        styles = (ASSETS / "journal.css").read_text(encoding="utf-8")
        theme_styles = "journey.css" if theme == "journey" else "folio.css"
        styles += (ASSETS / theme_styles).read_text(encoding="utf-8")
        styles += (ASSETS / "controls.css").read_text(encoding="utf-8")
        styles += (ASSETS / "motion.css").read_text(encoding="utf-8")
        if self.reader:
            styles += (ASSETS / "reader.css").read_text(encoding="utf-8")
        if self.custom_style:
            styles = "@layer roadbook {\n" + styles + "\n}\n" + self.custom_style
        trip_index = "" if "days" in self.cover_slots or "story" in self.layout else self.trip_index()
        route_choice = "" if "plans" in self.cover_slots or self.day_decisions else self.route_decision()
        journal_notice = "" if "notice" in self.cover_slots else notice
        day_heading = "" if self.scenes and trip_index else (
            f'<div class="section-title"><h2>{self.local("逐日路书", "Day by day")}</h2></div>'
        )
        extras = "" if self.reader else self.travel_log() + self.tool_panel()
        return template.substitute(
            language=self.trip.get("language", "zh-CN"), title=quoted(self.trip["title"]),
            style=styles,
            behavior="\n".join((ASSETS / name).read_text(encoding="utf-8") for name in ("controls.js", "journal.js")),
            itinerary=json_for_script(self.spec),
            files=json_for_script({key: value for key, value in self.files.items() if key != "itinerary.json"}),
            labels=json_for_script(self.labels),
            theme=theme,
            body=(
                self.navigation() + self.hero() + '<main class="page">' + self.search_panel()
                + '<section class="chapter stage" id="routes" data-view-panel="journal">'
                + trip_index + day_heading
                + journal_notice + route_choice
                + routes + self.tips_panel() + "</section>" + self.places_panel()
                + f'<section class="chapter stage" id="travel-tools" data-view-panel="tools"><div class="section-title">'
                + f'<h2>{self.local("出行工具", "Travel tools")}</h2></div>' + notice + self.route_navigation("tools")
                + "".join(self.route_tools(route) for route in self.spec["routes"])
                + self.sources_panel() + extras + "</section></main>"
            ),
        )
