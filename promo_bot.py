# -*- coding: utf-8 -*-
"""Supermarket promo bot: SAS, Yerevan City -> Telegram channel.

Այս տարբերակում ուղղված է.
 1. Բոտը կարդում է ցուցակի ԲՈԼՈՐ էջերը, ոչ միայն առաջինը. SAS-ի զեղչերի
    բաժինը 825+ դիրք ունի՝ 24-ական էջերով (?offset=24, 48, 72...), ու առաջին
    էջի 16 ապրանքից բացի մնացածը բոտի համար ընդհանրապես գոյություն չուներ։
 2. Ամեն դիրք, որ կայքում կա ու դեռ հերթում չի եղել, ԱՆՑՆՈՒՄ Է ՀԵՐՔՈՎ։
    «Կարդացած» է համարվում միայն այն, ինչ արդեն հերթ է մտել կամ հրապարակվել։
 3. Հերթը FIFO է, ամեն խանութի համար՝ 900 դիրք. նորը գալիս է պոչը, ու երբ
    առաստաղը լրանում է, գլխից դուրս են գալիս ամենահները՝ 20 նոր մտավ,
    20 հին դուրս եկավ։ Հրապարակման կարգը կայքի կարգն է, ըստ զեղչի դասավորում
    չկա։
 4. Ծաղիկների բաժինը (SAS Flowers by Villani, Milani) ընդհանրապես չի
    հրապարակվում՝ ոչ ցուցակից, ոչ հերթից։
 5. Լուսանկարը գնում է ՈՐՊԵՍ ՆԿԱՐ (JPEG), ոչ ֆայլով. ընտրվում է ՉԱՓՍՈՎ՝
    ամենամեծ լայնություն×բարձրությունը, ոչ ֆայլի ծանրությամբ, ու նախապես
    դարձվում է JPEG լրիվ չափսը պահելով (27 ՄԲ PNG → մի քանի հարյուր ԿԲ JPEG)։
 6. Մեկ հատի գինը («2 127 դր./1լ») չի մտնում որպես նոր գին։
 7. SAS-ի քարտը ճանաչվում է ցուցակի մարկերով՝ [](/catalog/<բաժին>/<id>/),
    իսկ նավիգացիոն հղումները ապրանք չեն համարվում։
 8. JPEG դարձնելու համար պետք է Pillow-ը (pip install Pillow)։
 9. Միանվագ մաքրումներ՝ ծաղիկների դիրքերը հերթից ու հին ոչ-քարտ աղբը։
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
# Առաստաղը մեկ խանութի համար. նորը գալիս է պոչը, գլխից դուրս են գալիս
# ամենահները։ Կարգը կայքի կարգն է։
QUEUE_CAP = 900
# «Տեսածը» պահվում է լիքը, որ հրապարակված դիրքը չվերադառնա որպես նոր։
SEEN_KEEP = 3000
# Մեկ վազքում կարդացվող էջերի ու դիրքերի սահմանը, ու ժամանակի բյուջեն,
# որ աշխատանքը չկախվի 40 էջը մեկ վազքով կարդալիս։
PAGE_LIMIT = 900
PAGE_PAGES = 40
PAGE_BUDGET = 600
SAS_STEP = 24
API = "https://api.telegram.org/bot%s/" % TOKEN
JINA = "https://r.jina.ai/"

# Նկարը գնում է որպես նկար՝ JPEG։ Լրիվ լայնքն ու բարձրությունը պահվում են,
# ծանրությունը՝ ոչ. նույն 3000x4000 չափսով JPEG-ը PNG-ից մի քանի անգամ թեթև է։
JPEG_QUALITY = 92
PHOTO_MAX_BYTES = 9 * 1024 * 1024
# Telegram-ի սահմանը. լայնություն + բարձրություն ≤ 10000։
PHOTO_MAX_SIDE = 10000

SKIP_IMG = ("logo", "18-plus", "flags/", "icon", "banner", "banniere", "svg",
            "sprite", "placeholder", "no-photo", "nophoto")

# Ծաղիկների բաժինը չի հրապարակվում։ Դա բաժնի հասցեով է որոշվում, ոչ
# ապրանքի անունով. անվան մեջ «ծաղկ» բառը կա նաև մեղրի ու սերմերի մեջ։
FLOWER_URL = re.compile(r"/catalog/(?:sasexclusiveflowers|flowers|milaniroses|"
                        r"milani|milancomp|milanbalon|mona|monaflowers|myrose|"
                        r"my_rose|my_rose_fl|balloon|balloons|tsvety|flowersas|"
                        r"cataleya|cataleyabuyser|villaniflowers|milancompos|"
                        r"milanpuchik|cataleyaflowers|milanirose7)", re.I)
# Երկրորդ ստուգումը հին գրառումների համար է, որտեղ բաժնի հասցեն չկա։
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
# SAS-ը գները գրում է «19 000 դր.»; մեկ հատի/մեկ լիտրի գները
# («2 127 դր./1լ», «292 դր./1հատ») դեն ենք նետում lookahead-ով։ Կետը
# պարտադիր է lookahead-ի մեջ, այլապես «դր»-ի վրա այն չի տեսնում «/»-ը։
PRICE = re.compile(r"([\d][\d\s,\.]{1,12}?)\s*(?:֏|դր\.?|\bnull\b)(?!\.?\s*/)")
DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
# Ամեն ապրանքի քարտ սկսվում է դատարկ տեքստով հղումով՝ [](/catalog/<բաժին>/<id>/)։
# Սա է քարտի իսկական նշանը. նկարով չենք կողմնորոշվում, որովհետև մեկ քարտում
# կարող է երկու լուսանկար լինել (`![…](w1)![…](w2)`), ու հին կանոնը դրանք գցում էր։
SAS_CARD = re.compile(r"\[\]\((https://www\.sas\.am/(?!upload/)[^)\s]*/\d{3,}/?)\)")
# Քարտի լուսանկարի alt-տողը՝ «Image 383: Ապրանքի անունը»։
SAS_ALT = re.compile(r"!\[(?:Image\s+\d+\s*:\s*)?([^\]]{4,160})\]\(([^)]*)\)")
# Պահուստային կանոն, եթե կայքը փոխի ցուցակի կառուցվածքը։
SAS_LINK = re.compile(
    r"\[(?:!\[([^\]]{4,160})\]\(([^)]*)\)|([^\]\n]{4,160}))\]"
    r"\((https://www\.sas\.am/(?!upload/)[^)\s]+)\)")
CITY_LINK = re.compile(
    r"\[([^\]]{10,400}?)\]\((https://yerevan-city\.am/shop/product-details/(\d+))\)", re.S)
CITY_PRICE = re.compile(
    r"~~\s*([\d][\d\s,\.]{0,14}?)\s*(?:֏|\bnull\b)?\s*~~\s*([\d][\d\s,\.]{0,14})", re.S)
# Անվանումը պետք է հայերեն կամ ռուսերեն լինի. այսպես դեն են նետվում
# անգլերեն/ծառայողական տողերը («Image 52» և նմանները)։
NAME = re.compile(r"[Ա-Ֆա-ֆև]|[А-Яа-яЁё]")
RU_LABEL = re.compile(r"^\s*(Скидка|Эксклюзив|Акция|Суперцена|Sale)\s*[:.\-]?\s*", re.I)
PCT_HEAD = re.compile(r"^\s*[-–—+%]*\s*\d{1,3}\s*%?\s*")
ARTIC = re.compile(r"\s+\d{4,}$")
# Աղբյուրի մաքուր մնացորդները՝ «![Image 403: » / «Image 403: »։
IMG_PREFIX = re.compile(r"^!?\[?\s*(?:Image\s+\d+\s*:?\s*)?", re.I)
OG = re.compile(
    r"""<meta[^>]+(?:property|name)=['"]og:image['"][^>]+content=['"]([^'"]+)['"]""", re.I)
OG2 = re.compile(
    r"""<meta[^>]+content=['"]([^'"]+)['"][^>]+(?:property|name)=['"]og:image['"]""", re.I)
IMG_SRC = re.compile(r"""<img[^>]+src=['"]([^'"]+\.(?:webp|jpe?g|png)[^'"]*)['"]""", re.I)
IMG_MD = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")
# Yerevan City-ի ակցիայի ժամկետը միայն քարտի վրա է. «Գինը գործում է 08 Հոկտեմբեր 2026 -ից
# 31 Հոկտեմբեր 2026»։ Վերցնում ենք երկրորդ ամսաթիվը։
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

def num(s):
    s = (s or "").replace(" ", "").replace(",", "")
    s = s.split(".")[0]
    s = re.sub(r"\D", "", s)
    return int(s) if s else 0

def money(n):
    return "{:,}".format(n).replace(",", " ")

def is_flower(url, title):
    """Ծաղիկների բաժնի դիրք է, թե ոչ։"""
    return bool(FLOWER_URL.search(url or "") or FLOWER_TITLE.search(title or ""))

def is_flower_item(it):
    return is_flower(it.get("url") or "", it.get("title") or "")

def img_dims(data):
    """Նկարի լայնությունն ու բարձրությունը՝ հենց բայթերից (PNG, JPEG, WebP)։
    Եթե բայթերը նկար չեն (օրինակ՝ HTML կամ այլ ֆայլ), վերադարձնում է (0, 0)։"""
    if len(data) > 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
    if len(data) > 4 and data[:2] == b"\xff\xd8":  # JPEG
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
        if four == b"VP8X":                       # ընդլայնված
            w = int.from_bytes(data[24:27], "little") + 1
            h = int.from_bytes(data[27:30], "little") + 1
            return (w, h)
        if four == b"VP8L":                       # անկորուստ
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
    """Քարտերը վերցնում ենք ցուցակի մարկերով՝ [](/catalog/<բաժին>/<id>/):
    այդպես երկու լուսանկարով քարտերը նույնպես չեն կորչում։ Ծաղիկների բաժինը
    դեն է նետվում հենց այստեղ, որ հերթ ընդհանրապես…
it["key"] = k
            if k in seen_set or legacy_key(it) in seen_set or k in in_queue:
                continue
            fresh.append(it)
        # Ամեն նոր դիրք անցնում է հերթով. «կարդացած» է համարվում միայն այն,
        # ինչ արդեն հերթ մտավ կամ հրապարակվեց, ուրիշ ոչինչ դեն չի նետվում։
        for it in fresh:
            seen_set.add(it["key"])
            st["seen"][store].append(it["key"])
        q = st["queues"].setdefault(store, [])
        q.extend(fresh)
        # Առաստաղը լրանալիս գլխից են դուրս գալիս ամենահները, նորը մնում է պոչում,
        # կարգը կայքի կարգն է։ Ըստ զեղչի ոչ մի դասավորում չկա։
        if len(q) > QUEUE_CAP:
            del q[:len(q) - QUEUE_CAP]
        if len(st["seen"][store]) > SEEN_KEEP:
            del st["seen"][store][:-SEEN_KEEP]
        print("%s: նոր %d, հերթում %d" % (store, len(fresh), len(q)))
    st["seeded"] = True
    publish(st)
    if DRY:
        print("DRY RUN. վիճակը չպահվեց")
        return
    save_state(st)

if __name__ == "__main__":
    main()
