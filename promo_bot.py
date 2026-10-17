# -*- coding: utf-8 -*-
"""Supermarket promo bot (հայերեն): SAS + Yerevan City -> Telegram channel."""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests

TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL = os.environ.get("CHANNEL", "")
DRY = os.environ.get("DRY_RUN", "0") == "1"

VERSION = 2
STATE = "state-promo.json"
YE = timezone(timedelta(hours=4))
PUB_FROM, PUB_TO, STEP_MIN = 8, 24, 15
QUEUE_CAP, SEED_PER_STORE = 16, 8
API = "https://api.telegram.org/bot%s/" % TOKEN
JINA = "https://r.jina.ai/"
UA = {"User-Agent": "Mozilla/5.0", "Accept-Language": "hy-AM,hy;q=0.9,en;q=0.7"}
BOOST = "https://t.me/boost/supermarket_promos"
BTN = json.dumps({"inline_keyboard": [[{"text": "😊 Աջակցել ալիքին", "url": BOOST}]]})

STORES = {
    "SAS": "https://www.sas.am/catalog/discount/",
    "Yerevan City": "https://yerevan-city.am/shop/best-offers",
}

SKIP_IMG = ("logo", "18-plus", "flags/", "icon", "banner", "banniere", "svg",
            "no_res", "menu", "plus.svg", "minus.svg", "ic_menu")
CUR = r"(?:֏|դր\.)"
PRICE = re.compile(r"([\d][\d\s]{1,9})\s*" + CUR)
DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
IMG_MD = re.compile(r"!\[(?:Image \d+: )?([^\]]*)\]\((https?://[^)\s]+)\)")
SAS_CARD = re.compile(r"\[(?:(?:!\[[^\]]*\]\([^)\s]+\))+)\]\((https://www\.sas\.am/catalog/[^)\s]+/\d+/)\)")
CITY_LINK = re.compile(r"\[([^\]]{10,400}?)\]\((https://yerevan-city\.am/shop/product-details/\d+)\)", re.S)
TITLE_LINE = re.compile(r"^\s*Title:\s*(.+)$", re.M)
ARM = re.compile(r"[Ա-Ֆա-ֆև]")
BAD_LINE = ("հատ", "զամբյուղ", "Մանրամասներ", "Կարդալ")

def fetch(url):
    r = requests.get(JINA + url, timeout=120, headers=UA)
    r.raise_for_status()
    return r.text

def money_int(s):
    s = re.sub(r"[^\d]", "", (s or "").split(".")[0])
    return int(s) if s else 0

def money(n):
    return "{:,}".format(n).replace(",", " ")

def clean(t):
    return re.sub(r"\s+", " ", (t or "").replace("\\", " ")).strip(" -|")

def ok_img(u):
    return u and not any(s in u.lower() for s in SKIP_IMG)

def img_in(text):
    for alt, u in IMG_MD.findall(text):
        if ok_img(u):
            return u
    return ""

def name_in(chunk):
    """Անունը՝ երևացող տեքստից (alt-ը անվստահելի է)։"""
    for line in chunk.split("\n"):
        t = clean(line)
        if not (5 <= len(t) <= 140):
            continue
        if "%" in t or re.search(CUR, t) or DATE.search(t) or t.startswith("["):
            continue
        if any(b in t for b in BAD_LINE):
            continue
        return t
    return ""

def make(store, title, old, new, until, img):
    title = clean(title)
    if len(title) < 4 or new <= 0 or old <= new:
        return None
    pct = round((old - new) * 100 / old)
    if pct < 5:
        return None
    return {"store": store, "title": title, "old": old, "new": new,
            "pct": pct, "until": until or "", "img": img or "", "page": ""}

def parse_sas(md):
    out, cards = [], list(SAS_CARD.finditer(md))
    for i, m in enumerate(cards):
        end = cards[i + 1].start() if i + 1 < len(cards) else len(md)
        chunk = md[m.end():end]
        prices = [p for p in (money_int(x) for x in PRICE.findall(chunk)) if p > 0]
        if len(prices) < 2:
            continue
        dates = DATE.findall(chunk)
        it = make("SAS", name_in(chunk), prices[0], prices[1],
                  dates[-1] if dates else "", img_in(m.group(0)))
        if it:
            it["page"] = m.group(1)
            out.append(it)
    return out

def parse_city(md):
    out = []
    for m in CITY_LINK.finditer(md):
        t = clean(m.group(1))
        pr = re.search(r"~~\s*([\d\s,\.]+)\s*\S*\s*~~\s*([\d\s,\.]+)", t)
        if not pr:
            continue
        name = re.split(r"~~", t)[0]
        name = re.sub(r"^-\s*\d+\s*%\s*", "", name)
        name = re.sub(r"\s+\d{3,}$", "", name)
        it = make("Yerevan City", name, money_int(pr.group(1)), money_int(pr.group(2)), "", "")
        if it:
            it["page"] = m.group(2)
            out.append(it)
    return out

PARSERS = {"SAS": parse_sas, "Yerevan City": parse_city}

def big_img(md, title):
    imgs = [(clean(a), u) for a, u in IMG_MD.findall(md) if ok_img(u)]
    for a, u in imgs:
        if a == title:
            return u
    i = md.find("# " + title)
    if i < 0:
        return ""
    seg = md[max(0, i - 2500):i + 400]
    for a, u in imgs:
        if u in seg:
            return u
    return ""

def og_img(url):
    try:
        h = requests.get(url, timeout=60, headers=UA).text
    except Exception:
        return ""
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)', h)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:image', h)
    return m.group(1) if m else ""

def enrich(it):
    """Ուղարկելուց առաջ՝ ճշգրիտ անուն և մեծ ֆոտո քարտի էջից։"""
    page = it.get("page") or ""
    if not page:
        return it
    try:
        md = fetch(page)
    except Exception:
        return it
    m = TITLE_LINE.search(md)
    if m:
        t = clean(m.group(1)).split(" | ")[0]
        if 5 <= len(t) <= 140 and ARM.search(t):
            it["title"] = t
    img = big_img(md, it["title"]) or og_img(page)
    if img:
        it["img"] = img
    return it

def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"seen": {}, "queues": {}, "seeded": False, "rr": 0, "last_publish": "", "version": VERSION}

def save_state(st):
    st["version"] = VERSION
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)

def key(it):
    return "%s|%s|%s|%s|%s" % (it["store"], it["title"].lower(), it["old"], it["new"], it["until"])

def send(it):
    text = "%s\n%s\n%s ֏ → %s ֏ (-%s%%)" % (it["store"], it["title"], money(it["old"]), money(it["new"]), it["pct"])
    if it["until"]:
        text += "\nՄինչև՝ %s" % it["until"]
    if DRY:
        print("[DRY] %s | img=%s" % (text.replace("\n", " | "), it["img"][:70]))
        return True
    if it["img"]:
        try:
            b = requests.get(it["img"], timeout=60, headers=UA).content
        except Exception:
            b = b""
        if len(b) > 3000:
            name = "photo" + (os.path.splitext(it["img"])[1] or ".jpg")
            r = requests.post(API + "sendPhoto",
                              data={"chat_id": CHANNEL, "caption": text, "reply_markup": BTN},
                              files={"photo": (name, b)}, timeout=120)
            if r.ok and r.json().get("ok"):
                return True
    r = requests.post(API + "sendMessage",
                      data={"chat_id": CHANNEL, "text": text, "reply_markup": BTN}, timeout=60)
    if not (r.ok and r.json().get("ok")):
        print("Ошибка отправки: %s" % r.text[:300])
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
        print("Вне окна публикации (%s)" % now.strftime("%H:%M"))
        return
    if last and now - last < timedelta(minutes=STEP_MIN):
        print("Слот ещё не наступил")
        return
    names = list(STORES)
    for i in range(len(names)):
        idx = (st.get("rr", 0) + i) % len(names)
        name = names[idx]
        q = st["queues"].get(name) or []
        if not q:
            continue
        it = enrich(q.pop(0))
        st["queues"][name] = q
        if send(it):
            st["rr"] = (idx + 1) % len(names)
            st["last_publish"] = now.isoformat()
        return
    print("Все очереди пусты")

def main():
    st = load_state()
    if st.get("version") != VERSION:
        st["version"] = VERSION
        st["queues"], st["seen"], st["seeded"] = {}, {}, False
        print("Новая версия %s: очереди сброшены, будет новый сид" % VERSION)
    for store, url in STORES.items():
        try:
            md = fetch(url)
        except Exception as e:
            print("%s: ошибка загрузки: %s" % (store, e))
            continue
        items = PARSERS[store](md)
        print("%s: найдено %d позиций со скидкой" % (store, len(items)))
        if DRY:
            for it in items[:5]:
                print("    - %s | %s->%s (-%s%%) %s | %s" % (
                    it["title"][:60], it["old"], it["new"], it["pct"], it["until"], it["img"][:60]))
        seen = st["seen"].setdefault(store, [])
        seen_set = set(seen)
        fresh = []
        for it in items:
            k = key(it)
            if k in seen_set:
                continue
            seen_set.add(k)
            seen.append(k)
            fresh.append(it)
        if not st.get("seeded"):
            fresh = items[:SEED_PER_STORE]
        q = st["queues"].setdefault(store, [])
        q.extend(fresh)
        if len(q) > QUEUE_CAP:
            q.sort(key=lambda x: -x["pct"])
            del q[QUEUE_CAP:]
        print("%s: новых %d, в очереди %d" % (store, len(fresh), len(q)))
    st["seeded"] = True
    publish(st)
    if DRY:
        print("DRY RUN: состояние не сохранено")
        return
    save_state(st)

if __name__ == "__main__":
    main()
