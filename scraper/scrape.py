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


def page_urls(user):
    base = f"https://pubhtml5.com/homepage/{user}/"
    yield base
    for n in range(2, MAX_PAGES + 1):
        yield f"{base}{n}/"


def scrape_user(user):
    books, seen = [], set()
    for i, url in enumerate(page_urls(user)):
        html = get(url)
        if html is None:
            break
        if i == 0:
            DEBUG.mkdir(exist_ok=True)
            (DEBUG / f"{user}-page1.html").write_text(html, encoding="utf-8")
        new = [b for b in parse_page(html, user, url) if b["bid"] not in seen]
        print(f"  {url}: {len(new)} new")
        if not new:
            break
        for b in new:
            seen.add(b["bid"])
            books.append(b)
        time.sleep(1)
    return books


def check_download(b):
    """เปิดหน้ารายละเอียดของเล่ม ดูว่ามีปุ่มดาวน์โหลดหรือไม่"""
    url = b.get("page_url") or f"https://pubhtml5.com/{b['user']}/{b['bid']}/"
    html = get(url)
    if html is None:
        return None, url
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(["a", "button"]):
        text = clean(el.get_text()).lower() + " " + " ".join(el.get("class", [])).lower()
        if "download" in text or "ดาวน์โหลด" in text:
            href = el.get("href")
            if href and not href.startswith(("javascript", "#")):
                return True, urljoin(url, href)
            return True, url
    return False, url


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
            merged["read_url"] = f"https://online.pubhtml5.com/{user}/{b['bid']}/"
            if not merged.get("title"):
                merged["title"] = b["bid"]
            if "can_download" not in prev:
                merged["can_download"], merged["download_url"] = check_download(merged)
                time.sleep(0.5)
            old[b["id"]] = merged

    if total_live == 0:
        print("ERROR: ไม่พบหนังสือเลย โครงสร้างหน้าเว็บอาจเปลี่ยน ดูไฟล์ใน debug/", file=sys.stderr)
        sys.exit(1)

    for bid, b in old.items():
        if bid not in live_ids:
            b["gone"] = True

    data = {"updated": now, "users": USERS, "books": list(old.values())}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {len(old)} books ({total_live} live)")


if __name__ == "__main__":
    main()
