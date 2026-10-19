# -*- coding: utf-8 -*-
"""Supermarket promo bot: SAS, Yerevan City -> Telegram channel.

Այս տարբերակում ուղղված է.
 1. Բոտը կարդում է ցուցակի ԲՈԼՈՐ էջերը, ոչ միայն առաջինը. SAS-ի զեղչերի
    բաժինը 825+ դիրք ունի՝ 24-ական էջերով (?offset=24, 48, 72...), ու առաջին
    էջի 16 ապրանքից բացի մնացածը բոտի համար ընդհանրապես գոյություն չուներ։
 2. Հերթը 200 դիրք է ու գործում է «մեկը գնաց, մեկը եկավ» կանոնով. ամեն
    հրապարակումից ազատված տեղի չափով նոր դիրք է մտնում հերթ, ուստի ոչինչ
    առանց հրապարակվելու դուրս չի ընկնում։ Կարգը կայքի կարգն է։
 3. «Տեսած» է համարվում ՄԻԱՅՆ այն, ինչ մտել է հերթ։ Բանալին ապրանքի համարն է
    + գնային զույգը, ուստի նույն ակցիան երկու անգամ չի հրապարակվում, իսկ նույն
    ապրանքը նոր գնով նորից է գալիս։
 4. Yerevan City-ն կարդացվում է բաց API-ից (GetDiscounted)՝ 94 էջ 30-ական,
    ոչ թե HTML-ի առաջին էջից։ Էջերի միջև անցնում է ցուցիչը, ու մեկ էջից
    վերցվում է այնքան, որքան տեղ կա հերթում։
 5. Ծաղիկների բաժինը (SAS Flowers by Villani, Milani) ընդհանրապես չի
    հրապարակվում՝ ոչ ցուցակից, ոչ հերթից։
 6. Լուսանկարը գնում է ՈՐՊԵՍ ՆԿԱՐ (JPEG), ոչ ֆայլով. ընտրվում է ՉԱՓՍՈՎ՝
    ամենամեծ լայնություն×բարձրությունը, ոչ ֆայլի ծանրությամբ, ու նախապես
    դարձվում է JPEG լրիվ չափսը պահելով (27 ՄԲ PNG → մի քանի հարյուր ԿԲ JPEG)։
 7. Մեկ հատի գինը («2 127 դր./1լ») չի մտնում որպես նոր գին։
 8. SAS-ի քարտը ճանաչվում է ցուցակի մարկերով՝ [](/catalog/<բաժին>/<id>/),
    իսկ նավիգացիոն հղումները ապրանք չեն համարվում։
 9. Ամեն էջի համար 3 փորձ՝ աճող դադարով, ու էջերի միջև կարճ դադար, որ
    կայքի ու միջնորդի սահմանաչափերից էջը դատարկ չվերադառնա։
10. JPEG դարձնելու համար պետք է Pillow-ը (pip install Pillow)։
11. Միանվագ մաքրումներ՝ ծաղիկների դիրքերը հերթից ու հին ոչ-քարտ աղբը։
"""
import io
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

try:
    from PIL import Image
except ImportError:
    Image = None

TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL = os.environ.get("CHANNEL", "")
DRY = os.environ.get("DRY_RUN", "0") == "1"

STATE = "state-promo.json"
YE = timezone(timedelta(hours=4))
# Քայլ 14, ոչ 15. GitHub-ի ռանները գալիս են 15 րոպեով ու վայրկյաններով,
# ուղիղ 15-ի դեպքում ամեն երկրորդ սլոտը դուրս էր ընկնում։
STEP_MIN = 14
PUB_FROM, PUB_TO = 0, 24
QUEUE_CAP = 200
# «Տեսածը» պահվում է լիքը, որ հրապարակված դիրքը չվերադառնա որպես նոր։
SEEN_KEEP = 6000
PAGE_LIMIT = 900
PAGE_PAGES = 40
PAGE_BUDGET = 600
PAGE_PAUSE = 1.5
PAGE_TRIES = 3
SAS_STEP = 24
API = "https://api.telegram.org/bot%s/" % TOKEN
JINA = "https://r.jina.ai/"
JPEG_QUALITY = 92
PHOTO_MAX_BYTES = 9 * 1024 * 1024
PHOTO_MAX_SIDE = 10000

SKIP_IMG = ("logo", "18-plus", "flags/", "icon", "banner", "banniere", "svg",
            "sprite", "placeholder", "no-photo", "nophoto")

FLOWER_URL = re.compile(r"/catalog/(?:sasexclusiveflowers|flowers|milaniroses|"
                        r"milani|milancomp|milanbalon|mona|monaflowers|myrose|"
                        r"my_rose|balloon|balloons|tsvety|flowersas|"
                        r"cataleya|cataleyabuyser|villaniflowers|milancompos|"
                        r"milanpuchik|cataleyaflowers|milanirose7)", re.I)
FLOWER_TITLE = re.compile(r"Flowers by Villani|Milani|Ծաղկեփունջ|ծաղկային "
                          r"կոմպոզիցիա|փուչիկ", re.I)

HDRS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "hy,ru;q=0.9,en;q=0.8",
}

BOOST = "https://t.me/boost/supermarket_promos"
BUTTON = json.dumps(
    {"inline_keyboard": [[{"text": "😊 Աջակցել ալիքին", "url": BOOST}]]},
    ensure_ascii=False,
)

STORES = {
    "SAS": "https://www.sas.am/catalog/discount/",
    "Yerevan City": "https://yerevan-city.am/shop/best-offers",
}
PRICE = re.compile(r"([\d][\d\s,\.]{1,12}?)\s*(?:֏|դր\.?|\bnull\b)(?!\.?\s*/)")
DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
SAS_CARD = re.compile(r"\[\]\((https://www\.sas\.am/(?!upload/)[^)\s]*/\d{3,}/?)\)")
SAS_ALT = re.compile(r"!\[(?:Image\s+\d+\s*:\s*)?([^\]]{4,160})\]\(([^)]*)\)")
SAS_LINK = re.compile(
    r"\[(?:!\[([^\]]{4,160})\]\(([^)]*)\)|([^\]\n]{4,160}))\]"
    r"\((https://www\.sas\.am/(?!upload/)[^)\s]+)\)")
CITY_LINK = re.compile(
    r"\[([^\]]{10,400}?)\]\((https://yerevan-city\.am/shop/product-details/(\d+))\)", re.S)
CITY_PRICE = re.compile(
    r"~~\s*([\d][\d\s,\.]{0,14}?)\s*(?:֏|\bnull\b)?\s*~~\s*([\d][\d\s,\.]{0,14})", re.S)
NAME = re.compile(r"[Ա-Ֆա-ֆև]|[А-Яа-яЁё]")
RU_LABEL = re.compile(r"^\s*(Скидка|Эксклюзив|Акция|Суперцена|Sale)\s*[:.\-]?\s*", re.I)
PCT_HEAD = re.compile(r"^\s*[-–—+%]*\s*\d{1,3}\s*%?\s*")
ARTIC = re.compile(r"\s+\d{4,}$")
IMG_PREFIX = re.compile(r"^!?\[?\s*(?:Image\s+\d+\s*:?\s*)?", re.I)
OG = re.compile(
    r"""<meta[^>]+(?:property|name)=['"]og:image['"][^>]+content=['"]([^'"]+)['"]""", re.I)
OG2 = re.compile(
    r"""<meta[^>]+content=['"]([^'"]+)['"][^>]+(?:property|name)=['"]og:image['"]""", re.I)
IMG_SRC = re.compile(r"""<img[^>]+src=['"]([^'"]+\.(?:webp|jpe?g|png)[^'"]*)['"]""", re.I)
IMG_MD = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")
MONTHS = {"հունվար": 1, "փետրվար": 2, "մարտ": 3, "ապրիլ": 4, "մայիս": 5,
          "հունիս": 6, "հուլիս": 7, "օգոստոս": 8, "սեպտեմբեր": 9,
          "հոկտեմբեր": 10, "նոյեմբեր": 11, "դեկտեմբեր": 12}
CARD_DATE = re.compile(r"(\d{1,2})\s+([Ա-Ֆա-ֆև]{3,12})\s+(\d{4})")

def fetch(url):
    r = requests.get(JINA + url, timeout=120,
                     headers={"User-Agent": HDRS["User-Agent"],
                              "Accept-Language": HDRS["Accept-Language"]})
    r.raise_for_status()
    return r.text

def fetch_page(store, page_url):
    for t in range(PAGE_TRIES):
        try:
            md = fetch(page_url)
            if md and len(md) > 2000:
                return md
            print("%s: էջը կարճ եկավ (%d նշան), փորձ %d/%d"
                  % (store, len(md or ""), t + 1, PAGE_TRIES))
        except Exception as e:
            print("%s: բեռնելու սխալ (%d/%d): %s" % (store, t + 1, PAGE_TRIES, e))
        time.sleep(4 * (t + 1))
    return ""
def num(s):
    s = (s or "").replace(" ", "").replace(",", "")
    s = s.split(".")[0]
    s = re.sub(r"\D", "", s)
    return int(s) if s else 0

def money(n):
    return "{:,}".format(n).replace(",", " ")

def is_flower(url, title):
    return bool(FLOWER_URL.search(url or "") or FLOWER_TITLE.search(title or ""))

def is_flower_item(it):
    return is_flower(it.get("url") or "", it.get("title") or "")

def img_dims(data):
    if len(data) > 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
    if len(data) > 4 and data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker == 0xD8 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg = int.from_bytes(data[i + 2:i + 4], "big")
            if seg < 2:
                break
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h = int.from_bytes(data[i + 5:i + 7], "big")
                w = int.from_bytes(data[i + 7:i + 9], "big")
                return (w, h)
            i += 2 + seg
        return (0, 0)
    if len(data) > 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        four = data[12:16]
        if four == b"VP8X":
            w = int.from_bytes(data[24:27], "little") + 1
            h = int.from_bytes(data[27:30], "little") + 1
            return (w, h)
        if four == b"VP8L":
            n = int.from_bytes(data[21:25], "little")
            return ((n & 0x3FFF) + 1, ((n >> 14) & 0x3FFF) + 1)
        if four == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            w = int.from_bytes(data[26:28], "little") & 0x3FFF
            h = int.from_bytes(data[28:30], "little") & 0x3FFF
            return (w, h)
        return (0, 0)
    return (0, 0)

def has_name(s):
    return bool(NAME.search(s or ""))

def img_in(chunk):
    for u in IMG_MD.findall(chunk):
        if not any(s in u.lower() for s in SKIP_IMG):
            return u
    return ""

def clean_title(t):
    t = re.sub(r"~~.*$", "", t or "", flags=re.S)
    t = re.sub(r"\s+", " ", t.replace("\\", " ")).strip(" -|")
    for _ in range(3):
        before = t
        t = IMG_PREFIX.sub("", t).strip(" -|")
        t = PCT_HEAD.sub("", t).strip(" -|%")
        t = RU_LABEL.sub("", t).strip(" -|")
        if t == before:
            break
    return ARTIC.sub("", t).strip(" -|")

def make(store, title, old, new, until, img, url=""):
    title = clean_title(title)
    if len(title) < 4 or new <= 0 or old <= new:
        return None
    if not has_name(title):
        return None
    pct = round((old - new) * 100 / old)
    if pct < 5:
        return None
    return {"store": store, "title": title, "old": old, "new": new,
            "pct": pct, "until": until or "", "img": img or "", "url": url or ""}
def parse_sas(md):
    cards = list(SAS_CARD.finditer(md))
    if not cards and DRY:
        print("SAS debug: %s" % md[:300].replace("\n", " | "))
    if not cards:
        return parse_sas_links(md)
    out, flowers = [], 0
    for i, m in enumerate(cards):
        url = m.group(1)
        end = cards[i + 1].start() if i + 1 < len(cards) else min(len(md), m.end() + 1200)
        chunk = md[m.end():end]
        cut = chunk.find("Զամբյուղում")
        if cut != -1:
            chunk = chunk[:cut]
        alt = SAS_ALT.search(chunk)
        if not alt:
            continue
        if is_flower(url, alt.group(1)):
            flowers += 1
            continue
        prices = [p for p in (num(x) for x in PRICE.findall(chunk)) if p > 0]
        if len(prices) < 2:
            continue
        dates = DATE.findall(chunk)
        out.append(make("SAS", alt.group(1), prices[0], prices[-1],
                        dates[-1] if dates else "", alt.group(2), url))
    if flowers:
        print("SAS: ծաղիկների բաժինը դուրս մնաց՝ %d դիրք" % flowers)
    return [x for x in out if x]

def parse_sas_links(md):
    out, links = [], list(SAS_LINK.finditer(md))
    skip = ("հավելին", "ցույց", "ցուցադրել", "ֆիլտր", "փակել", "շուտով",
            "купить", "в корзину", "подробнее", "все акции",
            "ամբողջ բաժինը", "զամբյուղ", "զամբյուղում", "ներբեռնել")
    for i, m in enumerate(links):
        text = (m.group(1) or m.group(3) or "").strip()
        url = m.group(4)
        if not text or any(s in text.lower() for s in skip):
            continue
        if is_flower(url, text):
            continue
        end = links[i + 1].start() if i + 1 < len(links) else min(len(md), m.end() + 900)
        chunk = md[m.end():end]
        cut = chunk.find("Զամբյուղում")
        if cut != -1:
            chunk = chunk[:cut]
        if not re.search(r"/\d{3,}/?$", url) and "գործում է" not in chunk:
            continue
        prices = [p for p in (num(x) for x in PRICE.findall(chunk)) if p > 0]
        if len(prices) < 2:
            continue
        dates = DATE.findall(chunk)
        out.append(make("SAS", text, prices[0], prices[-1],
                        dates[-1] if dates else "",
                        m.group(2) or img_in(chunk), url))
    return [x for x in out if x]

def parse_city(md):
    out = []
    for m in CITY_LINK.finditer(md):
        inner = m.group(1)
        pr = CITY_PRICE.search(inner)
        if not pr:
            continue
        title = re.sub(r"~~.*$", "", inner, flags=re.S)
        out.append(make("Yerevan City", title, num(pr.group(1)), num(pr.group(2)),
                        "", "", m.group(2)))
    return [x for x in out if x]

# ==== Yerevan City. բաց API՝ ակցիաների ամբողջ ցուցակը (2026-10-19) ====
CITY_API = "https://apishopv2.yerevan-city.am/api/Product/GetDiscounted"
CITY_HDRS = dict(HDRS, **{
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://yerevan-city.am",
    "Referer": "https://yerevan-city.am/",
})
CITY_BODY = {"count": 30, "page": 1, "brands": [], "categories": [],
             "countries": [], "tags": [], "isDiscounted": False,
             "priceFrom": None, "priceTo": None, "search": None,
             "sortBy": 0, "type": 1}

def city_page(page):
    for t in range(PAGE_TRIES):
        try:
            r = requests.post(CITY_API, json=dict(CITY_BODY, page=page),
                              headers=CITY_HDRS, timeout=60)
            r.raise_for_status()
            d = (r.json() or {}).get("data") or {}
            if d.get("list"):
                return d
            print("City: էջ %d դատարկ եկավ" % page)
        except Exception as e:
            print("City: էջ %d սխալ (%d/%d): %s" % (page, t + 1, PAGE_TRIES, e))
        time.sleep(3 * (t + 1))
    return {}

def city_prices(it):
    def val(k):
        v = it.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return 0
        return int(round(v))
    old, new = val("price"), val("discountedPrice")
    return (old, new) if new > 0 and old > new else (0, 0)

def iso_day(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    return "%s.%s.%s" % (m.group(3), m.group(2), m.group(1)) if m else ""

def parse_city_api(d):
    out = []
    for it in (d.get("list") or []):
        old, new = city_prices(it)
        if not old or not new or old <= new:
            continue
        pct = round((old - new) * 100.0 / old)
        if pct < 5:
            continue
        name = clean_title(str(it.get("name") or it.get("title") or ""))
        if len(name) < 4:
            continue
        pid = it.get("id") or it.get("productId") or ""
        out.append({"store": "Yerevan City", "title": name, "old": old,
                    "new": new, "pct": pct,
                    "until": iso_day(it.get("dateTo") or it.get("endDate")),
                    "img": str(it.get("image") or it.get("imageUrl") or ""),
                    "url": "https://yerevan-city.am/shop/product-details/%s" % pid})
    return out

PARSERS = {"SAS": parse_sas, "Yerevan City": parse_city}
def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"seen": {}, "queues": {}, "seeded": False, "rr": 0, "last_publish": ""}

def save_state(st):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)

def key(it):
    """Ապրանքի համարը + գնային զույգը. նույն ակցիան երկու անգամ չի գա,
    իսկ նույն ապրանքը նոր գնով նորից կգա։"""
    m = re.search(r"/(\d{3,})/?$", it.get("url") or "")
    base = ("%s|id:%s" % (it["store"], m.group(1)) if m
            else "%s|t:%s" % (it["store"], it["title"].lower()))
    return "%s|%s|%s" % (base, it["old"], it["new"])

def legacy_key(it):
    return "%s|%s|%s|%s|%s" % (it["store"], it["title"].lower(), it["old"], it["new"], it["until"])

def fetch_all(store, url):
    items, seen_ids, t0 = [], set(), time.time()
    for p in range(PAGE_PAGES):
        if time.time() - t0 > PAGE_BUDGET:
            print("%s: ժամանակի բյուջեն լրացավ էջ %d-ի վրա" % (store, p + 1))
            break
        page_url = url if p == 0 else "%s?offset=%d" % (url, p * SAS_STEP)
        md = fetch_page(store, page_url)
        if not md:
            print("%s: էջ %d չբեռնվեց, կանգ" % (store, p + 1))
            break
        got = PARSERS[store](md)
        fresh = 0
        for it in got:
            k = key(it)
            if k in seen_ids:
                continue
            seen_ids.add(k)
            items.append(it)
            fresh += 1
        print("%s: էջ %d՝ %d դիրք, այս վազքում նոր՝ %d"
              % (store, p + 1, len(got), fresh))
        if fresh == 0:
            break
        if len(items) >= PAGE_LIMIT:
            break
        time.sleep(PAGE_PAUSE)
    print("%s: ցուցակը կարդացվեց՝ %d դիրք" % (store, len(items)))
    return items[:PAGE_LIMIT]

def card_images(it):
    urls = []
    page = it.get("url") or it.get("page") or ""
    if "/upload/" in page:
        urls.append(page)
        page = ""
    if page:
        html = ""
        try:
            r = requests.get(page, timeout=45, headers=HDRS)
            if r.ok:
                html = r.text
        except Exception as e:
            print("քարտ: %s" % e)
        m = OG.search(html) or OG2.search(html)
        if m:
            urls.append(m.group(1))
        urls.extend(IMG_SRC.findall(html))
    if it.get("img"):
        urls.append(it["img"])
    out = []
    for u in urls:
        u = (u or "").replace("&amp;", "&").strip()
        if u.startswith("/"):
            u = "https://www.sas.am" + u
        if not u.startswith("http") or any(s in u.lower() for s in SKIP_IMG):
            continue
        if u not in out:
            out.append(u)
    return out

def photo_candidates(it):
    cands = card_images(it)[:6]
    out = []
    for u in cands:
        if "/Image/Resize/" in u:
            alt = u.replace("/Image/Resize/", "/Image/")
            if alt not in out:
                out.append(alt)
        if u not in out:
            out.append(u)
    return out

def card_until(it):
    page = it.get("url") or it.get("page") or ""
    if not page or "product-details" not in page:
        return ""
    try:
        html = requests.get(page, timeout=45, headers=HDRS).text
    except Exception as e:
        print("ամսաթիվ: %s" % e)
        return ""
    i = html.find("գործում է")
    if i == -1:
        return ""
    d = CARD_DATE.findall(html[i:i + 600])
    if len(d) >= 2:
        day, mon, year = d[1]
        m = MONTHS.get(mon.lower())
        if m:
            return "%02d.%02d.%s" % (int(day), m, year)
    return ""

def best_photo(it, cands=None):
    cands = cands if cands is not None else photo_candidates(it)
    best, best_url, best_d = b"", "", (0, 0)
    for group in (cands[:3], cands[3:]):
        for u in group:
            try:
                r = requests.get(u, timeout=60, headers=HDRS)
            except Exception as e:
                print("նկար: %s — %s" % (u, e))
                continue
            if not r.ok or len(r.content) < 3000:
                continue
            d = img_dims(r.content)
            if d == (0, 0):
                print("նկար չէ՝ %s (%d ԿԲ)" % (u, len(r.content) // 1024))
                continue
            if d[0] * d[1] > best_d[0] * best_d[1]:
                best, best_url, best_d = r.content, u, d
        if best:
            break
    if not best:
        print("հարմար լուսանկար չգտնվեց")
        return b"", "photo.jpg"
    name = best_url.split("?")[0].rsplit("/", 1)[-1] or "photo.jpg"
    print("նկար՝ %s (%dx%d, %d ԿԲ)" % (best_url, best_d[0], best_d[1],
                                       len(best) // 1024))
    return best, name

def to_jpeg(data):
    if Image is None or not data:
        return data
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:
        print("JPEG չդարձավ՝ %s" % e)
        return data
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    if w + h > PHOTO_MAX_SIDE:
        k = PHOTO_MAX_SIDE / float(w + h)
        im = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    q = JPEG_QUALITY
    while True:
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        out = buf.getvalue()
        if len(out) <= PHOTO_MAX_BYTES or q <= 60:
            break
        q -= 8
    print("JPEG՝ %dx%d, %d ԿԲ (որակ %d)" % (im.size[0], im.size[1],
                                            len(out) // 1024, q))
    return out
def send(it):
    it["title"] = clean_title(it["title"])
    if not it.get("until"):
        it["until"] = card_until(it)
    text = "%s\n%s\n%s ֏ → %s ֏ (-%s%%)" % (
        it["store"], it["title"], money(it["old"]), money(it["new"]), it["pct"])
    if it["until"]:
        text += "\nՄինչև՝ %s" % it["until"]
    cands = photo_candidates(it)
    if DRY:
        data, name = best_photo(it, cands)
        print("[DRY] " + text.replace("\n", " | ") +
              " | նկար՝ %s (%d ԿԲ)" % (name, len(data) // 1024))
        return True
    try:
        data, _ = best_photo(it, cands)
    except Exception as e:
        print("լուսանկարի սխալ: %s" % e)
        data = b""
    if data:
        r = requests.post(API + "sendPhoto",
                          data={"chat_id": CHANNEL, "caption": text,
                                "reply_markup": BUTTON},
                          files={"photo": ("photo.jpg", to_jpeg(data))},
                          timeout=120)
        if r.ok and r.json().get("ok"):
            return True
        print("Նկարը չգնաց: %s" % r.text[:200])
    for u in cands[:4]:
        r = requests.post(API + "sendPhoto",
                          data={"chat_id": CHANNEL, "photo": u, "caption": text,
                                "reply_markup": BUTTON}, timeout=60)
        if r.ok and r.json().get("ok"):
            return True
        print("Հղումով նկարը չգնաց (%s): %s" % (u, r.text[:200]))
    r = requests.post(API + "sendMessage",
                      data={"chat_id": CHANNEL, "text": text, "reply_markup": BUTTON},
                      timeout=60)
    if not (r.ok and r.json().get("ok")):
        print("Ուղարկելու սխալ: %s" % r.text[:300])
        return False
    return True

def publish(st):
    now = datetime.now(YE)
    last = st.get("last_publish") or ""
    if last:
        try:
            last = datetime.fromisoformat(last)
        except ValueError:
            last = None
    if not (PUB_FROM <= now.hour < PUB_TO):
        print("Հրապարակման պատուհանից դուրս (%s)" % now.strftime("%H:%M"))
        return
    if last and now - last < timedelta(minutes=STEP_MIN):
        print("Սլոտը դեռ չի հասել")
        return
    names = list(STORES)
    for i in range(len(names)):
        idx = (st.get("rr", 0) + i) % len(names)
        name = names[idx]
        q = st["queues"].get(name) or []
        if not q:
            continue
        it = q.pop(0)
        st["queues"][name] = q
        # Ժամկետանց ակցիան չի հրապարակվում. դիրքը հերթից դուրս է գալիս։
        if it.get("until"):
            try:
                dd, mm, yy = [int(x) for x in it["until"].split(".")]
                if datetime(yy, mm, dd, tzinfo=YE) < now:
                    print("Ակցիան վերջացել է՝ %s" % it["title"][:40])
                    continue
            except Exception:
                pass
        try:
            ok = send(it)
        except Exception as e:
            print("ուղարկելու բացառություն: %s" % e)
            ok = False
        if ok:
            st["rr"] = (idx + 1) % len(names)
            st["last_publish"] = now.isoformat()
        else:
            q.insert(0, it)
            st["queues"][name] = q
        return
    print("Կայքերում նոր բան չկա. բոլոր հերթերը դատարկ են")
def main():
    st = load_state()
    # ՄԻԱՆՎԱԳ վերակայում. հերթը և «տեսածը» զրոյանում են մեկ անգամ,
    # հետո հերթը նորից լցվում է կայքից՝ կայքի հերթականությամբ։
    if not st.get("reset_done"):
        st["queues"] = {s: [] for s in STORES}
        st["seen"] = {s: [] for s in STORES}
        st["rr"] = 0
        st["reset_done"] = True
        print("Վերակայում. հերթը և տեսածը զրոյացան, նորը կգա կայքից")
    # ՄԻԱՆՎԱԳ մաքրում. հերթից դուրս են գալիս ծաղիկների բաժնի դիրքերը։
    if not st.get("flowers_cleaned"):
        dropped = 0
        for name in STORES:
            q = st["queues"].get(name) or []
            keep = [x for x in q if not is_flower_item(x)]
            dropped += len(q) - len(keep)
            st["queues"][name] = keep
        if dropped:
            print("Մաքրում. ծաղիկների բաժնից հանվեց %d դիրք" % dropped)
        st["flowers_cleaned"] = True
    # ՄԻԱՆՎԱԳ մաքրում. մինչ այս տարբերակը SAS-ի նավիգացիոն հղումները
    # («0 դր. Զամբյուղում», «Դիտել ամբողջ բաժինը») մտել էին հերթ որպես
    # ապրանք։ Հանվում են միայն դրանք, մնացածի կարգը չի փոխվում։
    if not st.get("junk_cleaned"):
        q = st["queues"].get("SAS") or []
        good = [x for x in q if re.search(r"/(\d{3,})/?$", x.get("url") or "")]
        if len(good) != len(q):
            print("Մաքրում. SAS-ի հերթից հանվեց %d աղբ դիրք" % (len(q) - len(good)))
        st["queues"]["SAS"] = good
        st["junk_cleaned"] = True
    # ՄԻԱՆՎԱԳ մաքրում. City-ի բանալին փոխվեց (id + գնային զույգ), ուստի
    # հին բանալիներով «տեսածը» նորերի հետ չի համընկնի. City-ն սկսում է մաքուր։
    if not st.get("city_key_migrated"):
        st["queues"]["Yerevan City"] = []
        st["seen"]["Yerevan City"] = []
        st["city_page"] = 1
        st["city_key_migrated"] = True

        print("City: հերթն ու տեսածը զրոյացան՝ նոր բանալու անցնելու համար")
    for store, url in STORES.items():
        pc = 0
        if store == "Yerevan City":
            p = int(st.get("city_page") or 1)
            d = city_page(p)
            items = parse_city_api(d)
            pc = int(d.get("pageCount") or 0)
            print("Yerevan City: API էջ %d/%s՝ %d դիրք" % (p, pc or "?", len(items)))
            if DRY and (d.get("list") or []):
                print("    [debug] դաշտերը՝ %s" % sorted(d["list"][0].keys()))
                print("    [debug] առաջինը՝ %s"
                      % json.dumps(d["list"][0], ensure_ascii=False)[:600])
        else:
            items = fetch_all(store, url)
        if DRY:
            for it in items[:5]:
                print("    - %s | %s->%s ֏ (-%s%%) %s"
                      % (it["title"][:70], it["old"], it["new"], it["pct"], it["until"]))
        seen_set = set(st["seen"].setdefault(store, []))
        in_queue = set(x.get("key") for x in st["queues"].get(store, []))
        fresh = []
        for it in items:
            k = key(it)
            it["key"] = k
            if k in seen_set or legacy_key(it) in seen_set or k in in_queue:
                continue
            fresh.append(it)
        q = st["queues"].setdefault(store, [])
        # «Մեկը գնաց, մեկը եկավ». նորը վերցվում է ազատ տեղի չափով, ուստի
        # ոչինչ առանց հրապարակվելու դուրս չի ընկնում։
        room = QUEUE_CAP - len(q)
        take = fresh[:room] if room > 0 else []
        for it in take:
            seen_set.add(it["key"])
            st["seen"][store].append(it["key"])
        q.extend(take)
        if store == "Yerevan City" and pc and len(take) == len(fresh):
            st["city_page"] = p % pc + 1
        if len(st["seen"][store]) > SEEN_KEEP:
            del st["seen"][store][:-SEEN_KEEP]
        print("%s: ցուցակում %d, հերթ ընդունվեց %d, հերթում %d, ազատ տեղ %d"
              % (store, len(items), len(take), len(q), QUEUE_CAP - len(q)))
    st["seeded"] = True
    publish(st)
    if DRY:
        print("DRY RUN. վիճակը չպահվեց")
        return
    save_state(st)

if __name__ == "__main__":
    main()
