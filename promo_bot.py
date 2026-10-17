# -*- coding: utf-8 -*-
"""Supermarket promo bot: SAS, Yerevan City, Carrefour -> Telegram channel."""
import html as html_lib
import json
import os
import re
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
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
SKIP_IMG = ("logo", "18-plus", "flags/", "icon", "banner", "banniere", "svg", "avatar")

STORES = {
    "SAS": "https://www.sas.am/ru/catalog/discount/",
    "Yerevan City": "https://yerevan-city.am/shop/best-offers",
}
PRICE_DR = re.compile(r"([\d][\d\s]{2,10})\s*др")
PRICE_AM = re.compile(r"([\d][\d\s]{1,10})\s*֏")
DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
IMG_LINK = re.compile(r"\[!\[[^\]]*\]\((https?://[^)\s]+)\)\]\((https?://[^)\s]+)\)")
CITY_LINK = re.compile(r"\[([^\]]{8,400}?)\]\((https://yerevan-city\.am/shop/product-details/\d+)\)", re.S)
CAR_LINK = re.compile(r"\[([^\]\n]{4,160})\]\((https?://carrefour\.am/[^)\s]+)\)")

def html_to_text(html):
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    h = re.sub(r"(?is)<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>", r"![](\1)", h)
    h = re.sub(r"(?is)</?(del|s|strike)[^>]*>", "~~", h)
    h = re.sub(r"(?s)<[^>]+>", "\n", h)
    h = html_lib.unescape(h)
    h = re.sub(r"[ \t\u00a0]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n\n", h)

def fetch(store, url):
    for u in (JINA + url, url):
        try:
            r = requests.get(u, timeout=90, headers=HEADERS)
            if r.status_code != 200:
                print("  ! %s -> HTTP %s" % (u[:70], r.status_code))
                continue
            text = r.text if u.startswith(JINA) else html_to_text(r.text)
            if len(text) > 5000:
                print("  источник: %s" % ("jina" if u.startswith(JINA) else "сайт напрямую"))
                return text
            print("  ! %s -> слишком короткий ответ (%d симв.)" % (u[:70], len(text)))
        except Exception as e:
            print("  ! %s -> %s" % (u[:70], e))
    return ""

def num(s):
    s = re.sub(r"[\s\u00a0]", "", s or "")
    if "." in s:
        s = s.split(".")[0]
    s = re.sub(r"\D", "", s)
    return int(s) if s else 0

def money(n):
    return "{:,}".format(n).replace(",", " ")

def img_in(chunk):
    for u in re.findall(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", chunk):
        if not any(s in u.lower() for s in SKIP_IMG):
            return u
    return ""

def make(store, title, old, new, until, img):
    title = re.sub(r"\s+", " ", (title or "").replace("\\", " ")).strip(" -|")
    if len(title) < 4 or new <= 0 or old <= new:
        return None
    pct = round((old - new) * 100.0 / old)
    if pct < 5:
        return None
    return {"store": store, "title": title, "old": old, "new": new,
            "pct": pct, "until": until or "", "img": img or ""}

def parse_sas(md):
    out = []
    anchors = list(IMG_LINK.finditer(md))
    for i, m in enumerate(anchors):
        if "sas.am" not in m.group(2):
            continue
        end = anchors[i + 1].start() if i + 1 < len(anchors) else min(len(md), m.end() + 700)
        chunk = md[m.end():end]
        prices = [p for p in (num(x) for x in PRICE_DR.findall(chunk)) if p > 0]
        if len(prices) < 2:
            continue
        dates = DATE.findall(chunk)
        until = dates[1] if len(dates) > 1 else (dates[0] if dates else "")
        title = ""
        for line in chunk.split("\n"):
            line = line.strip()
            if (len(line) > 4 and "др" not in line and not line.startswith("-")
                    and not line.startswith("Акция") and not line.startswith("[")):
                title = line
                break
        it = make("SAS", title, prices[0], prices[1], until, m.group(1))
        if it:
            pct = re.search(r"-(\d{1,2})\s*%", chunk)
            if pct:
                it["pct"] = int(pct.group(1))
            out.append(it)
    return out

def parse_city(md):
    out = []
    for m in CITY_LINK.finditer(md):
        inner = m.group(1)
        pr = re.search(r"~~\s*([\d\s,\.]+?)\s*(?:֏|null)?\s*~~\s*([\d\s,\.]+)", inner)
        if not pr:
            continue
        text = re.sub(r"~~.*?~~", " ", inner, flags=re.S)
        text = re.sub(r"[\d][\d\s,\.]{2,}\s*(?:֏|null)", " ", text)
        text = text.replace("null", " ")
        text = re.sub(r"-?\d{1,2}%", " ", text)
        it = make("Yerevan City", text, num(pr.group(1)), num(pr.group(2)), "",
                  img_in(md[max(0, m.start() - 700):m.end()]))
        if it:
            pct = re.search(r"-(\d{1,2})\s*%", inner)
            if pct:
                it["pct"] = int(pct.group(1))
            out.append(it)
    return out

def parse_carrefour(md):
    out = []
    anchors = list(CAR_LINK.finditer(md))
    for i, m in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else min(len(md), m.end() + 1500)
        chunk = md[m.end():end]
        sp = re.search(r"Special\s*Price\s*([\d\s,\.]{1,10})\s*֏\s*Regular\s*Price\s*([\d\s,\.]{1,10})\s*֏", chunk, re.I)
        if sp:
            old, new = num(sp.group(2)), num(sp.group(1))
        else:
            prices = [p for p in (num(x) for x in PRICE_AM.findall(chunk)) if p > 0]
            if len(prices) < 2:
                continue
            old, new = prices[0], prices[1]
        out.append(make("Carrefour", m.group(1), old, new, "", img_in(chunk)))
    return [x for x in out if x]

PARSERS = {"SAS": parse_sas, "Yerevan City": parse_city, "Carrefour": parse_carrefour}

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

def send(it):
    text = "%s\n%s\n%s ֏ → %s ֏ (-%s%%)" % (it["store"], it["title"], money(it["old"]), money(it["new"]), it["pct"])
    if it["until"]:
        text += "\nՄինչև՝ %s" % it["until"]
    if DRY:
        print("[DRY] " + text.replace("\n", " | "))
        return True
    if it["img"]:
        r = requests.post(API + "sendPhoto", data={"chat_id": CHANNEL, "photo": it["img"], "caption": text}, timeout=60)
        if r.ok and r.json().get("ok"):
            return True
    r = requests.post(API + "sendMessage", data={"chat_id": CHANNEL, "text": text}, timeout=60)
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
        return
    print("Все очереди пусты")

def main():
    st = load_state()
    for store, url in STORES.items():
        print("== %s" % store)
        md = fetch(store, url)
        if not md:
            print("   не удалось получить страницу")
            continue
        items = PARSERS[store](md)
        print("   найдено %d позиций со скидкой" % len(items))
        if DRY:
            for it in items[:5]:
                print("    - %s | %s->%s ֏ (-%s%%) %s | фото: %s"
                      % (it["title"][:60], it["old"], it["new"], it["pct"], it["until"], "да" if it["img"] else "нет"))
            if not items:
                probe = re.search(r"[^\n]*(֏|др)[^\n]*", md)
                print("    проба: %s" % (probe.group(0)[:200] if probe else md[:200].replace("\n", " ")))
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
        q.extend(fresh)
        if len(q) > QUEUE_CAP:
            q.sort(key=lambda x: -x["pct"])
            del q[QUEUE_CAP:]
        print("   новых %d, в очереди %d" % (len(fresh), len(q)))
    st["seeded"] = True
    publish(st)
    if DRY:
        print("DRY RUN: состояние не сохранено")
        return
    save_state(st)

if __name__ == "__main__":
    main()
