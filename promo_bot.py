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
PUB_FROM, PUB_TO = 8, 24
STEP_MIN = 15
QUEUE_CAP = 16
SEED_PER_STORE = 8
API = "https://api.telegram.org/bot%s/" % TOKEN
JINA = "https://r.jina.ai/"
SKIP_IMG = ("logo", "18-plus", "flags/", "icon", "banner", "banniere", "svg")

# кнопка под каждым постом
BOOST = "https://t.me/boost/supermarket_promos"
BUTTON = json.dumps(
    {"inline_keyboard": [[{"text": "😊 Աջակցել ալիքին", "url": BOOST}]]},
    ensure_ascii=False,
)

# только армянские версии сайтов
STORES = {
    "SAS": "https://www.sas.am/hy/catalog/discount/",
    "Yerevan City": "https://yerevan-city.am/shop/best-offers",
}
PRICE = re.compile(r"([\d][\d\s]{1,9})\s*֏")
DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
SAS_LINK = re.compile(r"\[([^\]\n]{4,160})\]\((https://www\.sas\.am/[^)\s]+)\)")
CITY_LINK = re.compile(
    r"\[([^\]]{10,400}?)\]\((https://yerevan-city\.am/shop/product-details/(\d+))\)", re.S
)
CYR = re.compile(r"[А-Яа-яЁё]")
RU_LABEL = re.compile(r"^\s*(Скидка|Эксклюзив|Акция|Суперцена|Sale)\s*[:.\-]?\s*", re.I)
CITY_PHOTO = "https://media.yerevan-city.am/api/Image/Resize/ProductPhoto/%s.png"

def fetch(url):
    r = requests.get(JINA + url, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text

def num(s):
    s = re.sub(r"\D", "", s or "")
    return int(s) if s else 0

def money(n):
    return "{:,}".format(n).replace(",", " ")

def img_in(chunk):
    for u in re.findall(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", chunk):
        if not any(s in u.lower() for s in SKIP_IMG):
            return u
    return ""

def has_cyr(s):
    return bool(CYR.search(s or ""))

def clean_title(t):
    t = re.sub(r"\s+", " ", (t or "").replace("\\", " ")).strip(" -|")
    return RU_LABEL.sub("", t).strip(" -|")

def make(store, title, old, new, until, img, url=""):
    title = clean_title(title)
    if len(title) < 4 or new <= 0 or old <= new:
        return None
    if has_cyr(title):          # публикуем только армянские названия
        return None
    pct = round((old - new) * 100 / old)
    if pct < 5:
        return None
    return {"store": store, "title": title, "old": old, "new": new,
            "pct": pct, "until": until or "", "img": img or "", "url": url or ""}

def parse_sas(md):
    out, links = [], list(SAS_LINK.finditer(md))
    skip = ("купить", "в корзину", "подробнее", "все акции", "գնել", "զամբյուղ", "ավելին")
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
        pr = re.search(r"~~\s*([\d\s,]+)\s*֏\s*~~\s*([\d\s,]+)\s*֏", inner)
        if not pr:
            continue
        parts = [p.strip(" \\\n-|") for p in re.split(r"\n|\\", inner)]
        parts = [p for p in parts if len(p) > 3 and "֏" not in p and not p.startswith("-")]
        title = parts[-1] if parts else ""
        out.append(make("Yerevan City", title, num(pr.group(1)), num(pr.group(2)), "",
                        CITY_PHOTO % m.group(3), m.group(2)))
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
    return "%s|%s|%s|%s|%s" % (it["store"], it["title"].lower(), it["old"], it["new"], it["until"])

def og_image(url):
    """Большое фото карточки товара (og:image), а не превью из списка."""
    if not url:
        return ""
    try:
        r = requests.get(url, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
        if r.ok:
            m = (re.search(r"""<meta[^>]+(?:property|name)=["']og:image["'][^>]+content=["']([^"']+)""", r.text, re.I)
                 or re.search(r"""<meta[^>]+content=["']([^"']+)["'][^>]+(?:property|name)=["']og:image["']""", r.text, re.I))
            if m:
                return m.group(1)
    except Exception as e:
        print("og:image: %s" % e)
    return ""

def photos(it):
    out = []
    if it["store"] == "SAS":
        big = og_image(it.get("url", ""))
        if big:
            out.append(big)
    if it["img"] and it["img"] not in out:
        out.append(it["img"])
    return out

def send(it):
    text = "%s\n%s\n%s ֏ → %s ֏ (-%s%%)" % (
        it["store"], it["title"], money(it["old"]), money(it["new"]), it["pct"])
    if it["until"]:
        text += "\nՄինչև՝ %s" % it["until"]
    if DRY:
        print("[DRY] " + text.replace("\n", " | ") + " | фото: " + ((photos(it) or ["нет"])[0]))
        return True
    for u in photos(it):
        r = requests.post(API + "sendPhoto",
                          data={"chat_id": CHANNEL, "photo": u, "caption": text,
                                "reply_markup": BUTTON}, timeout=60)
        if r.ok and r.json().get("ok"):
            return True
        print("Фото не ушло (%s): %s" % (u, r.text[:200]))
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
        it = q.pop(0)            # публикация всегда с головы
        st["queues"][name] = q
        if send(it):
            st["rr"] = (idx + 1) % len(names)
            st["last_publish"] = now.isoformat()
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
            md = fetch(url + "?r=%d" % int(time.time()))   # список иногда приходит на русском
            items = PARSERS[store](md)
        print("%s: найдено %d позиций со скидкой" % (store, len(items)))
        if DRY:
            for it in items[:5]:
                print("    - %s | %s->%s ֏ (-%s%%) %s | фото: %s"
                      % (it["title"][:70], it["old"], it["new"], it["pct"], it["until"],
                         (photos(it) or ["нет"])[0]))
        seen = st["seen"].setdefault(store, [])
        seen_set = set(seen)
        fresh = []
        for it in items:
            k = key(it)
            it["key"] = k
            if k in seen_set:
                continue
            seen_set.add(k)
            seen.append(k)
            fresh.append(it)
        if not st.get("seeded"):
            fresh = items[:SEED_PER_STORE]
        q = st["queues"].setdefault(store, [])
        q.extend(fresh)                                    # новое всегда в хвост
        if len(q) > QUEUE_CAP:
            for x in q[QUEUE_CAP:]:
                seen_set.discard(x["key"])                 # отброшенное вернём в очередь позже
            del q[QUEUE_CAP:]
            st["seen"][store] = [k for k in st["seen"][store] if k in seen_set]
        print("%s: новых %d, в очереди %d" % (store, len(fresh), len(q)))
    st["seeded"] = True
    publish(st)
    if DRY:
        print("DRY RUN: состояние не сохранено")
        return
    save_state(st)

if __name__ == "__main__":
    main()
