# -*- coding: utf-8 -*-
"""경쟁사 제품 현황 — 홈페이지 제품 목록을 매일 읽어 어제와 비교한다.

  · 회사마다 읽는 법이 다르다 (SOURCES). 그대로 읽히는 곳은 요청 한 번, 스크립트로 그리는 곳(시몬스·에이스)은
    서버 PC 의 크롬을 화면 없이 띄워 읽는다.
  · robots.txt 로 자동 수집을 막아 둔 곳(코웨이·슬로우·리바트·이케아)은 건드리지 않는다.
  · 하루 한 번, 회사당 몇 페이지. 뉴스 스케줄러 뒤에 이어서 돈다. «지금 갱신» 도 있다.
  · 제품스냅.json 에 회사별 최신 목록, 제품변화.jsonl 에 «신제품 · 단종 · 가격 변동» 이 쌓인다.
    첫 수집은 기준선이라 변화로 치지 않는다.
  · 홈페이지가 개편되면 그 회사 읽기가 멈춘다. 화면에 «읽기 실패» 로 바로 보이고, 그때 맞춰 주면 된다.
"""
import os, io, re, json, time, html, datetime, threading, subprocess, tempfile, shutil
import urllib.request, urllib.parse, urllib.error, ssl

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "제품스냅.json")
LOG = os.path.join(HERE, "제품변화.jsonl")
STATE = os.path.join(HERE, "제품상태.json")
_lock = threading.Lock()
TIMEOUT = 25
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36", "Accept-Language": "ko"}
_ctx = ssl.create_default_context()

CHROME = next((p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)

# 약관(robots.txt) 때문에 읽지 않는 곳 — 화면에 그렇게 적는다
EXCLUDED = (("코웨이 (비렉스)", "robots.txt 가 전체 수집을 금지"), ("슬로우", "robots.txt 가 전체 수집을 금지"),
            ("현대리바트", "robots.txt 가 전체 수집을 금지"), ("이케아", "robots.txt 가 전체 수집을 금지"),
            ("한샘", "제품 수천 개 · 별도 스토어 — 보류"), ("씰리 (가격)", "공식몰은 가격을 «오프라인» 으로만 표시"))


# ═══════════════════════════════════════════════ 읽기 도구
def _get(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers=dict(UA, **(headers or {})))
    return urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx).read().decode("utf-8", "replace")


def _render(url, tall=True, budget_ms=12000):
    """스크립트로 그려지는 페이지를 크롬으로 그린 뒤 HTML 을 돌려준다."""
    if not CHROME:
        raise RuntimeError("크롬이 없어 스크립트 페이지를 읽을 수 없습니다")
    prof = tempfile.mkdtemp(prefix="rdhub_chrome_")
    try:
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir=" + prof,
               "--window-size=1280,%d" % (16000 if tall else 900), "--virtual-time-budget=%d" % budget_ms,
               "--dump-dom", url]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        out = r.stdout.decode("utf-8", "replace")
        if len(out) < 2000:
            raise RuntimeError("크롬이 페이지를 그리지 못했습니다")
        return out
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def _txt(x):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x or ""))).strip()


def _plain(name):
    """비교용 이름: 대괄호 딱지([공식몰 특가] 등)·공백·대소문자를 뺀다."""
    return re.sub(r"\[[^\]]*\]|\s+", "", name or "").lower()


def _num(s):
    m = re.search(r"\d[\d,]*", s or "")
    return int(m.group(0).replace(",", "")) if m else None


# ═══════════════════════════════════════════════ 회사별 읽기 — 각 함수는 {id: item} 를 돌려준다
#   item = {"name", "price"(int|None), "line"(시리즈), "sizes", "link", "cat"}
def read_simmons():
    items = {}
    for cat_no, cat in (("848502", "뷰티레스트 매트리스"), ("847692", "뷰티레스트 블랙")):
        t = _render("https://www.simmons.co.kr/products?categoryNo=%s" % cat_no)
        for m in re.finditer(r'data-product-no="(\d+)"(.*?)(?=data-product-no="|$)', t, re.S):
            pid, blk = m.groups()
            name = re.search(r'product-thumb-title-product-name">(.*?)</div>', blk, re.S)
            price = re.search(r'product-thumb-price">([^<]*)<', blk)
            if not name:
                continue
            items[pid] = {"name": _txt(name.group(1)), "price": _num(price.group(1) if price else ""),
                          "line": cat, "sizes": "", "cat": cat,
                          "link": "https://www.simmons.co.kr/product-detail?productNo=" + pid}
    return items


def read_ace():
    items, page, total_pages = {}, 1, 1
    while page <= total_pages and page <= 6:
        t = _render("https://www.acebed.com/product/bed/mattress/list.do?pageIndex=%d" % page, tall=False)
        tp = re.search(r'data-total-page-count="(\d+)"', t)
        total_pages = int(tp.group(1)) if tp else 1
        pat = (r'<div class="list[^"]*"\s+data-link="([^"]*)"\s+data-seq="(\d+)".*?'
               r'<p class="value">(.*?)</p>\s*<p class="tit">(.*?)</p>\s*<p class="txt">(.*?)</p>')
        for link, seq, sizes, name, line in re.findall(pat, t, re.S):
            items[seq] = {"name": _txt(name), "price": None, "line": _txt(line), "sizes": _txt(sizes), "cat": "매트리스",
                          "link": html.unescape(link) or "https://www.acebed.com/product/bed/mattress/list.do"}
        page += 1
    return items


def read_sealy():
    items = {}
    home = _get("https://www.sealy.co.kr")
    # 1) 컬렉션(라인업) — 메뉴에 새 라인이 생기면 신제품
    for link, name in re.findall(r'href="(/collection/[^"]+\.html)"[^>]*>(.*?)</a>', home, re.S):
        nm = _txt(name)
        if not nm or nm.lower() == "view more" or len(nm) > 20:
            continue
        items["col:" + link] = {"name": nm, "price": None, "line": "컬렉션", "sizes": "", "cat": "라인업",
                                "link": "https://www.sealy.co.kr" + link}
    # 2) 공식몰 목록 — 품목별 페이지 (슈퍼싱글 392 · 퀸 394 · 킹 395 · 칼킹 396 · 레귤러킹 397 · 투매트리스 399 · 하단 400)
    for cate in ("392", "394", "395", "396", "397", "399", "400"):
        t = _get("https://www.sealy.co.kr/product/list.html?cate_no=%s" % cate)
        blk = t[t.find("xans-product-listnormal"):] if "xans-product-listnormal" in t else ""
        # 상품 li 안에 다른 li 가 겹쳐 있어 </li> 로 자르면 가격 전에 끊긴다 — 다음 상품 시작까지를 한 블록으로
        for no, body in re.findall(r'<li id="anchorBoxId_(\d+)"(.*?)(?=<li id="anchorBoxId_|</ul>)', blk, re.S):
            link = re.search(r'<a href="(/product/[^"]+)"', body)
            name = re.search(r'alt="([^"]+)"', body)
            price = re.search(r'판매가.*?([\d,]+)원', body, re.S)
            if not (link and name):
                continue
            items.setdefault("no:" + no, {"name": _txt(name.group(1)), "price": _num(price.group(1)) if price else None,
                                          "line": "", "sizes": "", "cat": "공식몰",
                                          "link": "https://www.sealy.co.kr" + html.unescape(link.group(1).split("?")[0])})
        time.sleep(0.3)
    return items


def read_tempur():
    items = {}
    for url, cat in (("https://kr.tempur.com/mattresses/by-range/", "매트리스"), ("https://kr.tempur.com/mattresses/", "매트리스")):
        t = _get(url)
        for pid, link, name in re.findall(r'<div data-pid="([^"]+)">\s*<div class="product-tile">.*?<a href="([^"]+)">.*?alt="([^"]+)"', t, re.S):
            items.setdefault(pid, {"name": _txt(name).replace("&trade;", "™"), "price": None, "line": "", "sizes": "",
                                   "cat": cat, "link": "https://kr.tempur.com" + link})
        time.sleep(0.3)
    return items


def read_zinus():
    items = {}
    for cate, cat in (("001", "매트리스"), ("009", "토퍼")):
        t = _get("https://www.zinus.co.kr/goods/goods_list.php?cateCd=%s" % cate)
        blk = t[t.find('<div class="list">'):]
        for no, body in re.findall(r'goods_view\.php\?goodsNo=(\d+)">\s*<strong>(.*?)</div>\s*</div>\s*</a>', blk, re.S):
            name = _txt(body.split("</strong>")[0])
            price = re.search(r'priceNumber">([^<]*)<', body)
            level = re.search(r'levelText">\s*<span>([^<]*)</span>\s*<span[^>]*>([^<]*)</span>', blk[blk.find(no):blk.find(no) + 3000])
            sizes = " / ".join(_txt(s) for s in re.findall(r'<div class="type">(.*?)</div>', blk[blk.find(no):blk.find(no) + 3000], re.S)[:1])
            items[no] = {"name": name, "price": _num(price.group(1) if price else ""), "line": (level.group(1) + " " + level.group(2)) if level else "",
                         "sizes": sizes.replace(" ", ""), "cat": cat, "link": "https://www.zinus.co.kr/goods/goods_view.php?goodsNo=" + no}
        time.sleep(0.3)
    return items


def read_emons():
    items = {}
    H = {"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.emons.co.kr/product/product_top.php?category=PRI2C2"}
    for cat_code, cat in (("PRI2C2", "퀸·킹 매트리스"), ("PRI2C1", "슈퍼·싱글 매트리스"), ("PRI2C5", "토퍼·하단매트"), ("PRI2C6", "에르디앙스")):
        page, total = 1, None
        while page <= 6:
            data = urllib.parse.urlencode({"page": page, "sch_type": "SS", "prodCategory": cat_code, "prodGrp": "PRI2", "odrType": "date"}).encode()
            t = _get("https://www.emons.co.kr/common/ajaxPage/ajaxProductTop.php", H, data)
            if total is None:
                m = re.search(r'listLeng">총 <b>(\d+)', t)
                total = int(m.group(1)) if m else 0
            got = []
            for pid, body in re.findall(r'<li id="product_(\d+)">(.*?)</li>', t, re.S):
                name = re.search(r'<div class="tit">\s*<p>(.*?)</p>', body, re.S)
                price = re.search(r"<p class='price'>([^<]*)</p>", body)
                if name:
                    got.append((pid, name.group(1), price.group(1) if price else ""))
            for pid, name, price in got:
                items.setdefault(pid, {"name": _txt(name), "price": _num(price), "line": "", "sizes": "", "cat": cat,
                                       "link": "https://www.emons.co.kr/product/product_view.php?grp=PRI2&prodId=" + pid})
            if not got or len(items) >= total:
                break
            page += 1
            time.sleep(0.3)
    # 사이즈별로 따로 등록돼 있다 (리브 매트리스 [KK] / [K] / [Q]). 모델 하나로 묶고 사이즈는 나열, 가격은 최저가
    models = {}
    for pid, it in items.items():
        m = re.match(r"^(.*?)\s*\[([^\]]+)\]\s*$", it["name"])
        base, size = (m.group(1).strip(), m.group(2).strip()) if m else (it["name"], "")
        key = "m:" + re.sub(r"\s+", "", base).lower()
        mo = models.setdefault(key, {"name": base, "price": None, "line": "", "sizes": [], "cat": it["cat"], "link": it["link"]})
        if size and size not in mo["sizes"]:
            mo["sizes"].append(size)
        if it["price"] and (mo["price"] is None or it["price"] < mo["price"]):
            mo["price"] = it["price"]
            mo["link"] = it["link"]
    for mo in models.values():
        mo["sizes"] = " / ".join(mo["sizes"])
    return models


SOURCES = (
    ("시몬스", "자사", read_simmons, "simmons.co.kr · 뷰티레스트 매트리스 · 블랙 (크롬으로 그려서 읽음)"),
    ("에이스침대", "국내 침대·매트리스", read_ace, "acebed.com · 매트리스 전체 (크롬으로 그려서 읽음)"),
    ("씰리코리아", "국내 침대·매트리스", read_sealy, "sealy.co.kr · 컬렉션 메뉴 + 공식몰 매트리스"),
    ("템퍼", "국내 침대·매트리스", read_tempur, "kr.tempur.com · 매트리스 라인"),
    ("지누스", "종합 가구", read_zinus, "zinus.co.kr · 매트리스 · 토퍼"),
    ("에몬스", "국내 침대·매트리스", read_emons, "emons.co.kr · 매트리스 네 카테고리 · 사이즈별 등록을 모델로 묶음"),
)


# ═══════════════════════════════════════════════ 수집 · 비교
def _load_snap():
    if os.path.exists(SNAP):
        try:
            return json.load(io.open(SNAP, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(path, obj):
    with _lock:
        tmp = path + ".tmp"
        json.dump(obj, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, path)


def _append(rows):
    if not rows:
        return
    with _lock:
        with io.open(LOG, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


_busy = {"on": False, "now": ""}


def collect():
    if _busy["on"]:
        return None
    _busy["on"] = True
    try:
        snap = _load_snap()
        today = datetime.date.today().isoformat()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        changes, status = [], {}
        for company, grp, reader, how in SOURCES:
            _busy["now"] = company
            t0 = time.time()
            try:
                items = reader()
                if not items:
                    raise RuntimeError("제품이 하나도 안 읽혔습니다 — 홈페이지가 바뀐 듯합니다")
            except Exception as e:
                status[company] = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:120]), "at": now,
                                   "secs": round(time.time() - t0, 1)}
                continue
            old = snap.get(company, {}).get("items", {})
            first = not old
            if not first:
                added = {pid: it for pid, it in items.items() if pid not in old}
                gone = {pid: it for pid, it in old.items() if pid not in items}
                # 번호만 바뀌고 이름이 같은 것(특가 딱지가 붙거나 떨어진 재등록)은 신제품·단종이 아니다
                gone_by_name = {_plain(it["name"]): pid for pid, it in gone.items()}
                for pid, it in list(added.items()):
                    twin = gone_by_name.get(_plain(it["name"]))
                    if twin:
                        o = gone.pop(twin)
                        added.pop(pid)
                        if o.get("price") and it.get("price") and o["price"] != it["price"]:
                            changes.append({"date": today, "company": company, "type": "price", "id": pid, "name": it["name"],
                                            "old": o["price"], "price": it["price"], "cat": it["cat"], "link": it["link"],
                                            "note": "재등록"})
                for pid, it in added.items():
                    changes.append({"date": today, "company": company, "type": "new", "id": pid, "name": it["name"],
                                    "price": it["price"], "cat": it["cat"], "link": it["link"]})
                for pid, it in items.items():
                    if pid in old and old[pid].get("price") and it.get("price") and old[pid]["price"] != it["price"]:
                        changes.append({"date": today, "company": company, "type": "price", "id": pid, "name": it["name"],
                                        "old": old[pid]["price"], "price": it["price"], "cat": it["cat"], "link": it["link"]})
                for pid, it in gone.items():
                    changes.append({"date": today, "company": company, "type": "removed", "id": pid, "name": it["name"],
                                    "price": it.get("price"), "cat": it.get("cat", ""), "link": it.get("link", "")})
            snap[company] = {"items": items, "date": now, "first": snap.get(company, {}).get("first") or today}
            status[company] = {"ok": True, "n": len(items), "at": now, "secs": round(time.time() - t0, 1),
                               "baseline": first}
            time.sleep(0.5)
        _save(SNAP, snap)
        _append(changes)
        st = {"last_run": now, "last_day": today, "changes": len(changes), "status": status}
        _save(STATE, st)
        return len(changes), [c for c in status if not status[c]["ok"]]
    finally:
        _busy["on"] = False
        _busy["now"] = ""


def collect_safe(logger=None):
    try:
        collect()
    except Exception:
        if logger:
            logger.exception("제품 현황 수집 실패")


def _state():
    if os.path.exists(STATE):
        try:
            return json.load(io.open(STATE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def data(days=30):
    snap, st = _load_snap(), _state()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    changes = []
    if os.path.exists(LOG):
        with io.open(LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("date", "") >= since:
                    changes.append(r)
    changes.sort(key=lambda r: (r["date"], r["company"]), reverse=True)
    companies = []
    for company, grp, _, how in SOURCES:
        s = snap.get(company, {})
        items = sorted((dict(v, _id=k) for k, v in s.get("items", {}).items()),
                       key=lambda i: (i.get("cat", ""), i.get("line", ""), i["name"]))
        companies.append({"company": company, "group": grp, "how": how, "n": len(items), "date": s.get("date", ""),
                          "first": s.get("first", ""), "items": items, "status": st.get("status", {}).get(company)})
    return {"companies": companies, "changes": changes, "state": st, "busy": _busy["on"], "now": _busy["now"],
            "excluded": [{"company": c, "why": w} for c, w in EXCLUDED], "chrome": bool(CHROME),
            "price_map": price_map(snap)}


BANDS = ((0, 1000000, "100만 미만"), (1000000, 2000000, "100~200만"), (2000000, 3000000, "200~300만"),
         (3000000, 5000000, "300~500만"), (5000000, 10000000, "500만~1천만"), (10000000, 10 ** 12, "1천만 이상"))


def price_map(snap):
    """회사별 표시 가격의 최저·중간·최고와 가격대별 개수. 가격이 없는 제품(상담·매장 문의)은 센 수만 적는다."""
    out = []
    for company, grp, _, _ in SOURCES:
        items = list(snap.get(company, {}).get("items", {}).values())
        prices = sorted(i["price"] for i in items if i.get("price"))
        row = {"company": company, "group": grp, "n": len(items), "n_priced": len(prices),
               "bands": [sum(1 for p in prices if lo <= p < hi) for lo, hi, _ in BANDS]}
        if prices:
            mid = len(prices) // 2
            row.update({"min": prices[0], "max": prices[-1],
                        "median": prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) // 2,
                        "cheapest": min((i for i in items if i.get("price")), key=lambda i: i["price"])["name"],
                        "dearest": max((i for i in items if i.get("price")), key=lambda i: i["price"])["name"]})
        out.append(row)
    return {"rows": out, "bands": [b[2] for b in BANDS]}


def history(company, pid):
    """한 제품의 표시 가격 이력. 첫 수집 가격부터 바뀐 날마다 한 점."""
    snap = _load_snap()
    co = snap.get(company, {})
    it = co.get("items", {}).get(pid)
    pts, name = [], it["name"] if it else ""
    if os.path.exists(LOG):
        with io.open(LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("company") != company or r.get("id") != pid:
                    continue
                name = name or r.get("name", "")
                if r["type"] == "price":
                    if not pts and r.get("old"):
                        pts.append({"date": co.get("first") or r["date"], "price": r["old"], "note": "첫 수집"})
                    pts.append({"date": r["date"], "price": r["price"], "note": r.get("note", "")})
                elif r["type"] == "new" and r.get("price"):
                    pts.append({"date": r["date"], "price": r["price"], "note": "신제품"})
                elif r["type"] == "removed":
                    pts.append({"date": r["date"], "price": r.get("price"), "note": "단종"})
    if it and not pts:
        pts.append({"date": co.get("first") or (co.get("date") or "")[:10], "price": it.get("price"), "note": "첫 수집 — 이후 변동 없음"})
    elif it and it.get("price") and pts[-1]["price"] != it["price"]:
        pts.append({"date": (co.get("date") or "")[:10], "price": it["price"], "note": "현재"})
    pts.sort(key=lambda p: p["date"])
    return {"company": company, "id": pid, "name": name, "points": pts, "first": co.get("first", "")}


# ═══════════════════════════════════════════════ 화면
PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>경쟁사 제품 현황</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" onerror="this.remove()">
<style>
:root{--ink:#0f0f11;--ink-2:#3a3a40;--mute:#84848a;--faint:#b4b4b9;--line:#e3e0d9;--line-2:#eeebe4;--paper:#fff;--bg:#f1efea;--black:#0a0a0b;--acc:#8c3325;--acc-soft:#f3e4e0;--ok:#23573f;--ok-soft:#e9f1ec}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Pretendard Variable",Pretendard,"Malgun Gothic",system-ui,sans-serif}
__NAVCSS__
.wrap{max-width:1160px;margin:0 auto;padding:44px 40px 90px}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;flex-wrap:wrap;margin-bottom:8px}
.eyebrow{font-size:11px;letter-spacing:.2em;color:var(--mute);font-weight:600}
h1{font-size:30px;font-weight:700;letter-spacing:-.02em;margin:4px 0 0}
.status{font-size:12.5px;color:var(--mute);text-align:right;line-height:1.7}
.status b{color:var(--ink-2);font-weight:600}
.status button{font:inherit;font-size:12px;padding:6px 12px;border:1px solid var(--line);background:#fff;cursor:pointer;margin-left:10px}
.status button[disabled]{color:var(--faint)}
.lead{font-size:14px;color:var(--ink-2);max-width:820px;margin:10px 0 24px;line-height:1.7}
.card{background:var(--paper);border:1px solid var(--line);padding:22px 24px;margin-bottom:20px}
.card h2{font-size:15px;font-weight:700;margin:0 0 4px}
.card .hint{font-size:12.5px;color:var(--mute);margin-bottom:14px;line-height:1.6}
/* 회사 카드들 */
.cos{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-bottom:20px}
.co{background:var(--paper);padding:16px 18px;cursor:pointer;position:relative}
.co:hover{background:#fbfaf7}
.co.on{outline:2px solid var(--black);outline-offset:-2px}
.co .n{font-size:14px;font-weight:700}
.co .c{font-size:26px;font-weight:700;letter-spacing:-.02em;margin-top:4px}
.co .c small{font-size:11px;color:var(--mute);font-weight:500;margin-left:4px}
.co .d{font-size:11px;color:var(--mute);margin-top:4px}
.co .bad{color:var(--acc);font-size:11px;margin-top:4px;line-height:1.4}
.co .delta{position:absolute;right:14px;top:14px;font-size:11px;font-weight:600;color:var(--acc)}
/* 변화 목록 */
.chg{display:grid;grid-template-columns:86px 100px 1fr auto;gap:0 14px;padding:9px 0;border-bottom:1px solid var(--line-2);align-items:baseline;font-size:13px}
.chg .d{color:var(--mute);font-size:12px;font-variant-numeric:tabular-nums}
.chg .co2{font-weight:600}
.chg a{color:var(--ink);text-decoration:none}
.chg a:hover{text-decoration:underline;text-underline-offset:3px}
.chg .p{font-size:12px;color:var(--mute);white-space:nowrap;font-variant-numeric:tabular-nums}
.tag{display:inline-block;font-size:10.5px;padding:1px 7px;border-radius:10px;margin-right:6px;vertical-align:1px}
.tag.new{background:var(--acc);color:#fff}.tag.removed{background:#e8e6e1;color:var(--ink-2)}.tag.price{background:var(--ok-soft);color:var(--ok)}
/* 제품 표 */
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{font-size:10.5px;letter-spacing:.1em;color:var(--mute);font-weight:600;text-align:left;padding:8px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid var(--line-2);vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td a{color:var(--ink);text-decoration:none}
td a:hover{text-decoration:underline;text-underline-offset:3px}
.cat{font-size:10.5px;color:var(--mute);letter-spacing:.06em}
.ex{font-size:12px;color:var(--mute);line-height:1.8}
.ex b{color:var(--ink-2);font-weight:600}
.empty{padding:34px;text-align:center;color:var(--mute);line-height:1.8}
.seg{display:inline-flex;border:1px solid var(--line);background:#fff;margin-left:auto}
.seg button{font:inherit;font-size:12px;padding:5px 11px;background:transparent;border:none;border-right:1px solid var(--line);cursor:pointer;color:var(--ink-2)}
.seg button:last-child{border-right:none}.seg button.on{background:var(--black);color:#fff}
.row{display:flex;align-items:center;gap:12px;margin-bottom:12px}
/* 가격대 지도 */
.pm{display:grid;grid-template-columns:130px 1fr 150px;gap:0 14px;align-items:center;padding:9px 0;border-bottom:1px solid var(--line-2);font-size:12.5px}
.pm .nm{font-weight:600}.pm .nm small{display:block;font-weight:400;color:var(--mute);font-size:10.5px}
.pm .rt{font-size:11.5px;color:var(--mute);text-align:right;font-variant-numeric:tabular-nums;line-height:1.45}
.pm .rt b{color:var(--ink);font-weight:600}
.pm svg{width:100%;height:28px;display:block}
.pm.us .nm{color:var(--acc)}
.axis{display:grid;grid-template-columns:130px 1fr 150px;gap:0 14px;font-size:10.5px;color:var(--faint);margin-top:4px}
.axis div:nth-child(2){display:flex;justify-content:space-between;font-variant-numeric:tabular-nums}
.bands{margin-top:18px}
.bands td,.bands th{text-align:right}
.bands td:first-child,.bands th:first-child{text-align:left}
.bands td.hot{background:#f6ebe8;font-weight:600}
tr.pick{cursor:pointer}
tr.pick:hover td{background:#fbfaf7}
tr.pick.on td{background:#f6ebe8}
.hist{margin-top:16px;border-top:1px solid var(--line);padding-top:14px}
.hist .t{font-size:13px;font-weight:600;margin-bottom:6px}
.hist svg{width:100%;height:160px;display:block;background:#fff}
.hist .pts{font-size:12px;color:var(--ink-2);margin-top:8px;display:flex;flex-wrap:wrap;gap:6px 16px}
.hist .pts span b{font-weight:600}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-bottom:22px}
.sum a{display:flex;flex-direction:column;background:var(--paper);padding:16px 20px 14px;text-decoration:none;color:inherit}
.sum a:hover{background:#fbfaf7}
.sum .k{font-size:11.5px;color:var(--mute);font-weight:600}
.sum .v{font-size:34px;font-weight:700;letter-spacing:-.03em;line-height:1.05;margin:8px 0 6px;font-variant-numeric:tabular-nums}
.sum .v small{font-size:12px;font-weight:500;color:var(--mute);margin-left:3px;letter-spacing:0}
.sum .s{font-size:12px;color:var(--ink-2);line-height:1.5}
.sum .v.ok{color:var(--ok)}
.fold{border:1px solid var(--line);background:var(--paper);font-size:12.5px;margin-top:14px}
.fold summary{cursor:pointer;list-style:none;padding:10px 16px;font-weight:600;color:var(--ink-2)}
.fold summary::-webkit-details-marker{display:none}
.fold summary::before{content:"▸ ";font-size:10px;color:var(--mute)}
.fold[open] summary::before{content:"▾ "}
.fold .in{padding:0 16px 14px}
@media print{.status button,.act,.tabs,.fold,.seg,.lead{display:none!important}.wrap{padding:0}body{background:#fff}.card{border:none;padding:0 0 18px;break-inside:avoid}}
@media(max-width:900px){.wrap{padding:28px 16px 70px}.chg{grid-template-columns:70px 1fr;}.chg .p{display:none}}
</style></head><body>
__NAV__
<div class="wrap">
<div class="head">
  <div><div class="eyebrow">시몬스 연구소</div><h1>경쟁사 제품 현황</h1></div>
  <div class="status" id="status"></div>
</div>
<div class="lead">경쟁사 홈페이지의 매트리스 목록을 매일 읽어 어제와 비교합니다. 보도자료 없이 조용히 올라오는 제품도 여기서 잡힙니다.</div>

<div class="sum" id="sum"></div>
<div class="hint" style="font-size:12.5px;color:var(--mute);margin:-10px 0 8px">회사를 누르면 아래에 지금 올라와 있는 제품 목록이 보입니다.</div>
<div class="cos" id="cos"></div>

<div class="card"><h2>가격대 비교</h2><div class="hint">막대 왼쪽 끝이 가장 싼 제품, 오른쪽 끝이 가장 비싼 제품, 검은 선이 중간값입니다.</div>
  <div id="pmap"></div>
  <div class="bands" id="bands"></div></div>

<div class="card"><div class="row"><div><h2>최근 변화</h2><div class="hint" style="margin:0">신제품 · 단종 · 가격 변동. 첫 수집은 기준선이라 여기 나오지 않습니다.</div></div>
  <span class="seg" id="days"><button data-d="7">7일</button><button data-d="30" class="on">30일</button><button data-d="90">90일</button></span></div>
  <div id="changes"></div></div>

<div class="card"><h2 id="lineupT">제품 목록</h2><div class="hint" id="lineupH">위에서 회사를 고르면 지금 홈페이지에 올라와 있는 제품이 보입니다. 제품 줄을 누르면 가격이 언제 어떻게 바뀌었는지 아래에 그려집니다.</div><div id="lineup"></div><div class="hist" id="hist" style="display:none"></div></div>

<details class="fold"><summary>읽지 않는 홈페이지와 그 이유</summary><div class="in ex" id="ex"></div></details>
</div>
<script>
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
let D=null, PICK=null, DAYS=30, HPICK=null;
const man=n=>n==null?'':(n>=10000000?(n/10000000).toFixed(n%10000000?1:0)+'천만':Math.round(n/10000)+'만');
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
const won=n=>n==null?'':n.toLocaleString()+'원';
async function load(){ D=await (await fetch('/제품/data?days='+DAYS)).json(); if(!PICK&&D.companies.length) PICK=D.companies[0].company; render(); }
function renderPriceMap(){
  const P=D.price_map; const rows=P.rows; const mx=Math.max(...rows.filter(r=>r.max).map(r=>r.max),1);
  const X=v=>(v/mx*100).toFixed(2);
  $('#pmap').innerHTML=rows.map(r=>`<div class="pm ${r.company==='시몬스'?'us':''}"><div class="nm">${esc(r.company)}<small>${r.n}개 중 가격 표시 ${r.n_priced}개</small></div>
    <div>${r.n_priced?`<svg viewBox="0 0 100 28" preserveAspectRatio="none"><line x1="0" y1="14" x2="100" y2="14" stroke="#eeebe4" stroke-width="1"/>
      <rect x="${X(r.min)}" y="7" width="${Math.max(0.6,(r.max-r.min)/mx*100).toFixed(2)}" height="14" fill="${r.company==='시몬스'?'#8c3325':'#c9c4ba'}" opacity=".9"/>
      <line x1="${X(r.median)}" y1="3" x2="${X(r.median)}" y2="25" stroke="#0f0f11" stroke-width="1.2"/></svg>`:`<span style="font-size:11.5px;color:var(--faint)">가격을 표시하지 않음</span>`}</div>
    <div class="rt">${r.n_priced?`<b>${man(r.min)} ~ ${man(r.max)}원</b><br>중간 ${man(r.median)}원`:''}</div></div>`).join('')
    +`<div class="axis"><div></div><div><span>0</span><span>${man(mx/2)}</span><span>${man(mx)}원</span></div><div></div></div>`;
  const priced=rows.filter(r=>r.n_priced);
  $('#bands').innerHTML=priced.length?`<table><tr><th>가격대</th>${priced.map(r=>`<th>${esc(r.company)}</th>`).join('')}</tr>${P.bands.map((b,i)=>`<tr><td>${b}</td>${priced.map(r=>{const v=r.bands[i]; const hot=v&&v===Math.max(...r.bands); return `<td class="${hot?'hot':''}">${v||'<span style="color:var(--faint)">·</span>'}</td>`;}).join('')}</tr>`).join('')}</table>
    <div class="hint" style="margin:8px 0 0">진한 칸이 그 회사 제품이 가장 많이 몰린 가격대입니다. 가장 싼 제품: ${priced.map(r=>`${esc(r.company)} ${esc(r.cheapest)}`).join(' · ')}.</div>`:'';
}
async function showHist(tr){
  HPICK=tr.dataset.link; $$('tr.pick').forEach(x=>x.classList.toggle('on',x===tr));
  const co=D.companies.find(c=>c.company===PICK); const it=co.items.find(i=>i.link===HPICK); const pid=it&&it._id;
  const H=await (await fetch(`/제품/이력?company=${encodeURIComponent(PICK)}&id=${encodeURIComponent(pid||'')}&link=${encodeURIComponent(HPICK)}`)).json();
  const box=$('#hist'); box.style.display='block';
  const pts=H.points.filter(p=>p.price);
  if(!pts.length){ box.innerHTML=`<div class="t">${esc(H.name||tr.dataset.name)}</div><div class="hint" style="margin:0">이 제품은 가격을 표시하지 않아 이력이 없습니다.</div>`; return; }
  const lo=Math.min(...pts.map(p=>p.price)), hi=Math.max(...pts.map(p=>p.price)); const pad=(hi-lo)||hi*0.1;
  const d0=new Date(pts[0].date), d1=new Date(pts[pts.length-1].date); const span=Math.max(1,(d1-d0)/864e5);
  const X=p=>8+((new Date(p.date)-d0)/864e5)/span*84, Y=p=>128-((p.price-(lo-pad*0.3))/(pad*1.6))*110;
  let path=''; pts.forEach((p,i)=>{ path+=(i?'L':'M')+X(p).toFixed(2)+' '+Y(p).toFixed(2)+' '; if(i<pts.length-1) path+='L'+X(pts[i+1]).toFixed(2)+' '+Y(p).toFixed(2)+' '; });
  box.innerHTML=`<div class="t">${esc(H.name)} · 표시 가격 이력 <span style="font-weight:400;color:var(--mute);font-size:12px">${pts.length>1?`${pts.length-1}번 바뀜`:'아직 바뀐 적 없음'}${H.first?` · 첫 수집 ${esc(H.first)}`:''}</span></div>
    <svg viewBox="0 0 100 140" preserveAspectRatio="none"><path d="${path}" fill="none" stroke="#8c3325" stroke-width="1.2" vector-effect="non-scaling-stroke"/>
      ${pts.map(p=>`<circle cx="${X(p).toFixed(2)}" cy="${Y(p).toFixed(2)}" r="1.4" fill="#8c3325"/>`).join('')}</svg>
    <div class="pts">${pts.map(p=>`<span>${esc(p.date.slice(5).replace('-','.'))} <b>${won(p.price)}</b>${p.note?` <small style="color:var(--mute)">${esc(p.note)}</small>`:''}</span>`).join('')}</div>
    <div class="hint" style="margin:8px 0 0">홈페이지에 표시된 가격 기준이며 할인 전 정가인지 행사가인지는 구분하지 않습니다. 매일 한 번 읽으므로 하루 안의 변동은 보이지 않습니다.</div>`;
}
function render(){
  const st=D.state||{};
  $('#status').innerHTML=`${D.busy?`<b>읽는 중…</b> ${esc(D.now)}`:st.last_run?`마지막 확인 <b>${esc(st.last_run)}</b> · 변화 ${st.changes??0}건`:'아직 한 번도 읽지 않았습니다'}
    <button id="run" ${D.busy?'disabled':''}>지금 갱신</button>`;
  const n={new:0,removed:0,price:0}; D.changes.forEach(c=>n[c.type]=(n[c.type]||0)+1);
  const tracked=D.companies.reduce((a,c)=>a+c.n,0), okCos=D.companies.filter(c=>!(c.status&&c.status.ok===false));
  const per={7:'지난 7일',30:'지난 30일',90:'지난 90일'}[DAYS]||'';
  $('#sum').innerHTML=`
    <a href="#changes"><span class="k">신제품 · ${per}</span><span class="v">${n.new}<small>건</small></span><span class="s">${n.new?[...new Set(D.changes.filter(c=>c.type==='new').map(c=>c.company))].join(' · '):'새로 올라온 제품이 없습니다'}</span></a>
    <a href="#changes"><span class="k">단종 · ${per}</span><span class="v">${n.removed}<small>건</small></span><span class="s">${n.removed?'홈페이지에서 내려간 제품':'내려간 제품이 없습니다'}</span></a>
    <a href="#changes"><span class="k">가격 변동 · ${per}</span><span class="v">${n.price}<small>건</small></span><span class="s">${n.price?'표시 가격이 바뀐 제품':'표시 가격 변동이 없습니다'}</span></a>
    <a href="#cos"><span class="k">추적 중</span><span class="v">${tracked}<small>개 제품</small></span><span class="s">${okCos.length}개사 정상 읽음${okCos.length<D.companies.length?` · ${D.companies.length-okCos.length}개사 읽기 실패`:''}</span></a>`;
  const recent=new Set(D.changes.filter(c=>c.type==='new').map(c=>c.company));
  $('#cos').innerHTML=D.companies.map(c=>{const s=c.status||{}; const nNew=D.changes.filter(x=>x.company===c.company&&x.type==='new').length;
    return `<div class="co ${PICK===c.company?'on':''}" data-c="${esc(c.company)}"><div class="n">${esc(c.company)}</div>
      <div class="c">${c.n}<small>개</small></div>
      ${nNew?`<div class="delta">신제품 +${nNew}</div>`:''}
      ${s.ok===false?`<div class="bad">읽기 실패 · ${esc(s.error||'')}</div>`:`<div class="d">${c.date?esc(c.date.slice(5)):'미확인'}${s.baseline?' · 기준선':''}</div>`}</div>`;}).join('');
  if(!D.changes.length) $('#changes').innerHTML=`<div class="empty">${st.last_run?'이 기간에 변화가 없습니다.':'«지금 갱신» 을 누르면 오늘 목록을 기준선으로 저장합니다. 변화는 내일부터 보입니다.'}</div>`;
  else $('#changes').innerHTML=D.changes.map(c=>`<div class="chg"><span class="d">${c.date.slice(5).replace('-','.')}</span><span class="co2">${esc(c.company)}</span>
      <span><span class="tag ${c.type}">${{new:'신제품',removed:'단종',price:'가격'}[c.type]}</span><a href="${esc(c.link)}" target="_blank" rel="noopener">${esc(c.name)}</a> <span class="cat">${esc(c.cat||'')}</span></span>
      <span class="p">${c.type==='price'?`${won(c.old)} → <b>${won(c.price)}</b>`:won(c.price)}</span></div>`).join('');
  renderPriceMap();
  const co=D.companies.find(c=>c.company===PICK);
  if(co){ $('#lineupT').textContent=`${co.company} · 제품 ${co.n}개`; $('#lineupH').textContent=`${co.how}${co.date?` · ${co.date} 기준`:''}`;
    const newIds=new Set(D.changes.filter(x=>x.company===PICK&&x.type==='new').map(x=>x.id));
    $('#lineup').innerHTML=co.items.length?`<div style="overflow-x:auto"><table><tr><th>구분</th><th>제품</th><th>시리즈·등급</th><th>사이즈</th><th class="n">표시 가격</th></tr>
      ${co.items.map(i=>{const pid=Object.keys(co.items).length&&i._id||''; return `<tr class="pick ${HPICK===i.link?'on':''}" data-link="${esc(i.link)}" data-name="${esc(i.name)}"><td class="cat">${esc(i.cat)}</td><td><a href="${esc(i.link)}" target="_blank" rel="noopener">${esc(i.name)}</a></td><td>${esc(i.line)}</td><td>${esc(i.sizes)}</td><td class="n">${won(i.price)||'—'}</td></tr>`;}).join('')}</table></div>`:`<div class="empty">아직 읽은 목록이 없습니다.</div>`; }
  $('#ex').innerHTML=D.excluded.map(e=>`<b>${esc(e.company)}</b> — ${esc(e.why)}`).join('<br>')+(D.chrome?'':'<br><b style="color:var(--acc)">이 PC에 크롬이 없어 시몬스·에이스는 읽지 못합니다.</b>');
}
document.addEventListener('click',async e=>{
  const co=e.target.closest('.co'); if(co){ PICK=co.dataset.c; HPICK=null; $('#hist').style.display='none'; render(); return; }
  const tr=e.target.closest('tr.pick'); if(tr&&!e.target.closest('a')){ showHist(tr); return; }
  const b=e.target.closest('#days button'); if(b){ DAYS=+b.dataset.d; $$('#days button').forEach(x=>x.classList.toggle('on',x===b)); load(); return; }
  if(e.target.closest('#run')){ e.target.disabled=true; e.target.textContent='읽는 중… (1~2분)'; await fetch('/제품/수집',{method:'POST'}); setTimeout(load,800); }
});
load(); setInterval(()=>{ if(D&&D.busy) load(); },5000);
</script></body></html>"""


def page(build=""):
    import portal
    return PAGE.replace("__NAV__", portal.nav("/제품", "", build)).replace("__NAVCSS__", portal.NAV_CSS)
