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
# Քայլ 14, ոչ 15. GitHub-ի ռանները գալիս են 15 րոպեով ու վայրկյաններով,
# ուղիղ 15-ի դեպքում ամեն երկրորդ սլոտը դուրս էր ընկնում։
STEP_MIN = 14
PUB_FROM, PUB_TO = 0, 24
QUEUE_CAP = 200
SEED_PER_STORE = 8
CITY_SEEN_KEEP = 20
SAS_SEEN_KEEP = 500
API = "https://api.telegram.org/bot%s/" % TOKEN
JINA = "https://r.jina.ai/"

# Ֆայլով ուղարկելիս Telegram-ը չի սեղմում։ Սա պարտադիր է, որ լուսանկարը
# գնա լրիվ չափով, ոչ թե 1280px-ի սեղմված։
SEND_AS_FILE = True

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
# SAS-ը գները գրում է «19 000 դր.», ոչ «֏»; մեկ հատի գները («292 դր./1հատ»)
# դեն ենք նետում lookahead-ով։
PRICE = re.compile(r"([\d][\d\s,\.]{1,12}?)\s*(?:֏|դր\.?|\bnull\b)(?!\s*/)")
DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
# SAS-ի ապրանքի քարտի հղումը ՄԻՇՏ վերջանում է id-ով՝ /catalog/<բաժին>/<թիվ>/։
# Նավիգացիոն հղումները («Դիտել ամբողջ բաժինը» → /catalog/xxx/,
# «0 դր. Զամբյուղում» → /order/) id չունեն, ուստի այլևս չեն անցնում։
SAS_LINK = re.compile(
    r"\[(?:!\[([^\]]{4,160})\]\(([^)]*)\)|([^\]\n]{4,160}))\]"
    r"\((https://www\.sas\.am/(?!upload/)[^)\s]*/\d{3,}/?)\)")
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

def img_in(chunk):
    for u in IMG_MD.findall(chunk):
        if not any(s in u.lower() for s in SKIP_IMG):
            return u
    return ""

def has_name(s):
    return bool(NAME.search(s or ""))

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
    out, links = [], list(SAS_LINK.finditer(md))
    # Երկրորդ պաշտպանություն՝ եթե կայքը փոխի URL-ի ձևը։
    skip = ("հավելին", "ցույց", "ցուցադրել", "ֆիլտր", "փակել", "շուտով",
            "купить", "в корзину", "подробнее", "все акции",
            "ամբողջ բաժինը", "զամբյուղ", "զամբյուղում", "ներբեռնել")
    for i, m in enumerate(links):
        text = (m.group(1) or m.group(3) or "").strip()
        if not text or any(s in text.lower() for s in skip):
            continue
        end = links[i + 1].start() if i + 1 < len(links) else min(len(md), m.end() + 900)
        chunk = md[m.end():end]
        # Քարտը վերջանում է «Զամբյուղում» կոճակով, որից հետո գալիս է հաջորդ
        # ապրանքը։ Պատուհանը կտրում ենք այդ կոճակի վրա, որ ուրիշ ապրանքի գինն
        # ու ամսաթիվը չխառնվեն։
        cut = chunk.find("Զամբյուղում")
        if cut != -1:
            chunk = chunk[:cut]
        prices = [p for p in (num(x) for x in PRICE.findall(chunk)) if p > 0]
        if len(prices) < 2:
            continue
        dates = DATE.findall(chunk)
        out.append(make("SAS", text, prices[0], prices[-1],
                        dates[-1] if dates else "",
                        m.group(2) or img_in(chunk), m.group(4)))
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
    m = re.search(r"/(\d{3,})/?$", it.get("url") or "")
    if m:
        return "%s|id:%s" % (it["store"], m.group(1))
    return "%s|t:%s" % (it["store"], it["title"].lower())

def legacy_key(it):
    return "%s|%s|%s|%s|%s" % (it["store"], it["title"].lower(), it["old"], it["new"], it["until"])

def card_images(it):
    urls = []
    page = it.get("url") or it.get("page") or ""
    # Հին գրառումներ հերթում. url-ում նկարի հղումն է, ոչ քարտի։
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
    # Քարտի գլխավոր լուսանկարը (og:image) ցանկի առաջին պիտանին է։ Չափով
    # ամենամեծը վերցնել չի կարելի. քարտի էջում ուրիշ նկարներ էլ կան։
    # webp-ը չենք հրում վերջը. og:image-ն է իսկական լուսանկարը։
    return card_images(it)[:6]

def card_until(it):
    """Ակցիայի ժամկետը ապրանքի քարտից (Yerevan City-ն ցուցակում ամսաթիվ չի տալիս)։"""
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

def best_photo(it):
    """Ապրանքի իսկական լուսանկարը՝ ցանկի առաջին պիտանին (og:image)։"""
    for u in photo_candidates(it):
        try:
            r = requests.get(u, timeout=60, headers=HDRS)
        except Exception as e:
            print("նկար: %s — %s" % (u, e))
            continue
        if r.ok and len(r.content) > 5000:
            return r.content, u.split("?")[0].rsplit("/", 1)[-1] or "photo.jpg"
    return b"", "photo.jpg"

def send(it):
    it["title"] = clean_title(it["title"])
    if not it.get("until"):
        it["until"] = card_until(it)
    text = "%s\n%s\n%s ֏ → %s ֏ (-%s%%)" % (
        it["store"], it["title"], money(it["old"]), money(it["new"]), it["pct"])
    if it["until"]:
        text += "\nՄինչև՝ %s" % it["until"]
    if DRY:
        cand = card_images(it)
        print("[DRY] " + text.replace("\n", " | ") + " | նկար: " + (cand[0] if cand else "չկա"))
        return True
    try:
        data, name = best_photo(it)
    except Exception as e:
        print("լուսանկարի սխալ: %s" % e)
        data, name = b"", "photo.jpg"
    if data:
        field = "document" if SEND_AS_FILE else "photo"
        r = requests.post(API + ("sendDocument" if SEND_AS_FILE else "sendPhoto"),
                          data={"chat_id": CHANNEL, "caption": text,
                                "reply_markup": BUTTON},
                          files={field: (name, data)}, timeout=120)
        if r.ok and r.json().get("ok"):
            return True
        print("Ֆայլը չգնաց: %s" % r.text[:200])
    for u in photo_candidates(it)[:4]:
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
    print("Բոլոր հերթերը դատարկ են")

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
    # ՄԻԱՆՎԱԳ մաքրում. մինչ այս տարբերակը SAS-ի նավիգացիոն հղումները
    # («0 դր. Զամբյուղում», «Դիտել ամբողջ բաժինը») մտել էին հերթ որպես
    # ապրանք։ Այստեղ հանվում են միայն դրանք, մնացածի կարգը չի փոխվում։
    # Եթե այս բլոկը պետք չէ՝ ջնջիր ամբողջությամբ, մինչև «for store, url...»։
    if not st.get("junk_cleaned"):
        q = st["queues"].get("SAS") or []
        good = [x for x in q if re.search(r"/(\d{3,})/?$", x.get("url") or "")]
        if len(good) != len(q):
            print("Մաքրում. SAS-ի հերթից հանվեց %d աղբ դիրք" % (len(q) - len(good)))
        st["queues"]["SAS"] = good
        st["junk_cleaned"] = True
    for store, url in STORES.items():
        try:
            md = fetch(url)
        except Exception as e:
            print("%s: բեռնելու սխալ: %s" % (store, e))
            continue
        items = PARSERS[store](md)
        if not items and store == "Yerevan City":
            md = fetch(url + "?r=%d" % int(time.time()))
            items = PARSERS[store](md)
        print("%s: գտնվեց %d զեղչով դիրք" % (store, len(items)))
        if DRY:
            for it in items[:5]:
                cand = card_images(it)
                print("    - %s | %s->%s ֏ (-%s%%) %s | նկար: %s"
                      % (it["title"][:70], it["old"], it["new"], it["pct"], it["until"],
                         cand[0] if cand else "չկա"))
        seen_set = set(st["seen"].setdefault(store, []))
        in_queue = set(x.get("key") for x in st["queues"].get(store, []))
        fresh = []
        for it in items:
            k = key(it)
            it["key"] = k
            if k in seen_set or legacy_key(it) in seen_set or k in in_queue:
                continue
            fresh.append(it)
        if not st.get("seeded"):
            fresh = fresh[:SEED_PER_STORE]
        for it in fresh:
            seen_set.add(it["key"])
            st["seen"][store].append(it["key"])
        q = st["queues"].setdefault(store, [])
        q.extend(fresh)
        # Առաստաղը լրանալիս գլխից են դուրս գալիս ամենահները, նորը մնում է պոչում,
        # կարգը կայքի կարգն է։ Ըստ զեղչի ոչ մի դասավորում չկա։
        if len(q) > QUEUE_CAP:
            del q[:len(q) - QUEUE_CAP]
        keep = CITY_SEEN_KEEP if store == "Yerevan City" else SAS_SEEN_KEEP
        if len(st["seen"][store]) > keep:
            del st["seen"][store][:-keep]
        print("%s: նոր %d, հերթում %d" % (store, len(fresh), len(q)))
    st["seeded"] = True
    publish(st)
    if DRY:
        print("DRY RUN. վիճակը չպահվեց")
        return
    save_state(st)

if __name__ == "__main__":
    main()
