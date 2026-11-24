"""Render this trip's editorial layout from the skill's validated itinerary."""

from base64 import b64encode
from copy import deepcopy
import json
from pathlib import PurePosixPath
from string import Template
from urllib.parse import urlencode

from model import event_time, group_day_items, item_start, return_plan_values
from render import clock_face, external_links, item_clocks, json_for_script, paragraph, quoted


CITIES = (
    ("青岛", "中山路", 3, 1, 3, "story-d2-bridge", "qd-hotel"),
    ("威海", "韩乐坊", 2, 4, 5, "story-d4-xingfu", "wh-hotel"),
    ("烟台", "芝罘", 2, 6, 8, "story-d7-visit", "yt-hotel"),
)
DAY_INDEX_LABELS = {
    "浮山湾夜色": "浮山湾",
    "乘船上刘公岛": "刘公岛",
    "烟台开埠老街": "烟台老街",
    "登临蓬莱阁": "蓬莱阁",
}
DAY_ART = (
    ("zhongshan", "qingdao", "zhongshan"),
    ("oldtown", "qingdao", "zhongshan"),
    ("fushan", "qingdao", "may4"),
    ("weihai", "weihai", "xingfu"),
    ("harbor", "weihai", "liugong-pier"),
    ("lighthouse", "yantai", "yt-hill"),
    ("yantai", "penglai", "penglai"),
    ("airport", "yantai", "ynt"),
)
SCENES = (
    ("church", "青岛", "d2-church", "church"),
    ("stone-villa", "青岛", "d3-badaguan", "badaguan"),
    ("yuehai", "威海", "d4-lighthouse", "lighthouse-wh"),
    ("suocheng", "烟台", "d6-suo", "suocheng"),
)
PLACE_REGIONS = tuple(city[0] for city in CITIES) + ("出发与返程",)
BOOKING_STEPS = (
    ("先定机酒", "从第 8 天回自贡倒排", ("flight", "rooms", "meeting")),
    ("再订车票和景区", "同一车次、同一参观时段", ("rail", "scenic", "vehicles")),
    ("出发前复核", "风雨、行李与离线凭证", ("weather-check", "bag", "offline")),
    ("返程前一晚", "按票面重算出门时间", ("backcheck",)),
)
BUDGET_GROUPS = (
    ("交通", "transport", {"air", "sc-rail", "qd-wh", "wh-yt", "pl-car", "yt-taxi", "city"}),
    ("住宿", "stay", {"qd-rooms", "wh-rooms", "yt-rooms"}),
    ("餐饮", "food", {"meals"}),
    ("门票与船票", "tickets", {"tickets"}),
    ("预备金", "buffer", {"buffer"}),
)
MAP_WINDOW = (118.46, 35.73, 123.72, 38.25)
MAP_STOPS = (
    ("qingdao", "青岛", 1, "第 1–3 天", 120.32, 36.075, "above"),
    ("weihai", "威海", 4, "第 4–5 天", 122.11, 37.489, "right"),
    ("yantai", "烟台", 6, "第 6、8 天", 121.39, 37.536, "below"),
    ("penglai", "蓬莱", 7, "第 7 天", 120.75, 37.814, "left"),
)
DISHES = (
    ("青岛", "辣炒蛤蜊", "spicy-clams", "d2-dinner", "pichai", "中山路晚餐先点一盘辣炒蛤蜊分着尝。想吃得清淡，可请店家少放辣椒。"),
    ("威海 · 韩乐坊", "韩式甜辣炸鸡", "yangnyeom", "d4-dinner", "hanle", "在韩乐坊逛夜市，可点一份甜辣炸鸡分着吃，怕辣就选原味。"),
    ("烟台 · 芝罘", "福山大面", "fushan-noodles", "d6-checkin", "nanhong", "第 6 天午饭想吃面，可在芝罘老城找福山大面，问清当天能选的粗细和卤子。"),
    ("青岛", "鲅鱼水饺", "dumpling", "d2-lunch", "qd-fish-dumplings", "逛完中山路，想吃鲅鱼水饺就去海泊路裕兴里的船歌。可以再点一盘蛤蜊。"),
    ("威海 · 韩乐坊", "石锅拌饭", "bibimbap", "d4-dinner", "hanle", "到威海第一晚，在韩乐坊挑一家韩餐店点热石锅拌饭。怕辣可以请店家分装辣酱。"),
    ("烟台 · 芝罘", "海肠捞饭", "sea-rice", "d6-dinner", "benjia", "逛完所城里，点一份韭菜海肠浇饭。五六个人可以先点一份分着尝，再搭一盘焖子。"),
    ("威海", "清蒸海鲜", "seafood", "d5-dinner", "changfeng", "下岛后去长峰邻里，先问斤重和加工费，再选当日有的虾、蛤蜊或熟牡蛎。"),
    ("烟台 · 蓬莱", "蓬莱小面", "noodle", "d7-lunch", "noodles", "游完水城后吃一碗细面和鱼卤。建兴面馆售完时，可就近找同类小面。"),
    ("青岛", "春和楼香酥鸡", "chicken", "d2-lunch", "chunhe", "逛完教堂广场，午饭到中山路春和楼。五六个人可点一只香酥鸡，再配蒸饺和青菜。"),
    ("烟台 · 芝罘", "烟台焖子", "menzi", "d6-dinner", "benjia", "逛完所城里，可以点煎焖子配海肠捞饭。想尝小吃摊的做法，也可到老城小吃街找。"),
    ("青岛", "排骨米饭", "pork-ribs", "d2-lunch", "zhongshan", "在中山路走累了，可以各点一份炖排骨配米饭。五六人同行再加一份时蔬。"),
    ("威海 · 韩乐坊", "韩式炒年糕", "tteokbokki", "d4-dinner", "hanle", "逛韩乐坊时先点一小份酱汁炒年糕。几个人分尝，还能留点食量吃正餐。"),
    ("烟台 · 芝罘", "烟台苹果", "yantai-apples", "d6-checkin", "nanhong", "逛芝罘老城遇到水果铺，可问有没有栖霞产的苹果。挑几只带回酒店分吃。"),
    ("青岛 · 中山路", "海菜凉粉", "sea-jelly", "d2-lunch", "zhongshan", "海藻熬汁凝成的凉粉清凉滑口，常配蒜、醋或调味酱。老城午餐可以先点一小碗分尝，问店家能否把蒜汁与辣油单放。"),
    ("青岛 · 台东", "青岛锅贴", "potstickers", "d3-lunch", "taidong", "到台东找现煎锅贴，焦脆的一面是特色。五六人可以挑两种馅各来一份，再配热汤；当午饭吃按每人食量补单。"),
    ("青岛 · 浮山湾", "炸蛎黄", "fried-oysters", "d3-dinner", "may4", "将牡蛎肉挂糊炸成小块，是青岛地方菜单里常见的吃法。晚餐到浮山湾附近鲁菜馆先问当天供应，点一小盘趁热分吃。"),
    ("威海 · 长峰", "鱼锅饼子", "fish-pot", "d5-dinner", "changfeng", "鲜鱼在锅里炖，玉米面饼子贴在锅沿，靠近汤汁的一边入味。想吃这道可先问市场周边鲁菜馆是否做整锅；确认鱼种、份量和刺多不多，五六人合点一锅。"),
    ("威海 · 长峰", "蒜蓉乳山牡蛎", "garlic-oyster", "d5-dinner", "changfeng", "想试本地牡蛎，先问产地、按个或按斤计价，再选蒜蓉烤或蒸熟的做法。五六人先按每人一只点，连着加工费一起确认。"),
    ("威海 · 韩乐坊", "韩式鱼饼串", "fishcake-skewer", "d4-dinner", "hanle", "薄鱼饼折成串，在汤锅里煮热。逛夜市先买两三串分尝，口味偏淡时可另外选蘸料，搭炒年糕还能换一口热汤。"),
    ("烟台 · 所城里", "胶东花饽饽", "flower-buns", "d6-dinner", "suocheng", "花饽饽是胶东有造型的蒸面点，庆贺用的造型通常较大。逛所城里的非遗小店时问是否有小份和当天现蒸款，想做伴手礼就问保存方式。"),
    ("烟台 · 芝罘", "胶东海菜包", "seaweed-bun", "d6-checkin", "nanhong", "胶东沿海把海菜做进包子馅，有的铺子会再加贝丁。烟台午饭可在老城面食店问当日馅料，先买一两个分尝，再搭热粥或小面。"),
    ("烟台 · 芝罘", "莱阳茌梨", "laiyang-pear", "d7-dinner", "chaoyang", "这类烟台地方果品适合当餐后水果。随晚餐在芝罘找水果店时先问产地、时令及能否按个买，同行分尝即可，无需另去莱阳。"),
    ("青岛 · 中山路", "郑庄脂渣", "crispy-pork", "d2-dinner", "zhongshan", "青岛口味的猪肉脂渣，咸香偏脆。逛老城时可在特产店问郑庄脂渣，先买小袋分尝。带走前看明保质期和保存条件。"),
    ("威海 · 长峰", "葱烧海参", "braised-cucumber", "d5-dinner", "changfeng", "威海鲁菜里常见的海参做法，葱段煸香后入汁。想加菜可在长峰附近鲁菜馆问是否供应、按位还是按盘，以及能否做成共享小份。"),
    ("烟台 · 蓬莱", "蓬莱八仙宴", "eight-immortals", "d7-lunch", "", "蓬莱以八仙故事命名的主题宴席。可提前问海情广场或宝龙海上仙街一带的鲁菜馆，五六人能否做小份或单点几道，确认总价和备餐时间。插图以齐鲁八仙宴展陈实拍为参考。赶下午行程时，午饭照常吃小面。"),
    ("烟台 · 蓬莱", "蓬莱蒸汽海鲜", "pl-steam", "d7-lunch", "", "想把蓬莱午饭吃长一点，可去海情广场或抹直口一带找蒸汽海鲜。五六人先问时令贝虾的重量、锅价和加工费，合点一锅，再配小面或一盘青菜。插图参考青岛店家的同类蒸锅实拍。"),
)
MEAL_AREAS = {"hanle", "pichai", "nanhong", "zhongshan", "may4", "taidong", "changfeng", "suocheng", "chaoyang"}
FOOD_LEADS = {"spicy-clams", "potstickers", "fish-pot", "yangnyeom", "sea-rice", "noodle"}
FOOD_EVIDENCE = {
    "sea-jelly": ("青岛市文旅局 · 街巷特色美食", "https://www.qingdao.gov.cn/zwgk/xxgk/whly/gkml/gzxx/202512/t20251222_10415836.shtml"),
    "potstickers": ("青岛市文旅局 · 街巷特色美食", "https://www.qingdao.gov.cn/zwgk/xxgk/whly/gkml/gzxx/202512/t20251222_10415836.shtml"),
    "fried-oysters": ("青岛早报 · 青岛食材节评选", "https://epaper.qingdaonews.com/qdzb/resfile/2024-12-13/A03/qdzb-20241213-A03.pdf"),
    "fish-pot": ("威海日报 · 鱼锅饼子", "https://www.whnews.cn/news/node/2021-10/02/content_7194199.htm"),
    "garlic-oyster": ("威海市政府 · 威海味与乳山牡蛎", "https://www.weihai.gov.cn/art/2025/7/23/art_58817_5668927.html"),
    "fishcake-skewer": ("威海市政府 · 韩乐坊与夜市小吃", "https://www.weihai.gov.cn/art/2025/7/23/art_58817_5668927.html"),
    "flower-buns": ("烟台文旅局 · 非遗美食生活周", "https://whlyj.yantai.gov.cn/art/2025/9/12/art_42161_2928101.html"),
    "seaweed-bun": ("烟台文旅局 · 非遗美食生活周", "https://whlyj.yantai.gov.cn/art/2025/9/12/art_42161_2928101.html"),
    "laiyang-pear": ("烟台文旅局 · 烟台水果与莱阳梨", "https://whlyj.yantai.gov.cn/col/col42216/art/2026/art_1e401e77e8b44945a0152c8bd85befb9.html"),
    "crispy-pork": ("青岛早报 · 青岛老字号与脂渣", "https://epaper.qingdaonews.com/qdzb/h5/html5/2026-01/22/content_144796_3066822.htm"),
    "braised-cucumber": ("威海公共文旅服务云 · 威海味道", "https://www.whggwly.com/new-25480.html"),
    "eight-immortals": ("烟台市政府 · 蓬莱风味与就餐片区", "https://www.yantai.gov.cn/art/2023/11/9/art_50727_3154373.html"),
    "pl-steam": ("烟台市政府 · 蓬莱蒸汽海鲜与就餐片区", "https://www.yantai.gov.cn/art/2023/11/9/art_50727_3154373.html"),
}
CHURCH_REFERENCE = "https://www.qingdao.gov.cn/yfqd/qdwl/cjfw/wyqtsjd/202009/t20200910_521996.shtml"
KINDS = {"sight": "景点", "stay": "住宿", "food": "美食", "transport": "交通", "other": "其他"}


def join(values):
    return "".join(values)


def data_url(path):
    return "data:image/webp;base64," + b64encode(path.read_bytes()).decode("ascii")


def place_url(place_id):
    return "#place-" + place_id


def activity_label(item):
    if item["id"] == "d5-check":
        return "早餐后查船班和风浪"
    return item["title"].removeprefix("示例航段 · ")


def link(href, label, classes="text-action", flags=""):
    return f'<a class="{classes}" href="{quoted(href)}"{flags}>{quoted(label)}</a>'


def citation(href, label, classes="source-link"):
    return link(href, label, classes, ' target="_blank" rel="noopener noreferrer"')


class FieldGuide:
    def __init__(self, spec, art, coastline, folder, asset_url=data_url, offline_href=None):
        self.spec = spec
        self.trip = spec["trip"]
        self.route = spec["routes"][0]
        self.key = self.route["id"]
        self.days = self.route["days"]
        self.places = {place["id"]: place for place in spec["places"]}
        self.sources = {source["id"]: source for source in spec["sources"]}
        self.activities = {item["id"]: (day, item) for day in self.days for item in day["items"]}
        self.day_numbers = {item["id"]: idx for idx, day in enumerate(self.days, 1) for item in day["items"]}
        self.folder = folder
        self.art = art
        self.asset_url = asset_url
        self.offline_href = offline_href
        self.embedded_art = set()
        self.coastline = coastline
        self.place_stories = json.loads((folder / "place-stories.json").read_text(encoding="utf-8"))
        self.place_media = json.loads((folder / "place-media.json").read_text(encoding="utf-8"))
        self.sights = json.loads((folder / "sight-catalog.json").read_text(encoding="utf-8"))
        if set(self.place_stories) != set(self.places) or set(self.place_media) != set(self.places):
            raise ValueError("地点简介和图集必须对应行程地点")
        catalog = [row[0] for city in self.sights["cities"] for group in city["groups"] for row in group["sights"]]
        if set(catalog) != {key for key, place in self.places.items() if place["category"] == "sight"}:
            raise ValueError("所有景点都应出现在三城图册中")
        if len(catalog) != len(set(catalog)):
            raise ValueError("景点在图册中出现了两次")
        self.sight_count = len(catalog)
        for record in art.values():
            self.art_path(record["file"])
            if record.get("thumb"):
                self.art_path(record["thumb"])
        for place_id, photos in self.place_media.items():
            if len(photos) < 2:
                raise ValueError(f"{place_id} 需要至少两张可追溯的参考图")

    def day_id(self, number):
        return f"route-{self.key}--day-{number}"

    @staticmethod
    def photo_id(number):
        return f"photo-day-{number}"

    def event_id(self, item_id):
        return f"event-{self.key}--{item_id}"

    def day_link(self, number, label, classes="text-action"):
        return link("#" + self.day_id(number), label, classes)

    def evidence(self, item):
        return join(
            citation(self.sources[key]["url"], self.sources[key]["title"])
            for key in item.get("source_ids", [])
        )

    def art_path(self, name):
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "places" in path.parts or path.suffix != ".webp":
            raise ValueError(f"插画资产不能指向原片 {name}")
        return self.folder / "art" / path

    def image(self, key, cover=False, caption_name=True):
        record = self.art[key]
        self.embedded_art.add(key)
        address = self.asset_url(self.art_path(record["file"]))
        attrs = 'fetchpriority="high"' if cover else 'loading="lazy" decoding="async"'
        art = f'<img src="{address}" alt="{quoted(record["alt"])}" {attrs}>'
        credit = link(record["reference"], record.get("reference_label", "实拍参考"),
                      "image-source", ' target="_blank" rel="noopener noreferrer"')
        art_class = "cover-plate" if cover else "art-plate"
        caption = f'{quoted(record["name"])} · 据实拍生成' if caption_name else "据实拍生成"
        return (
            f'<figure class="{art_class}" data-art="{key}" data-art-title="{quoted(record["name"])}">'
            f'<div class="art-image">{art}<button class="image-opener" type="button" aria-haspopup="dialog" '
            f'aria-label="看全幅 · {quoted(record["name"])}" hidden><span aria-hidden="true"></span></button></div>'
            f'<figcaption><span>{caption}</span>{credit}</figcaption></figure>'
        )

    def place_link(self, place_id):
        return link(place_url(place_id), self.places[place_id]["name"], "inline-place")

    def edited_photo_path(self, record):
        original = PurePosixPath(record["file"])
        if original.parts != ("places", original.name) or original.suffix != ".webp":
            raise ValueError(f"未知的实拍参考路径 {original}")
        picture = self.folder / "art" / "stylized-places" / original.name
        if not picture.is_file():
            raise ValueError(f"还没有根据实拍绘制 {original.name}")
        if picture.read_bytes() == (self.folder / "art" / original).read_bytes():
            raise ValueError(f"展示图与原片相同 {original.name}")
        return picture

    def actions(self, item):
        content = external_links(item.get("links", [])) + self.evidence(item)
        return f'<div class="actions">{content}</div>' if content else ""

    def connections(self, item):
        ids = dict.fromkeys(item[key] for key in ("from_id", "to_id", "place_id") if item.get(key))
        if not ids:
            return ""
        separator = '<span class="connection-divider" aria-hidden="true">→</span>'
        return f'<p class="connections">{separator.join(self.place_link(key) for key in ids)}</p>'

    def field_steps(self, item, label="操作步骤"):
        rows = []
        for step in item.get("steps", []):
            places = step.get("places", [])
            links = (
                f'<div class="field-step-links">{"".join(self.place_link(key) for key in places)}</div>'
                if places else ""
            )
            rows.append(
                f'<li><strong class="field-step-name">{quoted(step["label"])}</strong>'
                f'<div>{paragraph(step["detail"])}{links}</div></li>'
            )
        return f'<ol class="field-steps" role="list" aria-label="{label}">{"".join(rows)}</ol>' if rows else ""

    def stops(self):
        return join(
            f'<a href="#{self.day_id(first)}"><strong>{name}</strong>'
            f'<span class="trip-meta"><span>第 {first}–{last} 天</span><span>{area} · {nights} 晚</span></span></a>'
            for name, area, nights, first, last, _, _ in CITIES
        )

    def day_tabs(self):
        return join(
            f'<a href="#{self.day_id(number)}" data-day-select="{number}" aria-label="第 {number} 天 {quoted(day["label"])}">'
            f'<b>{number:02d}</b><span class="day-dot" aria-hidden="true"></span>'
            f'<span class="day-label">{quoted(DAY_INDEX_LABELS.get(day["label"], day["label"]))}</span></a>'
            for number, day in enumerate(self.days, 1)
        )

    def chapters(self):
        return join(
            f'<aside class="city-chapter" id="{anchor}" data-city-chapter="{first}" data-last="{last}">'
            f'<details class="sheet"><summary>{name} · {area} {nights} 晚</summary>'
            f'<div class="sheet-body"><h3>{quoted(scene["title"])}</h3>{paragraph(scene["summary"])}'
            f'{link(place_url(hotel), "查住宿地址", "chapter-hotel")}</div></details></aside>'
            for (name, area, nights, first, last, anchor, hotel), scene in zip(CITIES, self.trip["scenes"])
        )

    def map_pins(self):
        west, south, east, north = MAP_WINDOW
        locations = []
        for key, name, day, dates, lon, lat, side in MAP_STOPS:
            x = (lon - west) / (east - west) * 100
            y = (north - lat) / (north - south) * 100
            locations.append(
                f'<a class="coast-pin pin-{side}" href="#{self.photo_id(day)}" data-stop="{key}" '
                f'data-x="{x:.4f}" data-y="{y:.4f}" style="--pin-x:{x:.4f}%;--pin-y:{y:.4f}%" '
                f'aria-label="{name} · {dates}"><span>{name}</span></a>'
            )
        return join(locations)

    def atlas_pages(self):
        return join(
            f'<article class="atlas-page" id="{self.photo_id(number)}" data-atlas-day="{number}" data-map-stop="{region}" '
            f'aria-label="第 {number} 天 · {quoted(self.art[key]["name"])}">'
            f'{self.image(key, caption_name=False)}'
            f'<div class="atlas-caption"><div><p class="day-meta">第 {number} 天 · {quoted(DAY_INDEX_LABELS.get(day["label"], day["label"]))}</p>'
            f'<h4>{quoted(self.art[key]["name"])}</h4></div>'
            f'<div class="atlas-links">{self.day_link(number, "看当天安排")}'
            f'{link(place_url(place) + f"?day={number - 1}", "查图中地点")}</div></div></article>'
            for number, ((key, region, place), day) in enumerate(zip(DAY_ART, self.days), 1)
        )

    def scenes(self):
        cards = []
        for art, city, item, place in SCENES:
            number = self.day_numbers[item]
            name = quoted(self.art[art]["name"])
            cards.append(
                f'<article class="scene-card" id="scene-{art}" data-scene-day="{number}">'
                f'{self.image(art, caption_name=False)}<div class="scene-copy">'
                f'<p class="day-meta">{city} · 第 {number} 天</p><h3>{name}</h3><div class="scene-links">'
            f'{link(place_url(place), "地点详情")}'
            f'{link("#" + self.event_id(item), f"去第 {number} 天行程")}</div></div></article>'
            )
        return join(cards)

    def clock_strip(self, number, day):
        marks = []
        for item in day["items"]:
            stamp = item_start(item)
            if not stamp:
                continue
            when = event_time(stamp, day)
            marks.append((when.hour * 60 + when.minute, when.strftime("%H:%M"), item))
        if len(marks) < 2 or marks[-1][0] <= marks[0][0]:
            return ""
        first, first_stamp, item = marks[0]
        last, last_stamp, _ = marks[-1]
        control = f"clock-day-{number}"
        ticks = join(
            f'<i class="time-mark" style="--mark:{(minute - first) / (last - first) * 100:.3f}%" '
            f'data-minute="{minute}" data-stamp="{stamp}" data-event="{self.event_id(activity["id"])}" '
            f'data-name="{quoted(activity_label(activity))}"></i>'
            for minute, stamp, activity in marks
        )
        title = activity_label(item)
        return (
            f'<div class="day-clock js-only" data-clock><label for="{control}">拖动浏览当天时刻</label>'
            f'<div class="clock-axis"><div class="clock-ticks" aria-hidden="true">{ticks}</div>'
            f'<input id="{control}" type="range" min="{first}" max="{last}" value="{first}" step="1" '
            f'aria-valuetext="{first_stamp} {quoted(title)}"></div>'
            f'<div class="clock-ends" aria-hidden="true"><span>{first_stamp}</span><span>{last_stamp}</span></div>'
            f'<div class="clock-preview"><p aria-live="polite"><time datetime="{first_stamp}" data-clock-time>{first_stamp}</time>'
            f'<span data-clock-name>{quoted(title)}</span></p>'
            f'{link("#" + self.event_id(item["id"]), "展开", flags=" data-clock-link")}</div></div>'
        )

    def fallback(self, option, number, index):
        anchor = f"{self.day_id(number)}--fallback-{index}"
        place_id = option.get("place_id")
        destination = ""
        if place_id:
            place = self.places[place_id]
            destination = (
                f'<div class="fallback-destination">{self.place_link(place_id)}'
                f'{paragraph(place.get("address", ""), "address")}</div>'
            )
        resume = option.get("resume_item_id")
        continuation = ""
        if resume:
            _, item = self.activities[resume]
            continuation = link("#" + self.event_id(resume), f"接回 {item_start(item)} · {item['title']}")
        return (
            f'<details class="fallback" id="{anchor}"><summary>{quoted(option["title"])}</summary>'
            f'<div class="fallback-body"><p class="condition">{quoted(option["trigger"])}</p>{destination}'
            f'{self.field_steps(option, "改线步骤")}{paragraph(option["detail"], "activity-context")}'
            f'{paragraph(option.get("cost_note", ""), "muted")}{continuation}{self.actions(option)}</div></details>'
        )

    def activity(self, item):
        title = item["title"]
        clock = item_start(item)
        arrival = item.get("arrive_by")
        deadline = ""
        if arrival:
            deadline = f'<p class="activity-limit">{quoted(item.get("arrive_label", "最晚抵达"))} <strong>{clock_face(arrival)}</strong></p>'
        details = f'<p class="elapsed">{item_clocks(item, " – ")}</p>' if item.get("end") else ""
        status = '<small class="sample">示例</small>' if title.startswith("示例航段") or "参考窗口" in title else ""
        short_title = activity_label(item)
        return (
            f'<details class="activity" id="{self.event_id(item["id"])}">'
            f'<summary>{clock_face(clock) if clock else "<span></span>"}<span>{quoted(short_title)}{status}</span></summary>'
            f'<div class="activity-body">{details}{self.connections(item)}{deadline}{self.field_steps(item)}'
            f'{paragraph(item.get("detail", ""), "activity-context")}'
            f'{self.actions(item)}</div></details>'
        )

    def schedule(self, number, day):
        day_id = self.day_id(number)
        stage_tabs, stages = [], []
        choices = list(enumerate(day.get("alternatives", []), 1))
        for index, (title, items) in enumerate(group_day_items(day), 1):
            anchor = f"{day_id}--stage-{index}"
            heading = f'<h4>{quoted(title)}</h4>' if title else ""
            if title:
                stage_tabs.append(link("#" + anchor, title, "jump-link"))
            rows = []
            for item in items:
                rows.append(self.activity(item))
                rows.extend(
                    self.fallback(option, number, idx) for idx, option in choices
                    if option.get("decision_item_id") == item["id"]
                )
            stages.append(f'<div class="day-stage" id="{anchor}">{heading}{"".join(rows)}</div>')
        jumps = f'<nav class="stage-jumps" aria-label="第 {number} 天各段">{"".join(stage_tabs)}</nav>' if stage_tabs else ""
        alternatives = join(self.fallback(option, number, idx) for idx, option in choices if not option.get("decision_item_id"))
        forecast = ""
        if number == 5:
            ferry = (("d5-check", "查船班"), ("d5-board", "到大陆码头"), ("d5-back", "岛上会合目标"))
            periods = join(
                f'<a href="#{self.event_id(key)}">{clock_face(item_start(self.activities[key][1]))}<span>{label}</span></a>'
                for key, label in ferry
            )
            forecast = f'<nav class="ferry-times" aria-label="刘公岛登船时刻">{periods}</nav>'
        if number == len(self.days):
            forecast = link(f"#field-{self.key}--event-{self.route['return_item_id']}", "打开机场时限与返程试算", "button primary")
        stay = f'<p class="day-stay">住宿 {self.place_link(day["stay_id"])}</p>' if day.get("stay_id") else ""
        place_list = link(f"#place-lookup?day={number - 1}", "查当天地址", "text-action day-places")
        meta = " · ".join(day[key] for key in ("area", "pace") if day.get(key))
        day_story = paragraph(day.get("story", ""), "day-story")
        expand = (
            f'<button class="detail-toggle js-only" type="button" data-day-expand '
            f'aria-expanded="false" aria-controls="{day_id}--schedule">展开当天细节</button>'
        )
        return (
            f'<article class="day-page" id="{day_id}" data-day-page="{number}" '
            f'data-scenery="{DAY_ART[number - 1][0]}" aria-labelledby="{day_id}-title">'
            f'<div class="day-brief"><header class="day-heading"><p class="day-meta">第 {number} 天 <span>{quoted(meta)}</span></p>'
            f'<h3 id="{day_id}-title">{quoted(day["title"])}</h3></header>{day_story}'
            f'<p class="day-focus">{quoted(day.get("focus", ""))}</p>{self.day_illustration(number)}{stay}{forecast}</div>'
            f'<div class="day-route"><div class="day-controls">{expand}{place_list}</div>'
            f'{self.clock_strip(number, day)}{jumps}<div class="day-schedule" id="{day_id}--schedule">{"".join(stages)}</div>'
            f'{alternatives}{self.day_options(number)}</div></article>'
        )

    def day_illustration(self, number):
        art_key, _, place_id = DAY_ART[number - 1]
        art = self.art[art_key]
        title = quoted(art["name"])
        src = self.asset_url(self.thumbnail(self.art_path(art.get("thumb", art["file"]))))
        return (
            f'<figure class="day-illustration"><a href="{place_url(place_id)}" class="day-illustration-link">'
            f'<img src="{src}" alt="{quoted(art["alt"])}" loading="lazy" decoding="async" fetchpriority="low">'
            f'<span>{title}<span aria-hidden="true">↗</span></span></a></figure>'
        )

    def day_options(self, number):
        options = self.sights["day_choices"].get(str(number), [])
        if not options:
            return ""
        items = join(
            f'<li>{self.place_link(place_id)}{paragraph(description)}</li>'
            for place_id, description in options
        )
        return f'<details class="day-options sheet"><summary>顺路加站或替换 <span>{len(options)} 处</span></summary><ul>{items}</ul></details>'

    def extra_day(self):
        extra = self.sights["extra_day"]
        group = next(group for city in self.sights["cities"] for group in city["groups"] if group.get("extra_day"))
        previews = join(
            f'<a href="{place_url(place_id)}">{self.sight_image(place_id, 0)}'
            f'<span>{quoted(self.places[place_id]["name"])}</span></a>'
            for place_id, *_ in group["sights"]
        )
        rows = join(
            f'<li><span class="longer-clock">{quoted(clock)}</span>'
            f'<div>{link(place_url(place_id), title, "inline-place")}{paragraph(detail)}</div></li>'
            for clock, title, place_id, detail in extra["stages"]
        )
        return (
            '<section class="longer-route" id="extra-day" data-scenery="weihai" aria-labelledby="extra-day-title">'
            '<div><p class="day-meta">可选第 6 天 · 9 天 8 晚</p>'
            f'<h3 id="extra-day-title">{quoted(extra["title"])}</h3>{paragraph(extra["intro"])}'
            f'<div class="longer-sights">{previews}</div></div>'
            f'<div><ol>{rows}</ol><p class="longer-planning">{quoted(extra["planning"])}</p>'
            f'<nav class="longer-next" aria-label="九天行程后段">{self.day_link(6, "第 7 天 · 芝罘老城")}'
            f'{self.day_link(7, "第 8 天 · 蓬莱")}{self.day_link(8, "第 9 天 · 返程")}</nav></div></section>'
        )

    def food(self):
        menus = {city: [] for city, *_ in CITIES}
        for area, dish, art, item, place, desc in sorted(DISHES, key=lambda row: row[2] not in FOOD_LEADS):
            city, _, district = area.partition(" · ")
            day = self.day_numbers[item]
            day_label = f"第 {day} 天" + (f" · {district}" if district else "")
            source = FOOD_EVIDENCE.get(art)
            credit = citation(source[1], source[0]) if source else ""
            if place:
                where = link(place_url(place), "查附近用餐" if place in MEAL_AREAS else "查用餐地点")
            else:
                nearby = "蒸汽海鲜" if art == "pl-steam" else "鲁菜馆"
                query = urlencode({"keyword": f"蓬莱{nearby}", "city": "烟台", "src": "jiaodong-roadbook", "callnative": 0})
                where = citation(f"https://uri.amap.com/search?{query}", f"查蓬莱城区{nearby}", "text-action")
            menus[city].append(
                f'<article class="food-card" id="food-{art}">'
                f'{self.image(art, caption_name=False)}<details class="dish-details">'
                f'<summary><span class="dish-day">{day_label}</span><span class="dish-name">{quoted(dish)}</span></summary>'
                '<div class="food-copy">'
                f'{paragraph(desc, "dish-description")}<div class="food-actions">'
                f'{where}'
                f'{link("#" + self.event_id(item), f"去第 {day} 天餐段")}'
                f'{credit}</div></div></details></article>'
            )
        return join(
            f'<section class="food-city" data-food-city="{quoted(city)}" '
            f'data-scenery="{DAY_ART[CITIES[number - 1][3] - 1][0]}" aria-labelledby="menu-city-{number}">'
            f'<header><h3 class="subhead" id="menu-city-{number}">{quoted(city)}</h3><span>{len(cards)} 道</span></header>'
            f'<div class="food-city-grid" data-film>{"".join(cards)}</div></section>'
            for number, (city, cards) in enumerate(menus.items(), 1)
        )

    def food_tip(self):
        topic = next(tip for tip in self.spec["tips"] if tip["category"] == "美食")
        return f'<details class="sheet food-tip"><summary>五六人怎么点菜</summary><div class="sheet-body">{paragraph(topic["text"])}{self.actions(topic)}</div></details>'

    def place_atlas(self):
        landings, sections = [], []
        for city, (_, area, nights, start, end, _, hotel) in zip(self.sights["cities"], CITIES):
            name, anchor, lead = city["city"], city["id"], city["lead"]
            count = sum(len(group["sights"]) for group in city["groups"])
            landings.append(f'<a href="#{anchor}">{name}<small>{count} 处</small></a>')
            image_link = f'<a class="city-view" href="{place_url(lead)}" aria-label="看{quoted(self.places[lead]["name"])}详情">'
            groups = join(self.sight_group(group) for group in city["groups"])
            sections.append(
                f'<article class="city-gallery" id="{anchor}" data-scenery="{DAY_ART[start - 1][0]}" aria-labelledby="{anchor}-title">'
                f'<header class="city-gallery-intro">{image_link}{self.sight_image(lead, -1, lead=True)}</a>'
                f'<div><p class="day-meta">第 {start}–{end} 天 · {count} 处可游览</p>'
                f'<h3 id="{anchor}-title">{name}</h3><p class="city-gallery-heading">{quoted(city["heading"])}</p>'
                f'{paragraph(city["summary"])}<div class="city-gallery-links">{self.day_link(start, "看这一段的行程")}'
                f'{link(place_url(hotel), f"住{area} {nights} 晚")}</div></div></header>{groups}</article>'
            )
        return f'<nav class="section-landings" aria-label="跳至城市地点">{join(landings)}</nav>{join(sections)}'

    def thumbnail(self, path):
        thumb = self.folder / "art" / "thumbnails" / path.name
        return thumb if thumb.is_file() else path

    def sight_image(self, place_id, index, lead=False):
        photo = self.place_media[place_id][index]
        if "art" in photo:
            art = self.art[photo["art"]]
            path = self.art_path(art["file"] if lead else art.get("thumb", art["file"]))
        else:
            path = self.edited_photo_path(photo)
        if not lead:
            path = self.thumbnail(path)
        return f'<img src="{self.asset_url(path)}" alt="{quoted(photo["caption"])}" loading="lazy" decoding="async">'

    def sight_group(self, group):
        items = []
        for place_id, role, time, detail in group["sights"]:
            place = self.places[place_id]
            count = len(self.place_media[place_id])
            items.append(
                f'<li id="view-{place_id}" data-sight="{place_id}"><a class="sight-card" href="{place_url(place_id)}">'
                f'<span class="sight-picture">{self.sight_image(place_id, 0)}<span>{count} 幅</span></span>'
                f'<span class="sight-card-title"><strong>{quoted(place["name"])}</strong><i aria-hidden="true">↗</i></span>'
                f'<span class="sight-use">{quoted(role)} · {quoted(time)}</span>'
                f'<span class="sight-line">{quoted(detail)}</span></a></li>'
            )
        day = group.get("day")
        route = self.day_link(day, f"看第 {day} 天") if day else link("#extra-day", "看九天版走法")
        classes = "sight-group extra-sights" if group.get("extra_day") else "sight-group"
        backdrop = DAY_ART[day - 1][0] if day else "weihai"
        return (
            f'<section class="{classes}" data-scenery="{backdrop}"><header><div>'
            f'<h4>{quoted(group["title"])}</h4>{paragraph(group["caption"])}</div>{route}</header>'
            f'<ul class="sight-grid">{join(items)}</ul></section>'
        )

    def place_routes(self):
        routes = []
        for number, day in enumerate(self.days, 1):
            ordered = []
            for item in day["items"]:
                start = item_start(item)
                for place_id, time in (
                    (item.get("from_id"), start),
                    (item.get("place_id"), start),
                    (item.get("to_id"), item.get("end") or start),
                ):
                    if place_id and (not ordered or ordered[-1][0] != place_id):
                        ordered.append((place_id, time))
            stops = []
            for place_id, time in ordered:
                place = self.places[place_id]
                clock = clock_face(time) if time else '<span class="event-clock">按当天安排</span>'
                stops.append(
                    f'<li class="index-stop" data-kind="{quoted(place["category"])}">'
                    f'<a href="{place_url(place_id)}">{clock}<span class="index-stop-dot" aria-hidden="true"></span>'
                    f'<strong>{quoted(place["name"])}</strong></a></li>'
                )
            routes.append(
                f'<ol class="index-stops" id="place-route-{number}" data-place-route="{number}" '
                f'aria-label="第 {number} 天计划停靠时刻" tabindex="0" hidden>{"".join(stops)}</ol>'
            )
        return join(routes)

    def place_controls(self):
        options = "".join(f'<option value="{i}">第 {i} 天 · {quoted(day["label"])}</option>' for i, day in enumerate(self.days, 1))
        type_buttons = join(
            f'<button type="button" data-place-filter="{key}" aria-controls="place-results" '
            f'aria-pressed="{str(key == "all").lower()}">{label}</button>'
            for key, label in (("all", "全部"), ("sight", "景点"), ("stay", "住宿"), ("transport", "交通"), ("food", "美食"))
        )
        return (
            '<div class="place-controls js-only"><label for="place-query">搜全程地点'
            '<input id="place-query" type="search" placeholder="地名、酒店或车站"></label>'
            '<label class="date-field" for="place-day">按天查看'
            f'<select id="place-day"><option value="all">全程地点</option>{options}</select></label></div>'
            '<div class="place-types js-only" role="group" aria-label="筛选地点类型">' + type_buttons + '</div>'
        )

    def address_actions(self, place):
        address = place.get("address", "")
        copy = (
            f'<button class="chip js-only" type="button" data-copy="{quoted(address)}">'
            '<span data-copy-label>复制地址</span></button>'
        ) if address else ""
        maps = external_links(place.get("links", []))
        return f'<div class="actions address-actions">{maps}{copy}</div>' if maps or copy else ""

    def place(self, place, region):
        note = paragraph(place.get("note", ""))
        place_id = place["id"]
        sources = self.evidence(place)
        if place_id == "church":
            sources = citation(CHURCH_REFERENCE, "青岛政务网 · 教堂资料") + sources
        details = f'<details class="place-note"><summary>现场提示与资料</summary><div>{note}<div class="actions">{sources}</div></div></details>' if note or sources else ""
        kind = place["category"]
        kind_label = quoted(KINDS.get(kind, kind))
        name = quoted(place["name"])
        area = quoted(place.get("area", ""))
        intro, reason = self.place_stories[place_id]
        photos = self.place_media.get(place_id, [])
        references = join(citation(photo.get("reference") or self.art[photo["art"]]["reference"], photo["caption"]) for photo in photos)
        photo_links = f'<details class="place-note photo-reference"><summary>实拍来源与视角</summary><div class="actions">{references}</div></details>' if references else ""
        return (
            f'<details class="place-entry" data-place-entry="{place_id}" data-kind="{quoted(kind)}" data-region="{region}">'
            f'<summary data-place-link="{place_url(place_id)}"><span>{name}</span><span class="place-entry-kind">{kind_label}</span></summary>'
            f'<article class="place-card" id="place-{place_id}"><h4 class="sr-only">{name}</h4>'
            f'<div class="place-facts"><p class="place-kind">{kind_label} · {area}</p>'
            f'{paragraph(intro, "place-intro")}<section class="place-reason"><h3>为什么选这里</h3>{paragraph(reason)}</section>'
            f'<section class="place-address"><h3>地址与导航</h3>{paragraph(place.get("address", ""), "address")}'
            f'{self.address_actions(place)}</section>{details}{photo_links}</div></article></details>'
        )

    def media_payload(self):
        photos, groups = {}, {}
        for place, records in self.place_media.items():
            for index, record in enumerate(records):
                art_key = record.get("art")
                key = f"{place}-{index + 1}"
                entry = dict(record)
                entry.pop("original", None)
                if art_key:
                    art = self.art[art_key]
                    entry.setdefault("reference", art["reference"])
                    entry["illustration"] = True
                    if art_key not in self.embedded_art:
                        entry["src"] = self.asset_url(self.art_path(art["file"]))
                else:
                    entry["src"] = self.asset_url(self.edited_photo_path(record))
                    entry.pop("file")
                    entry["illustration"] = True
                photos[key] = entry
                groups.setdefault(place, []).append(key)
        return {"places": groups, "photos": photos}

    def place_directory(self):
        groups = {region: [] for region in PLACE_REGIONS}
        for place in self.places.values():
            city = place.get("area", "").partition(" · ")[0]
            region = city if city in groups else "出发与返程"
            groups[region].append(self.place(place, region))
        return join(
            f'<details class="place-group"><summary><span>{region}</span><span>{len(entries)} 处</span></summary>'
            f'<div class="place-group-entries">{join(entries)}</div></details>'
            for region, entries in groups.items() if entries
        )

    def planner(self):
        defaults = return_plan_values(self.route, self.activities)
        departure = defaults["departure"]
        buffers = join(
            f'<label>{label}<span class="buffer-input"><input type="number" name="{key}" value="{defaults.get(key, 0)}"'
            f' inputmode="numeric" min="0" max="1439" required> 分钟</span></label>'
            for key, label in (("entry", "值机与安检"), ("ride", "去机场"), ("bags", "酒店退房取箱"))
        )
        return (
            '<details class="sheet js-only return-planner"><summary>按实际起飞时间倒推</summary>'
            '<div class="sheet-body"><form id="departure-form" class="departure-form">'
            f'<label for="departure">起飞时间 <input id="departure" type="time" name="departure" value="{departure}" required>'
            '</label><div class="actions"><button class="button primary">计算</button>'
            '<button type="reset" class="chip">恢复示例</button></div>'
            f'<details class="planner-buffers"><summary>调整预留时间</summary><div>{buffers}</div></details>'
            '<output id="departure-result" aria-live="polite"></output>'
            '</form></div></details>'
        )

    def returning(self):
        route = self.route
        ids = route["return_plan"]
        _, connection = self.activities[route["return_item_id"]]
        _, flight = self.activities[ids["departure_item_id"]]
        route_steps = join(
            f'<li>{link("#" + self.event_id(key), label, "return-point")}</li>'
            for key, label in (("d8-flight", "烟台"), ("d8-rail", "成都天府"), ("d8-home", "自贡"))
        )
        times = join(f'<div><dt>{label}</dt><dd>{clock_face(stamp)}</dd></div>' for label, stamp in (
            ("酒店出发", item_start(connection)), ("预计到达", connection["end"]), ("示例起飞", item_start(flight))
        ))
        addresses = []
        for key, title in (("from_id", "上车点"), ("to_id", "到达点")):
            place = self.places[connection[key]]
            addresses.append(
                f'<div class="endpoint"><p class="endpoint-role">{title}</p><h4>{self.place_link(place["id"])}</h4>'
                f'{paragraph(place["address"], "address")}{self.address_actions(place)}</div>'
            )
        limit = clock_face(connection["arrive_by"])
        alternatives = join(
            f'<li>{link(f"#{self.day_id(len(self.days))}--fallback-{index}", option["title"])}'
            f'{paragraph(option["trigger"], "muted")}</li>'
            for index, option in enumerate(self.days[-1].get("alternatives", []), 1)
        )
        return (
            '<div class="return-grid"><section class="return-main" aria-labelledby="return-times-title">'
            '<h3 class="subhead" id="return-times-title">航段与时限</h3>'
            f'<div class="return-ticket"><ol aria-label="返程换乘顺序">{route_steps}</ol>'
            f'<p class="return-limit"><span>{quoted(connection["arrive_label"])}</span><strong>{limit}</strong></p>'
            f'<dl class="return-times">{times}</dl></div>{self.planner()}</section>'
            '<section class="endpoints" aria-labelledby="return-addresses-title">'
            '<h3 class="subhead" id="return-addresses-title">接驳地址</h3>'
            f'{"".join(addresses)}'
            f'<div class="return-extra">{link("#" + self.event_id(route["return_item_id"]), "看酒店送机步骤")}'
            f'{link("#" + self.event_id("d8-rail"), "看天府空铁换乘")}</div></section></div>'
            f'<details class="sheet return-options" id="return-options"><summary>主路接不上时怎么改</summary>'
            f'<ul class="return-choice-list">{alternatives}</ul></details>'
        )

    @staticmethod
    def row_amount(row, size):
        count = size if row["basis"] == "per_person" else row.get("quantity", 1)
        return float(row["amount"]) * count, float(row.get("amount_max", row["amount"])) * count

    def budget(self):
        rows = [row for row in self.route["budget"] if row["status"] != "pending"]
        sizes = (5, 6)
        totals = {size: tuple(map(sum, zip(*(self.row_amount(row, size) for row in rows)))) for size in sizes}
        initial = self.trip["travelers"]
        low, high = totals[initial]
        start_total = f"¥{low:,.0f}–{high:,.0f}"
        groups = {row_id: key for _, key, ids in BUDGET_GROUPS for row_id in ids}
        amounts = {key: 0 for _, key, _ in BUDGET_GROUPS}
        amounts["other"] = 0
        for row in rows:
            amounts[groups.get(row["id"], "other")] += self.row_amount(row, initial)[1]
        labels = [(label, key) for label, key, _ in BUDGET_GROUPS]
        if any(row["id"] not in groups for row in rows):
            labels.append(("其他", "other"))
        bar = join(
            f'<span data-budget-share="{key}" style="flex-grow:{amounts[key]}"></span>' for _, key in labels
        )
        legend = join(
            f'<div data-budget-total="{key}"><dt>{label}</dt><dd>¥{amounts[key]:,.0f}</dd></div>' for label, key in labels
        )
        numbers = join(
            f'<label><input type="radio" name="budget-people" value="{size}"{" checked" if size == initial else ""}><span>{size} 人</span></label>'
            for size in sizes
        )
        costs = join(
            f'<li id="budget-{self.key}--{row["id"]}" data-budget-group="{groups.get(row["id"], "other")}"><span>{quoted(row["label"])}</span>'
            f'<strong>¥{self.row_amount(row, initial)[0]:,.0f}–{self.row_amount(row, initial)[1]:,.0f}</strong>'
            f'<div>{paragraph(row.get("note", ""))}{self.actions(row)}</div></li>'
            for row in rows
        )
        return (
            '<section class="budget" id="trip-budget" aria-labelledby="budget-title">'
            f'<header class="prep-module-head"><h3 class="subhead" id="budget-title">全队预算</h3>'
            f'<fieldset class="budget-switch js-only"><legend class="sr-only">同行人数</legend>{numbers}</fieldset></header>'
            f'<p id="budget-summary" aria-live="polite">{start_total}</p>'
            f'<p class="budget-caption"><span>人均 <b id="budget-average">¥{low / initial:,.0f}–{high / initial:,.0f}</b></span>'
            '<span>八天主线 · 人民币估算</span></p>'
            f'<p class="budget-bar-label">预算上限构成</p><div class="budget-bar" aria-hidden="true">{bar}</div>'
            f'<dl class="budget-key">{legend}</dl>'
            f'<details class="sheet budget-details" id="route-{self.key}--budget"><summary>看每项费用</summary>'
            f'<div class="sheet-body"><ul class="budget-list">{costs}</ul></div></details></section>'
        )

    def prep(self):
        task_steps = {key: ids[0] for _, _, ids in BOOKING_STEPS for key in ids}
        first_steps = join(
            f'<li data-booking-step="{ids[0]}" data-task-count="{len(ids)}">'
            f'<a href="#task-{self.key}--{ids[0]}"><span class="booking-dot" aria-hidden="true"></span>'
            f'<span><strong>{label}</strong><small>{hint}</small></span>'
            f'<span class="booking-count js-only" aria-label="已完成 0 项，共 {len(ids)} 项">0/{len(ids)}</span></a></li>'
            for label, hint, ids in BOOKING_STEPS
        )
        tasks = join(
            f'<li id="task-{self.key}--{task["id"]}"><label>'
            f'<input class="js-only" type="checkbox" data-task-step="{task_steps.get(task["id"], "")}" '
            f'data-check="{self.key}--{task["id"]}"><span>{quoted(task["label"])}</span></label>'
            f'{self.field_steps(task)}{paragraph(task["detail"], "activity-context")}{self.actions(task)}</li>'
            for task in self.route["tasks"]
        )
        tips = join(
            f'<details class="sheet"><summary>{quoted(tip["title"])}</summary><div class="sheet-body">'
            f'{paragraph(tip["text"])}{self.actions(tip)}</div></details>'
            for tip in self.spec["tips"] if tip["category"] in ("季节", "交通", "住宿", "途中")
        )
        size = len(self.route["tasks"])
        check = (
            '<section class="booking" aria-labelledby="booking-title">'
            '<header class="prep-module-head"><h3 class="subhead" id="booking-title">预订顺序</h3>'
            f'<output id="check-count" class="js-only">0/{size}</output></header>'
            f'<progress id="prep-progress" class="prep-progress js-only" max="{size}" value="0" aria-label="预订与出发进度"></progress>'
            f'<ol class="booking-track">{first_steps}</ol>'
            f'<details id="route-{self.key}--tasks" class="sheet checklist"><summary>预订与出发清单</summary><ul>{tasks}</ul></details></section>'
        )
        return (
            f'<div class="prep-grid">{check}{self.budget()}</div>'
            '<section class="prep-tips" aria-labelledby="prep-tips-title">'
            '<h3 class="subhead" id="prep-tips-title">出行提示</h3>'
            f'<div class="compact-tips">{tips}</div></section>'
        )

    def prep_plates(self):
        plates = (
            ("packing", "证件随身带，海边穿的防风外层放箱顶。"),
            ("station", "青岛站和青岛北站分开核对，两车都按票面发定位。"),
        )
        return join(f'<div>{self.image(key, caption_name=False)}{paragraph(copy)}</div>' for key, copy in plates)

    def source_list(self):
        credits = []
        for art in self.art.values():
            raw = link(art["reference"], art["credit"], "text-action", ' target="_blank" rel="noopener noreferrer"')
            license_link = link(art["license"], "参考图许可", "source-link") if art.get("license") else ""
            credits.append(f'<li><b>{quoted(art["name"])}</b> {raw} {license_link}</li>')
        rock_credit = link("https://www.pexels.com/photo/rocks-on-sea-shore-17538315/", "lee starry · Pexels", "text-action",
                           ' target="_blank" rel="noopener noreferrer"')
        credits.append(f'<li><b>海岸装饰</b> 威海岩岸 {rock_credit} · 回澜阁参考栈桥封面实拍。</li>')
        verified = join(
            f'<li id="source-{key}"><a href="{quoted(entry["url"])}" target="_blank" rel="noopener noreferrer">{quoted(entry["title"])}</a>'
            f'{paragraph(entry.get("note", ""))}</li>'
            for key, entry in self.sources.items()
        )
        return f'<h3>据实拍生成的插图</h3><ul class="source-credits">{"".join(credits)}</ul><h3>出行原始资料</h3><ol class="list-sources">{verified}</ol>'

    def render(self):
        snapshot = deepcopy(self.spec)
        snapshot["trip"].pop("cover", None)
        snapshot["trip"].pop("scenes", None)
        for day in snapshot["routes"][0]["days"]:
            day.pop("photo", None)
        snapshot["nearby_sights"] = {
            day: [row[0] for row in rows] for day, rows in self.sights["day_choices"].items()
        }
        snapshot["tips"] = [tip for tip in snapshot["tips"] if tip["category"] not in ("使用", "图源")]
        texture = self.asset_url(self.folder / "art" / "navigation.webp")
        ornaments = self.asset_url(self.folder / "art" / "marginalia.webp")
        styles = f':root{{--motifs: url("{texture}");--ornaments: url("{ornaments}")}}\n' + "\n".join(
            (self.folder / name).read_text(encoding="utf-8")
            for name in ("style.css", "atlas.css", "gallery.css", "directory.css", "steps.css")
        )
        script = "\n".join(
            (self.folder / name).read_text(encoding="utf-8") for name in ("app.js", "atlas.js")
        )
        if "</style" in styles.lower() or "</script" in script.lower():
            raise ValueError("内嵌样式与脚本应为完整源文件")
        template = Template((self.folder / "index.html").read_text(encoding="utf-8"))
        coast = json_for_script({"window": MAP_WINDOW, "coast": self.coastline})
        title = quoted(self.trip["title"])
        cover_title = title.replace("沿着胶东海岸", "<span>沿着</span>胶东海岸")
        preload, offline = "", ""
        if self.offline_href:
            cover_source = self.asset_url(self.art_path(self.art["qingdao"]["file"]))
            preload = f'<link rel="preload" as="image" href="{quoted(cover_source)}" fetchpriority="high">'
            offline = link(self.offline_href, "保存离线版", flags=' download="胶东海岸八日.html"')
        return template.substitute(
            title=title, cover_title=cover_title, intro=quoted(self.trip["summary"]), preload=preload, offline=offline,
            notice=quoted(self.trip["notice"]), styles=styles, script=script,
            hero=self.image("qingdao", cover=True), stops=self.stops(), days=self.day_tabs(), chapters=self.chapters(),
            atlas=self.atlas_pages(), pins=self.map_pins(), coast=coast, scenes=self.scenes(),
            schedules=join(self.schedule(n, day) + (self.extra_day() if n == 5 else "") for n, day in enumerate(self.days, 1)),
            food=self.food(), food_tip=self.food_tip(),
            place_atlas=self.place_atlas(), place_routes=self.place_routes(), place_controls=self.place_controls(),
            places=self.place_directory(), place_total=len(self.places), sight_total=self.sight_count, returning=self.returning(),
            prep=self.prep(), packing=self.prep_plates(),
            sources=self.source_list(), data=json_for_script(snapshot), place_media=json_for_script(self.media_payload()),
        )
