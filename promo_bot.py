# -*- coding: utf-8 -*-
"""Supermarket promo bot (հայերեն): SAS + Yerevan City -> Telegram channel."""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL = os.environ.get("CHANNEL", "")
DRY = os.environ.get("DRY_RUN", "0") == "1"

VERSION = 3
STATE = "state-promo.json"
YE = timezone(timedelta(hours=4))
PUB_FROM, PUB_TO, STEP_MIN = 8, 24, 15
QUEUE_CAP, SEED_PER_STORE = 16, 8
API = "https://api.telegram.org/bot%s/" % TOKEN
JINA = "https://r.jina.ai/"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "hy-AM,hy;q=0.9,en;q=0.7",
}
BOOST = "https://t.me/boost/supermarket_promos"
BTN = json.dumps({"inline_keyboard": [[{"text": "😊 Աջակցել ալիքին", "url": BOOST}]]})

STORES = {
    "SAS": "https://www.sas.am/catalog/discount/",
    "Yerevan City": "https://yerevan-city.am/shop/best-offers",
}

CITY_PHOTO = "https://media.yerevan-city.am/api/Image/Resize/ProductPhoto/%s.png"
CUR = r"(?:֏|դր\.)"
PRICE = re.compile(r"([\d][\d\s]{1,9})\s*" + CUR)
DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
IMG_MD = re.compile(r"!\[(?:Image \d+: )?([^\]]*)\]\((https?://[^)\s]+)\)")
SAS_CARD = re.compile(r"\[(?:(?:!\[[^\]]*\]\([^)\s]+\))+)\]\((https://www\.sas\.am/catalog/[^)\s]+/\d+/)\)")
CITY_LINK = re.compile(r"\[([^\]]{10,400}?)\]\((https://yerevan-city\.am/shop/product-details/\d+)\)", re.S)
OG_A = re.compile(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]*content=["\']([^"\']+)', re.I)
OG_B = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:image["\']', re.I)
ARM = re.compile(r"[Ա-Ֆա-ֆև]")
ART = re.compile(r"(?:Արտիկուլ|Артикул|Article)\s*:?\s*([0-9A-Za-z\-]{4,})")
BAD_IMG = ("logo", "/local/", "favicon", "markup-images", "svg", "icon", "menu",
           "minus", "plus", "banner", "flags/", "no_res")
SKIP_IMG = BAD_IMG
BAD_LINE = ("հատ", "զամբյուղ", "Մանրամասներ", "Կարդալ", "Ակցիան")

def fetch(url):
    r = requests.get(JINA + url, timeout=120, headers=UA)
    r.raise_for_status()
    return r.text

def clean(t):
    return re.sub(r"\s+", " ", (t or "").replace("\\", " ")).strip(" -|")

def money(s):
    s = (s or "").replace(",", "").strip()
    try:
        return int(round(float(s)))
    except ValueError:
        pass
    d = re.sub(r"[^\d]", "", s.split(".")[0])
    return int(d) if d else 0

def money_fmt(n):
    return "{:,}".format(n).replace(",", " ")

def ok_img(u):
    return bool(u) and not any(s in u.lower() for s in SKIP_IMG)

def img_in(text):
    for alt, u in IMG_MD.findall(text):
        if ok_img(u):
            return u
    return ""

def big_img(md, title):
    for alt, u in IMG_MD.findall(md):
        if clean(alt) == title and ok_img(u):
            return u
    return ""

def og_img(url):
    """Ապրանքի էջի og:image — մեծ ֆոտոն։"""
    try:
        r = requests.get(url, timeout=60, headers=UA)
        if r.status_code != 200:
            return ""
        h = r.text
    except Exception:
        return ""
    for rx in (OG_A, OG_B):
        m = rx.search(h)
        if m:
            img = m.group(1).strip()
            if ok_img(img) and "logo" not in img.lower():
                return img
    return ""

def name_in(chunk):
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

def make(store, title, old, new, until, img, page):
    title = clean(title)
    if len(title) < 4 or new <= 0 or old <= new:
        return None
    pct = int(round((old - new) * 100.0 / old))
    if pct < 5:
        return None
    return {"store": store, "title": title, "old": old, "new": new,
            "pct": pct, "until": until or "", "img": img or "", "page": page}

def parse_sas(md):
    out, cards = [], list(SAS_CARD.finditer(md))
    for i, m in enumerate(cards):
        end = cards[i + 1].start() if i + 1 < len(cards) else len(md)
        chunk = md[m.end():end]
        prices = [p for p in (money(x) for x in PRICE.findall(chunk)) if p > 0]
        if len(prices) < 2:
            continue
        dates = DATE.findall(chunk)
        it = make("SAS", name_in(chunk), prices[0], prices[1],
                  dates[-1] if dates else "", img_in(m.group(0)), m.group(1))
        if it:
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
        name = re.sub(r"^[-\s]*\d+\s*%\s*", "", name)
        name = re.sub(r"\s+\d{3,}$", "", name).strip()
        if not ARM.search(name):
            continue          # ռուսերեն/անգլերեն անունը ալիք չի գնում
        it = make("Yerevan City", name, money(pr.group(1)), money(pr.group(2)), "", "", m.group(2))
        if it:
            out.append(it)
    return out

def city_items():
    """City-ի ցանկը. եթե հայատառ չեկավ՝ նոր փորձ նոր URL-ով (jina-ն նորից render անի)։"""
    for attempt in (0, 1):
        url = STORES["Yerevan City"] + ("?r=%d" % int(time.time()) if attempt else "")
        try:
            md = fetch(url)
        except Exception as e:
            print("Yerevan City: ошибка загрузки: %s" % e)
            return []
        items = parse_city(md)
        if items:
            return items
        print("Yerevan City: հայերեն ցանկ չեկավ, նոր փորձ")
    return []

def enrich(it):
    """Մեծ ֆոտո. City՝ արտիկուլի հղում (Cloudflare-ից անկախ) → og:image.",
                      SAS՝ og:image → քարտի պատկեր (alt=անուն)։"""
    page = it.get("page") or ""
    if not page:
        return it
    img = ""
    if it["store"] == "Yerevan City":
        try:
            md = fetch(page)
        except Exception as e:
            print("    էջը չբացվեց: %s" % e)
            md = ""
        if md:
            m = ART.search(md)
            if m:
                img = CITY_PHOTO % m.group(1)
        if not img:
            img = og_img(page)
    else:
        img = og_img(page)
        if not img:
            try:
                img = big_img(fetch(page), it["title"])
            except Exception as e:
                print("    էջը չբացվեց: %s" % e)
    if img:
        it["img"] = img
    return it

def post_text(it):
    lines = [it["store"], it["title"], "Զեղչ՝ -%d%%" % it["pct"],
             "%s ֏ → %s ֏" % (money_fmt(it["old"]), money_fmt(it["new"]))]
    if it["until"]:
        lines.append("Մինչև %s" % it["until"])
    return "\n".join(lines)

def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"seen": {}, "queues": {}, "seeded": False, "rr": 0,
            "last_publish": "", "version": VERSION}

def save_state(st):
    st["version"] = VERSION
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)

def key(it):
    return "%s|%s|%s|%s" % (it["store"], it["title"].lower(), it["old"], it["new"])

def send(it):
    text = post_text(it)
    if DRY:
        print("[DRY] %s" % text.replace("\n", " | "))
        return True
    if it["img"]:
        try:
            b = requests.get(it["img"], timeout=90, headers=UA).content
        except Exception:
            b = b""
        if len(b) > 5000:
            ext = os.path.splitext(it["img"].split("?")[0])[1] or ".jpg"
            r = requests.post(API + "sendPhoto",
                              data={"chat_id": CHANNEL, "caption": text, "reply_markup": BTN},
                              files={"photo": ("photo" + ext, b)}, timeout=180)
            if r.ok and r.json().get("ok"):
                return True
            print("sendPhoto: %s" % r.text[:200])
    r = requests.post(API + "sendMessage",
                      data={"chat_id": CHANNEL, "text": text, "reply_markup": BTN}, timeout=60)
    if not (r.ok and r.json().get("ok")):
        print("sendMessage: %s" % r.text[:200])
        return False
    return True

def publish(st):
    now = datetime.now(YE)
    if not (PUB_FROM <= now.hour < PUB_TO):
        print("Вне окна публикации (%s)" % now.strftime("%H:%M"))
        return
    last = st.get("last_publish") or ""
    if last:
        try:
            if now - datetime.fromisoformat(last) < timedelta(minutes=STEP_MIN):
                print("Слот ещё не наступил")
                return
        except ValueError:
            pass
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
        st["queues"] = {}
        st["seeded"] = False
        print("Նոր տարբերակ %s՝ հերթերը զրոյացված, նոր սիդ" % VERSION)
    for store, url in STORES.items():
        if store == "Yerevan City":
            items = city_items()
        else:
            try:
                items = parse_sas(fetch(url))
            except Exception as e:
                print("%s: ошибка загрузки: %s" % (store, e))
                continue
        print("%s: найдено %d позиций со скидкой" % (store, len(items)))
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
            fresh = (fresh or items)[:SEED_PER_STORE]
        q = st["queues"].setdefault(store, [])
        q.extend(fresh)
        if len(q) > QUEUE_CAP:
            q.sort(key=lambda x: -x["pct"])
            del q[QUEUE_CAP:]
        print("%s: новых %d, в очереди %d" % (store, len(fresh), len(q)))
        if DRY:
            for probe in items[:3]:
                pr = enrich(dict(probe))
                print("    ПРОБА %s | %s | %s->%s (-%d%%)" % (
                    store, pr["title"][:55], pr["old"], pr["new"], pr["pct"]))
                print("        фото: %s" % (pr["img"] or "НЕТ"))
    st["seeded"] = True
    publish(st)
    if DRY:
        print("DRY RUN: состояние не сохранено")
        return
    save_state(st)

if __name__ == "__main__":
    main()
