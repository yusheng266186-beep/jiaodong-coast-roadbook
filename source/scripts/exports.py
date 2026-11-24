"""Independent calendar, waypoint, CSV, and Markdown exports."""

import csv
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from io import StringIO
import json
from xml.etree import ElementTree as ET

from model import DAY, budget_range, budget_totals, day_date, event_time, item_start, multiplier, offset_time, point_is_exportable


def json_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def number(value):
    plain = format(value, "f")
    return plain.rstrip("0").rstrip(".") if "." in plain else plain


def estimate(low, high):
    return number(low) if low == high else f"{number(low)}–{number(high)}"


def average(low, high, travelers):
    return estimate(round(low / travelers, 2), round(high / travelers, 2))


def escape_ics(value):
    escaped = value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
    return escaped.replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def fold_ics(line):
    chunks, current = [], ""
    size = 0
    for character in line:
        width = len(character.encode("utf-8"))
        if size + width > 75:
            chunks.append(current)
            current, size = " ", 1
        current += character
        size += width
    chunks.append(current)
    return "\r\n".join(chunks)


def utc_stamp(stamp):
    return stamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def calendar_event(trip_id, route_id, event_id, stamp, title, start, *, end=None, detail="", place="", task=False,
                   booked=False, deadline=False):
    key = sha256(f"{trip_id}/{route_id}/{event_id}".encode()).hexdigest()[:32]
    date_start = f"DTSTART;VALUE=DATE:{start:%Y%m%d}" if not isinstance(start, datetime) else f"DTSTART:{utc_stamp(start)}"
    rows = [
        "BEGIN:VEVENT", f"UID:{key}@travel-roadbook", f"DTSTAMP:{stamp}", date_start,
        f"SUMMARY:{escape_ics(title)}",
    ]
    if end:
        rows.append(f"DTEND:{utc_stamp(end)}")
    if detail:
        rows.append(f"DESCRIPTION:{escape_ics(detail)}")
    if place:
        rows.append(f"LOCATION:{escape_ics(place)}")
    if task:
        rows.extend(("TRANSP:TRANSPARENT", "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY",
                     f"DESCRIPTION:{escape_ics(title)}", "END:VALARM"))
    else:
        rows.append("STATUS:CONFIRMED" if booked else "STATUS:TENTATIVE")
        if deadline:
            rows.append("TRANSP:TRANSPARENT")
    rows.append("END:VEVENT")
    return rows


def calendars(spec, places):
    trip = spec["trip"]
    stamp = utc_stamp(offset_time(trip["updated_at"]) if trip.get("updated_at") else datetime.now(timezone.utc))
    english = trip.get("language") == "en"
    files = {}
    for route in spec["routes"]:
        rows = []
        for day in route["days"]:
            if not day.get("date"):
                continue
            for item in day["items"]:
                start = item_start(item)
                boundary = item.get("arrive_by")
                if not (start or boundary) or not item.get("calendar", True) or item.get("status") == "pending":
                    continue
                end = event_time(item["end"], day) if item.get("end") else None
                departure = item.get("from_id") if item["kind"] == "transport" else None
                destination = places.get(item.get("to_id"))
                place = (destination if not start and destination else places.get(departure or item.get("place_id"))) or {}
                detail = item.get("detail", "")
                if destination and start:
                    arrival = "Arrival" if english else "抵达"
                    address = " · ".join(value for value in (destination["name"], destination.get("address")) if value)
                    detail = "\n".join(filter(None, (detail, f"{arrival} · {address}")))
                if boundary:
                    label = item.get("arrive_label") or ("Arrive by" if english else "最晚到达")
                    deadline = f"{label} · {boundary}"
                    detail = "\n".join(filter(None, (detail, deadline)))
                title = item["title"]
                if not start:
                    marker = "Deadline" if english else "截止"
                    title = f"[{marker}] {title}"
                place_name = " · ".join(value for value in (place.get("name"), place.get("address")) if value)
                rows.extend(calendar_event(
                    trip["id"], route["id"], "item-" + item["id"], stamp, title,
                    event_time(start or boundary, day), end=end,
                    detail=detail, place=place_name,
                    booked=item.get("status") in {"booked", "paid"}, deadline=not start,
                ))
        for task in route.get("tasks", []):
            due = task.get("due")
            if due:
                start = day_date(due) if DAY.fullmatch(due) else offset_time(due)
                tag = "Deadline" if english else "截止"
                rows.extend(calendar_event(
                    trip["id"], route["id"], "task-" + task["id"], stamp, f"[{tag}] {task['label']}",
                    start, detail=task.get("detail", ""), task=True,
                ))
        if rows:
            header = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Travel Roadbook//Itinerary//EN",
                      "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{escape_ics(trip['title'] + ' · ' + route['name'])}"]
            if trip.get("notice"):
                header.append(f"X-WR-CALDESC:{escape_ics(trip['notice'])}")
            files[f"calendar-{route['id']}.ics"] = "\r\n".join(
                map(fold_ics, header + rows + ["END:VCALENDAR"])
            ) + "\r\n"
    return files


def waypoint_files(spec):
    points = [place for place in spec.get("places", []) if point_is_exportable(place)]
    if not points:
        return {}
    english = spec["trip"].get("language") == "en"
    gpx = ET.Element("gpx", {"version": "1.1", "creator": "Travel Roadbook",
                             "xmlns": "http://www.topografix.com/GPX/1/1"})
    metadata = ET.SubElement(gpx, "metadata")
    ET.SubElement(metadata, "name").text = spec["trip"]["title"]
    ET.SubElement(metadata, "desc").text = "WGS84 waypoints only." if english else "WGS84 地点标记。"
    features = []
    for place in points:
        point = place["point"]
        rough = point["accuracy"] == "approximate"
        label = place["name"]
        if rough:
            label += " (approx.)" if english else "（大致位置）"
        waypoint = ET.SubElement(gpx, "wpt", lat=str(point["lat"]), lon=str(point["lon"]))
        ET.SubElement(waypoint, "name").text = label
        if place.get("address"):
            ET.SubElement(waypoint, "desc").text = place["address"]
        if place.get("links"):
            link = place["links"][0]
            anchor = ET.SubElement(waypoint, "link", href=link["url"])
            ET.SubElement(anchor, "text").text = link["label"]
        ET.SubElement(waypoint, "type").text = place["category"]
        features.append({
            "type": "Feature", "id": place["id"],
            "properties": {
                "name": label, "category": place["category"], "address": place.get("address", ""),
                "accuracy": point["accuracy"], "links": place.get("links", []),
            },
            "geometry": {"type": "Point", "coordinates": [point["lon"], point["lat"]]},
        })
    ET.indent(gpx, space="  ")
    xml = ET.tostring(gpx, encoding="unicode", xml_declaration=True) + "\n"
    return {"places.gpx": xml, "places.geojson": json_text({"type": "FeatureCollection", "features": features})}


def spreadsheet_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def budget_csv(spec):
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["route", "item", "currency", "status", "unit_low", "unit_high",
                     "quantity", "group_low", "group_high", "note", "source_ids"])
    travelers = spec["trip"]["travelers"]
    for route in spec["routes"]:
        for row in route.get("budget", []):
            pending = row["status"] == "pending"
            low, high = ("", "") if pending else map(number, budget_range(row, travelers))
            writer.writerow([
                spreadsheet_text(route["name"]), spreadsheet_text(row["label"]), row["currency"], row["status"],
                row.get("amount", ""), row.get("amount_max", row.get("amount", "")), multiplier(row, travelers),
                low, high, spreadsheet_text(row.get("note", "")), " ".join(row.get("source_ids", [])),
            ])
    return "\ufeff" + buffer.getvalue()


def markdown_text(value):
    plain = " ".join(value.splitlines())
    for character in ("\\", "`", "*", "_", "[", "]", "|"):
        plain = plain.replace(character, "\\" + character)
    return escape(plain, quote=False)


def markdown_links(links):
    return " · ".join(
        f"[{markdown_text(item['label'])}](<{item['url'].replace('<', '%3C').replace('>', '%3E')}>)"
        for item in links
    )


def markdown_evidence(item):
    return " ".join(f"[{source_id}](#source-{source_id})" for source_id in item.get("source_ids", []))


def markdown_notes(item, fields, links=()):
    return " · ".join(filter(None, [
        *(markdown_text(item.get(field, "")) for field in fields),
        markdown_links([*item.get("links", []), *links]),
        markdown_evidence(item),
    ]))


def markdown_steps(item, places):
    for number, step in enumerate(item.get("steps", []), 1):
        locations = [
            " · ".join(markdown_text(value) for value in (places[key]["name"], places[key].get("address")) if value)
            for key in step.get("places", [])
        ]
        yield " · ".join((
            f"  {number}. **{markdown_text(step['label'])}**",
            markdown_text(step["detail"]),
            *locations,
        ))


def export_markdown(spec, places, labels):
    trip = spec["trip"]
    lines = [f"# {markdown_text(trip['title'])}", "", markdown_text(trip.get("summary", "")), ""]
    if trip.get("notice"):
        lines.extend((f"> {markdown_text(trip['notice'])}", ""))
    if trip.get("decision"):
        decision = trip["decision"]
        lines.extend((f"## {markdown_text(decision['title'])}", "", markdown_notes(decision, ("when", "stop")), ""))
    for route in spec["routes"]:
        lines.extend((f"## {markdown_text(route['name'])}", "", markdown_notes(route, ("summary", "tradeoff")), ""))
        for index, day in enumerate(route["days"], 1):
            fallback_date = f"Day {index}" if spec["trip"].get("language") == "en" else f"第 {index} 天"
            date = day.get("date", fallback_date)
            lines.extend((f"### {date} · {markdown_text(day['title'])}", "",
                          markdown_notes(day, ("area", "pace", "focus")), ""))
            if day.get("story"):
                lines.extend((markdown_text(day["story"]), ""))
            stage_titles = {stage["item_id"]: stage["title"] for stage in day.get("stages", [])}
            for item in day["items"]:
                title = stage_titles.get(item["id"])
                if title:
                    if lines[-1]:
                        lines.append("")
                    lines.extend((f"#### {markdown_text(title)}", ""))
                clock = f"{item['start']}–{item['end']}" if item.get("start") else item.get("at", "")
                place = places.get(item.get("place_id")) or places.get(item.get("to_id")) or {}
                status = labels[item.get("status", "planned")]
                ends = []
                for part in ("from_id", "to_id") if item.get("from_id") else ("place_id", "to_id"):
                    if item.get(part):
                        name = markdown_text(places[item[part]]["name"])
                        if name not in ends:
                            ends.append(name)
                context = " → ".join(ends)
                details = markdown_notes(item, ("detail",), place.get("links", []))
                if item.get("arrive_by"):
                    cutoff = markdown_text(item.get("arrive_label") or labels["arrive_by"])
                    details = " · ".join(filter(None, (f"{cutoff} {item['arrive_by']}", details)))
                line = f"- {clock + ' ' if clock else ''}**{markdown_text(item['title'])}** · {status}"
                lines.append(" · ".join(filter(None, (line, context, details))))
                lines.extend(markdown_steps(item, places))
            if stage_titles and any(day.get(field) for field in ("stay_id", "notes", "alternatives")):
                notes_heading = "Day notes" if trip.get("language") == "en" else "当天补充"
                lines.extend(("", f"#### {notes_heading}", ""))
            if day.get("stay_id"):
                stay = places[day["stay_id"]]
                lines.append(f"- {labels['overnight']} · {markdown_text(stay['name'])} · "
                             + markdown_notes(stay, ("address", "note")))
            for note in day.get("notes", []):
                lines.append(f"- **{markdown_text(note['title'])}** · {markdown_notes(note, ('text',))}")
            if day.get("alternatives"):
                activities = {item["id"]: item for item in day["items"]}
                for alternative in day["alternatives"]:
                    replaces = " / ".join(markdown_text(activities[key]["title"]) for key in alternative["replace"])
                    parts = [f"- {labels['alternative']} · {markdown_text(alternative['title'])}",
                             f"{labels['replaces']} {replaces}", markdown_notes(alternative, ("trigger", "detail", "cost_note"))]
                    if alternative.get("place_id"):
                        place = places[alternative["place_id"]]
                        location = " · ".join(markdown_text(value) for value in (place["name"], place.get("address")) if value)
                        parts.append(f"{labels['fallback_where']} · {location}")
                    for key, label in (("decision_item_id", "fallback_decision"), ("resume_item_id", "fallback_resume")):
                        item = activities.get(alternative.get(key))
                        if item:
                            moment = " ".join(value for value in (item_start(item), markdown_text(item["title"])) if value)
                            parts.append(f"{labels[label]} · {moment}")
                    lines.append(" · ".join(parts))
                    lines.extend(markdown_steps(alternative, places))
            lines.append("")
        if route.get("budget"):
            lines.extend((f"### {labels['budget']}", ""))
            for row in route["budget"]:
                value = labels["pending"]
                if row["status"] != "pending":
                    value = f"{estimate(*budget_range(row, trip['travelers']))} {row['currency']}"
                lines.append(" · ".join(filter(None, (
                    f"- {markdown_text(row['label'])}", value, labels[row["status"]], markdown_notes(row, ("note",)),
                ))))
            for currency, total in budget_totals(route["budget"], trip["travelers"]).items():
                if any(row["currency"] == currency and row["status"] != "pending" for row in route["budget"]):
                    lines.append(f"- **{currency} {labels['subtotal']}** · {estimate(total['low'], total['high'])}")
            lines.append("")
        if route.get("tasks"):
            lines.extend((f"### {labels['tasks']}", ""))
            for task in sorted(route["tasks"], key=lambda task: task.get("due", "9999")):
                lines.append(" · ".join(filter(None, (f"- [ ] {markdown_text(task['label'])}",
                                                        task.get("due"), markdown_notes(task, ("category", "detail"))))))
                lines.extend(markdown_steps(task, places))
            lines.append("")
    for field, key in (("places", "places"), ("tips", "tips")):
        if spec.get(field):
            lines.extend((f"## {labels[key]}", ""))
            for record in spec[field]:
                title = markdown_text(record.get("title") or record["name"])
                fields = ("category", "text") if field == "tips" else ("area", "address", "note")
                notes = markdown_notes(record, fields)
                lines.append(f"- {title}" + (f" · {notes}" if notes else ""))
            lines.append("")
    if spec.get("sources"):
        lines.extend((f"## {labels['sources']}", ""))
        for source in spec["sources"]:
            entry = markdown_links([{"label": source["title"], "url": source["url"]}]) if source.get("url") else markdown_text(source["title"])
            lines.append(f'<a id="source-{source["id"]}"></a>')
            lines.append(" · ".join(filter(None, (f"- {entry}", source.get("checked_at"), markdown_text(source.get("note", ""))))))
    return "\n".join(lines).strip() + "\n"
