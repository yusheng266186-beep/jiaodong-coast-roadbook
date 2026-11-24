"""Validation and shared calculations for portable roadbook data."""

import base64
import binascii
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


IDENTIFIER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
CLOCK = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
MAX_PHOTO_BYTES = 2 * 1024 * 1024
STATUSES = {"planned", "estimated", "observed", "booked", "paid", "pending"}
THEMES = {"landscape", "city", "journey"}


def day_date(value):
    if not isinstance(value, str) or not DAY.fullmatch(value):
        raise ValueError("需要 YYYY-MM-DD 日期")
    return date.fromisoformat(value)


def offset_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError("需要带 UTC 偏移的 ISO 日期时间") from error
    if parsed.utcoffset() is None:
        raise ValueError("需要带 UTC 偏移的 ISO 日期时间")
    return parsed


def event_time(value, day):
    if not CLOCK.fullmatch(value):
        return offset_time(value)
    trip_day = day.get("date")
    clock = time.fromisoformat(value)
    if not trip_day:
        return datetime.combine(date(2000, 1, 1), clock)
    if not day.get("timezone"):
        raise ValueError("有日期的 HH:MM 需要当天 timezone，也可用完整日期时间和 UTC 偏移")
    zone = ZoneInfo(day["timezone"])
    stamp = datetime.combine(day_date(trip_day), clock, zone)
    if stamp.utcoffset() != stamp.replace(fold=1).utcoffset():
        raise ValueError("当地时钟存在歧义或跳时，请写完整时刻和 UTC 偏移")
    return stamp


def ordering_time(value):
    return value.astimezone(timezone.utc) if value.tzinfo else value


def item_start(item):
    return item.get("at") or item.get("start")


def return_plan_values(route, activities):
    """Derive the editable calculator's defaults from one itinerary."""
    setup = route["return_plan"]
    days = {id(day): index for index, day in enumerate(route["days"])}

    def stamp(item_id, deadline=False):
        day, item = activities[item_id]
        value = item.get("arrive_by") if deadline else item_start(item)
        if not value:
            raise ValueError("倒推引用的活动需要时刻，接驳还需要时限")
        result = event_time(value, day)
        if result.tzinfo is None:
            result += timedelta(days=days[id(day)])
        if result.second or result.microsecond:
            raise ValueError("倒推预填需要分钟精度")
        return result

    return_id = route["return_item_id"]
    departure = stamp(setup["departure_item_id"])
    arrival = stamp(return_id, deadline=True)
    ride = stamp(return_id)
    marks = [departure, arrival, ride]
    if setup.get("luggage_item_id"):
        marks.append(stamp(setup["luggage_item_id"]))
    if len({value.utcoffset() for value in marks}) != 1:
        raise ValueError("倒推预填需要同一当地时钟口径的时间，跨时区请用手填")
    defaults = {"departure": departure.strftime("%H:%M")}
    for key, (later, earlier) in zip(("entry", "ride", "bags"), zip(marks, marks[1:])):
        minutes = int((ordering_time(later) - ordering_time(earlier)).total_seconds() / 60)
        if not 0 <= minutes <= 1439:
            raise ValueError("倒推预留须按取件、上车、抵达边界、发车排序，单段最多 1439 分钟")
        defaults[key] = minutes
    return defaults


def amount(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("需要十进制金额") from error
    if not number.is_finite() or number < 0 or number > 10**12:
        raise ValueError("金额需为有限的非负数，且不超过 1 万亿")
    if number == 0:
        return Decimal(0)
    if number.normalize().as_tuple().exponent < -4:
        raise ValueError("金额最多保留四位小数")
    return number


def multiplier(row, travelers):
    return {"group": 1, "per_person": travelers, "units": row.get("quantity", 1)}[row["basis"]]


def budget_range(row, travelers):
    factor = multiplier(row, travelers)
    return amount(row["amount"]) * factor, amount(row.get("amount_max", row["amount"])) * factor


def budget_totals(rows, travelers):
    totals = {}
    for row in rows:
        currency = row["currency"]
        bucket = totals.setdefault(currency, dict(low=0, high=0, paid_low=0, paid_high=0, pending=0))
        if row["status"] == "pending":
            bucket["pending"] += 1
            continue
        low, high = budget_range(row, travelers)
        bucket["low"] += low
        bucket["high"] += high
        if row["status"] == "paid":
            bucket["paid_low"] += low
            bucket["paid_high"] += high
    return totals


def is_web_url(value):
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"https", "http"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not any(character.isspace() or ord(character) < 32 for character in value)
        )
    except (AttributeError, TypeError, ValueError):
        return False


def point_is_exportable(place):
    return (place.get("point") or {}).get("crs") == "WGS84"


def group_day_items(day):
    items = day["items"]
    stages = day.get("stages", [])
    if not stages:
        return [(None, items)]
    indices = {item["id"]: index for index, item in enumerate(items)}
    starts = [indices[stage["item_id"]] for stage in stages]
    return [
        (stage["title"], items[start:end])
        for stage, start, end in zip(stages, starts, starts[1:] + [len(items)])
    ]


def photo_mime(content):
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("封面需为 JPEG、PNG、WebP 或 GIF")


def normalize_photo(photo, directory):
    if "data" in photo:
        uri = photo["data"]
        if not isinstance(uri, str) or len(uri) > MAX_PHOTO_BYTES * 4 // 3 + 100:
            raise ValueError("封面超过 2 MiB")
        prefix, separator, encoded = uri.partition(",")
        if not separator:
            raise ValueError("封面编码无效")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("封面编码无效") from error
        if prefix != f"data:{photo_mime(content)};base64":
            raise ValueError("封面格式与编码不匹配")
    else:
        filename = photo.get("file")
        if not isinstance(filename, str) or Path(filename).is_absolute():
            raise ValueError("封面需使用相对于 JSON 的文件路径")
        location = (directory / filename).resolve()
        if not location.is_relative_to(directory.resolve()):
            raise ValueError("将封面文件放在 JSON 同级目录或其子目录")
        if not location.is_file() or location.stat().st_size > MAX_PHOTO_BYTES:
            raise ValueError("封面文件不存在或超过 2 MiB")
        content = location.read_bytes()
    if len(content) > MAX_PHOTO_BYTES:
        raise ValueError("封面超过 2 MiB")
    mime = photo_mime(content)
    photo["data"] = f"data:{mime};base64," + base64.b64encode(content).decode("ascii")
    photo.pop("file", None)


class Validator:
    def __init__(self):
        self.errors = []
        self.sources = {}
        self.places = {}
        self.shared_tasks = {}

    def photo(self, record, directory, where):
        if not isinstance(record, dict):
            self.errors.append(f"{where} · 需要图片对象")
            return
        self.text(record, ("alt", "credit"), where, required=("alt", "credit"))
        for field in ("focal", "mobile_focal"):
            if field not in record:
                continue
            focal = record[field]
            self.check(isinstance(focal, list) and len(focal) == 2 and all(
                type(value) in (int, float) and 0 <= value <= 100 for value in focal
            ), f"{where}.{field}", "需要两个 0–100 的百分数，依次表示横向、纵向焦点")
        if "url" in record:
            self.check(is_web_url(record["url"]), where, "图片来源需为 HTTP 或 HTTPS")
        try:
            normalize_photo(record, directory)
        except (OSError, ValueError) as error:
            self.errors.append(f"{where} · {error}")

    def check(self, condition, where, message):
        if not condition:
            self.errors.append(f"{where} · {message}")

    def rows(self, parent, field, where, required=False):
        value = parent.get(field, None if required else [])
        if not isinstance(value, list):
            self.errors.append(f"{where}.{field} · 需要数组")
            return []
        self.check(not required or bool(value), f"{where}.{field}", "至少需要一条")
        self.check(all(isinstance(row, dict) for row in value), f"{where}.{field}", "数组成员需要是对象")
        return [row for row in value if isinstance(row, dict)]

    def text(self, obj, fields, where, required=()):
        for field in fields:
            if field in obj or field in required:
                value = obj.get(field)
                ok = (
                    isinstance(value, str)
                    and (field not in required or bool(value.strip()))
                    and all(ord(character) >= 32 or character in "\r\n\t" for character in value)
                )
                self.check(ok, f"{where}.{field}", "需要文本")

    def identifier(self, value, where, used=None):
        if not isinstance(value, str) or len(value) > 80 or not IDENTIFIER.fullmatch(value):
            self.errors.append(f"{where} · 需要小写字母、数字或短横线组成的 ID")
            return None
        if used is not None:
            self.check(value not in used, where, f"重复 ID {value}")
            used.add(value)
        return value

    def one_of(self, value, choices, where):
        self.check(isinstance(value, str) and value in choices, where, "可用值为 " + "、".join(sorted(choices)))

    def refs(self, values, known, where, required=False):
        if not isinstance(values, list):
            self.errors.append(f"{where} · 需要 ID 数组")
            return []
        self.check(not required or bool(values), where, "至少需要一个引用")
        matched = []
        for value in values:
            if isinstance(value, str) and value in known:
                matched.append(value)
            else:
                self.errors.append(f"{where} · 引用了不存在的 ID {value!r}")
        return matched

    def operation_steps(self, item, where):
        for number, step in enumerate(self.rows(item, "steps", where), 1):
            step_at = f"{where}.steps[{number}]"
            self.text(step, ("label", "detail"), step_at, required=("label", "detail"))
            self.refs(step.get("places", []), self.places, f"{step_at}.places")

    def evidence(self, obj, where):
        matched = self.refs(obj.get("source_ids", []), self.sources, f"{where}.source_ids")
        for index, link in enumerate(self.rows(obj, "links", where), 1):
            link_at = f"{where}.links[{index}]"
            self.text(link, ("label",), link_at, required=("label",))
            self.check(is_web_url(link.get("url")), link_at, "需要 HTTP 或 HTTPS 入口")
        status = obj.get("status")
        if status == "observed":
            confirmed = [
                source_id
                for source_id in matched
                if self.sources[source_id].get("kind") in ("official", "map", "provider", "community")
                and self.sources[source_id].get("checked_at")
                and self.sources[source_id].get("url")
            ]
            self.check(bool(confirmed), where, "实际查到的状态需要 URL 和核验时点")
        if status in ("booked", "paid"):
            self.check(bool(matched), where, "已订或已付需注明用户或订票凭证来源")
            if matched:
                self.check(any(self.sources[source_id].get("kind") not in ("map", "community") for source_id in matched),
                           where, "地图与社区资料可用于计划，已订或已付需本次订单、付款凭证或用户确认")

    def date_value(self, value, where, parser):
        try:
            return parser(value)
        except (ValueError, TypeError, OverflowError) as error:
            self.errors.append(f"{where} · {error}")
            return None

    def lookup_tables(self, obj):
        identifiers = set()
        for index, source in enumerate(self.rows(obj, "sources", "root"), 1):
            where = f"sources[{index}]"
            source_id = self.identifier(source.get("id"), where, identifiers)
            self.text(source, ("title", "note"), where, required=("title",))
            self.one_of(source.get("kind"), {"official", "provider", "map", "community", "user", "history"}, where)
            if "url" in source:
                self.check(is_web_url(source["url"]), where, "来源 URL 需为 HTTP 或 HTTPS")
            if "checked_at" in source:
                value = source["checked_at"]
                parser = day_date if isinstance(value, str) and DAY.fullmatch(value) else offset_time
                self.date_value(value, f"{where}.checked_at", parser)
            if source_id:
                self.sources[source_id] = source

        identifiers.clear()
        for index, place in enumerate(self.rows(obj, "places", "root"), 1):
            where = f"places[{index}]"
            place_id = self.identifier(place.get("id"), where, identifiers)
            self.text(place, ("name", "area", "address", "note"), where, required=("name",))
            self.one_of(place.get("category"), {"sight", "food", "stay", "transport", "other"}, where)
            self.evidence(place, where)
            if "point" in place:
                self.validate_point(place["point"], f"{where}.point")
            if place_id:
                self.places[place_id] = place

    def validate_point(self, point, where):
        if not isinstance(point, dict):
            self.errors.append(f"{where} · 需要坐标对象")
            return
        self.one_of(point.get("crs"), {"WGS84", "GCJ02", "BD09"}, f"{where}.crs")
        self.one_of(point.get("accuracy"), {"exact", "approximate"}, f"{where}.accuracy")
        for field, limit in (("lat", 90), ("lon", 180)):
            value = point.get(field)
            self.check(type(value) in (float, int) and -limit <= value <= limit and math.isfinite(value),
                       f"{where}.{field}", "坐标超出范围或缺失")

    def validate_item(self, item, day, where, ids):
        self.identifier(item.get("id"), where, ids)
        self.text(item, ("title", "detail", "arrive_label"), where, required=("title",))
        self.one_of(item.get("kind"), {"visit", "meal", "transport", "rest", "buffer", "stay", "other"}, where)
        self.one_of(item.get("status", "planned"), STATUSES, f"{where}.status")
        self.evidence(item, where)
        self.operation_steps(item, where)
        for field in ("place_id", "from_id", "to_id"):
            if field in item:
                self.refs([item[field]], self.places, f"{where}.{field}")
        if "calendar" in item:
            self.check(type(item["calendar"]) is bool, f"{where}.calendar", "需要布尔值")
        moment = "at" in item
        span = "start" in item or "end" in item
        if "arrive_label" in item:
            self.check("arrive_by" in item, f"{where}.arrive_label", "需要对应的 arrive_by 时限")
        if not moment and not span and "arrive_by" not in item:
            return None
        if moment and span:
            self.errors.append(f"{where} · 单点时刻 at 与起止时段分开填写")
            return None
        try:
            boundary = None
            if "arrive_by" in item:
                if not isinstance(item["arrive_by"], str):
                    raise ValueError("最晚到达需为文本时刻")
                boundary = event_time(item["arrive_by"], day)
                if boundary.tzinfo and not day.get("date"):
                    raise ValueError("含完整日期时间的时限需要注明当日日期")
            if not moment and not span:
                return None
            if moment:
                if not isinstance(item["at"], str):
                    raise ValueError("单点时刻 at 需要文本")
                start = end = event_time(item["at"], day)
            else:
                if not isinstance(item.get("start"), str) or not isinstance(item.get("end"), str):
                    raise ValueError("起止时间需成对填写")
                start = event_time(item["start"], day)
                end = event_time(item["end"], day)
            if (start.tzinfo is None) != (end.tzinfo is None):
                raise ValueError("需要统一的日期和时区口径")
            if start.tzinfo and not day.get("date"):
                raise ValueError("含日期时间的活动需要注明当日日期")
            if day.get("date") and start.date() != day_date(day["date"]):
                raise ValueError("开始日期与当天日期不同")
            start_key, end_key = ordering_time(start), ordering_time(end)
            if not moment and end_key <= start_key:
                raise ValueError("结束需晚于开始，跨午夜时写完整日期时间")
            if boundary is not None:
                if (boundary.tzinfo is None) != (end.tzinfo is None):
                    raise ValueError("最晚到达与活动需使用统一的日期和时区口径")
                self.check(end_key <= ordering_time(boundary), where, "预计结束时间超过最晚到达")
            return start_key, end_key
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            self.errors.append(f"{where} · 无效时段，{error}")
            return None

    def validate_days(self, route, where, directory):
        item_ids = set()
        transport_ids = set()
        activities = {}
        previous_date, previous_zone, prior_dated_end = None, None, None
        for index, day in enumerate(self.rows(route, "days", where, required=True), 1):
            day_at = f"{where}.days[{index}]"
            self.text(day, ("title", "label", "area", "pace", "focus", "story"), day_at, required=("title",))
            self.evidence(day, day_at)
            if "photo" in day:
                self.photo(day["photo"], directory, f"{day_at}.photo")
            current = self.date_value(day["date"], f"{day_at}.date", day_date) if "date" in day else None
            zone = day.get("timezone")
            if "timezone" in day:
                try:
                    ZoneInfo(zone)
                except ZoneInfoNotFoundError:
                    self.errors.append(f"{day_at}.timezone · 找不到 {zone}。核对时区名，缺系统时区数据时可为同一 Python 安装 tzdata")
                except (ValueError, TypeError):
                    self.errors.append(f"{day_at}.timezone · 需要有效的 IANA 时区")
            if current and previous_date and zone == previous_zone:
                self.check(current > previous_date, day_at, "同一时区内日期需按顺序且唯一")
            if current:
                previous_date, previous_zone = current, zone
            if "stay_id" in day:
                self.refs([day["stay_id"]], self.places, f"{day_at}.stay_id")
            old_end = prior_dated_end if current else None
            items = self.rows(day, "items", day_at, required=True)
            positions = {item["id"]: number for number, item in enumerate(items) if isinstance(item.get("id"), str)}
            for number, item in enumerate(items, 1):
                item_at = f"{day_at}.items[{number}]"
                interval = self.validate_item(item, day, item_at, item_ids)
                if isinstance(item.get("id"), str):
                    activities[item["id"]] = (day, item)
                    if item.get("kind") == "transport":
                        transport_ids.add(item["id"])
                if interval:
                    start, end = interval
                    self.check(old_end is None or start >= old_end, item_at, "与前一活动重叠或排列次序有误")
                    old_end = end if old_end is None else max(old_end, end)
                    if current:
                        prior_dated_end = old_end
            stage_positions = []
            for number, stage in enumerate(self.rows(day, "stages", day_at), 1):
                stage_at = f"{day_at}.stages[{number}]"
                self.text(stage, ("title",), stage_at, required=("title",))
                for key in self.refs([stage.get("item_id")], positions, f"{stage_at}.item_id"):
                    stage_positions.append(positions[key])
            if stage_positions:
                self.check(stage_positions[0] == 0, f"{day_at}.stages", "第一段需从当天第一个活动开始")
                self.check(
                    all(first < second for first, second in zip(stage_positions, stage_positions[1:])),
                    f"{day_at}.stages", "各段起点需按活动顺序且不重复",
                )
            for number, alternative in enumerate(self.rows(day, "alternatives", day_at), 1):
                alt_at = f"{day_at}.alternatives[{number}]"
                fields = ("title", "trigger", "detail")
                self.text(alternative, (*fields, "cost_note"), alt_at, required=fields)
                replaced = self.refs(alternative.get("replace"), positions, f"{alt_at}.replace", required=True)
                if "decision_item_id" in alternative:
                    self.refs([alternative["decision_item_id"]], positions, f"{alt_at}.decision_item_id")
                if "place_id" in alternative:
                    self.refs([alternative["place_id"]], self.places, f"{alt_at}.place_id")
                if "resume_item_id" in alternative:
                    resume = self.refs([alternative["resume_item_id"]], positions, f"{alt_at}.resume_item_id")
                    if resume and replaced:
                        self.check(all(positions[resume[0]] > positions[key] for key in replaced),
                                   f"{alt_at}.resume_item_id", "接回活动需在所有替换活动之后")
                self.evidence(alternative, alt_at)
                self.operation_steps(alternative, alt_at)
            for number, note in enumerate(self.rows(day, "notes", day_at), 1):
                note_at = f"{day_at}.notes[{number}]"
                self.text(note, ("title", "text"), note_at, required=("title", "text"))
                self.evidence(note, note_at)
        if "return_item_id" in route:
            self.refs([route["return_item_id"]], transport_ids, f"{where}.return_item_id")
        if "return_plan" in route:
            self.validate_return_plan(route, where, transport_ids, activities)
        return activities

    def validate_return_plan(self, route, where, transport_ids, activities):
        where += ".return_plan"
        setup = route["return_plan"]
        if not isinstance(setup, dict):
            self.errors.append(f"{where} · 需要对象")
            return
        keys = [route.get("return_item_id"), setup.get("departure_item_id")]
        if "luggage_item_id" in setup:
            keys.append(setup["luggage_item_id"])
        matched = self.refs(keys, activities, where)
        if len(matched) != len(keys) or keys[0] not in transport_ids:
            return
        if len(set(matched)) != len(matched):
            self.errors.append(f"{where} · 请引用各自对应的接驳、票面和取件活动")
            return
        try:
            return_plan_values(route, activities)
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            self.errors.append(f"{where} · {error}")

    def validate_budget(self, route, where):
        budget_ids = set()
        for index, row in enumerate(self.rows(route, "budget", where), 1):
            row_at = f"{where}.budget[{index}]"
            self.identifier(row.get("id"), row_at, budget_ids)
            self.text(row, ("label", "note"), row_at, required=("label",))
            currency = row.get("currency")
            self.check(isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency), row_at, "需要三字母币种")
            basis = row.get("basis")
            self.one_of(basis, {"group", "per_person", "units"}, f"{row_at}.basis")
            status = row.get("status")
            self.one_of(status, STATUSES - {"planned"}, f"{row_at}.status")
            if basis == "units":
                quantity = row.get("quantity")
                self.check(type(quantity) is int and 0 < quantity <= 10000, row_at, "单价需对应正整数数量")
            if status == "pending":
                self.check("amount" not in row and "amount_max" not in row, row_at, "待核验项留空金额")
            else:
                try:
                    low = amount(row.get("amount"))
                    high = amount(row.get("amount_max", row.get("amount")))
                    self.check(high >= low, row_at, "金额上限应不小于下限")
                except ValueError as error:
                    self.errors.append(f"{row_at} · {error}")
            self.evidence(row, row_at)

    def validate_tasks(self, route, where):
        task_ids = set()
        for index, task in enumerate(self.rows(route, "tasks", where), 1):
            task_at = f"{where}.tasks[{index}]"
            task_id = self.identifier(task.get("id"), task_at, task_ids)
            self.text(task, ("label", "category", "detail"), task_at, required=("label",))
            for flag in ("critical", "shared"):
                if flag in task:
                    self.check(type(task[flag]) is bool, task_at, f"{flag} 需要布尔值")
            if task_id and task.get("shared") is True:
                identity = (task.get("label"), task.get("due"))
                original = self.shared_tasks.setdefault(task_id, identity)
                self.check(identity == original, task_at, "跨路线共用待办的名称和截止时间需一致")
            if "due" in task:
                due = task["due"]
                parser = day_date if isinstance(due, str) and DAY.fullmatch(due) else offset_time
                self.date_value(due, f"{task_at}.due", parser)
            self.evidence(task, task_at)
            self.operation_steps(task, task_at)

    def validate(self, obj, directory):
        if not isinstance(obj, dict):
            return ["root · 需要 JSON 对象"]
        self.check(type(obj.get("schema_version")) is int and obj["schema_version"] == 1,
                   "schema_version", "目前使用版本 1")
        trip = obj.get("trip")
        if not isinstance(trip, dict):
            self.errors.append("trip · 需要对象")
        else:
            self.identifier(trip.get("id"), "trip.id")
            self.text(trip, ("title", "subtitle", "summary", "notice"), "trip", required=("title",))
            self.one_of(trip.get("language", "zh-CN"), {"zh-CN", "en"}, "trip.language")
            self.one_of(trip.get("theme", "landscape"), THEMES, "trip.theme")
            travelers = trip.get("travelers")
            self.check(type(travelers) is int and 0 < travelers <= 500, "trip.travelers", "需要正整数人数")
            if "updated_at" in trip:
                self.date_value(trip["updated_at"], "trip.updated_at", offset_time)
            if "cover" in trip:
                self.photo(trip["cover"], directory, "trip.cover")
        self.lookup_tables(obj)
        route_ids = set()
        activities = {}
        routes = self.rows(obj, "routes", "root", required=True)
        for index, route in enumerate(routes, 1):
            where = f"routes[{index}]"
            key = self.identifier(route.get("id"), where, route_ids)
            self.text(route, ("name", "summary", "tradeoff"), where, required=("name",))
            indexed = self.validate_days(route, where, directory)
            if key:
                activities[key] = indexed
            self.validate_budget(route, where)
            self.validate_tasks(route, where)
        if isinstance(trip, dict) and "decision" in trip:
            self.validate_decision(trip["decision"], routes, activities)
        if isinstance(trip, dict) and "scenes" in trip:
            self.validate_scenes(trip, routes)
        for index, tip in enumerate(self.rows(obj, "tips", "root"), 1):
            where = f"tips[{index}]"
            self.text(tip, ("title", "category", "text"), where, required=("title", "text"))
            self.evidence(tip, where)
        return self.errors

    def validate_scenes(self, trip, routes):
        scenes = self.rows(trip, "scenes", "trip")
        if not scenes:
            return
        self.check(trip.get("theme") == "journey" and isinstance(trip.get("cover"), dict),
                   "trip.scenes", "场景章需要 journey 主题和封面")
        photographed_items = {
            item["id"]
            for route in routes
            for day in self.rows(route, "days", "route")
            if isinstance(day.get("photo"), dict) and isinstance(day.get("items"), list)
            for item in day["items"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        item_ids = set()
        fields = ("label", "title", "summary", "item_id")
        for index, scene in enumerate(scenes, 1):
            where = f"trip.scenes[{index}]"
            self.text(scene, fields, where, required=fields)
            item_id = self.identifier(scene.get("item_id"), f"{where}.item_id", item_ids)
            if item_id:
                self.check(item_id in photographed_items, f"{where}.item_id", "需指向至少一条路线内有日图的活动")

    def validate_decision(self, decision, routes, activities):
        where = "trip.decision"
        if not isinstance(decision, dict):
            self.errors.append(f"{where} · 需要对象")
            return
        self.text(decision, ("title", "when", "stop"), where, required=("title", "when"))
        self.evidence(decision, where)
        self.check(len(routes) > 1, where, "方案比较至少需要两条路线")
        targets = decision.get("days", {})
        if not isinstance(targets, dict):
            self.errors.append(f"{where}.days · 需要路线 ID 和目标天次组成的对象")
            return
        day_counts = {route["id"]: len(route["days"]) for route in routes
                      if isinstance(route.get("id"), str) and isinstance(route.get("days"), list)}
        for route_id, day in targets.items():
            self.check(type(day) is int and 1 <= day <= day_counts.get(route_id, 0),
                       f"{where}.days.{route_id}", "需指向此路线内存在的天次，从 1 开始")
        items = decision.get("item_ids", {})
        if not isinstance(items, dict):
            self.errors.append(f"{where}.item_ids · 需要路线 ID 和活动 ID 组成的对象")
            return
        for route_id, item_id in items.items():
            self.refs([item_id], activities.get(route_id, ()), f"{where}.item_ids.{route_id}")
