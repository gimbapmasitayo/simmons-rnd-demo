# -*- coding: utf-8 -*-
"""R&D 동향 — 세 탭.

  1. 신제품 보드   : 뉴스 클리핑에서 «신제품·기술» 태그가 붙은 기사를 회사 × 월 격자로.
  2. 규격·인증 감시 : 법제처 API 로 우리 시험과 얽힌 법령·고시의 공포/시행일을 매일 비교해 바뀌면 알리고,
                     국가기술표준원 공지·공고/보도자료와 규격 관련 뉴스 중 침대·매트리스·생활용품에 닿는 것만 모은다.
  3. 특허 동향     : KIPRIS Plus API 로 경쟁사 출원을 모아 출원인 × 월 격자와 목록으로. 열쇠(ServiceKey)가 필요하다.

수집은 뉴스 스케줄러에 얹혀 평일 8시에 같이 돈다. 기록은 동향기록.jsonl, 법령 스냅샷은 규격상태.json,
★·메모는 동향표시.json, KIPRIS 열쇠는 특허설정.json. 검색어와 출원인 이름만 바깥에 보내고 사내 자료는 보내지 않는다.
"""
import os, io, re, json, time, html, hashlib, datetime, threading
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET

import news

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "동향기록.jsonl")
LAWSTATE = os.path.join(HERE, "규격상태.json")
MARKS = os.path.join(HERE, "동향표시.json")
PATSET = os.path.join(HERE, "특허설정.json")
STATE = os.path.join(HERE, "동향상태.json")
_lock = threading.Lock()
TIMEOUT = 20
UA = {"User-Agent": "Mozilla/5.0 (R&D trend watch)"}

# ═══════════════════════════════════════════════ 규격·인증 — 지켜볼 법령·고시
# (법제처 target, 검색어, 화면 이름, 왜 보는지)
WATCH_LAWS = (
    ("law", "생활주변방사선 안전관리법", "생활주변방사선 안전관리법 (법·시행령·시행규칙)", "라돈·토론 성적서의 근거"),
    ("law", "전기용품 및 생활용품 안전관리법", "전기용품 및 생활용품 안전관리법 (법·시행령·시행규칙)", "KC 안전기준의 모법"),
    ("admrul", "안전기준준수대상생활용품의 안전기준", "안전기준준수대상 생활용품의 안전기준 (고시)", "부속서 19 침대 매트리스 — KC 성적서"),
    ("admrul", "공급자적합성확인대상생활용품의 안전기준", "공급자적합성확인대상 생활용품의 안전기준 (고시)", "가구류"),
    ("admrul", "어린이제품 공통안전기준", "어린이제품 공통안전기준 (고시)", "어린이 침대·매트리스"),
    ("admrul", "가공제품 안전기준", "가공제품 안전기준 (원안위 고시)", "라돈 가공제품 기준"),
)
REG_KEYS = ("침대", "매트리스", "가구", "생활용품", "안전기준", "KS G", "라돈", "방사선", "어린이제품",
            "스프링", "안전확인", "공급자적합성", "안전기준준수")   # KOLAS·ISO·인사 공고 같은 일반 공지는 뺀다
REG_NEWS_QUERIES = ("매트리스 안전기준", "침대 KC 인증", "KS 개정 가구", "라돈 침대 규제", "생활용품 안전기준 개정",
                    "국가기술표준원 매트리스", "매트리스 리콜")
KATS_BOARDS = (("13", "국가기술표준원 공지·공고"), ("240", "국가기술표준원 보도자료"))

# ═══════════════════════════════════════════════ 특허 — 출원인
APPLICANTS = ("시몬스", "에이스침대", "씰리코리아", "템퍼", "코웨이", "지누스", "한샘", "에몬스", "바디프랜드",
              "청호나이스", "교원", "현대리바트", "퍼시스", "일룸", "삼분의일", "슬로우")
PAT_KEYS = ("매트리스", "침대", "스프링", "토퍼", "수면", "쿠션", "폼", "라텍스", "베개", "침구", "안마")


def _fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    return urllib.request.urlopen(req, timeout=TIMEOUT).read()


def _jl_load(path):
    if not os.path.exists(path):
        return []
    out = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def _json_load(path, default):
    if os.path.exists(path):
        try:
            return json.load(io.open(path, encoding="utf-8"))
        except Exception:
            pass
    return default


def _json_save(path, obj):
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


def _key(*parts):
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:16]


# ═══════════════════════════════════════════════ 1. 신제품 보드 (뉴스에서)
def board(months=6):
    today = datetime.date.today()
    cols = []
    y, m = today.year, today.month
    for _ in range(months):
        cols.append("%04d-%02d" % (y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    cols.reverse()
    hidden = {k for k, v in news.marks().items() if v.get("hide")}
    picked = [dict(r) for r in news.load()
              if "신제품·기술" in r.get("tags", []) and r["group"] != "업계" and r["key"] not in hidden
              and (r.get("date") or r.get("fetched") or "")[:7] in cols]
    rows = {}
    for r in news.cluster(picked):          # 한 보도자료가 매체 수만큼 세어지지 않게
        mon = (r.get("date") or r.get("fetched") or "")[:7]
        rows.setdefault(r["company"], {c: [] for c in cols})[mon].append(
            {"title": r["title"], "link": r["link"], "source": r["source"] + (" 외 %d곳" % (r["n_src"] - 1) if r["n_src"] > 1 else ""),
             "date": r.get("date", ""), "key": r["key"]})
    # 홈페이지에서 확인된 신제품 (경쟁사 제품 현황) 도 같은 격자에 올린다 — 보도 없이 나온 제품이 여기서 보인다
    try:
        import products
        NAME = {"템퍼": "템퍼코리아"}
        for ch in products.data(days=months * 31)["changes"]:
            if ch["type"] != "new":
                continue
            mon = ch["date"][:7]
            if mon not in cols:
                continue
            co = NAME.get(ch["company"], ch["company"])
            rows.setdefault(co, {c: [] for c in cols})[mon].append(
                {"title": ch["name"] + ("  ·  " + ch["cat"] if ch.get("cat") else ""), "link": ch["link"],
                 "source": "홈페이지", "date": ch["date"], "key": "p" + ch["id"]})
    except Exception:
        pass
    known = [c for _, c, _, _ in news.COMPANIES]
    order = [c for c in known if c in rows] + [c for c in rows if c not in known]
    # 자료가 없는 앞쪽 달은 보이지 않는다 (수집 시작 전이라 비어 있을 뿐이다). 최소 3개월은 둔다.
    used = [m for m in cols if any(rows[c][m] for c in order)]
    if used:
        first = min(cols.index(used[0]), len(cols) - 3)
        cols = cols[first:]
    return {"months": cols, "companies": order,
            "cells": {c: {mo: rows[c][mo] for mo in cols} for c in order},
            "groups": {c: g for g, c, _, _ in news.COMPANIES}}


# ═══════════════════════════════════════════════ 2. 규격·인증 감시
def _law_search(target, q):
    url = ("https://www.law.go.kr/DRF/lawSearch.do?OC=test&target=%s&type=XML&display=20&query=%s"
           % (target, urllib.parse.quote(q)))
    root = ET.fromstring(_fetch(url))
    out = []
    for it in root:
        if it.tag not in ("law", "admrul"):
            continue
        g = lambda t: (it.findtext(t) or "").strip()
        name = g("법령명한글") or g("행정규칙명")
        if not name or q.replace(" ", "")[:6] not in name.replace(" ", ""):
            continue
        link = g("법령상세링크") or g("행정규칙상세링크")
        out.append({"name": name, "kind": g("법령구분명") or g("행정규칙종류"),
                    "promul": g("공포일자") or g("발령일자"), "enforce": g("시행일자"),
                    "change": g("제개정구분명"), "ministry": g("소관부처명"),
                    "link": ("https://www.law.go.kr" + html.unescape(link)) if link.startswith("/") else link})
    return out


def collect_laws():
    """법령·고시의 공포/시행일을 지난번과 비교. 달라진 것은 기록에 «law_change» 로 남긴다."""
    snap = _json_load(LAWSTATE, {})
    changes, errors, seen_now = [], [], {}
    for target, q, label, why in WATCH_LAWS:
        try:
            found = _law_search(target, q)
        except Exception as e:
            errors.append("%s: %s" % (label, type(e).__name__))
            continue
        for f in found:
            f["label"], f["why"] = label, why
            seen_now[f["name"]] = f
            old = snap.get(f["name"])
            if old and (old.get("promul") != f["promul"] or old.get("enforce") != f["enforce"]):
                changes.append({"key": _key("law", f["name"], f["promul"], f["enforce"]), "type": "law_change",
                                "title": "%s — %s (공포 %s · 시행 %s)" % (f["name"], f["change"] or "개정", _d(f["promul"]), _d(f["enforce"])),
                                "detail": "이전: 공포 %s · 시행 %s" % (_d(old.get("promul")), _d(old.get("enforce"))),
                                "link": f["link"], "source": "법제처", "date": datetime.date.today().isoformat(),
                                "why": why, "fetched": _now()})
    if seen_now:
        snap.update(seen_now)
        snap["_checked"] = _now()
        _json_save(LAWSTATE, snap)
    return changes, errors


def _d(s):
    s = s or ""
    return "%s.%s.%s" % (s[:4], s[4:6], s[6:8]) if len(s) == 8 else (s or "-")


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def collect_kats():
    rows, errors = [], []
    for cmsid, label in KATS_BOARDS:
        for page in (1, 2):
            try:
                t = _fetch("https://www.kats.go.kr/content.do?cmsid=%s&page=%d" % (cmsid, page)).decode("utf-8", "replace")
            except Exception as e:
                errors.append("%s: %s" % (label, type(e).__name__))
                break
            # 일반 글: 제목 칸 다음에 등록일 칸. 상단 고정 «공지» 글은 날짜 칸이 없어 오늘 날짜로 둔다
            pat = r'<a href="(/content\.do\?cmsid=%s&amp;mode=view[^"]*)">(.*?)</a>(?:\s*</strong>)?\s*</td>(?:\s*<td\s*>\s*(\d{4}-\d{2}-\d{2}))?' % cmsid
            for m in re.finditer(pat, t, re.S):
                link, title, date = m.groups()
                date = date or datetime.date.today().isoformat()
                title = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title))).strip()
                if not any(k in title for k in REG_KEYS):
                    continue
                rows.append({"key": _key("kats", title, date), "type": "kats", "title": title,
                             "link": "https://www.kats.go.kr" + html.unescape(link), "source": label,
                             "date": date, "fetched": _now()})
    return rows, errors


def collect_regnews():
    rows, errors = [], []
    fetch = news._fetch_naver if news.active_source() == "naver" else news._fetch_rss
    for q in REG_NEWS_QUERIES:
        try:
            for a in fetch(q):
                t = a["title"]
                if not t or any(d in t for d in news.DROP):
                    continue
                if not any(k in t for k in ("매트리스", "침대", "가구", "생활용품", "라돈", "KS", "KC", "안전기준", "인증", "리콜")):
                    continue
                rows.append({"key": _key("regnews", news._norm(t)[:60]), "type": "regnews", "title": t,
                             "link": a["link"], "source": a["source"], "date": a["date"], "fetched": _now()})
        except Exception as e:
            errors.append("규격 뉴스 «%s»: %s" % (q, type(e).__name__))
        time.sleep(0.2)
    return rows, errors


# ═══════════════════════════════════════════════ 3. 특허 (KIPRIS Plus)
def pat_settings():
    """열쇠는 .env 의 KIPRIS_SERVICE_KEY. 옛 특허설정.json 에 남은 값은 .env 에 없을 때만 쓴다."""
    import config
    key = config.get("KIPRIS_SERVICE_KEY") or _json_load(PATSET, {}).get("service_key", "")
    return {"service_key": (key or "").strip()}


def save_pat_settings(patch):
    import config
    if "service_key" in patch:
        config.set_many({"KIPRIS_SERVICE_KEY": str(patch["service_key"] or "").strip()})
        if os.path.exists(PATSET):
            _json_save(PATSET, {"service_key": ""})      # JSON 에는 더 이상 열쇠를 두지 않는다
    return pat_settings()


def has_pat_key():
    return bool(pat_settings().get("service_key"))


def _kipris(applicant):
    key = pat_settings()["service_key"]
    url = ("https://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getAdvancedSearch"
           "?applicant=%s&patent=true&utility=true&numOfRows=100&pageNo=1&sortSpec=AD&descSort=true&ServiceKey=%s"
           % (urllib.parse.quote(applicant), key if "%" in key else urllib.parse.quote(key, safe="")))
    data = _fetch(url)
    root = ET.fromstring(data)
    code = root.findtext(".//resultCode") or root.findtext(".//header/resultCode") or ""
    msg = root.findtext(".//resultMsg") or ""
    if code not in ("", "00") and "SERVICE_KEY" in (msg or "").upper():
        raise RuntimeError("KIPRIS 열쇠 오류: %s — KIPRIS Plus 에서 «특허 상세검색 서비스» 신청이 승인됐는지, "
                           "열쇠를 통째로 붙여넣었는지 확인하세요" % msg)
    out = []
    for it in root.iter("item"):
        g = lambda t: (it.findtext(t) or "").strip()
        title = g("inventionTitle")
        if not title:
            continue
        ad = g("applicationDate")
        out.append({"title": title, "applicant": g("applicantName") or applicant, "status": g("registerStatus"),
                    "app_no": g("applicationNumber"), "app_date": "%s-%s-%s" % (ad[:4], ad[4:6], ad[6:8]) if len(ad) == 8 else ad,
                    "ipc": g("ipcNumber"), "abstract": g("astrtCont")[:300],
                    "link": "https://doi.org/10.8080/%s" % g("applicationNumber") if g("applicationNumber") else ""})
    return out


def collect_patents():
    if not has_pat_key():
        return [], []          # 열쇠가 없는 건 오류가 아니다 — 화면이 안내한다
    rows, errors = [], []
    for ap in APPLICANTS:
        try:
            for p in _kipris(ap):
                if not any(k in p["title"] for k in PAT_KEYS):
                    continue
                rows.append({"key": _key("pat", p["app_no"] or p["title"]), "type": "patent", "title": p["title"],
                             "link": p["link"], "source": p["applicant"], "applicant_q": ap, "date": p["app_date"],
                             "status": p["status"], "ipc": p["ipc"], "abstract": p["abstract"], "fetched": _now()})
        except Exception as e:
            errors.append("%s: %s" % (ap, str(e)[:80] or type(e).__name__))
            if "열쇠" in str(e):
                break
        time.sleep(0.3)
    return rows, errors


# ═══════════════════════════════════════════════ 전체 수집
_busy = {"on": False, "now": ""}


def collect():
    if _busy["on"]:
        return None
    _busy["on"] = True
    try:
        seen = {r["key"] for r in _jl_load(LOG)}
        new, errors = [], []
        for name, fn in (("법령", collect_laws), ("국가기술표준원", collect_kats), ("규격 뉴스", collect_regnews), ("특허", collect_patents)):
            _busy["now"] = name
            rows, errs = fn()
            errors += errs
            for r in rows:
                if r["key"] not in seen:
                    seen.add(r["key"])
                    new.append(r)
        _append(new)
        st = _json_load(STATE, {})
        st.update({"last_run": _now(), "last_new": len(new), "last_errors": errors[:20],
                   "last_day": datetime.date.today().isoformat()})
        _json_save(STATE, st)
        return len(new), errors
    finally:
        _busy["on"] = False
        _busy["now"] = ""


def collect_safe(logger=None):
    try:
        collect()
        errs = _json_load(STATE, {}).get("last_errors") or []
        if errs and logger:
            logger.warning("동향 수집 오류 %d건: %s", len(errs), " | ".join(errs))   # 상세는 로그로만
    except Exception:
        if logger:
            logger.exception("동향 수집 실패")


# ═══════════════════════════════════════════════ 표시 · 조회
def marks():
    return _json_load(MARKS, {})


def set_mark(key, star=None, memo=None, hide=None):
    m = marks()
    cur = m.get(key, {})
    if star is not None:
        cur["star"] = bool(star)
    if memo is not None:
        cur["memo"] = str(memo)[:300]
    if hide is not None:
        cur["hide"] = bool(hide)
    m[key] = cur
    _json_save(MARKS, m)
    return cur


def regs(days=90):
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    m = marks()
    rows = []
    for r in _jl_load(LOG):
        if r["type"] == "patent":
            continue
        if (r.get("date") or r.get("fetched") or "")[:10] < since and r["type"] != "law_change":
            continue
        mk = m.get(r["key"], {})
        if mk.get("hide"):
            continue
        rr = dict(r)
        rr["star"], rr["memo"] = bool(mk.get("star")), mk.get("memo", "")
        rows.append(rr)
    rows.sort(key=lambda r: (r["type"] != "law_change", (r.get("date") or "")), reverse=False)
    rows.sort(key=lambda r: (r.get("date") or r.get("fetched") or ""), reverse=True)
    snap = _json_load(LAWSTATE, {})
    laws = [dict(v, promul_d=_d(v.get("promul")), enforce_d=_d(v.get("enforce")))
            for k, v in snap.items() if not k.startswith("_")]
    laws.sort(key=lambda v: (v["label"], v["name"]))
    return {"rows": rows[:300], "laws": laws, "checked": snap.get("_checked", ""),
            "watch": [{"label": l, "why": w} for _, _, l, w in WATCH_LAWS]}


# IPC 메인그룹 → 쉬운 말. 여기 없는 것은 코드 그대로 보인다.
IPC_LABELS = {
    "A47C 27": "매트리스 (스프링·폼·충전재)", "A47C 23": "스프링 바닥·침대 베이스", "A47C 21": "침대 부속 (난방·환기·조절)",
    "A47C 19": "침대 프레임", "A47C 20": "머리·발 받침, 조절 침대", "A47C 31": "가구 세부 (커버·센서)",
    "A47C 7": "의자 시트·등받이", "A47C 17": "소파베드", "A47G 9": "베개·이불·침구",
    "B68G": "충전재·쿠션 제조", "B68G 7": "충전재 가공", "F16F": "스프링·완충", "F16F 1": "코일 스프링",
    "D04B": "편직 원단", "D03D": "직물", "D06M": "섬유 처리 (항균·난연)", "B32B": "적층 소재",
    "C08G 18": "폴리우레탄 폼", "C08J 9": "발포체", "C08L": "고분자 조성",
    "A61B 5": "생체 신호 측정 (수면·호흡·심박)", "A61M 21": "수면 유도", "G16H": "헬스케어 정보", "G06Q": "서비스·사업 방법",
    "H04L": "통신", "G08B": "알림·경보", "A61G 7": "의료용 침대", "A61H": "마사지·물리치료",
    "A47B": "테이블·수납 가구", "B60N": "차량 시트",
}


def _ipc_group(code):
    """'A47C 27/06' → 'A47C 27'. 여럿이면 첫 것."""
    c = re.split(r"[|,;]", code or "")[0].strip()
    m = re.match(r"([A-H]\d{2}[A-Z])\s*(\d+)?", c)
    if not m:
        return ""
    return (m.group(1) + " " + m.group(2)) if m.group(2) else m.group(1)


def ipc_label(g):
    if g in IPC_LABELS:
        return IPC_LABELS[g]
    sub = g.split(" ")[0]
    return IPC_LABELS.get(sub, "")


def patents(months=12):
    today = datetime.date.today()
    cols, y, mth = [], today.year, today.month
    for _ in range(months):
        cols.append("%04d-%02d" % (y, mth))
        mth -= 1
        if mth == 0:
            y, mth = y - 1, 12
    cols.reverse()
    m = marks()
    rows, grid = [], {}
    for r in _jl_load(LOG):
        if r["type"] != "patent" or m.get(r["key"], {}).get("hide"):
            continue
        rr = dict(r)
        rr["star"], rr["memo"] = bool(m.get(r["key"], {}).get("star")), m.get(r["key"], {}).get("memo", "")
        rows.append(rr)
        mon = (r.get("date") or "")[:7]
        if mon in cols:
            grid.setdefault(r["applicant_q"], {c: 0 for c in cols})[mon] += 1
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    # 출원인 × IPC 분야 — 누가 어느 기술에 힘을 주는지
    ipc = {}
    for r in rows:
        g = _ipc_group(r.get("ipc", ""))
        if g:
            ipc.setdefault(r["applicant_q"], {}).setdefault(g, 0)
            ipc[r["applicant_q"]][g] += 1
    tot = {}
    for a, d in ipc.items():
        for g, n in d.items():
            tot[g] = tot.get(g, 0) + n
    top = sorted(tot, key=lambda g: -tot[g])[:8]
    focus = {a: max(d, key=d.get) for a, d in ipc.items()}
    return {"rows": rows[:300], "months": cols, "grid": grid,
            "applicants": [a for a in APPLICANTS if a in grid], "has_key": has_pat_key(),
            "ipc": {"groups": [{"code": g, "label": ipc_label(g), "n": tot[g]} for g in top],
                    "by": {a: {g: ipc[a].get(g, 0) for g in top} for a in ipc},
                    "focus": {a: {"code": g, "label": ipc_label(g), "n": ipc[a][g], "share": round(100.0 * ipc[a][g] / sum(ipc[a].values()))}
                              for a, g in focus.items()},
                    "other": {a: sum(n for g, n in d.items() if g not in top) for a, d in ipc.items()}}}


def data():
    st = _json_load(STATE, {})
    return {"board": board(), "regs": regs(), "patents": patents(), "state": st,
            "busy": _busy["on"], "now": _busy["now"], "news_source": news.active_source()}


# ═══════════════════════════════════════════════ 화면
PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R&D 동향</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" onerror="this.remove()">
<style>
:root{--ink:#0f0f11;--ink-2:#3a3a40;--mute:#84848a;--faint:#b4b4b9;--line:#e3e0d9;--line-2:#eeebe4;--paper:#fff;--bg:#f1efea;--black:#0a0a0b;--acc:#8c3325;--acc-soft:#f3e4e0;--ok:#23573f}
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
.lead{font-size:14px;color:var(--ink-2);max-width:800px;margin:10px 0 24px;line-height:1.7}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin-bottom:22px}
.tabs button{font:inherit;font-size:14px;font-weight:600;padding:12px 18px;background:none;border:none;border-bottom:2px solid transparent;margin-bottom:-1px;cursor:pointer;color:var(--mute)}
.tabs button.on{color:var(--ink);border-bottom-color:var(--acc)}
.tabs button .n{font-size:11px;color:var(--faint);margin-left:6px;font-weight:500}
.card{background:var(--paper);border:1px solid var(--line);padding:22px 24px;margin-bottom:20px}
.card h2{font-size:15px;font-weight:700;margin:0 0 4px}
.card .hint{font-size:12.5px;color:var(--mute);margin-bottom:14px;line-height:1.6}
/* 격자 */
.gridwrap{overflow-x:auto}
table.g{border-collapse:collapse;width:100%;font-size:12.5px}
table.g th{font-size:10.5px;letter-spacing:.1em;color:var(--mute);font-weight:600;padding:8px 10px;border-bottom:1px solid var(--line);text-align:center;white-space:nowrap}
table.g th:first-child{text-align:left}
table.g td{padding:6px 8px;border-bottom:1px solid var(--line-2);text-align:center;vertical-align:middle}
table.g td:first-child{text-align:left;font-weight:600;white-space:nowrap}
table.g td:first-child small{display:block;font-weight:400;color:var(--faint);font-size:10.5px}
.cell{display:inline-flex;align-items:center;justify-content:center;min-width:34px;height:30px;padding:0 8px;border-radius:3px;cursor:pointer;font-weight:600;font-variant-numeric:tabular-nums}
.cell.c1{background:#f6ebe8;color:var(--acc)}.cell.c2{background:#eccfc8;color:var(--acc)}.cell.c3{background:var(--acc);color:#fff}
.cell:hover{outline:2px solid var(--acc);outline-offset:-2px}
.cell.on{outline:2px solid var(--black);outline-offset:-2px}
.sub{margin-top:16px;border-top:1px solid var(--line)}
.sub .t{font-size:12.5px;font-weight:600;padding:12px 0 6px;color:var(--ink-2)}
/* 목록 */
.item{display:grid;grid-template-columns:26px 1fr auto;gap:0 12px;padding:11px 0;border-bottom:1px solid var(--line-2);align-items:start}
.item.star{background:#fdf7f5;margin:0 -12px;padding-left:12px;padding-right:12px}
.st{font-size:16px;cursor:pointer;color:var(--faint);user-select:none;padding-top:1px}
.item.star .st{color:var(--acc)}
.tt{font-size:14px;font-weight:500;line-height:1.5}
.tt a{color:var(--ink);text-decoration:none}
.tt a:hover{text-decoration:underline;text-underline-offset:3px}
.meta{font-size:12px;color:var(--mute);margin-top:2px;display:flex;gap:10px;flex-wrap:wrap}
.meta b{color:var(--ink-2);font-weight:600}
.badge{font-size:10.5px;padding:1px 7px;border-radius:10px;border:1px solid var(--line);color:var(--mute)}
.badge.law{background:var(--acc);border-color:var(--acc);color:#fff}
.badge.kats{border-color:#c9d6cf;color:var(--ok)}
.memo{font-size:12.5px;color:var(--ink-2);margin-top:5px;padding:5px 10px;background:#f7f5f0;border-left:2px solid var(--line);white-space:pre-wrap}
.memo:empty{display:none}
.abs{font-size:12px;color:var(--mute);margin-top:4px;line-height:1.55}
.act{display:flex;gap:6px;opacity:0}
.item:hover .act{opacity:1}
.act button{font:inherit;font-size:11px;padding:3px 8px;border:1px solid var(--line);background:#fff;cursor:pointer;color:var(--ink-2)}
.laws{width:100%;border-collapse:collapse;font-size:12.5px}
.laws th{font-size:10.5px;letter-spacing:.1em;color:var(--mute);font-weight:600;text-align:left;padding:8px;border-bottom:1px solid var(--line)}
.laws td{padding:8px;border-bottom:1px solid var(--line-2);vertical-align:top}
.laws td.d{white-space:nowrap;font-variant-numeric:tabular-nums}
.laws td small{color:var(--mute);display:block;font-size:11px}
.laws .new td{background:#fdf7f5}
.empty{padding:40px 20px;text-align:center;color:var(--mute);line-height:1.8}
.keybox{display:flex;flex-wrap:wrap;gap:8px 10px;align-items:center;margin-top:10px}
.keybox label{font-size:11px;letter-spacing:.1em;color:var(--mute);font-weight:600}
.keybox input{font:inherit;font-size:12.5px;padding:6px 9px;border:1px solid var(--line);background:#fff;min-width:320px}
.keybox button{font:inherit;font-size:12px;padding:6px 12px;background:var(--black);color:#fff;border:none;cursor:pointer}
.keybox span{font-size:12px;color:var(--ok)}
.foot{font-size:11.5px;color:var(--faint);margin-top:16px;line-height:1.7}
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
@media(max-width:900px){.wrap{padding:28px 16px 70px}}
</style></head><body>
__NAV__
<div class="wrap">
<div class="head">
  <div><div class="eyebrow">시몬스 연구소</div><h1>R&amp;D 동향</h1></div>
  <div class="status" id="status"></div>
</div>
<div class="lead">경쟁사 신제품, 우리 시험 근거 법령의 변경, 경쟁사 특허를 한곳에서 봅니다. 평일 아침 8시 자동 갱신.</div>
<div class="sum" id="sum"></div>
<div class="tabs" id="tabs">
  <button data-t="board" class="on">신제품 보드<span class="n" id="nB"></span></button>
  <button data-t="regs">규격·인증 감시<span class="n" id="nR"></span></button>
  <button data-t="pat">특허 동향<span class="n" id="nP"></span></button>
</div>
<div id="view"></div>
</div>
<script>
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
let D=null, TAB='board', PICK=null;
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
const mon=m=>m.slice(2,4)+'.'+m.slice(5,7);
async function load(){ D=await (await fetch('/동향/data')).json(); render(); }
function render(){
  const st=D.state||{};
  const errs=(st.last_errors||[]); const keyErr=errs.length&&errs.every(e=>/KIPRIS|열쇠/.test(e));
  $('#status').innerHTML=`${D.busy?`<b>가져오는 중…</b> ${esc(D.now)}`:st.last_run?`마지막 갱신 <b>${esc(st.last_run)}</b>${errs.length?(keyErr?` · <span>특허 수집 설정 필요(관리자)</span>`:` · <span style="color:var(--acc)">일부 항목을 가져오지 못함(관리자 확인)</span>`):''}`:'아직 한 번도 가져오지 않았습니다'}
    <button id="run" ${D.busy?'disabled':''}>지금 갱신</button>`;
  const nb=Object.values(D.board.cells).reduce((a,c)=>a+Object.values(c).reduce((x,y)=>x+y.length,0),0);
  $('#nB').textContent=nb||''; $('#nR').textContent=D.regs.rows.length||''; $('#nP').textContent=D.patents.rows.length||'';
  $$('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.t===TAB));
  renderSum(nb);
  $('#view').innerHTML = TAB==='board'?vBoard():TAB==='regs'?vRegs():vPat();
}
function renderSum(nb){
  const B=D.board, R=D.regs, P=D.patents; const thisM=B.months[B.months.length-1];
  const nThis=B.companies.reduce((a,c)=>a+(B.cells[c][thisM]||[]).length,0);
  const cosThis=B.companies.filter(c=>(B.cells[c][thisM]||[]).length);
  const law=R.rows.filter(r=>r.type==='law_change'), kats=R.rows.filter(r=>r.type==='kats');
  const since30=new Date(Date.now()-30*864e5).toISOString().slice(0,10);
  const law30=law.filter(r=>(r.date||r.fetched||'')>=since30);
  const pat3=P.rows.filter(r=>(r.date||'')>=new Date(Date.now()-92*864e5).toISOString().slice(0,10));
  $('#sum').innerHTML=`
    <a data-t="board"><span class="k">경쟁사 신제품·기술 발표 · 이번 달</span><span class="v">${nThis}<small>건</small></span><span class="s">${cosThis.length?esc(cosThis.slice(0,4).join(' · '))+(cosThis.length>4?' 외':''):'이번 달 발표가 아직 없습니다'} · 6개월 ${nb}건</span></a>
    <a data-t="regs"><span class="k">우리 시험 근거 법령·고시 변경 · 30일</span><span class="v ${law30.length?'':'ok'}">${law30.length}<small>건</small></span><span class="s">${law30.length?'바뀐 것이 있습니다. 규격·인증 탭에서 확인':`지켜보는 ${R.laws.length}개 모두 그대로입니다`}</span></a>
    <a data-t="regs"><span class="k">국표원 공고·규격 뉴스 · 90일</span><span class="v">${R.rows.length-law.length}<small>건</small></span><span class="s">국가기술표준원 ${kats.length}건 · 뉴스 ${R.rows.length-law.length-kats.length}건</span></a>
    <a data-t="pat"><span class="k">경쟁사 특허 출원 · 최근 3개월</span><span class="v">${P.has_key?pat3.length:'–'}<small>${P.has_key?'건':''}</small></span><span class="s">${P.has_key?`12개월 누계 ${P.rows.length}건 · 출원인 ${P.applicants.length}곳`:'특허 수집 설정 필요(관리자)'}</span></a>`;
}
function vBoard(){
  const B=D.board;
  if(!B.companies.length) return `<div class="card"><div class="empty">아직 「신제품·기술」 태그가 붙은 기사가 없습니다.<br>경쟁사 뉴스 클리핑이 모이면 여기에 회사 × 월 격자로 쌓입니다.</div></div>`;
  let t=`<div class="card"><h2>경쟁사 신제품·기술 발표</h2><div class="hint">신제품·출시·기술 기사와 홈페이지에 새로 올라온 제품의 수. 같은 소식은 하나로 셉니다. 칸을 누르면 목록이 열립니다. 수집은 ${esc(D.board.months[0].replace('-','.'))}부터 시작했습니다.</div>
    <div class="gridwrap"><table class="g"><tr><th>회사</th>${B.months.map(m=>`<th>${mon(m)}</th>`).join('')}<th>합계</th></tr>`;
  B.companies.forEach(c=>{ const row=B.cells[c]; const tot=B.months.reduce((a,m)=>a+row[m].length,0);
    t+=`<tr><td>${esc(c)}<small>${esc(B.groups[c]||'')}</small></td>${B.months.map(m=>{const n=row[m].length; const on=PICK&&PICK[0]===c&&PICK[1]===m;
      return `<td>${n?`<span class="cell c${Math.min(3,n)} ${on?'on':''}" data-c="${esc(c)}" data-m="${m}">${n}</span>`:'<span style="color:var(--line)">·</span>'}</td>`;}).join('')}<td><b>${tot}</b></td></tr>`; });
  t+=`</table></div>`;
  if(PICK&&B.cells[PICK[0]]){ const list=B.cells[PICK[0]][PICK[1]]||[];
    t+=`<div class="sub"><div class="t">${esc(PICK[0])} · ${mon(PICK[1])} · ${list.length}건</div>${list.map(a=>`<div class="item"><span></span><div><div class="tt"><a href="${esc(a.link)}" target="_blank" rel="noopener">${esc(a.title)}</a></div><div class="meta"><span>${esc(a.source)}</span><span>${esc((a.date||'').slice(0,10))}</span></div></div><div></div></div>`).join('')}</div>`; }
  return t+`</div>`;
}
function vRegs(){
  const R=D.regs;
  let t=`<div class="card"><h2>지켜보는 법령·고시</h2><div class="hint">법제처에서 매일 공포일·시행일을 읽어 지난번과 비교합니다. 바뀌면 아래 목록 맨 위에 붉은 «법령 변경» 으로 올라옵니다.${R.checked?` 마지막 확인 ${esc(R.checked)}.`:''}</div>`;
  if(R.laws.length){ t+=`<table class="laws"><tr><th>법령·고시</th><th>구분</th><th>소관</th><th>공포·발령</th><th>시행</th><th>최근 개정</th></tr>${R.laws.map(l=>`<tr><td><a href="${esc(l.link)}" target="_blank" rel="noopener" style="color:inherit">${esc(l.name)}</a><small>${esc(l.why)}</small></td><td>${esc(l.kind)}</td><td>${esc(l.ministry)}</td><td class="d">${l.promul_d}</td><td class="d">${l.enforce_d}</td><td>${esc(l.change)}</td></tr>`).join('')}</table>`; }
  else t+=`<div class="empty">아직 확인하지 않았습니다. «지금 갱신» 을 누르면 법제처에서 읽어 옵니다.<br><span style="font-size:12px">${R.watch.map(w=>esc(w.label)).join(' · ')}</span></div>`;
  t+=`</div><div class="card"><h2>공고·보도·규격 뉴스</h2><div class="hint">국가기술표준원 공지·공고와 보도자료, 규격·인증 관련 뉴스 중 침대·매트리스·생활용품·라돈에 닿는 것만. 최근 90일.</div>`;
  if(!R.rows.length) t+=`<div class="empty">모인 것이 없습니다.</div>`;
  else t+=R.rows.map(r=>item(r, r.type==='law_change'?'<span class="badge law">법령 변경</span>':r.type==='kats'?'<span class="badge kats">국표원</span>':'<span class="badge">뉴스</span>', r.detail?`<div class="abs">${esc(r.detail)}${r.why?` · ${esc(r.why)}`:''}</div>`:'')).join('');
  return t+`</div>`;
}
function vPat(){
  const P=D.patents;
  let t=`<div class="card"><h2>경쟁사 특허 출원</h2>`;
  if(!P.has_key){ t+=`<div class="hint">특허 수집 설정이 필요합니다(관리자). 열쇠 발급 방법은 README.md 의 «KIPRIS 열쇠» 항목에 있습니다. 열쇠는 서버의 .env 파일(KIPRIS_SERVICE_KEY)에 저장됩니다.</div>`; }
  else t+=`<div class="hint">출원인 이름으로 찾아 제목에 매트리스·침대·스프링·수면 같은 말이 든 것만 남깁니다. 출원일 기준 최근 12개월 격자. 공개 전 출원(18개월)은 보이지 않습니다.</div>`;
  t+=`<details class="fold" ${P.has_key?'':'open'}><summary>열쇠 설정 (담당자용)</summary><div class="in"><div class="keybox"><label>KIPRIS ServiceKey</label><input id="pkey" type="password" autocomplete="off" placeholder="${P.has_key?'저장되어 있습니다 — 바꾸려면 새로 입력':'ServiceKey 붙여넣기'}"><button id="savePat">저장</button><span id="patMsg"></span></div><p style="margin:8px 0 0;font-size:11.5px;color:var(--mute)">저장할 때 관리 비밀번호를 묻습니다. 열쇠는 .env 에 저장되고 화면에 다시 보이지 않습니다.</p></div></details>`;
  if(P.applicants.length){ t+=`<div class="gridwrap" style="margin-top:18px"><table class="g"><tr><th>출원인</th>${P.months.map(m=>`<th>${mon(m)}</th>`).join('')}<th>합계</th></tr>${P.applicants.map(a=>{const g=P.grid[a]; const tot=P.months.reduce((x,m)=>x+g[m],0); return `<tr><td>${esc(a)}</td>${P.months.map(m=>`<td>${g[m]?`<span class="cell c${Math.min(3,g[m])}">${g[m]}</span>`:'<span style="color:var(--line)">·</span>'}</td>`).join('')}<td><b>${tot}</b></td></tr>`;}).join('')}</table></div>`; }
  const I=P.ipc||{groups:[]};
  if(I.groups.length){
    const apps=Object.keys(I.by);
    t+=`</div><div class="card"><h2>어느 기술에 힘을 주나 — 출원인 × 특허 분류</h2><div class="hint">특허마다 붙는 국제 분류(IPC)의 앞부분으로 묶었습니다. 같은 분류가 많을수록 그 회사가 거기에 연구를 집중한다는 뜻입니다. 숫자는 최근 12개월 출원 수.</div>
      <div class="gridwrap"><table class="g"><tr><th>출원인</th>${I.groups.map(g=>`<th title="${esc(g.code)}">${esc(g.label||g.code)}<br><span style="font-weight:400;color:var(--faint)">${esc(g.code)}</span></th>`).join('')}<th>그 외</th><th>가장 많은 분야</th></tr>
      ${apps.map(a=>`<tr><td>${esc(a)}</td>${I.groups.map(g=>{const n=I.by[a][g.code]; return `<td>${n?`<span class="cell c${Math.min(3,n)}">${n}</span>`:'<span style="color:var(--line)">·</span>'}</td>`;}).join('')}<td>${I.other[a]||'<span style="color:var(--line)">·</span>'}</td><td style="text-align:left;font-weight:400;font-size:12px">${esc(I.focus[a].label||I.focus[a].code)} <span style="color:var(--mute)">${I.focus[a].share}%</span></td></tr>`).join('')}</table></div>
      <div class="foot">분류 이름은 연구소에서 쉽게 풀어 쓴 것이며 공식 명칭과 다를 수 있습니다. 한 특허에 분류가 여럿이면 첫 분류로 셉니다.</div>`;
  }
  t+=`</div><div class="card"><h2>출원 목록</h2>`;
  if(!P.rows.length) t+=`<div class="empty">${P.has_key?'아직 모인 출원이 없습니다. «지금 갱신» 을 누르세요.':'특허 수집 설정이 끝나면 여기에 채워집니다.'}</div>`;
  else t+=P.rows.map(r=>item(r, `<span class="badge">${esc(r.status||'출원')}</span>`, r.abstract?`<div class="abs">${esc(r.abstract)}</div>`:'')).join('');
  return t+`</div>`;
}
function item(r,badge,extra){
  return `<div class="item ${r.star?'star':''}" data-k="${r.key}"><span class="st" title="중요 표시">★</span>
    <div><div class="tt"><a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.title)}</a></div>
      <div class="meta">${badge}<b>${esc(r.source)}</b><span>${esc((r.date||'').slice(0,10))}</span>${r.ipc?`<span>${esc(r.ipc)}</span>`:''}</div>${extra||''}
      <div class="memo">${esc(r.memo)}</div></div>
    <div class="act"><button data-a="memo">메모</button><button data-a="hide">숨기기</button></div></div>`;
}
document.addEventListener('click',async e=>{
  const tb=e.target.closest('#tabs button, #sum a'); if(tb){ TAB=tb.dataset.t; render(); if(tb.closest('#sum')) $('#tabs').scrollIntoView({behavior:'smooth',block:'start'}); return; }
  const cl=e.target.closest('.cell[data-c]'); if(cl){ PICK=(PICK&&PICK[0]===cl.dataset.c&&PICK[1]===cl.dataset.m)?null:[cl.dataset.c,cl.dataset.m]; render(); return; }
  if(e.target.closest('#run')){ e.target.disabled=true; e.target.textContent='가져오는 중…'; await fetch('/동향/수집',{method:'POST'}); setTimeout(load,800); return; }
  if(e.target.closest('#savePat')){ const pw=prompt('관리 비밀번호'); if(pw===null) return;
    const res=await fetch('/동향/특허설정',{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Pw':pw},body:JSON.stringify({service_key:$('#pkey').value})}); const r=await res.json();
    $('#patMsg').textContent=!res.ok?(r.error||'저장하지 못했습니다'):r.has_key?'저장했습니다. «지금 갱신» 을 누르면 가져옵니다.':'열쇠가 비어 있습니다.'; load(); return; }
  const st=e.target.closest('.item .st'); if(st){ const it=st.closest('.item'); const on=!it.classList.contains('star');
    await fetch('/동향/표시',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:it.dataset.k,star:on})}); it.classList.toggle('star',on); return; }
  const ab=e.target.closest('.act button'); if(ab){ const it=ab.closest('.item');
    if(ab.dataset.a==='hide'){ await fetch('/동향/표시',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:it.dataset.k,hide:true})}); it.remove(); return; }
    const m=prompt('한 줄 메모 (비우면 지움)',$('.memo',it).textContent); if(m===null) return;
    await fetch('/동향/표시',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:it.dataset.k,memo:m})}); $('.memo',it).textContent=m; return; }
});
load(); setInterval(()=>{ if(D&&D.busy) load(); },4000);
</script></body></html>"""


def page(build=""):
    import portal
    return PAGE.replace("__NAV__", portal.nav("/동향", "", build)).replace("__NAVCSS__", portal.NAV_CSS)
