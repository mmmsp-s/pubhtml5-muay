"""ดึงรายการหนังสือจากหน้า homepage ของ pubhtml5 แล้วเก็บลง site/books.json

ข้อมูลเก่าจะไม่ถูกลบ ถ้าเจ้าของลบเล่มไป ลิงก์เดิมยังอยู่ (ทำเครื่องหมาย gone=True)
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

USERS = ["aswhk", "fqeu"]
MAX_PAGES = 200
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "books.json"
DEBUG = ROOT / "debug"

DEADLINE = time.time() + 40 * 60  # กันไม่ให้รันนานเกินไป

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "th,en;q=0.8",
})


def get(url):
    for i in range(3):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            print(f"  ! {url}: {e}", file=sys.stderr)
            time.sleep(2 * (i + 1))
    return None


def book_re(user):
    # https://online.pubhtml5.com/aswhk/abcd/  หรือ  https://pubhtml5.com/aswhk/abcd/ชื่อ.html
    return re.compile(rf"https?://(?:online\.|www\.)?pubhtml5\.com/{re.escape(user)}/([a-z0-9]{{3,12}})(?:/|$)", re.I)


def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


def parse_page(html, user, base):
    soup = BeautifulSoup(html, "html.parser")
    rx = book_re(user)
    found = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        m = rx.match(href)
        if not m:
            continue
        bid = m.group(1).lower()
        if bid in ("homepage", "bookcase", "explore"):
            continue
        b = found.setdefault(bid, {"id": f"{user}/{bid}", "user": user, "bid": bid,
                                   "title": "", "cover": "", "page_url": ""})
        img = a.find("img")
        title = clean(a.get("title")) or clean(img.get("alt") if img else "") or clean(a.get_text())
        if len(title) > len(b["title"]):
            b["title"] = title
        if img and not b["cover"]:
            src = img.get("data-original") or img.get("data-src") or img.get("src") or ""
            if src and not src.startswith("data:"):
                b["cover"] = urljoin(base, src)
        if "online.pubhtml5.com" not in href and not b["page_url"]:
            b["page_url"] = href.split("#")[0]
    # ลำดับตามที่ปรากฏในหน้า
    return list(found.values())


API = "https://pubhtml5.com/hostInfo/get-homepage-books.php"
PAGE_SIZE = 20


def pick(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", 0):
            return str(v)
    return ""


def from_api(item, user):
    """แปลงข้อมูลเล่มจาก API ให้เป็นรูปแบบของเรา"""
    bid = str(item.get("bLink") or "").strip("/")
    if not bid:
        m = book_re(user).match(str(item.get("url") or ""))
        bid = m.group(1).lower() if m else ""
    return {
        "id": f"{user}/{bid}", "user": user, "bid": bid,
        "title": clean(item.get("title")) or bid,
        "num": int(item.get("bookid") or 0),
        "read_url": item.get("url") or f"https://online.pubhtml5.com/{user}/{bid}/",
        "cover": f"https://online.pubhtml5.com/{user}/{bid}/files/shot.jpg",
        "page_url": f"https://pubhtml5.com/{user}/{bid}/",
    }


def scrape_user(user):
    home = f"https://pubhtml5.com/homepage/{user}/"
    html = get(home)
    if html is None:
        return []
    m = re.search(r'homeUserId\s*=\s*"(\d+)"', html) or re.search(r'userid:\s*"(\d+)"', html)
    if not m:
        dump(html, home)
        return []
    uid = m.group(1)
    last_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    books, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        try:
            r = S.post(API, data={"pageSize": PAGE_SIZE, "lastTime": last_time, "userid": uid,
                                  "page": page, "myUid": "-1"},
                       headers={"Referer": home, "X-Requested-With": "XMLHttpRequest"}, timeout=30)
            data = r.json()
        except Exception as e:
            print(f"  ! page {page}: {e}", file=sys.stderr)
            break
        items = data.get("values") or []
        if page == 1:
            print(f"  status={data.get('status')} keys={list(data.keys())}")
            if items:
                print("  sample:", json.dumps(items[0], ensure_ascii=False)[:1500])
        new = 0
        for it in items:
            b = from_api(it, user)
            if b["bid"] and b["bid"] not in seen:
                seen.add(b["bid"])
                books.append(b)
                new += 1
        print(f"  page {page}: {len(items)} items, {new} new")
        if len(items) < PAGE_SIZE or not new or time.time() > DEADLINE:
            break
        time.sleep(0.7)
    return books


def dump(html, label):
    """พิมพ์โครงสร้างหน้าเว็บลง log เพื่อใช้ตรวจเวลาดึงไม่เจอ"""
    soup = BeautifulSoup(html, "html.parser")
    print(f"---- DEBUG {label}: {len(html)} bytes, title={clean(soup.title.string if soup.title else '')!r}")
    hrefs = sorted({a['href'] for a in soup.find_all('a', href=True)})
    print(f"links ({len(hrefs)}):")
    for h in hrefs[:80]:
        print("  ", h[:160])
    for sc in soup.find_all('script'):
        if sc.get('src'):
            print("  script", sc['src'][:160])
        else:
            t = sc.get_text()
            for m in re.findall(r"[\w/.:-]*(?:ajax|api|\.php|json|getBook|bookList|page)[\w/.?=&:-]*", t, re.I)[:30]:
                print("  js>", m[:160])
    for m in sorted(set(re.findall(r"(?:data-[\w-]+|id|class)=\"[^\"]*(?:book|item|list|page|more)[^\"]*\"", html, re.I)))[:60]:
        print("  attr", m[:160])
    for sc in soup.find_all('script'):
        t = sc.get_text()
        if re.search(r"homepage-books|encrypt|password|pwd", t, re.I):
            print("  ==== SCRIPT ====")
            print(t[:6000])
    for f in soup.find_all(['form', 'input']):
        print("  form", str(f)[:300])
    for m in re.finditer(r"encrypt", html, re.I):
        print("  ctx", html[max(0, m.start()-400):m.end()+600].replace("\n", " ")[:1000])
    body = soup.body.get_text(" ", strip=True) if soup.body else ""
    print("  text:", body[:1500])


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    old = {}
    if OUT.exists():
        old = {b["id"]: b for b in json.loads(OUT.read_text(encoding="utf-8")).get("books", [])}

    total_live = 0
    live_ids = set()
    for user in USERS:
        print(f"== {user}")
        books = scrape_user(user)
        total_live += len(books)
        for pos, b in enumerate(books):
            live_ids.add(b["id"])
            prev = old.get(b["id"], {})
            merged = {**prev, **{k: v for k, v in b.items() if v}}
            merged["first_seen"] = prev.get("first_seen", now)
            merged["last_seen"] = now
            merged["pos"] = pos
            merged["gone"] = False
            old[b["id"]] = merged

    if total_live == 0:
        print("ERROR: ไม่พบหนังสือเลย โครงสร้างหน้าเว็บอาจเปลี่ยน ดูไฟล์ใน debug/", file=sys.stderr)
        sys.exit(1)

    for bid, b in old.items():
        if bid not in live_ids:
            b["gone"] = True

    for b in old.values():
        b.pop("can_download", None)
        b.pop("download_url", None)
    data = {"updated": now, "users": USERS, "books": list(old.values())}
    OUT.parent.mkdir(exist_ok=True)
    rows = ",\n".join(json.dumps(b, ensure_ascii=False, separators=(",", ":")) for b in data["books"])
    head = json.dumps({k: v for k, v in data.items() if k != "books"}, ensure_ascii=False)[:-1]
    OUT.write_text(f'{head},"books":[\n{rows}\n]}}\n', encoding="utf-8")
    print(f"saved {len(old)} books ({total_live} live)")


if __name__ == "__main__":
    main()
