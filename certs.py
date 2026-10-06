# -*- coding: utf-8 -*-
"""인증 현황 — 보유 인증(환경표지·라돈·토론·비건·PS·UL 그린가드·더마테스트)의 만료일 관리.

  · 자료는 인증현황.json 한 파일. 인증서(번호) 단위로 두고 제품 목록을 붙인다 — 담당자가 쓰던
    「인증계획」 시트와 같은 단위. 「통합인증현황」(제품 × 인증 매트릭스)은 같은 자료를 돌려 그린다.
  · 상태는 날짜에서 계산한다: 만료(지남) → 임박(30일) → 준비(90일) → 정상. 일수는 설정에서 바꾼다.
    담당자가 적는 것은 진행 상태(인증 중 · 갱신 진행 중 · 갱신 안 함 · 종료)와 진행 메모뿐이다.
  · 담당자 엑셀(시몬스 인증 현황_YYYYMMDD.xlsx)을 그대로 가져온다. 두 시트가 어긋나면 «확인 필요» 표시를 남긴다.
  · 밖으로 나가는 요청은 없다.
"""
import os, io, json, datetime, threading, uuid, re, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "인증현황.json")
_lock = threading.Lock()

# (키, 이름, 발급·심사 기관, 통합현황 시트 머리글에 들어 있는 글자)
KINDS = (
    ("eco",   "환경표지인증",        "한국환경산업기술원",     "환경표지"),
    ("radon", "라돈 안전제품인증",   "한국원자력안전기술원",   "라돈"),
    ("thoron","토론 안전제품인증",   "한국원자력안전기술원",   "토론"),
    ("vegan", "비건인증",            "한국비건인증원",         "비건"),
    ("ps",    "PS 인증 (Pet Product Safety)", "", "Pet Product"),
    ("ul",    "UL 그린가드 인증",    "UL Solutions",           "Greenguard"),
    ("derma", "더마테스트 인증",     "Dermatest",              "더마"),
)
KIND_KEYS = [k for k, *_ in KINDS]
KIND_NAME = {k: n for k, n, *_ in KINDS}
PROGRESS = ("인증 중", "갱신 진행 중", "갱신 안 함", "종료")
DEFAULT_SETTINGS = {"lead_ready": 90, "lead_soon": 30}


# ═══════════════════════════════════════════════ 저장
def _empty():
    return {"settings": dict(DEFAULT_SETTINGS), "products": [], "certs": [], "imported": "", "updated": ""}


def _load():
    if os.path.exists(FILE):
        try:
            d = json.load(io.open(FILE, encoding="utf-8"))
            d.setdefault("settings", {}); d.setdefault("products", []); d.setdefault("certs", [])
            for k, v in DEFAULT_SETTINGS.items():
                d["settings"].setdefault(k, v)
            return d
        except Exception:
            pass
    return _empty()


def _save(d):
    d["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with _lock:
        tmp = FILE + ".tmp"
        json.dump(d, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, FILE)


def _backup():
    if os.path.exists(FILE):
        bdir = os.path.join(HERE, "_backup"); os.makedirs(bdir, exist_ok=True)
        shutil.copy2(FILE, os.path.join(bdir, "인증현황_%s.json" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")))


def _d(v):
    """엑셀 셀 → YYYY-MM-DD. datetime · 'YYYY-MM-DD' · 'YY.MM.DD' · 그 외는 ''."""
    if v is None or v == "":
        return ""
    if isinstance(v, datetime.datetime):
        return v.date().isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    s = str(v).strip()
    m = re.match(r"^(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", s)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if m:
        return "20%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return ""


def _ov(want, have):
    """두 이름 집합이 몇 개 겹치는가. 'heon' 과 'beautyrest heon' 처럼 한쪽이 다른 쪽을 품으면 같은 것으로 본다."""
    n = 0
    for w in want:
        if any(w == h or h.endswith(" " + w) or w.endswith(" " + h) for h in have if h):
            n += 1
    return n


def _no(v):
    """인증번호 셀 → 한 줄. 숫자면 그대로, 줄바꿈은 ' / '."""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(int(v))
    s = re.sub(r"호(?=[A-Za-z0-9])", "호\n", str(v).replace("\r", ""))
    return " / ".join(x.strip() for x in s.split("\n") if x.strip())


# ═══════════════════════════════════════════════ 엑셀 가져오기
def import_xlsx(path_or_file):
    """담당자 엑셀을 읽어 인증현황.json 을 새로 만든다. 돌려주는 값: 요약 dict.

    통합인증현황 시트(제품 × 인증)를 기본으로 삼고, 인증계획_YYYY 시트의 진행사항·날짜를 덧입힌다.
    두 시트의 날짜가 다르면 계획 시트를 따르되 check=True(확인 필요) 를 남긴다.
    """
    import openpyxl
    wb = openpyxl.load_workbook(path_or_file, data_only=True)
    names = wb.sheetnames
    main = next((n for n in names if n.startswith("통합인증현황") and "구" not in n), None) or \
           next((n for n in names if n.startswith("통합인증현황")), None)
    if not main:
        raise ValueError("「통합인증현황」 시트를 찾지 못했습니다")
    ws = wb[main]
    rows = list(ws.iter_rows(values_only=True))

    # 머리글: 3행에 인증 이름(병합 시작 칸), 4행에 칸 이름
    hdr_i = next((i for i, r in enumerate(rows) if r and r[0] == "No."), None)
    if hdr_i is None:
        raise ValueError("「통합인증현황」 시트의 머리글(No.)을 찾지 못했습니다")
    H1, H2 = rows[hdr_i], rows[hdr_i + 1]
    groups = []   # (kind_key, 시작 열)
    for c, v in enumerate(H1):
        if c < 4 or not v:
            continue
        for k, n, org, tag in KINDS:
            if tag in str(v):
                groups.append((k, c)); break
    # 각 그룹의 칸 위치
    def col_of(start, end, label_sub):
        for c in range(start, end):
            v = H2[c] if c < len(H2) else None
            if v and label_sub in str(v).replace("\n", "").replace(" ", ""):
                return c
        return None
    bounds = [(k, s, (groups[i + 1][1] if i + 1 < len(groups) else len(H1))) for i, (k, s) in enumerate(groups)]
    spec = {}
    for k, s, e in bounds:
        spec[k] = {"no": col_of(s, e, "인증번호"), "start": col_of(s, e, "시작"), "end": col_of(s, e, "종료"),
                   "issued": col_of(s, e, "최근발급일") or col_of(s, e, "발급일"), "first": col_of(s, e, "최초발급일")}

    products, cert_map, seen = [], {}, {}
    cat1 = cat2 = ""
    for r in rows[hdr_i + 2:]:
        if not r or not any(r):
            continue
        no, c1, c2, name = r[0], r[1], r[2], r[3]
        if not name:
            continue
        cat1 = (str(c1).strip() if c1 else cat1) or cat1
        cat2 = (str(c2).strip() if c2 else "") if c1 or c2 else cat2
        if cat2 == "-":
            cat2 = ""
        nm = re.sub(r"\s+", " ", str(name)).strip()
        disc = bool(no) and "단종" in str(no) or "단종" in nm
        nm = re.sub(r"\s*-?\s*단종\s*$", "", nm).strip()
        key = (cat2, nm)
        if key in seen:                       # 같은 이름이 둘 — 담당자가 확인하도록 표시
            nm = nm + " ②"
        seen[key] = True
        pid = uuid.uuid4().hex[:8]
        products.append({"id": pid, "cat1": cat1, "cat2": cat2, "name": nm, "discontinued": disc,
                         "check": nm.endswith("②")})
        for k, cols in spec.items():
            v_no = r[cols["no"]] if cols["no"] is not None and cols["no"] < len(r) else None
            if v_no is None or str(v_no).strip() in ("", "해당없음", "-"):
                continue
            no_s = _no(v_no)
            start = _d(r[cols["start"]]) if cols["start"] is not None else ""
            end = _d(r[cols["end"]]) if cols["end"] is not None else ""
            issued = _d(r[cols["issued"]]) if cols["issued"] is not None else ""
            first = _d(r[cols["first"]]) if cols["first"] is not None else ""
            if not end and not start:
                # 번호 칸에 '취득 예정(7월)' 같은 메모만 있는 경우 → 진행 메모로
                ck = (k, "메모:" + no_s)
                c = cert_map.setdefault(ck, {"id": uuid.uuid4().hex[:8], "kind": k, "no": "", "start": "", "end": "",
                                             "issued": "", "first": "", "progress": "인증 중", "note": no_s,
                                             "products": [], "check": True})
                c["products"].append(pid)
                continue
            # UL 처럼 제품마다 번호가 다르지만 기간이 같은 것은 한 인증서로 묶고 번호는 범위로
            ck = (k, start, end) if k in ("ul",) else (k, no_s, start, end)
            c = cert_map.setdefault(ck, {"id": uuid.uuid4().hex[:8], "kind": k, "no": no_s, "start": start, "end": end,
                                         "issued": issued, "first": first, "progress": "인증 중", "note": "",
                                         "products": [], "check": False, "_nos": []})
            c["products"].append(pid)
            c.setdefault("_nos", []).append(no_s)
            if first and not c["first"]:
                c["first"] = first
    certs = []
    for c in cert_map.values():
        nos = c.pop("_nos", [])
        if len(set(nos)) > 1:
            digits = sorted(x for x in nos if x.isdigit())
            c["no"] = ("%s–%s 외" % (digits[0], digits[-1])) if len(digits) >= 2 else (nos[0] + " 외 %d" % (len(set(nos)) - 1))
        certs.append(c)

    # 인증계획 시트 — 진행사항·날짜 덧입히기 (가장 최근 연도)
    plans = sorted((n for n in names if n.startswith("인증계획")), reverse=True)
    plan_applied = 0
    pname = {p["name"].lower(): p["id"] for p in products}
    if plans:
        pw = wb[plans[0]]
        prow = list(pw.iter_rows(values_only=True))
        kind_cur, ended = "", False
        for r in prow:
            if not r or not any(r):
                continue
            if r[0] == "종료":
                ended = True; continue
            if r[0] in ("No.", None) and not (r[1] or r[2]):
                continue
            if r[0] == "No.":
                continue
            kn = str(r[1]).replace("\n", "").strip() if r[1] else ""
            if kn:
                kind_cur = kn
            detail, prods_txt = _no(r[2]), str(r[4] or "")
            start, end, first = _d(r[5]), _d(r[6]), _d(r[7])
            progress = str(r[9] or "").strip()
            if not detail and not prods_txt:
                continue
            kkeys = []
            for k, n, org, tag in KINDS:
                if tag in kind_cur or (tag == "Greenguard" and "그린가드" in kind_cur) or (tag == "Pet Product" and "PS" in kind_cur):
                    kkeys.append(k)
            if "라돈" in kind_cur and "토론" in kind_cur:
                kkeys = ["radon", "thoron"]
            if not kkeys:
                continue
            # 번호 첫 토큰으로 맞춰 보고, 안 맞으면 제품 이름 겹침으로
            tok = detail.split(" / ")[0].split("–")[0].replace("호", "").strip()
            want = {x.strip().lower() for x in re.split(r"[,、]", prods_txt) if x.strip()}
            for c in certs:
                if c["kind"] not in kkeys:
                    continue
                have = {next((p["name"].lower() for p in products if p["id"] == pid), "") for pid in c["products"]}
                hit = bool(tok) and tok in c["no"].replace("호", "") and (not want or _ov(want, have) > 0 or len(want) == len(have))
                by_products = want and not hit and not ended and (not tok or not c["no"] or (len(kkeys) > 1 and c["kind"] == "thoron"))
                if by_products:
                    ov = _ov(want, have)
                    hit = ov and ov >= max(1, min(len(want), len(have)) * 0.6)
                if not hit:
                    continue
                plan_applied += 1
                if ended or progress.startswith("종료") or "갱신 안함" in progress or "갱신 안 함" in progress:
                    c["progress"] = "종료" if (ended or progress.startswith("종료")) else "갱신 안 함"
                elif "갱신 진행" in progress:
                    c["progress"] = "갱신 진행 중"
                elif progress.startswith("미갱신"):
                    c["progress"] = "갱신 안 함"
                if progress and progress not in c["note"]:
                    c["note"] = (c["note"] + " · " + progress).strip(" ·")
                if first and not c["first"]:
                    c["first"] = first
                if end and end != c["end"]:
                    c["note"] = ("통합현황 시트는 %s 만료 · 계획 시트는 %s — 확인 필요 · " % (c["end"], end) + c["note"]).strip(" ·")
                    c["end"], c["start"], c["check"] = end, start or c["start"], True

    merged = {}
    for c in certs:
        k = (c["kind"], c["no"], c["start"], c["end"])
        if k in merged and c["no"]:
            m = merged[k]
            m["products"] = list(dict.fromkeys(m["products"] + c["products"]))
            m["check"] = m["check"] or c["check"]
            m["note"] = m["note"] if len(m["note"]) >= len(c["note"]) else c["note"]
            m["first"] = m["first"] or c["first"]; m["issued"] = m["issued"] or c["issued"]
        else:
            merged[k if c["no"] else (c["kind"], c["id"], "", "")] = c
    certs = list(merged.values())
    disc = {p["id"] for p in products if p.get("discontinued")}
    for c in certs:
        if c["products"] and all(pid in disc for pid in c["products"]) and c["progress"] != "종료":
            c["progress"] = "종료"; c["note"] = ("단종 제품 · " + c["note"]).strip(" ·")
    d = _empty()
    d["products"], d["certs"] = products, certs
    d["imported"] = "%s · %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                 os.path.basename(path_or_file) if isinstance(path_or_file, str) else "업로드")
    _backup(); _save(d)
    return {"products": len(products), "certs": len(certs), "plan_applied": plan_applied,
            "check": sum(1 for c in certs if c.get("check")) + sum(1 for p in products if p.get("check"))}


# ═══════════════════════════════════════════════ 조회
def _days(end, today):
    try:
        return (datetime.date.fromisoformat(end) - today).days
    except Exception:
        return None


def _state(c, today, s):
    """날짜 상태: expired · soon · ready · ok · none(날짜 없음) · closed(종료·갱신 안 함은 알림 밖)."""
    if c.get("progress") in ("종료",):
        return "closed"
    d = _days(c.get("end", ""), today)
    if d is None:
        return "none"
    if c.get("progress") == "갱신 안 함":
        return "expired" if d < 0 else "closing"
    if d < 0:
        return "expired"
    if d <= s["lead_soon"]:
        return "soon"
    if d <= s["lead_ready"]:
        return "ready"
    return "ok"


def data():
    d = _load()
    today = datetime.date.today()
    s = d["settings"]
    pmap = {p["id"]: p for p in d["products"]}
    out_certs = []
    for c in d["certs"]:
        x = dict(c)
        x["days"] = _days(c.get("end", ""), today)
        x["state"] = _state(c, today, s)
        x["kind_name"] = KIND_NAME.get(c["kind"], c["kind"])
        x["product_names"] = [pmap[p]["name"] for p in c.get("products", []) if p in pmap]
        x["n_products"] = len(x["product_names"])
        out_certs.append(x)
    out_certs.sort(key=lambda x: (x["state"] in ("closed",), x["end"] or "9999", x["kind"]))
    # 제품 × 인증 매트릭스: 제품마다 종류별 가장 늦게 끝나는 인증서 하나
    matrix = {}
    for c in out_certs:
        for pid in c.get("products", []):
            cur = matrix.setdefault(pid, {}).get(c["kind"])
            if cur is None or (c["end"] or "") > (cur["end"] or ""):
                matrix[pid][c["kind"]] = {"id": c["id"], "no": c["no"], "end": c["end"], "days": c["days"],
                                          "state": c["state"], "check": c.get("check", False)}
    active = [c for c in out_certs if c["state"] not in ("closed",)]
    kpi = {"certs": len(active),
           "expired": sum(1 for c in active if c["state"] == "expired"),
           "soon": sum(1 for c in active if c["state"] == "soon"),
           "ready": sum(1 for c in active if c["state"] == "ready"),
           "renewing": sum(1 for c in active if c.get("progress") == "갱신 진행 중"),
           "check": sum(1 for c in out_certs if c.get("check")) + sum(1 for p in d["products"] if p.get("check")),
           "products": sum(1 for p in d["products"] if not p.get("discontinued"))}
    # 앞으로 12개월 타임라인
    months = []
    y, m = today.year, today.month
    for i in range(12):
        months.append("%04d-%02d" % (y, m)); m += 1
        if m > 12:
            m = 1; y += 1
    timeline = {mo: [] for mo in months}
    for c in active:
        if c["end"] and c["end"][:7] in timeline:
            timeline[c["end"][:7]].append({"id": c["id"], "kind": c["kind"], "no": c["no"], "end": c["end"],
                                           "n": c["n_products"], "state": c["state"], "progress": c["progress"]})
    return {"today": today.isoformat(), "settings": s, "kinds": [{"key": k, "name": n, "org": o} for k, n, o, _ in KINDS],
            "progress": list(PROGRESS), "products": d["products"], "certs": out_certs, "matrix": matrix,
            "kpi": kpi, "months": months, "timeline": timeline, "imported": d.get("imported", ""),
            "updated": d.get("updated", "")}


def alerts(limit=6):
    """첫 화면·주간 보고서용: 만료 지남 → 임박 → 준비 순으로."""
    dd = data()
    order = {"expired": 0, "soon": 1, "ready": 2, "closing": 3}
    rows = [c for c in dd["certs"] if c["state"] in order]
    rows.sort(key=lambda c: (order[c["state"]], c["end"]))
    return {"kpi": dd["kpi"], "rows": rows[:limit], "settings": dd["settings"], "n_total": len(dd["certs"])}


# ═══════════════════════════════════════════════ 고치기
def save_cert(item):
    d = _load()
    cid = (item.get("id") or "").strip()
    kind = item.get("kind", "")
    if kind not in KIND_KEYS:
        raise ValueError("인증 종류")
    for f in ("start", "end", "issued", "first"):
        v = (item.get(f) or "").strip()
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f)
    progress = item.get("progress") or "인증 중"
    if progress not in PROGRESS:
        progress = "인증 중"
    pids = [p for p in (item.get("products") or []) if any(x["id"] == p for x in d["products"])]
    rec = {"id": cid or uuid.uuid4().hex[:8], "kind": kind, "no": (item.get("no") or "").strip(),
           "start": item.get("start") or "", "end": item.get("end") or "", "issued": item.get("issued") or "",
           "first": item.get("first") or "", "progress": progress, "note": (item.get("note") or "").strip(),
           "products": pids, "check": bool(item.get("check"))}
    for i, c in enumerate(d["certs"]):
        if c["id"] == rec["id"]:
            hist = c.get("history", [])
            if c.get("end") != rec["end"]:
                hist.append({"ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "what": "만료일 %s → %s" % (c.get("end") or "–", rec["end"] or "–")})
            rec["history"] = hist[-20:]
            d["certs"][i] = rec
            break
    else:
        d["certs"].append(rec)
    _save(d)
    return rec["id"]


def delete_cert(cid):
    d = _load()
    d["certs"] = [c for c in d["certs"] if c["id"] != cid]
    _save(d)


def save_product(item):
    d = _load()
    pid = (item.get("id") or "").strip()
    name = re.sub(r"\s+", " ", item.get("name") or "").strip()
    if not name:
        raise ValueError("제품명")
    rec = {"id": pid or uuid.uuid4().hex[:8], "cat1": (item.get("cat1") or "").strip(), "cat2": (item.get("cat2") or "").strip(),
           "name": name, "discontinued": bool(item.get("discontinued")), "check": False}
    for i, p in enumerate(d["products"]):
        if p["id"] == rec["id"]:
            d["products"][i] = rec; break
    else:
        d["products"].append(rec)
    _save(d)
    return rec["id"]


def delete_product(pid):
    d = _load()
    d["products"] = [p for p in d["products"] if p["id"] != pid]
    for c in d["certs"]:
        c["products"] = [x for x in c.get("products", []) if x != pid]
    _save(d)


def save_settings(patch):
    d = _load()
    for k in ("lead_ready", "lead_soon"):
        if k in patch:
            try:
                d["settings"][k] = max(0, min(730, int(patch[k])))
            except (TypeError, ValueError):
                pass
    _save(d)
    return d["settings"]


def clear_check(kind, _id):
    d = _load()
    for x in (d["certs"] if kind == "cert" else d["products"]):
        if x["id"] == _id:
            x["check"] = False
    _save(d)


# ═══════════════════════════════════════════════ 엑셀 내보내기 — 담당자 양식 두 시트
def export_xlsx():
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    dd = data()
    today = dd["today"]
    wb = openpyxl.Workbook()
    thin = Side(style="thin", color="D9D9D9"); bd = Border(left=thin, right=thin, top=thin, bottom=thin)
    head = Font(bold=True); fill = PatternFill("solid", fgColor="F2F2F2"); center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # 1. 통합인증현황 — 제품 × 인증
    ws = wb.active; ws.title = "통합인증현황"
    ws["A1"] = "㈜ 시몬스 인증현황"; ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "(%s 기준 · 포털에서 내보냄)" % today.replace("-", ".")
    hdr = ["No.", "구분1", "구분2", "제품명"]
    sub = ["", "", "", ""]
    for k in dd["kinds"]:
        hdr += [k["name"], "", "", "", ""]; sub += ["인증번호", "인증기간(시작)", "인증기간(종료)", "최근 발급일", "인증 잔여일"]
    ws.append(hdr); ws.append(sub)
    for c in range(5, len(hdr) + 1, 5):
        ws.merge_cells(start_row=3, start_column=c, end_row=3, end_column=c + 4)
    for row in (3, 4):
        for c in range(1, len(hdr) + 1):
            cell = ws.cell(row=row, column=c); cell.font = head; cell.fill = fill; cell.alignment = center; cell.border = bd
    cmap = {c["id"]: c for c in dd["certs"]}
    for i, p in enumerate(dd["products"], 1):
        r = ["단종" if p.get("discontinued") else i, p["cat1"], p["cat2"], p["name"]]
        for k in dd["kinds"]:
            m = dd["matrix"].get(p["id"], {}).get(k["key"])
            if not m:
                r += ["해당없음", "", "", "", ""]
            else:
                c = cmap[m["id"]]
                r += [c["no"], c["start"], c["end"], c["issued"], m["days"]]
        ws.append(r)
        for cc in range(1, len(r) + 1):
            ws.cell(row=ws.max_row, column=cc).border = bd
    ws.freeze_panes = "E5"
    for c in range(1, len(hdr) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 14 if c > 4 else (26 if c == 4 else 10)

    # 2. 인증계획 — 인증서 단위
    w2 = wb.create_sheet("인증계획_%s" % today[:4])
    w2.append(["%s 인증 일정" % today[:4], "", "", "", "", "", "", "", "", "%s 업데이트" % today.replace("-", ". ")])
    w2.append(["No.", "인증명", "인증번호", "제품 수", "제품명", "인증기간(시작)", "인증기간(종료)", "최초발급일", "인증 잔여일", "상태", "진행사항", "확인 필요"])
    for c in range(1, 13):
        cell = w2.cell(row=2, column=c); cell.font = head; cell.fill = fill; cell.alignment = center; cell.border = bd
    for i, c in enumerate(dd["certs"], 1):
        w2.append([i, c["kind_name"], c["no"], c["n_products"], ", ".join(c["product_names"]), c["start"], c["end"], c["first"],
                   c["days"] if c["days"] is not None else "", c["progress"], c["note"], "확인 필요" if c.get("check") else ""])
        for cc in range(1, 13):
            w2.cell(row=w2.max_row, column=cc).border = bd
    w2.freeze_panes = "C3"
    for c, w in zip("ABCDEFGHIJKL", (5, 18, 24, 7, 60, 13, 13, 13, 9, 12, 40, 9)):
        w2.column_dimensions[c].width = w
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return buf, "시몬스 인증 현황_%s.xlsx" % today.replace("-", "")


def page(build=""):
    import portal
    return PAGE.replace("__NAV__", portal.nav("/인증", "", build)).replace("__NAVCSS__", portal.NAV_CSS)


PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>인증 현황</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" onerror="this.remove()">
<style>
:root{--ink:#0f0f11;--ink-2:#3a3a40;--mute:#84848a;--faint:#b4b4b9;--line:#e3e0d9;--line-2:#eeebe4;--paper:#fff;--bg:#f1efea;--black:#0a0a0b;--acc:#8c3325;--acc-soft:#f3e6e2;--ok:#1f5a3a;--ok-soft:#e6efe9;--warn-soft:#e9e6df}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 "Pretendard Variable",Pretendard,"Malgun Gothic",system-ui,sans-serif}
__NAVCSS__
.wrap{max-width:1180px;margin:0 auto;padding:40px 40px 90px}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;flex-wrap:wrap}
.eyebrow{font-size:11px;letter-spacing:.2em;color:var(--mute);font-weight:600}
h1{font-size:28px;font-weight:700;letter-spacing:-.02em;margin:4px 0 0;line-height:1.15}
.tools{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.tools button,.tools a,.tools label{font:inherit;font-size:12px;padding:7px 12px;border:1px solid var(--line);background:#fff;color:var(--ink);cursor:pointer;text-decoration:none}
.tools button:hover,.tools a:hover,.tools label:hover{border-color:var(--black)}
.tools input[type=file]{display:none}
.lead{font-size:13px;color:var(--ink-2);margin:10px 0 16px;max-width:860px;line-height:1.6}
.lead .meta{color:var(--mute);font-size:12px}
/* KPI */
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin-bottom:14px}
.kpi{background:var(--paper);padding:14px 16px 12px;cursor:pointer;border-top:3px solid transparent}
.kpi:hover{background:#fbfaf7}.kpi.on{border-top-color:var(--ink)}
.kpi .k{font-size:11.5px;color:var(--mute);font-weight:600}
.kpi .v{font-size:36px;font-weight:700;letter-spacing:-.03em;line-height:1.05;margin:6px 0 4px;font-variant-numeric:tabular-nums}
.kpi .v small{font-size:13px;font-weight:500;color:var(--mute);margin-left:3px;letter-spacing:0}
.kpi .d{font-size:11.5px;color:var(--mute)}
.kpi.bad .v{color:var(--acc)}
/* 카드·탭 */
.card{background:var(--paper);border:1px solid var(--line);padding:16px 20px;margin-bottom:14px}
.card h2{font-size:14px;font-weight:700;margin:0 0 4px}
.card .hint{font-size:12px;color:var(--mute);margin-bottom:10px;line-height:1.5}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin-bottom:12px}
.tabs button{font:inherit;font-size:12.5px;font-weight:600;padding:8px 12px;background:none;border:none;border-bottom:2px solid transparent;margin-bottom:-1px;cursor:pointer;color:var(--mute)}
.tabs button.on{color:var(--ink);border-bottom-color:var(--ink)}
/* 타임라인 */
.tl{display:grid;grid-template-columns:repeat(12,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}
.tl .mo{background:var(--paper);min-height:96px;padding:8px 8px 10px}
.tl .mo.now{background:#fbfaf7}
.tl .mh{font-size:11px;color:var(--mute);font-weight:600;letter-spacing:.04em;margin-bottom:6px;display:flex;justify-content:space-between}
.tl .mh b{color:var(--ink)}
.chip{display:block;font-size:11px;padding:3px 6px;margin-bottom:3px;border:1px solid var(--line);background:#fff;cursor:pointer;line-height:1.3;color:var(--ink-2);text-align:left;width:100%;font-family:inherit}
.chip b{font-weight:600;color:var(--ink)}
.chip.expired{background:var(--acc-soft);border-color:#dcc6c0;color:var(--acc)}.chip.expired b{color:var(--acc)}
.chip.soon{background:var(--ink);border-color:var(--ink);color:#fff}.chip.soon b{color:#fff}
.chip.ready{background:var(--warn-soft);border-color:#d8d4ca}
.chip.closing{color:var(--faint);border-style:dashed}.chip.closing b{color:var(--faint)}
/* 표 */
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{font-size:10.5px;letter-spacing:.08em;color:var(--mute);font-weight:600;text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid var(--line-2);vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.dim td{color:var(--faint)}
tr.sel td{background:#fbfaf7}
.st{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;font-weight:600}
.st i{width:8px;height:8px;border-radius:50%;background:var(--faint);display:inline-block;flex:none}
.st.expired{color:var(--acc)}.st.expired i{background:var(--acc)}
.st.soon{color:var(--ink)}.st.soon i{background:var(--ink)}
.st.ready{color:var(--ink-2)}.st.ready i{background:#a89f8c}
.st.ok{color:var(--ok)}.st.ok i{background:var(--ok)}
.st.closing,.st.closed,.st.none{color:var(--faint)}
.tag{display:inline-block;font-size:10.5px;padding:0 6px;border-radius:9px;background:var(--line-2);color:var(--mute);margin-left:6px;white-space:nowrap}
.tag.chk{background:var(--acc-soft);color:var(--acc);cursor:pointer}
.tag.pg{background:var(--ok-soft);color:var(--ok)}
.tag.no{background:#f3f1ec;color:var(--mute)}
.prods{color:var(--ink-2);font-size:12px;line-height:1.45;max-width:380px}
.prods .more{color:var(--mute);cursor:pointer}
select.inl,input.inl{font:inherit;font-size:12px;padding:3px 6px;border:1px solid var(--line);background:#fff}
button.x,button.e{font:inherit;font-size:11px;padding:3px 8px;border:1px solid var(--line);background:#fff;cursor:pointer;color:var(--ink-2)}
button.x:hover,button.e:hover{border-color:var(--black)}
.note{font-size:12px;color:var(--ink-2);line-height:1.45;max-width:320px;cursor:text}
.note:empty::before{content:"메모 적기";color:var(--faint)}
/* 매트릭스 */
.mx{overflow-x:auto}
.mx table{font-size:12px}
.mx th.p,.mx td.p{position:sticky;left:0;background:var(--paper);z-index:1;min-width:230px}
.mx td.c{text-align:center;font-variant-numeric:tabular-nums;white-space:nowrap;cursor:pointer}
.mx td.c.expired{background:var(--acc-soft);color:var(--acc);font-weight:600}
.mx td.c.soon{background:var(--ink);color:#fff;font-weight:600}
.mx td.c.ready{background:var(--warn-soft);font-weight:600}
.mx td.c.ok{color:var(--ink-2)}
.mx td.c.closing{color:var(--faint);text-decoration:line-through}
.mx td.c.closed,.mx td.c.none{color:var(--faint)}
.mx td.c.na{color:var(--faint)}
.mx tr.grp td{background:#f7f5f0;font-weight:600;font-size:11px;letter-spacing:.06em;color:var(--mute);padding:5px 8px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--mute);margin-top:10px}
.legend i{display:inline-block;width:12px;height:12px;margin-right:5px;vertical-align:-2px;border:1px solid var(--line)}
/* 폼 */
.form{display:grid;grid-template-columns:repeat(4,1fr);gap:10px 14px}
.form label{font-size:11px;color:var(--mute);font-weight:600;display:flex;flex-direction:column;gap:4px}
.form input,.form select,.form textarea{font:inherit;font-size:12.5px;padding:6px 8px;border:1px solid var(--line);background:#fff}
.form .full{grid-column:1/-1}
.plist{display:grid;grid-template-columns:repeat(4,1fr);gap:2px 14px;border:1px solid var(--line);padding:10px;max-height:220px;overflow:auto;background:#fff}
.plist .g{grid-column:1/-1;font-size:10.5px;letter-spacing:.08em;color:var(--mute);font-weight:600;margin-top:6px}
.plist label{flex-direction:row;align-items:center;gap:6px;font-weight:400;color:var(--ink-2);font-size:12px}
.fbtns{display:flex;gap:8px;align-items:center;margin-top:12px}
.fbtns button{font:inherit;font-size:12.5px;padding:8px 16px;border:1px solid var(--ink);background:var(--ink);color:#fff;cursor:pointer}
.fbtns button.sec{background:#fff;color:var(--ink)}
.fbtns .msg{font-size:12px;color:var(--mute)}
.empty{padding:28px;text-align:center;color:var(--mute);line-height:1.7}
.guide{background:var(--paper);border:1px solid var(--line);padding:34px;text-align:center;color:var(--ink-2);line-height:1.8;margin-bottom:14px}
.foot{font-size:12px;color:var(--mute);margin-top:14px}
@media(max-width:1000px){.kpis{grid-template-columns:repeat(3,1fr)}.tl{grid-template-columns:repeat(6,1fr)}.form,.plist{grid-template-columns:1fr 1fr}.wrap{padding:24px 16px 60px}}
@media print{.side,.tools,.tabs,#form,.fbtns,.legend{display:none!important}body{background:#fff;padding-left:0}.wrap{padding:0;max-width:none}.card{break-inside:avoid}}
</style></head><body>
__NAV__
<div class="wrap">
<div class="head">
  <div><div class="eyebrow">시몬스 연구소</div><h1>인증 현황</h1></div>
  <div class="tools"><label>엑셀 가져오기<input type="file" id="imp" accept=".xlsx"></label><a href="/인증/내보내기">엑셀 내려받기</a><button id="print">인쇄</button></div>
</div>
<div class="lead">보유 인증 7종(환경표지·라돈·토론·비건·PS·UL 그린가드·더마테스트)의 만료일을 한 장에 봅니다. 만료 <b id="ldS">30</b>일 전부터 «임박», <b id="ldR">90</b>일 전부터 «준비»로 표시하고, 첫 화면과 주간 보고서에 올립니다.
  <div class="meta" id="meta"></div></div>

<div class="kpis" id="kpis"></div>
<div id="guide" class="guide" hidden></div>
<div id="body">
<div class="card"><h2>앞으로 12개월</h2><div class="hint">만료일이 있는 달에 인증서가 놓입니다. 누르면 아래 목록에서 그 인증서로 갑니다. 「갱신 안 함」은 점선.</div><div class="tl" id="tl"></div></div>

<div class="card">
  <div class="tabs" id="tabs"><button data-t="list" class="on">인증서 목록</button><button data-t="mx">제품 × 인증</button><button data-t="prod">제품 목록</button><button data-t="set">설정</button></div>
  <div id="view"></div>
</div>

<div class="card" id="form"><h2 id="ftitle">인증서 더하기</h2><div class="hint">번호와 만료일만 있어도 됩니다. 목록에서 「고치기」를 누르면 여기에 불러옵니다. 지우기는 관리 비밀번호를 묻습니다.</div>
  <div class="form">
    <label>인증 종류<select id="f_kind"></select></label>
    <label>인증번호<input id="f_no" placeholder="예: 12933 · RSP25-M(B)001호"></label>
    <label>진행 상태<select id="f_progress"></select></label>
    <label>확인 필요<select id="f_check"><option value="0">아니오</option><option value="1">예 — 원본과 대조할 것</option></select></label>
    <label>인증기간 시작<input type="date" id="f_start"></label>
    <label>인증기간 종료 (만료일)<input type="date" id="f_end"></label>
    <label>최근 발급일<input type="date" id="f_issued"></label>
    <label>최초 발급일<input type="date" id="f_first"></label>
    <label class="full">진행 메모<input id="f_note" placeholder="예: 갱신 서류 10/15 제출 · 심사 11월 예정"></label>
    <div class="full"><div style="font-size:11px;color:var(--mute);font-weight:600;margin-bottom:4px">해당 제품 <span id="f_pn" style="font-weight:400"></span> · <a href="#" id="f_all" style="color:var(--ink-2)">전체</a> · <a href="#" id="f_none" style="color:var(--ink-2)">해제</a></div><div class="plist" id="f_products"></div></div>
  </div>
  <div class="fbtns"><button id="f_save">저장</button><button class="sec" id="f_new">새로</button><span class="msg" id="f_msg"></span></div>
</div>
</div>
<div class="foot">자료는 이 폴더의 인증현황.json 에 있고, 엑셀로 가져오면 이전 자료는 _backup 에 남습니다. 라돈·토론 성적서를 자동화로 발행해도 인증 만료일은 바뀌지 않습니다 — 인증기관의 갱신 통지서를 받은 뒤 여기서 고치세요.</div>
</div>
<script>
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
const SHORT={eco:'환경표지',radon:'라돈',thoron:'토론',vegan:'비건',ps:'PS',ul:'UL',derma:'더마'};
const SN={expired:'만료 지남',soon:'임박',ready:'준비',ok:'정상',closing:'갱신 안 함',closed:'종료',none:'날짜 없음'};
let D=null, T='list', FILTER='', SEL='', EXP={};
const dtxt=c=>c.days===null?'–':c.days<0?`D+${-c.days}`:c.days===0?'오늘':`D-${c.days}`;
const dot=(d)=>d?d.replace(/-/g,'.'):'–';
async function load(){ D=await (await fetch('/인증/data')).json(); render(); }
function render(){
  const K=D.kpi, S=D.settings;
  $('#ldS').textContent=S.lead_soon; $('#ldR').textContent=S.lead_ready;
  $('#meta').textContent=(D.imported?`엑셀에서 가져옴 ${D.imported}`:'')+(D.updated?` · 마지막 수정 ${D.updated}`:'');
  const kp=(id,k,v,u,d,bad)=>`<div class="kpi ${FILTER===id?'on':''} ${bad&&v?'bad':''}" data-f="${id}"><div class="k">${k}</div><div class="v">${v}<small>${u}</small></div><div class="d">${d}</div></div>`;
  $('#kpis').innerHTML=kp('','보유 인증서',K.certs,'건',`제품 ${K.products}개 · 종료 제외`)+kp('expired','만료 지남',K.expired,'건',K.expired?'갱신 통지서 확인 필요':'없음 ✓',true)+kp('soon',`${S.lead_soon}일 내 만료`,K.soon,'건',K.soon?'갱신 신청이 들어가 있어야 합니다':'없음 ✓',true)+kp('ready',`${S.lead_ready}일 내 만료`,K.ready,'건',K.ready?'서류 준비 시작':'없음 ✓')+kp('check','확인 필요',K.check,'건',K.check?'두 시트가 달랐거나 이름이 겹침':'없음 ✓');
  const empty=!D.certs.length&&!D.products.length;
  $('#guide').hidden=!empty; $('#body').style.display=empty?'none':'';
  if(empty){ $('#guide').innerHTML='아직 인증 자료가 없습니다.<br>오른쪽 위 「엑셀 가져오기」로 「시몬스 인증 현황_YYYYMMDD.xlsx」를 올리면 두 시트(통합인증현황·인증계획)를 읽어 채웁니다.'; return; }
  renderTL(); renderView(); fillForm(SEL?D.certs.find(c=>c.id===SEL):null);
}
function renderTL(){
  const now=D.today.slice(0,7);
  $('#tl').innerHTML=D.months.map(m=>{const rows=D.timeline[m]||[]; const [y,mm]=m.split('-');
    // 같은 종류·같은 날·같은 상태는 칩 하나로 묶는다 (비건처럼 번호가 제품마다 다른 인증)
    const g={}; rows.forEach(r=>{const k=r.kind+'|'+r.end+'|'+r.state; (g[k]=g[k]||{kind:r.kind,end:r.end,state:r.state,ids:[],n:0,nos:[]}); g[k].ids.push(r.id); g[k].n+=r.n; g[k].nos.push(r.no);});
    const chips=Object.values(g).sort((a,b)=>a.end<b.end?-1:1);
    return `<div class="mo ${m===now?'now':''}"><div class="mh"><span>${+mm}월${mm==='01'||m===D.months[0]?` <span style="color:var(--faint)">${y.slice(2)}</span>`:''}</span>${rows.length?`<b>${rows.reduce((a,r)=>a+r.n,0)}</b>`:''}</div>${chips.map(c=>`<button class="chip ${c.state}" data-id="${c.ids[0]}" title="${esc(c.nos.join(', '))} · ${dot(c.end)}"><b>${SHORT[c.kind]}</b> ${c.ids.length>1?`${c.ids.length}건 `:''}${c.n}개 · ${c.end.slice(8)}일</button>`).join('')}</div>`;}).join('');
}
function renderView(){
  $$('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.t===T));
  let h='';
  if(T==='list'){
    let rows=D.certs; if(FILTER==='check') rows=rows.filter(c=>c.check); else if(FILTER) rows=rows.filter(c=>c.state===FILTER);
    h=rows.length?`<div style="overflow-x:auto"><table><tr><th>상태</th><th>종류</th><th>인증번호</th><th>제품</th><th>인증기간</th><th class="n">잔여</th><th>진행</th><th>메모</th><th></th></tr>
      ${rows.map(c=>{const names=c.product_names, open=EXP[c.id]; const shown=open?names:names.slice(0,4);
        return `<tr id="r-${c.id}" class="${c.state==='closed'?'dim':''} ${SEL===c.id?'sel':''}"><td><span class="st ${c.state}"><i></i>${SN[c.state]}</span></td>
        <td>${esc(c.kind_name)}</td><td>${esc(c.no)||'<span style="color:var(--faint)">번호 없음</span>'}${c.check?`<span class="tag chk" data-clear="${c.id}" title="누르면 확인함으로 바꿉니다">확인 필요 ✕</span>`:''}</td>
        <td><div class="prods"><b>${c.n_products}개</b>${names.length?' · '+shown.map(esc).join(', ')+(names.length>4&&!open?` <span class="more" data-exp="${c.id}">외 ${names.length-4}개 …</span>`:''):''}</div></td>
        <td style="white-space:nowrap">${dot(c.start)} ~ <b>${dot(c.end)}</b>${c.first?`<div style="font-size:10.5px;color:var(--mute)">최초 ${dot(c.first)}</div>`:''}</td>
        <td class="n"><b>${dtxt(c)}</b></td>
        <td><select class="inl pg" data-id="${c.id}">${D.progress.map(p=>`<option ${p===c.progress?'selected':''}>${p}</option>`).join('')}</select></td>
        <td><div class="note" contenteditable="true" data-id="${c.id}">${esc(c.note)}</div></td>
        <td style="white-space:nowrap"><button class="e" data-edit="${c.id}">고치기</button> <button class="x" data-del="${c.id}">지우기</button></td></tr>`;}).join('')}</table></div>`
      :'<div class="empty">해당하는 인증서가 없습니다.</div>';
  } else if(T==='mx'){
    const groups={}; D.products.forEach(p=>{const g=(p.cat1||'')+(p.cat2?' · '+p.cat2:''); (groups[g]=groups[g]||[]).push(p);});
    h=`<div class="mx"><table><tr><th class="p">제품</th>${D.kinds.map(k=>`<th style="text-align:center">${SHORT[k.key]}</th>`).join('')}</tr>
      ${Object.entries(groups).map(([g,ps])=>`<tr class="grp"><td class="p" colspan="${D.kinds.length+1}">${esc(g)} · ${ps.length}</td></tr>`+ps.map(p=>`<tr class="${p.discontinued?'dim':''}"><td class="p">${esc(p.name)}${p.discontinued?'<span class="tag">단종</span>':''}${p.check?'<span class="tag chk" title="이름이 겹쳐 가져올 때 ② 를 붙였습니다 — 제품 목록에서 고치세요">확인</span>':''}</td>
        ${D.kinds.map(k=>{const m=(D.matrix[p.id]||{})[k.key]; if(!m) return '<td class="c na">–</td>'; return `<td class="c ${m.state}" data-id="${m.id}" title="${esc(m.no)} · ${dot(m.end)}">${m.days===null?'예정':m.days<0?`+${-m.days}`:m.days}</td>`;}).join('')}</tr>`).join('')).join('')}</table></div>
      <div class="legend"><span>칸의 숫자는 만료까지 남은 일수 (+는 지난 일수)</span><span><i style="background:var(--acc-soft)"></i>만료 지남</span><span><i style="background:var(--ink)"></i>${D.settings.lead_soon}일 내</span><span><i style="background:var(--warn-soft)"></i>${D.settings.lead_ready}일 내</span><span><i></i>정상</span><span style="text-decoration:line-through;color:var(--faint)">갱신 안 함</span><span>– 해당 없음</span></div>`;
  } else if(T==='prod'){
    h=`<table><tr><th>구분1</th><th>구분2</th><th>제품명</th><th>단종</th><th class="n">인증 수</th><th></th></tr>
      ${D.products.map(p=>`<tr class="${p.discontinued?'dim':''}"><td><input class="inl pf" data-id="${p.id}" data-f="cat1" value="${esc(p.cat1)}" style="width:90px"></td><td><input class="inl pf" data-id="${p.id}" data-f="cat2" value="${esc(p.cat2)}" style="width:90px"></td>
        <td><input class="inl pf" data-id="${p.id}" data-f="name" value="${esc(p.name)}" style="width:260px">${p.check?'<span class="tag chk">확인</span>':''}</td>
        <td><input type="checkbox" class="pf" data-id="${p.id}" data-f="discontinued" ${p.discontinued?'checked':''}></td><td class="n">${Object.keys(D.matrix[p.id]||{}).length}</td>
        <td><button class="x" data-pdel="${p.id}">지우기</button></td></tr>`).join('')}
      <tr><td><input class="inl" id="np_cat1" placeholder="매트리스" style="width:90px"></td><td><input class="inl" id="np_cat2" placeholder="Black" style="width:90px"></td><td><input class="inl" id="np_name" placeholder="새 제품명" style="width:260px"></td><td></td><td></td><td><button class="e" id="np_add">더하기</button></td></tr></table>
      <div class="hint" style="margin-top:8px">칸을 고치고 다른 곳을 누르면 저장됩니다. 지우면 인증서의 제품 목록에서도 빠집니다(관리 비밀번호).</div>`;
  } else {
    h=`<div class="form" style="max-width:520px"><label>«준비» 표시 — 만료 며칠 전부터<input type="number" id="s_ready" value="${D.settings.lead_ready}" min="0" max="730"></label><label>«임박» 표시 — 만료 며칠 전부터<input type="number" id="s_soon" value="${D.settings.lead_soon}" min="0" max="730"></label></div>
      <div class="fbtns"><button id="s_save">저장</button><span class="msg">첫 화면 카드와 주간 보고서도 같은 기준을 씁니다. 인증 종류마다 다르게 두고 싶으면 알려 주세요.</span></div>
      <div class="hint" style="margin-top:14px">인증 종류와 기관 — ${D.kinds.map(k=>`<b>${esc(k.name)}</b>${k.org?` (${esc(k.org)})`:''}`).join(' · ')}</div>`;
  }
  $('#view').innerHTML=h;
}
function fillForm(c){
  $('#f_kind').innerHTML=D.kinds.map(k=>`<option value="${k.key}" ${c&&c.kind===k.key?'selected':''}>${esc(k.name)}</option>`).join('');
  $('#f_progress').innerHTML=D.progress.map(p=>`<option ${c&&c.progress===p?'selected':''}>${p}</option>`).join('');
  $('#ftitle').textContent=c?`인증서 고치기 — ${c.kind_name} ${c.no||''}`:'인증서 더하기';
  $('#f_no').value=c?c.no:''; $('#f_start').value=c?c.start:''; $('#f_end').value=c?c.end:''; $('#f_issued').value=c?c.issued:''; $('#f_first').value=c?c.first:''; $('#f_note').value=c?c.note:''; $('#f_check').value=c&&c.check?'1':'0';
  const have=new Set(c?c.products:[]); const groups={}; D.products.forEach(p=>{const g=(p.cat1||'')+(p.cat2?' · '+p.cat2:''); (groups[g]=groups[g]||[]).push(p);});
  $('#f_products').innerHTML=Object.entries(groups).map(([g,ps])=>`<div class="g">${esc(g)}</div>`+ps.map(p=>`<label><input type="checkbox" value="${p.id}" ${have.has(p.id)?'checked':''}>${esc(p.name)}${p.discontinued?' <span style="color:var(--faint)">(단종)</span>':''}</label>`).join('')).join('');
  cnt();
}
function cnt(){ $('#f_pn').textContent=`${$$('#f_products input:checked').length}개 선택`; }
async function post(url,body,pw){ const r=await fetch(url,{method:'POST',headers:Object.assign({'Content-Type':'application/json'},pw?{'X-Admin-Pw':pw}:{}),body:JSON.stringify(body)}); const j=await r.json().catch(()=>({})); if(!r.ok||j.ok===false){ alert(j.error||'저장하지 못했습니다'); return null; } return j; }
document.addEventListener('click',async e=>{
  const k=e.target.closest('.kpi'); if(k){ FILTER=FILTER===k.dataset.f?'':k.dataset.f; T='list'; render(); return; }
  const t=e.target.closest('#tabs button'); if(t){ T=t.dataset.t; renderView(); return; }
  const chip=e.target.closest('.chip,.mx td.c[data-id]'); if(chip){ SEL=chip.dataset.id; T='list'; FILTER=''; render(); const r=$('#r-'+SEL); if(r) r.scrollIntoView({behavior:'smooth',block:'center'}); return; }
  const ex=e.target.closest('[data-exp]'); if(ex){ EXP[ex.dataset.exp]=true; renderView(); return; }
  const cl=e.target.closest('[data-clear]'); if(cl){ await post('/인증/확인',{kind:'cert',id:cl.dataset.clear}); load(); return; }
  const ed=e.target.closest('[data-edit]'); if(ed){ SEL=ed.dataset.edit; fillForm(D.certs.find(c=>c.id===SEL)); renderView(); $('#form').scrollIntoView({behavior:'smooth',block:'start'}); return; }
  const dl=e.target.closest('[data-del]'); if(dl){ const c=D.certs.find(x=>x.id===dl.dataset.del); if(!confirm(`${c.kind_name} ${c.no||''} 인증서를 지웁니다. 되돌릴 수 없습니다.`)) return; const pw=prompt('관리 비밀번호'); if(pw===null) return; if(await post('/인증/삭제',{id:c.id},pw)){ if(SEL===c.id) SEL=''; load(); } return; }
  const pd=e.target.closest('[data-pdel]'); if(pd){ const p=D.products.find(x=>x.id===pd.dataset.pdel); if(!confirm(`${p.name} 을 제품 목록과 모든 인증서에서 뺍니다.`)) return; const pw=prompt('관리 비밀번호'); if(pw===null) return; if(await post('/인증/제품삭제',{id:p.id},pw)) load(); return; }
  if(e.target.id==='np_add'){ const name=$('#np_name').value.trim(); if(!name) return; if(await post('/인증/제품저장',{cat1:$('#np_cat1').value,cat2:$('#np_cat2').value,name})) load(); return; }
  if(e.target.id==='s_save'){ if(await post('/인증/설정',{lead_ready:+$('#s_ready').value,lead_soon:+$('#s_soon').value})) load(); return; }
  if(e.target.id==='f_all'){ e.preventDefault(); $$('#f_products input').forEach(i=>i.checked=true); cnt(); return; }
  if(e.target.id==='f_none'){ e.preventDefault(); $$('#f_products input').forEach(i=>i.checked=false); cnt(); return; }
  if(e.target.id==='f_new'){ SEL=''; fillForm(null); renderView(); return; }
  if(e.target.id==='f_save'){
    const body={id:SEL,kind:$('#f_kind').value,no:$('#f_no').value,start:$('#f_start').value,end:$('#f_end').value,issued:$('#f_issued').value,first:$('#f_first').value,progress:$('#f_progress').value,note:$('#f_note').value,check:$('#f_check').value==='1',products:$$('#f_products input:checked').map(i=>i.value)};
    if(!body.end&&!body.no){ $('#f_msg').textContent='번호나 만료일 중 하나는 적어 주세요.'; return; }
    const j=await post('/인증/저장',body); if(j){ SEL=j.id; $('#f_msg').textContent='저장했습니다.'; setTimeout(()=>$('#f_msg').textContent='',2000); load(); } return; }
  if(e.target.id==='print'){ window.print(); return; }
});
document.addEventListener('change',async e=>{
  if(e.target.matches('#f_products input')){ cnt(); return; }
  const pg=e.target.closest('select.pg'); if(pg){ const c=D.certs.find(x=>x.id===pg.dataset.id); await post('/인증/저장',Object.assign({},c,{progress:pg.value})); load(); return; }
  const pf=e.target.closest('.pf'); if(pf){ const p=Object.assign({},D.products.find(x=>x.id===pf.dataset.id)); p[pf.dataset.f]=pf.type==='checkbox'?pf.checked:pf.value; await post('/인증/제품저장',p); load(); return; }
  if(e.target.id==='imp'&&e.target.files[0]){ const pw=prompt('엑셀을 가져오면 지금 자료를 바꿔 씁니다(이전 자료는 _backup 에 남음). 관리 비밀번호'); if(pw===null){e.target.value='';return;}
    const fd=new FormData(); fd.append('file',e.target.files[0]); const r=await fetch('/인증/가져오기',{method:'POST',headers:{'X-Admin-Pw':pw},body:fd}); const j=await r.json().catch(()=>({}));
    if(!r.ok||j.ok===false) alert(j.error||'가져오지 못했습니다'); else alert(`제품 ${j.products}개 · 인증서 ${j.certs}건을 가져왔습니다. 확인 필요 ${j.check}건.`); e.target.value=''; load(); }
});
document.addEventListener('focusout',async e=>{ const n=e.target.closest('.note[contenteditable]'); if(n){ const c=D.certs.find(x=>x.id===n.dataset.id); const v=n.textContent.trim(); if(v!==c.note){ await post('/인증/저장',Object.assign({},c,{note:v})); load(); } } });
document.addEventListener('keydown',e=>{ if(e.target.closest('.note[contenteditable]')&&e.key==='Enter'){ e.preventDefault(); e.target.blur(); } });
load();
</script></body></html>
"""
