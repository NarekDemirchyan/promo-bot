# -*- coding: utf-8 -*-
"""Supermarket promo bot: SAS, Yerevan City -> Telegram channel."""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL = os.environ.get("CHANNEL", "")
DRY = os.environ.get("DRY_RUN", "0") == "1"

STATE = "state-promo.json"
YE = timezone(timedelta(hours=4))
PUB_FROM, PUB_TO = 0, 24
STEP_MIN = 15
QUEUE_CAP = 200
SEED_PER_STORE = 8
CITY_SEEN_KEEP = 20
API = "https://api.telegram.org/bot%s/" % TOKEN
JINA = "https://r.jina.ai/"

# Фото уходит файлом — без пережатия Telegram. Нужен обычный пост-«фото»:
# поставьте False.
SEND_AS_FILE = False

SKIP_IMG = ("logo", "18-plus", "flags/", "icon", "banner", "banniere", "svg",
            "sprite", "placeholder", "no-photo", "nophoto")

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
PRICE = re.compile(r"([\d][\d\s,\.]{1,12}?)\s*(?:֏|\bnull\b|դր\.?)(?!\s*/)")
DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
SAS_LINK = re.compile(r"\[([^\]\n]{4,160})\]\((https://www\.sas\.am/[^)\s]+)\)")
CITY_LINK = re.compile(
    r"\[([^\]]{10,400}?)\]\((https://yerevan-city\.am/shop/product-details/(\d+))\)", re.S)
CITY_PRICE = re.compile(
    r"~~\s*([\d][\d\s,\.]{0,14}?)\s*(?:֏|\bnull\b)?\s*~~\s*([\d][\d\s,\.]{0,14})", re.S)
CYR = re.compile(r"[А-Яа-яёЁ]")
RU_LABEL = re.compile(r"^\s*(Скидка|Эксклюзив|Акция|Суперцена|Sale)\s*[:.\-]?\s*", re.I)
PCT_HEAD = re.compile(r"^\s*[-–—+%]*\s*\d{1,3}\s*%?\s*")
ARTIC = re.compile(r"\s+\d{4,}$")
OG = re.compile(
    r"""<meta[^>]+(?:property|name)=['"]og:image['"][^>]+content=['"]([^'"]+)""", re.I)
OG2 = re.compile(
    r"""<meta[^>]+content=['"]([^'"]+)['"][^>]+(?:property|name)=['"]og:image['"]""", re.I)
IMG_SRC = re.compile(r"""<img[^>]+src=['"]([^'"]+\.(?:webp|jpe?g|png)[^'"]*)['"]""", re.I)
IMG_MD = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")

def fetch(url):
    r = requests.get(JINA + url, timeout=120, headers={"User-Agent": HDRS["User-Agent"]})
    r.raise_for_status()
    return r.text

def num(s):
    s = (s or "").replace(" ", "").replace(",", "")
    s = s.split(".")[0]
    s = re.sub(r"\D", "", s)
    return int(s) if s else 0

def money(n):
    return "{:,}".format(n).replace(",", " ")

def img_in(chunk):
    for u in IMG_MD.findall(chunk):
        if not any(s in u.lower() for s in SKIP_IMG):
            return u
    return ""

def has_cyr(s):
    return bool(CYR.search(s or ""))

def clean_title(t):
    t = re.sub(r"~~.*$", "", t or "", flags=re.S)
    t = re.sub(r"\s+", " ", t.replace("\\", " ")).strip(" -|")
    t = PCT_HEAD.sub("", t).strip(" -|%")
    t = RU_LABEL.sub("", t).strip(" -|")
    return ARTIC.sub("", t).strip(" -|")

def make(store, title, old, new, until, img, url=""):
    title = clean_title(title)
    if len(title) < 4 or new <= 0 or old <= new:
        return None
    if has_cyr(title):
        return None
    pct = round((old - new) * 100 / old)
    if pct < 5:
        return None
    return {"store": store, "title": title, "old": old, "new": new,
            "pct": pct, "until": until or "", "img": img or "", "url": url or ""}

def parse_sas(md):
    out, links = [], list(SAS_LINK.finditer(md))
    skip = ("купить", "в корзину", "подробнее", "все акции", "հավելին", "ցույց տալ", "շուտով")
    for i, m in enumerate(links):
        if m.group(1).strip().lower() in skip:
            continue
        end = links[i + 1].start() if i + 1 < len(links) else min(len(md), m.end() + 900)
        chunk = md[m.end():end]
        prices = [p for p in (num(x) for x in PRICE.findall(chunk)) if p > 0]
        if len(prices) < 2:
            continue
        dates = DATE.findall(chunk)
        out.append(make("SAS", m.group(1), prices[0], prices[-1],
                        dates[-1] if dates else "", img_in(chunk), m.group(2)))
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
    m = re.search(r"/(\d{4,})/?$", it.get("url") or "")
    if m:
        return "%s|id:%s" % (it["store"], m.group(1))
    return "%s|t:%s" % (it["store"], it["title"].lower())

def legacy_key(it):
    return "%s|%s|%s|%s|%s" % (it["store"], it["title"].lower(), it["old"], it["new"], it["until"])

def card_images(it):
    urls = []
    page = it.get("url") or it.get("page") or ""
    if page:
        html = ""
        try:
            r = requests.get(page, timeout=45, headers=HDRS)
            if r.ok:
                html = r.text
        except Exception as e:
            print("карточка: %s" % e)
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

def best_photo(it):
    best = b""
    name = "photo.jpg"
    for u in card_images(it)[:6]:
        try:
            r = requests.get(u, timeout=60, headers=HDRS)
        except Exception as e:
            print("фото: %s — %s" % (u, e))
            continue
        if r.ok and len(r.content) > len(best) and len(r.content) > 5000:
            best = r.content
            name = u.split("?")[0].rsplit("/", 1)[-1] or "photo.jpg"
    return best, name

def send(it):
    text = "%s\n%s\n%s ֏ → %s ֏ (-%s%%)" % (
        it["store"], it["title"], money(it["old"]), money(it["new"]), it["pct"])
    if it["until"]:
        text += "\nՄինչև՝ %s" % it["until"]
    if DRY:
        cand = card_images(it)
        print("[DRY] " + text.replace("\n", " | ") + " | фото: " + (cand[0] if cand else "нет"))
        return True
    data, name = best_photo(it)
    if data:
        field = "document" if SEND_AS_FILE else "photo"
        r = requests.post(API + ("sendDocument" if SEND_AS_FILE else "sendPhoto"),
                          data={"chat_id": CHANNEL, "caption": text,
                                "reply_markup": BUTTON},
                          files={field: (name, data)}, timeout=120)
        if r.ok and r.json().get("ok"):
            return True
        print("Файл не ушёл: %s" % r.text[:200])
    for u in card_images(it)[:4]:
        r = requests.post(API + "sendPhoto",
                          data={"chat_id": CHANNEL, "photo": u, "caption": text,
                                "reply_markup": BUTTON}, timeout=60)
        if r.ok and r.json().get("ok"):
            return True
        print("Фото по ссылке не ушло (%s): %s" % (u, r.text[:200]))
    r = requests.post(API + "sendMessage",
                      data={"chat_id": CHANNEL, "text": text, "reply_markup": BUTTON},
                      timeout=60)
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
        it = q.pop(0)
        st["queues"][name] = q
        if send(it):
            st["rr"] = (idx + 1) % len(names)
            st["last_publish"] = now.isoformat()
        else:
            q.insert(0, it)
            st["queues"][name] = q
        return
    print("Все очереди пусты")

def main():
    st = load_state()
    for store, url in STORES.items():
        try:
            md = fetch(url)
        except Exception as e:
            print("%s: ошибка загрузки: %s" % (store, e))
            continue
        items = PARSERS[store](md)
        if not items and store == "Yerevan City":
            md = fetch(url + "?r=%d" % int(time.time()))
            items = PARSERS[store](md)
        print("%s: найдено %d позиций со скидкой" % (store, len(items)))
        if DRY:
            for it in items[:5]:
                cand = card_images(it)
                print("    - %s | %s->%s ֏ (-%s%%) %s | фото: %s"
                      % (it["title"][:70], it["old"], it["new"], it["pct"], it["until"],
                         cand[0] if cand else "нет"))
        seen_set = set(st["seen"].setdefault(store, []))
        in_queue = set(x.get("key") for x in st["queues"].get(store, []))
        fresh = []
        for it in items:
            k = key(it)
            it["key"] = k
            if k in seen_set or legacy_key(it) in seen_set or k in in_queue:
                continue
            fresh.append(it)
        if store == "Yerevan City" and len(st["seen"][store]) > CITY_SEEN_KEEP:
            del st["seen"][store][:-CITY_SEEN_KEEP]
        if not st.get("seeded"):
            fresh = fresh[:SEED_PER_STORE]
        for it in fresh:
            seen_set.add(it["key"])
            st["seen"][store].append(it["key"])
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
