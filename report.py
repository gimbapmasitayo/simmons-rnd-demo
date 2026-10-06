# -*- coding: utf-8 -*-
"""주간 보고서 — 지난주의 ★ 기사·회사별 소식·신제품·법령 변경·홈페이지 변화·성적서 실적을 A4 한두 장으로.

  · 매주 월요일 아침 수집이 끝나면 지난주(월~일) 보고서를 보고서/ 폴더에 PDF 로 떨어뜨린다 (weekly_if_due).
  · 화면(/보고서)에서 아무 주나 골라 다시 만들 수 있다. PDF 는 크롬 headless 로 /보고서/미리보기 를 인쇄한 것.
  · 사내 서버 안에서만 돈다. 밖으로 나가는 요청은 없다.
"""
import os, io, re, json, datetime, subprocess, tempfile, shutil, threading, html

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "보고서")
STATE = os.path.join(HERE, "보고서상태.json")
CHROME = next((p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
BASE_URL = "http://127.0.0.1:5000"
_busy = {"on": False, "msg": ""}
_lock = threading.Lock()


def week_of(d):
    """d 가 속한 주의 (월요일, 일요일)."""
    mon = d - datetime.timedelta(days=d.weekday())
    return mon, mon + datetime.timedelta(days=6)


def last_week(today=None):
    today = today or datetime.date.today()
    mon, _ = week_of(today)
    return week_of(mon - datetime.timedelta(days=1))


def fname(d_from, d_to):
    return "주간보고_%s_%s.pdf" % (d_from.isoformat(), d_to.isoformat())


# ═══════════════════════════════════════════════ 내용 모으기
def gather(d_from, d_to):
    import news, trend, products, stats
    days = (datetime.date.today() - d_from).days + 1
    out = {"from": d_from.isoformat(), "to": d_to.isoformat(), "made": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}

    # 뉴스 — 기간 안 소식 (같은 소식은 묶여서 옴)
    q = news.query(days=max(days, 1))
    rows = [r for r in q["rows"] if d_from.isoformat() <= (r.get("date") or r.get("fetched") or "")[:10] <= d_to.isoformat()]
    out["news_n"], out["news_raw"] = len(rows), sum(r["n_src"] for r in rows)
    out["stars"] = [r for r in rows if r.get("star")]
    by_co = {}
    for r in rows:
        by_co.setdefault(r["company"], []).append(r)
    order = [c for _, c in q["companies"] if c in by_co]
    grp = dict(q["companies"])
    out["companies"] = [{"company": c, "group": grp.get(c, ""), "n": len(by_co[c]),
                         "top": sorted(by_co[c], key=lambda r: (not r.get("star"), -r["n_src"]))[:3]} for c in order]
    tags = {}
    for r in rows:
        for t in r.get("tags", []):
            tags[t] = tags.get(t, 0) + 1
    out["tags"] = sorted(tags.items(), key=lambda x: -x[1])

    # 신제품 보드 (뉴스 + 홈페이지)
    try:
        b = trend.board(3)
        items = []
        for c in b["companies"]:
            for m in b["months"]:
                for a in b["cells"][c][m]:
                    if d_from.isoformat() <= (a.get("date") or "")[:10] <= d_to.isoformat():
                        items.append(dict(a, company=c))
        out["newprod"] = items
    except Exception:
        out["newprod"] = []

    # 규격·법령
    try:
        r = trend.regs(days)
        out["law"] = [x for x in r["rows"] if x["type"] == "law_change" and d_from.isoformat() <= (x.get("date") or x.get("fetched") or "")[:10] <= d_to.isoformat()]
        out["kats"] = [x for x in r["rows"] if x["type"] == "kats" and d_from.isoformat() <= (x.get("date") or x.get("fetched") or "")[:10] <= d_to.isoformat()]
        out["laws_n"] = len(r["laws"])
    except Exception:
        out["law"], out["kats"], out["laws_n"] = [], [], 0

    # 홈페이지 제품 변화
    try:
        p = products.data(days)
        ch = [c for c in p["changes"] if d_from.isoformat() <= c["date"] <= d_to.isoformat()]
        out["prod_changes"] = ch
        out["prod_tracked"] = sum(c["n"] for c in p["companies"])
        out["prod_cos"] = len(p["companies"])
    except Exception:
        out["prod_changes"], out["prod_tracked"], out["prod_cos"] = [], 0, 0

    # 성적서 실적
    try:
        s = stats.settings()
        wk = stats.summarize(stats.load(), s, d_from, d_to)["total"]
        yr = stats.summarize(stats.load(), s, d_from.replace(month=1, day=1), d_to)["total"]
        out["stats"] = {"n": wk["count"], "saved_h": wk["saved_h"], "by_kind": wk["by_kind"],
                        "year_n": yr["count"], "year_saved_h": yr["saved_h"]}
    except Exception:
        out["stats"] = None
    return out


# ═══════════════════════════════════════════════ 보고서 HTML (독립 문서 — 사이드바 없음)
def _e(s):
    return html.escape(str(s if s is not None else ""))


def render(d):
    f, t = d["from"], d["to"]
    def dk(s):
        return s[5:].replace("-", ".")
    def dt(s):
        return (s or "")[5:10].replace("-", ".")
    h = ['<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>주간 보고 %s ~ %s</title>' % (dk(f), dk(t)),
         '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" onerror="this.remove()">',
         '''<style>
:root{--ink:#0f0f11;--ink-2:#3a3a40;--mute:#84848a;--line:#e3e0d9;--line-2:#eeebe4;--acc:#8c3325}
*{box-sizing:border-box}@page{size:A4;margin:14mm 14mm 16mm}
body{margin:0;color:var(--ink);font:12px/1.55 "Pretendard Variable",Pretendard,"Malgun Gothic",system-ui,sans-serif;background:#fff}
.page{max-width:740px;margin:0 auto;padding:28px 20px 40px}
.eyebrow{font-size:10px;letter-spacing:.22em;color:var(--mute);font-weight:600}
h1{font-size:24px;font-weight:700;letter-spacing:-.02em;margin:4px 0 2px}
.sub{font-size:11.5px;color:var(--mute);margin-bottom:18px}
.tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin-bottom:18px}
.tile{background:#fff;padding:10px 12px 9px}
.tile .k{font-size:10px;color:var(--mute);font-weight:600}
.tile .v{font-size:24px;font-weight:700;letter-spacing:-.03em;line-height:1.1;margin:4px 0 3px;font-variant-numeric:tabular-nums}
.tile .v small{font-size:10px;color:var(--mute);font-weight:500;margin-left:2px}
.tile .s{font-size:10px;color:var(--ink-2);line-height:1.4}
h2{font-size:13px;font-weight:700;margin:18px 0 6px;padding-bottom:4px;border-bottom:1px solid var(--line);break-after:avoid}
h2 small{font-weight:500;color:var(--mute);font-size:10.5px;margin-left:8px}
.it{display:grid;grid-template-columns:1fr auto;gap:0 10px;padding:5px 0;border-bottom:1px solid var(--line-2);break-inside:avoid}
.it .t{font-size:12px;font-weight:500}
.it .t a{color:inherit;text-decoration:none}
.it .m{font-size:10.5px;color:var(--mute);margin-top:1px}
.it .m b{color:var(--ink-2);font-weight:600}
.it .memo{font-size:11px;color:var(--ink-2);margin-top:3px;padding:3px 8px;background:#f7f5f0;border-left:2px solid var(--line)}
.it .d{font-size:10.5px;color:var(--mute);white-space:nowrap;font-variant-numeric:tabular-nums}
.star .t::before{content:"★ ";color:var(--acc)}
.cos{display:grid;grid-template-columns:1fr 1fr;gap:0 24px}
.co{padding:6px 0;border-bottom:1px solid var(--line-2);break-inside:avoid}
.co .h{display:flex;justify-content:space-between;font-size:12px;font-weight:700}
.co .h span{font-weight:500;color:var(--mute);font-size:10.5px}
.co a{display:block;color:var(--ink-2);text-decoration:none;font-size:11px;line-height:1.45;padding:1px 0}
.co a small{color:var(--mute);margin-left:4px}
.law{background:var(--acc);color:#fff;font-size:9.5px;padding:0 6px;border-radius:8px;margin-right:6px;vertical-align:1px}
.tag{display:inline-block;font-size:9.5px;padding:0 6px;border:1px solid var(--line);border-radius:8px;color:var(--mute);margin-right:4px}
.none{color:var(--mute);font-size:11.5px;padding:6px 0}
.foot{margin-top:22px;font-size:10px;color:var(--mute);line-height:1.6;border-top:1px solid var(--line);padding-top:8px}
table{width:100%;border-collapse:collapse;font-size:11px}
th{font-size:9.5px;letter-spacing:.08em;color:var(--mute);font-weight:600;text-align:left;padding:4px 6px;border-bottom:1px solid var(--line)}
td{padding:4px 6px;border-bottom:1px solid var(--line-2);vertical-align:top}
td.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
</style></head><body><div class="page">''']
    h.append('<div class="eyebrow">시몬스 연구소 · R&amp;D 주간 보고</div><h1>%s ~ %s</h1>' % (dk(f), dk(t)))
    h.append('<div class="sub">자동 작성 %s · 경쟁사 뉴스 클리핑, R&amp;D 동향, 경쟁사 제품 현황, 성적서 실적에서 모았습니다</div>' % _e(d["made"]))

    st = d.get("stats") or {}
    law_n, kats_n = len(d["law"]), len(d["kats"])
    ch = d["prod_changes"]
    nch = {"new": 0, "removed": 0, "price": 0}
    for c in ch:
        nch[c["type"]] = nch.get(c["type"], 0) + 1
    h.append('<div class="tiles">')
    h.append('<div class="tile"><div class="k">경쟁사 소식</div><div class="v">%d<small>건</small></div><div class="s">기사 %d건 · 중요 ★ %d건</div></div>' % (d["news_n"], d["news_raw"], len(d["stars"])))
    h.append('<div class="tile"><div class="k">신제품·기술 발표</div><div class="v">%d<small>건</small></div><div class="s">%s</div></div>'
             % (len(d["newprod"]), _e(" · ".join(sorted({x["company"] for x in d["newprod"]})[:4]) or "발표 없음")))
    h.append('<div class="tile"><div class="k">법령·고시 변경</div><div class="v"%s>%d<small>건</small></div><div class="s">%s</div></div>'
             % ('' if law_n else ' style="color:#23573f"', law_n, ("국표원 공고 %d건" % kats_n) if kats_n else ("지켜보는 %d개 모두 그대로" % d["laws_n"])))
    h.append('<div class="tile"><div class="k">홈페이지 제품 변화</div><div class="v">%d<small>건</small></div><div class="s">신제품 %d · 단종 %d · 가격 %d</div></div>' % (len(ch), nch["new"], nch["removed"], nch["price"]))
    if st:
        h.append('<div class="tile"><div class="k">성적서 자동 작성</div><div class="v">%d<small>건</small></div><div class="s">절감 %s시간 · 올해 %d건 %s시간</div></div>' % (st["n"], st["saved_h"], st["year_n"], st["year_saved_h"]))
    else:
        h.append('<div class="tile"><div class="k">성적서 자동 작성</div><div class="v">–</div><div class="s">실적 기록 없음</div></div>')
    h.append('</div>')

    # ★ 중요
    h.append('<h2>중요 기사 ★<small>담당자가 표시한 것</small></h2>')
    if d["stars"]:
        for r in d["stars"]:
            h.append('<div class="it star"><div><div class="t"><a href="%s">%s</a></div><div class="m"><b>%s</b> · %s%s%s</div>%s</div><div class="d">%s</div></div>'
                     % (_e(r["link"]), _e(r["title"]), _e(r["company"]), _e(r["source"]),
                        (" 외 %d곳" % (r["n_src"] - 1)) if r["n_src"] > 1 else "",
                        "".join(' <span class="tag">%s</span>' % _e(t) for t in r.get("tags", [])),
                        ('<div class="memo">%s</div>' % _e(r["memo"])) if r.get("memo") else "", dt(r.get("date"))))
    else:
        h.append('<div class="none">이번 주에 ★ 표시한 기사가 없습니다. 아래 회사별 소식에서 가장 많이 보도된 것을 먼저 보세요.</div>')

    # 법령 변경
    if d["law"] or d["kats"]:
        h.append('<h2>규격·법령<small>우리 시험의 근거</small></h2>')
        for x in d["law"]:
            h.append('<div class="it"><div><div class="t"><span class="law">법령 변경</span><a href="%s">%s</a></div><div class="m">%s%s</div></div><div class="d">%s</div></div>'
                     % (_e(x["link"]), _e(x["title"]), _e(x.get("detail", "")), (" · " + _e(x["why"])) if x.get("why") else "", dt(x.get("date"))))
        for x in d["kats"][:8]:
            h.append('<div class="it"><div><div class="t"><a href="%s">%s</a></div><div class="m"><b>국가기술표준원</b></div></div><div class="d">%s</div></div>' % (_e(x["link"]), _e(x["title"]), dt(x.get("date"))))

    # 신제품
    h.append('<h2>경쟁사 신제품·기술<small>뉴스 + 홈페이지</small></h2>')
    if d["newprod"]:
        for a in sorted(d["newprod"], key=lambda a: a.get("date") or "", reverse=True)[:14]:
            h.append('<div class="it"><div><div class="t"><a href="%s">%s</a></div><div class="m"><b>%s</b> · %s</div></div><div class="d">%s</div></div>'
                     % (_e(a["link"]), _e(a["title"]), _e(a["company"]), _e(a["source"]), dt(a.get("date"))))
    else:
        h.append('<div class="none">이번 주 신제품·기술 발표가 없습니다.</div>')

    # 홈페이지 변화
    if ch:
        h.append('<h2>경쟁사 홈페이지 변화<small>%d개사 %d개 제품 추적</small></h2><table><tr><th>날짜</th><th>회사</th><th>구분</th><th>제품</th><th class="n">가격</th></tr>' % (d["prod_cos"], d["prod_tracked"]))
        K = {"new": "신제품", "removed": "단종", "price": "가격"}
        for c in ch[:20]:
            price = ("%s → %s" % (format(c.get("old") or 0, ","), format(c.get("price") or 0, ","))) if c["type"] == "price" else (format(c["price"], ",") if c.get("price") else "")
            h.append('<tr><td>%s</td><td>%s</td><td>%s</td><td><a href="%s" style="color:inherit;text-decoration:none">%s</a> <span style="color:var(--mute)">%s</span></td><td class="n">%s</td></tr>'
                     % (dt(c["date"]), _e(c["company"]), K.get(c["type"], c["type"]), _e(c["link"]), _e(c["name"]), _e(c.get("cat", "")), price))
        h.append('</table>')

    # 회사별 소식
    h.append('<h2>회사별 소식<small>소식 수 · 많이 보도된 순 3개</small></h2>')
    if d["companies"]:
        h.append('<div class="cos">')
        for c in d["companies"]:
            h.append('<div class="co"><div class="h">%s<span>%s · %d건</span></div>%s</div>'
                     % (_e(c["company"]), _e(c["group"]), c["n"],
                        "".join('<a href="%s">%s%s<small>%s%s</small></a>' % (_e(r["link"]), "★ " if r.get("star") else "", _e(r["title"]), _e(r["source"]),
                                                                           (" 외 %d곳" % (r["n_src"] - 1)) if r["n_src"] > 1 else "") for r in c["top"])))
        h.append('</div>')
    else:
        h.append('<div class="none">이 기간에 모인 기사가 없습니다.</div>')
    if d["tags"]:
        h.append('<div style="margin-top:8px;font-size:10.5px;color:var(--mute)">주제별: %s</div>' % " · ".join("%s %d" % (_e(t), n) for t, n in d["tags"]))

    h.append('<div class="foot">기사 제목과 링크는 뉴스 검색이 제공한 그대로이며 본문은 저장하지 않습니다. 홈페이지 변화는 각사 공개 페이지의 표시 가격 기준입니다. '
             '성적서 절감 시간은 성적서 실적 설정의 기준 시간으로 계산한 추정치입니다. 사내망 전용.</div>')
    h.append('</div></body></html>')
    return "".join(h)


# ═══════════════════════════════════════════════ PDF
def make_pdf(d_from, d_to):
    """크롬으로 /보고서/미리보기 를 인쇄해 보고서/ 폴더에 PDF 로. 돌려주는 값은 파일 이름."""
    if not CHROME:
        raise RuntimeError("이 PC에 크롬이 없어 PDF 를 만들 수 없습니다")
    os.makedirs(DIR, exist_ok=True)
    out = os.path.join(DIR, fname(d_from, d_to))
    url = "%s/%s?from=%s&to=%s" % (BASE_URL, "보고서/미리보기", d_from.isoformat(), d_to.isoformat())
    prof = tempfile.mkdtemp(prefix="rdhub_pdf_")
    try:
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir=" + prof,
               "--no-pdf-header-footer", "--virtual-time-budget=5000", "--print-to-pdf=" + out, url]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if not os.path.exists(out) or os.path.getsize(out) < 1000:
            raise RuntimeError("크롬이 PDF 를 만들지 못했습니다: %s" % r.stderr.decode("utf-8", "replace")[-200:])
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return os.path.basename(out)


def make_async(d_from, d_to):
    if _busy["on"]:
        return False
    def run():
        _busy["on"], _busy["msg"] = True, "%s ~ %s" % (d_from, d_to)
        try:
            name = make_pdf(d_from, d_to)
            _set_state(last=name, error="")
        except Exception as e:
            _set_state(error=str(e)[:200])
        finally:
            _busy["on"], _busy["msg"] = False, ""
    threading.Thread(target=run, daemon=True).start()
    return True


def _state():
    try:
        return json.load(io.open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def _set_state(**kw):
    with _lock:
        st = _state()
        st.update(kw)
        st["at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        tmp = STATE + ".tmp"
        json.dump(st, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STATE)


def weekly_if_due(logger=None):
    """월요일 아침 수집 뒤에 불린다. 지난주 보고서가 없으면 만든다."""
    today = datetime.date.today()
    if today.weekday() != 0:
        return
    a, b = last_week(today)
    if os.path.exists(os.path.join(DIR, fname(a, b))):
        return
    try:
        make_pdf(a, b)
        _set_state(last=fname(a, b), error="")
    except Exception as e:
        _set_state(error=str(e)[:200])
        if logger:
            logger.exception("주간 보고서 생성 실패")


def files():
    os.makedirs(DIR, exist_ok=True)
    out = []
    for fn in os.listdir(DIR):
        m = re.match(r"주간보고_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.pdf$", fn)
        if m:
            p = os.path.join(DIR, fn)
            out.append({"name": fn, "from": m.group(1), "to": m.group(2), "size_kb": round(os.path.getsize(p) / 1024.0),
                        "made": datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")})
    out.sort(key=lambda x: x["from"], reverse=True)
    return out


def data():
    a, b = last_week()
    return {"files": files(), "busy": _busy["on"], "msg": _busy["msg"], "state": _state(),
            "last_week": [a.isoformat(), b.isoformat()], "chrome": bool(CHROME)}


# ═══════════════════════════════════════════════ 화면
PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>주간 보고서</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" onerror="this.remove()">
<style>
:root{--ink:#0f0f11;--ink-2:#3a3a40;--mute:#84848a;--faint:#b4b4b9;--line:#e3e0d9;--line-2:#eeebe4;--paper:#fff;--bg:#f1efea;--black:#0a0a0b;--acc:#8c3325;--ok:#23573f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Pretendard Variable",Pretendard,"Malgun Gothic",system-ui,sans-serif}
__NAVCSS__
.wrap{max-width:1000px;margin:0 auto;padding:44px 40px 90px}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;flex-wrap:wrap;margin-bottom:8px}
.eyebrow{font-size:11px;letter-spacing:.2em;color:var(--mute);font-weight:600}
h1{font-size:30px;font-weight:700;letter-spacing:-.02em;margin:4px 0 0}
.status{font-size:12.5px;color:var(--mute);text-align:right;line-height:1.7}
.lead{font-size:14px;color:var(--ink-2);max-width:760px;margin:10px 0 24px;line-height:1.7}
.card{background:var(--paper);border:1px solid var(--line);padding:22px 24px;margin-bottom:20px}
.card h2{font-size:15px;font-weight:700;margin:0 0 4px}
.card .hint{font-size:12.5px;color:var(--mute);margin-bottom:14px;line-height:1.6}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.row label{font-size:11px;letter-spacing:.1em;color:var(--mute);font-weight:600}
.row input{font:inherit;font-size:13px;padding:7px 10px;border:1px solid var(--line);background:#fff}
.row button,.btn{font:inherit;font-size:12.5px;padding:8px 14px;background:var(--black);color:#fff;border:none;cursor:pointer}
.row button.ghost,.btn.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
.row button[disabled]{background:var(--faint);cursor:default}
.msg{font-size:12.5px;color:var(--ok)}
.msg.err{color:var(--acc)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{font-size:10.5px;letter-spacing:.1em;color:var(--mute);font-weight:600;text-align:left;padding:8px;border-bottom:1px solid var(--line)}
td{padding:9px 8px;border-bottom:1px solid var(--line-2);vertical-align:middle}
td a{color:var(--ink);text-decoration:none;font-weight:600}
td a:hover{text-decoration:underline;text-underline-offset:3px}
td .sm{font-size:11.5px;color:var(--mute)}
.empty{padding:30px;text-align:center;color:var(--mute);line-height:1.8}
.frame{width:100%;height:1100px;border:1px solid var(--line);background:#fff}
@media(max-width:900px){.wrap{padding:28px 16px 70px}}
</style></head><body>
__NAV__
<div class="wrap">
<div class="head"><div><div class="eyebrow">시몬스 연구소</div><h1>주간 보고서</h1></div><div class="status" id="status"></div></div>
<div class="lead">매주 월요일 아침, 지난주(월~일)의 ★ 기사·회사별 소식·신제품·법령 변경·홈페이지 변화·성적서 실적을 A4 한두 장 PDF 로 만들어 둡니다. 포털에 들어오지 않는 분께는 이 파일을 보내면 됩니다.</div>

<div class="card"><h2>만들기</h2><div class="hint">기간을 고르고 누르면 10초쯤 뒤 아래 목록에 생깁니다. 같은 기간을 다시 만들면 덮어씁니다.</div>
  <div class="row"><label>시작</label><input type="date" id="from"><label>끝</label><input type="date" id="to">
    <button id="make">PDF 만들기</button><button class="ghost" id="preview">화면으로 미리보기</button><button class="ghost" id="lastweek">지난주로</button><span class="msg" id="msg"></span></div></div>

<div class="card"><h2>만들어 둔 보고서</h2><div class="hint">파일 이름을 누르면 PDF 가 내려받아집니다. 서버의 보고서 폴더에도 같은 파일이 있습니다.</div><div id="list"></div></div>
<div class="card" id="pv" style="display:none"><h2>미리보기</h2><iframe class="frame" id="frame"></iframe></div>
</div>
<script>
const $=s=>document.querySelector(s); let D=null;
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
async function load(){ D=await (await fetch('/보고서/data')).json(); render(); }
function render(){
  if(!$('#from').value){ $('#from').value=D.last_week[0]; $('#to').value=D.last_week[1]; }
  const st=D.state||{};
  $('#status').innerHTML=D.busy?`<b>만드는 중…</b> ${esc(D.msg)}`:(st.last?`마지막 생성 <b>${esc(st.last)}</b> · ${esc(st.at||'')}`:'아직 만든 보고서가 없습니다')+(st.error?`<br><span style="color:var(--acc)">${esc(st.error)}</span>`:'');
  $('#make').disabled=D.busy||!D.chrome; if(!D.chrome) $('#msg').textContent='이 PC에 크롬이 없어 PDF 를 만들 수 없습니다. 미리보기로 보고 브라우저에서 인쇄하세요.';
  $('#list').innerHTML=D.files.length?`<table><tr><th>기간</th><th>파일</th><th>만든 시각</th><th>크기</th></tr>${D.files.map(f=>`<tr><td><b>${f.from.slice(5).replace('-','.')} ~ ${f.to.slice(5).replace('-','.')}</b><div class="sm">${f.from.slice(0,4)}년</div></td><td><a href="/보고서/파일/${encodeURIComponent(f.name)}" download>${esc(f.name)}</a></td><td>${esc(f.made)}</td><td>${f.size_kb} KB</td></tr>`).join('')}</table>`:`<div class="empty">아직 없습니다. 위에서 기간을 고르고 «PDF 만들기» 를 누르세요.<br>월요일 아침 수집이 끝나면 자동으로 지난주 것이 생깁니다.</div>`;
}
document.addEventListener('click',async e=>{
  if(e.target.id==='lastweek'){ $('#from').value=D.last_week[0]; $('#to').value=D.last_week[1]; return; }
  if(e.target.id==='preview'){ $('#pv').style.display='block'; $('#frame').src=`/보고서/미리보기?from=${$('#from').value}&to=${$('#to').value}`; $('#pv').scrollIntoView({behavior:'smooth'}); return; }
  if(e.target.id==='make'){ const r=await (await fetch('/보고서/생성',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:$('#from').value,to:$('#to').value})})).json();
    $('#msg').className='msg'+(r.ok?'':' err'); $('#msg').textContent=r.ok?'만드는 중입니다…':(r.error||'시작하지 못했습니다'); setTimeout(load,1000); return; }
});
load(); setInterval(()=>{ if(D&&D.busy) load(); },2500);
</script></body></html>"""


def page(build=""):
    import portal
    return PAGE.replace("__NAV__", portal.nav("/보고서", "", build)).replace("__NAVCSS__", portal.NAV_CSS)
