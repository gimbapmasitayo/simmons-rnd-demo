# -*- coding: utf-8 -*-
"""연구소 포털의 틀 — 이름 · 메뉴 · 공통 위 막대 · 첫 화면.

페이지가 늘면 MENU 에 한 줄 더하면 된다. 위 막대(topbar)는 모든 페이지가 이 모듈의
nav() 로 그리므로 메뉴가 한 곳에서 바뀐다. 포털 이름은 BRAND / TITLE 두 상수.
"""
import html, os, io, json

BRAND = "SIMMONS R&D"          # 위 막대 왼쪽에 박히는 영문 표기
TITLE = "시몬스 R&D"           # 브라우저 탭 · 첫 화면 제목

# (주소, 메뉴 이름, 첫 화면 카드의 한 줄 설명, 카드 번호)
MENU = (
    ("/성적서", "성적서 자동화", "측정 장비 파일을 올리면 계산·판정·양식 작성이 끝납니다. 라돈·토론 완제품, 라돈 원자재, 매트리스 KC·KS.", "01"),
    ("/실적",   "성적서 실적",   "자동 작성한 성적서 건수와 절감한 시간. 임원 보고용 한 장으로 인쇄됩니다.", "02"),
    ("/뉴스",   "경쟁사 뉴스 클리핑", "평일 아침 8시에 뉴스 검색으로 경쟁사·업계 기사를 모읍니다. 중요 표시와 메모로 월간 보고를 준비합니다.", "03"),
    ("/동향",   "R&D 동향", "경쟁사 신제품 보드, 우리 시험의 근거 법령·고시 변경 감시, 경쟁사 특허 출원 동향.", "04"),
    ("/제품",   "경쟁사 제품 현황", "경쟁사 홈페이지의 매트리스 목록을 매일 읽어 신제품·단종·가격 변동을 잡습니다.", "05"),
    ("/보고서", "주간 보고서", "매주 월요일 지난주의 ★ 기사·신제품·법령 변경·제품 변화·실적을 A4 한두 장 PDF 로 만들어 둡니다.", "06"),
    ("/일정",   "전시회·학회 일정", "침대·매트리스·수면·소재 분야 전시회와 학회, 국표원 설명회 일정.", "07"),
    ("/규격",   "시험 규격 요약집", "KS G 4300, KC 부속서 19, 라돈 법령의 핵심 수치와 최근 개정일을 한 장에.", "08"),
    ("/인증",   "인증 현황", "보유 인증 7종(환경표지·라돈·토론·비건·PS·UL·더마테스트)의 만료일을 한 장에. 90일 전 준비, 30일 전 임박을 첫 화면에 올립니다.", "09"),
)

SETTINGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "포털설정.json")
DEFAULT_ADMIN_PW = "simmons"          # 열쇠(네이버·KIPRIS)를 저장할 때 묻는 비밀번호. 포털설정.json 에서 바꾼다


def admin_pw():
    """.env 의 ADMIN_PW → 옛 포털설정.json → 기본값."""
    import config
    pw = config.get("ADMIN_PW")
    if pw:
        return pw
    try:
        return json.load(io.open(SETTINGS, encoding="utf-8")).get("admin_pw") or DEFAULT_ADMIN_PW
    except Exception:
        return DEFAULT_ADMIN_PW


def show_soon():
    """«준비 중» 메뉴를 보여줄지. .env 의 PORTAL_SHOW_SOON=1 또는 포털설정.json 의 show_soon."""
    import config
    v = config.get("PORTAL_SHOW_SOON")
    if v:
        return v.strip() in ("1", "true", "yes", "on")
    try:
        return bool(json.load(io.open(SETTINGS, encoding="utf-8")).get("show_soon"))
    except Exception:
        return False


def admin_ok(request):
    return (request.headers.get("X-Admin-Pw") or "") == admin_pw()


NAV_CSS = """
:root{--side:232px}
body{padding-left:var(--side)}
.side{position:fixed;left:0;top:0;bottom:0;width:var(--side);background:#0a0a0b;color:#fff;z-index:30;display:flex;flex-direction:column;padding:26px 0 18px}
.side .mark{display:block;font-size:12.5px;font-weight:800;letter-spacing:.3em;color:#fff;text-decoration:none;padding:0 26px 22px;line-height:1.3;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:14px}
.side .sec{font-size:10px;letter-spacing:.2em;color:rgba(255,255,255,.38);font-weight:600;padding:12px 26px 6px}
.side nav a{display:flex;align-items:center;gap:12px;color:rgba(255,255,255,.66);text-decoration:none;font-size:13.5px;font-weight:500;padding:11px 26px;border-left:3px solid transparent}
.side nav a i{font-style:normal;font-size:10px;letter-spacing:.1em;color:rgba(255,255,255,.35);width:18px;flex:none}
.side nav a:hover{color:#fff;background:rgba(255,255,255,.06)}
.side nav a.on{color:#fff;background:rgba(255,255,255,.1);border-left-color:#fff}
.side nav a.soon{color:rgba(255,255,255,.28);pointer-events:none}
.side .tools{margin-top:auto;padding:14px 26px 0;border-top:1px solid rgba(255,255,255,.1);display:flex;flex-direction:column;gap:2px}
.side .tools a,.side .tools button{color:rgba(255,255,255,.62);text-decoration:none;font:inherit;font-size:12.5px;background:none;border:none;cursor:pointer;text-align:left;padding:7px 0;letter-spacing:.02em}
.side .tools a:hover,.side .tools button:hover{color:#fff}
.side .ver{font-size:10.5px;font-weight:500;letter-spacing:.06em;color:rgba(255,255,255,.35);padding:12px 26px 0;margin:0;text-align:left;white-space:nowrap}
#bar{left:var(--side)!important}   /* 성적서 페이지 아래 고정 막대만 */
@media(max-width:900px){:root{--side:0px}body{padding-left:0}.side{position:sticky;bottom:auto;width:auto;flex-direction:row;align-items:center;padding:0 12px;height:52px;overflow-x:auto}
  .side .mark{padding:0 14px 0 6px;border:none;margin:0;white-space:nowrap}.side .sec,.side .ver{display:none}.side nav{display:flex}.side nav a{padding:8px 10px;border-left:none;font-size:12.5px}.side nav a i{display:none}
  .side .tools{margin-top:0;margin-left:auto;padding:0;border:none;flex-direction:row;gap:12px}}
@media print{.side{display:none}body{padding-left:0}}
"""


SOON = (("R&D 과제 탐색", "10"),)   # 아직 자리만 있는 메뉴


def nav(active, right="", build=""):
    """공통 왼쪽 사이드바. active 는 현재 페이지 주소, right 는 아래 도구 칸에 끼울 HTML(버튼·링크)."""
    links = "".join(
        '<a href="%s"%s><i>%s</i>%s</a>' % (html.escape(path), ' class="on"' if path == active else "",
                                             no, html.escape(name))
        for path, name, _, no in MENU)
    if show_soon():
        links += "".join('<a class="soon"><i>%s</i>%s</a>' % (no, html.escape(name)) for name, no in SOON)
    tools = '<div class="tools">%s</div>' % right if right else ""
    return ('<aside class="side"><a class="mark" href="/">%s</a>'
            '<div class="sec">프로그램</div><nav>%s</nav>%s'
            '<div class="ver">%s</div></aside>' % (html.escape(BRAND), links, tools, html.escape(build)))


def brief():
    """첫 화면 보고판에 쓰는 숫자와 주목할 항목. 다른 모듈을 여기서만 불러 순환 참조를 피한다."""
    import datetime, news, trend, products, stats
    today = datetime.date.today()
    out = {"date": today.isoformat(), "tiles": [], "notes": []}

    # 1. 성적서 실적 — 이번 달 / 올해
    try:
        rows, st = stats.load(), stats.settings()
        mon = stats.summarize(rows, st, today.replace(day=1), today)["total"]
        year = stats.summarize(rows, st, today.replace(month=1, day=1), today)["total"]
        out["tiles"].append({"href": "/실적", "k": "성적서 자동 작성 · 이번 달", "v": mon["count"], "u": "건",
                             "s": ("절감 %s시간 · 올해 %d건 %s시간" % (mon["saved_h"], year["count"], year["saved_h"]))
                                  if year["count"] else "아직 자동 작성한 성적서가 없습니다"})
    except Exception as e:
        out["tiles"].append({"href": "/실적", "k": "성적서 자동 작성 · 이번 달", "v": "–", "u": "", "s": "읽지 못했습니다"})

    # 2. 경쟁사 뉴스 — 오늘 / 7일 ★
    try:
        q = news.query(days=7)
        rows = q["rows"]
        n_today = sum(1 for r in rows if (r.get("date") or r.get("fetched") or "")[:10] == today.isoformat())
        stars = [r for r in rows if r.get("star")]
        out["tiles"].append({"href": "/뉴스", "k": "경쟁사 뉴스 · 지난 7일", "v": len(rows), "u": "건",
                             "s": "오늘 들어온 기사 %d건 · 중요 표시(★) %d건" % (n_today, len(stars))})
        for r in stars[:6]:
            out["notes"].append({"tag": "중요 기사", "href": r["link"], "title": r["title"],
                                 "sub": "%s · %s · %s" % (r["company"], r["source"], (r.get("date") or "")[:10]),
                                 "memo": r.get("memo", "")})
        out["news_latest"] = [{"title": r["title"], "href": r["link"], "sub": "%s · %s" % (r["company"], r["source"])}
                              for r in rows[:5]]
    except Exception:
        out["tiles"].append({"href": "/뉴스", "k": "경쟁사 뉴스 · 지난 7일", "v": "–", "u": "", "s": "읽지 못했습니다"})

    # 3. 신제품 (뉴스 + 홈페이지) · 최근 2개월
    try:
        b = trend.board(2)
        cells = [(c, m, a) for c in b["companies"] for m in b["months"] for a in b["cells"][c][m]]
        this_m = [x for x in cells if x[1] == today.strftime("%Y-%m")]
        cos = sorted({c for c, _, _ in this_m})
        out["tiles"].append({"href": "/동향", "k": "경쟁사 신제품·기술 · 이번 달", "v": len(this_m), "u": "건", "ok": not this_m,
                             "s": (("발표한 회사: " + " · ".join(cos[:5]) + (" 외" if len(cos) > 5 else "")) if cos
                                   else "이번 달 경쟁사 발표 없음 ✓")})
    except Exception:
        out["tiles"].append({"href": "/동향", "k": "경쟁사 신제품·기술 · 이번 달", "v": "–", "u": "", "s": "읽지 못했습니다"})

    # 4. 규격·법령 · 30일
    try:
        r = trend.regs(30)
        law = [x for x in r["rows"] if x["type"] == "law_change"]
        kats = [x for x in r["rows"] if x["type"] == "kats"]
        out["tiles"].append({"href": "/동향", "k": "규격·법령 변경 · 30일", "v": len(law), "u": "건", "ok": not law,
                             "s": ("지켜보는 법령·고시 %d개 모두 그대로 ✓" % len(r["laws"]) + (" · 국표원 공고 %d건" % len(kats) if kats else "")) if not law
                                  else "국표원 공고 %d건 · 아래 «주목할 것» 참고" % len(kats)})
        for x in law[:4]:
            out["notes"].append({"tag": "법령 변경", "href": x["link"], "title": x["title"],
                                 "sub": (x.get("detail") or "") + (" · " + x["why"] if x.get("why") else ""), "memo": x.get("memo", "")})
    except Exception:
        out["tiles"].append({"href": "/동향", "k": "규격·법령 변경 · 30일", "v": "–", "u": "", "s": "읽지 못했습니다"})

    # 5. 홈페이지 제품 변화 · 7일
    try:
        p = products.data(7)
        ch = p["changes"]
        n = {"new": 0, "removed": 0, "price": 0}
        for c in ch:
            n[c["type"]] = n.get(c["type"], 0) + 1
        tracked = sum(c["n"] for c in p["companies"])
        out["tiles"].append({"href": "/제품", "k": "경쟁사 홈페이지 변화 · 7일", "v": len(ch), "u": "건", "ok": not ch,
                             "s": ("추적 중 %d개사 %d개 제품 모두 변동 없음 ✓" % (len(p["companies"]), tracked)) if not ch else
                                  "신제품 %d · 단종 %d · 가격 변동 %d · 추적 중 %d개사 %d개 제품"
                                  % (n["new"], n["removed"], n["price"], len(p["companies"]), tracked)})
        for c in [c for c in ch if c["type"] == "new"][:4]:
            out["notes"].append({"tag": "홈페이지 신제품", "href": c["link"], "title": "%s · %s" % (c["company"], c["name"]),
                                 "sub": (c.get("cat") or "") + (" · %s원" % format(c["price"], ",") if c.get("price") else ""), "memo": ""})
    except Exception:
        out["tiles"].append({"href": "/제품", "k": "경쟁사 홈페이지 변화 · 7일", "v": "–", "u": "", "s": "읽지 못했습니다"})

    # 6. 인증 만료 — 지남 · 임박 · 준비
    try:
        import certs
        a = certs.alerts(4)
        k, s_ = a["kpi"], a["settings"]
        n_alert = k["expired"] + k["soon"]
        if a["n_total"]:
            out["tiles"].append({"href": "/인증", "k": "인증 만료 · %d일 내" % s_["lead_soon"], "v": n_alert, "u": "건", "ok": not n_alert,
                                 "s": ("보유 인증서 %d건 모두 기한 안 ✓" % k["certs"] + (" · %d일 내 준비 %d건" % (s_["lead_ready"], k["ready"]) if k["ready"] else "")) if not n_alert
                                      else "지남 %d · 임박 %d · 준비 %d · 보유 %d건" % (k["expired"], k["soon"], k["ready"], k["certs"])})
            for c in a["rows"]:
                if c["state"] not in ("expired", "soon", "ready"):
                    continue
                d = c["days"]
                when = ("D+%d 지남" % -d) if d < 0 else ("오늘 만료" if d == 0 else "D-%d" % d)
                out["notes"].append({"tag": "인증 만료", "href": "/인증", "title": "%s %s · 제품 %d개" % (c["kind_name"], c["no"] or "", c["n_products"]),
                                     "sub": "%s · %s 만료 · %s" % (when, c["end"].replace("-", "."), c["progress"]), "memo": c.get("note", "")[:80]})
    except Exception:
        pass

    # 주목할 것이 비지 않게 — ① 이번 주 가장 많이 보도된 소식 ② 다음 전시회 D-day ③ 경쟁사 가격 변동
    try:
        rows = news.query(days=7)["rows"]
        top = sorted((r for r in rows if r.get("n_src", 1) > 1 and r["company"] != "매트리스 업계"),
                     key=lambda r: -r["n_src"])[:3]
        for r in top:
            out["notes"].append({"tag": "많이 보도됨", "href": r["link"], "title": r["title"],
                                 "sub": "%s · %d개 매체 · %s" % (r["company"], r["n_src"], (r.get("date") or "")[:10]), "memo": ""})
    except Exception:
        pass
    try:
        import events
        up = [e for e in events.rows() if e.get("start") and e["start"] >= today.isoformat()]
        up.sort(key=lambda e: (bool(e.get("tbc")), e["start"]))
        for e in up[:2]:
            d = (datetime.date.fromisoformat(e["start"]) - today).days
            when = ("%d월 중 (날짜 확인 필요)" % int(e["start"][5:7])) if e.get("tbc") else ("D-%d · %s" % (d, e["start"].replace("-", ".")))
            out["notes"].append({"tag": "다음 전시회", "href": e.get("link") or "/일정", "title": e["title"],
                                 "sub": when + (" · " + e["place"] if e.get("place") else ""), "memo": ""})
    except Exception:
        pass
    try:
        pc = [c for c in products.data(30)["changes"] if c["type"] == "price" and c.get("old") and c.get("price")]
        if pc:
            diffs = [100.0 * (c["price"] - c["old"]) / c["old"] for c in pc]
            avg = sum(diffs) / len(diffs)
            cos = sorted({c["company"] for c in pc})
            out["notes"].append({"tag": "가격 변동", "href": "/제품", "title": "경쟁사 표시 가격 %d건 변동 · 평균 %+.1f%%" % (len(pc), avg),
                                 "sub": " · ".join(cos) + " · 최근 30일", "memo": ""})
    except Exception:
        pass
    try:
        out["last_run"] = news.state().get("last_run", "")
    except Exception:
        out["last_run"] = ""
    return out


def home(build=""):
    cards = "".join(
        '<a class="pcard" href="%s"><span class="no">%s</span><span class="n">%s</span><span class="d">%s</span>'
        '<span class="go">열기 <i>→</i></span></a>'
        % (html.escape(p), no, html.escape(name), html.escape(desc)) for p, name, desc, no in MENU)
    soon = "".join('<div class="pcard soon"><span class="no">%s</span><span class="n">%s</span><span class="d">준비 중</span><span class="go">곧 열립니다</span></div>'
                   % (no, html.escape(name)) for name, no in SOON) if show_soon() else ""
    return HOME.replace("__NAV__", nav("/", "", build)) \
               .replace("__CARDS__", cards + soon).replace("__TITLE__", html.escape(TITLE)) \
               .replace("__NAVCSS__", NAV_CSS).replace("__N__", str(len(MENU)))


HOME = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>__TITLE__</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" onerror="this.remove()">
<style>
:root{--ink:#0f0f11;--ink-2:#3a3a40;--mute:#84848a;--faint:#b4b4b9;--line:#e3e0d9;--line-2:#eeebe4;--paper:#fff;--bg:#f1efea;--black:#0a0a0b;--acc:#8c3325}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Pretendard Variable",Pretendard,"Malgun Gothic",system-ui,sans-serif}
__NAVCSS__
.wrap{max-width:1060px;margin:0 auto;padding:72px 32px 100px}
.eyebrow{font-size:11px;letter-spacing:.22em;color:var(--mute);font-weight:600}
h1{font-size:40px;font-weight:700;letter-spacing:-.025em;margin:8px 0 14px;line-height:1.1}
.lead{font-size:15px;color:var(--ink-2);max-width:640px;line-height:1.7;margin-bottom:56px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:1px;background:var(--line);border:1px solid var(--line)}
.pcard{display:flex;flex-direction:column;background:var(--paper);padding:34px 32px 30px;min-height:230px;text-decoration:none;color:inherit;position:relative;transition:background .15s}
.pcard:hover{background:#fbfaf7}
.pcard .no{font-size:11px;letter-spacing:.2em;color:var(--mute);font-weight:600}
.pcard .n{font-size:21px;font-weight:700;letter-spacing:-.015em;margin:14px 0 10px;color:var(--ink)}
.pcard .d{font-size:13px;color:var(--ink-2);line-height:1.65;flex:1}
.pcard .go{font-size:12px;font-weight:600;letter-spacing:.06em;color:var(--ink);margin-top:22px}
.pcard .go i{font-style:normal;display:inline-block;transition:transform .15s}
.pcard:hover .go i{transform:translateX(4px)}
.pcard.soon{color:var(--faint);pointer-events:none}
.pcard.soon .n,.pcard.soon .d,.pcard.soon .go{color:var(--faint)}
.foot{margin-top:40px;font-size:12px;color:var(--mute);line-height:1.7}
/* 오늘의 브리핑 */
.brief{margin-bottom:56px}
.bhead{display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:wrap;margin-bottom:14px}
.bhead .bdate{font-size:13px;color:var(--mute)}
.bhead .bdate b{color:var(--ink-2);font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}
@media(max-width:1180px){.tiles{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}}
.tile{display:flex;flex-direction:column;background:var(--paper);padding:22px 22px 20px;text-decoration:none;color:inherit;min-height:150px}
.tile:hover{background:#fbfaf7}
.tile .k{font-size:12px;color:var(--mute);font-weight:600;letter-spacing:.02em}
.tile .v{font-size:44px;font-weight:700;letter-spacing:-.03em;line-height:1.05;margin:10px 0 8px;font-variant-numeric:tabular-nums}
.tile .v small{font-size:14px;font-weight:500;color:var(--mute);margin-left:4px;letter-spacing:0}
.tile .s{font-size:12.5px;color:var(--ink-2);line-height:1.55;margin-top:auto}
.tile.ok .v{color:#23573f}
.tile.ok .s{color:#23573f}
.notes{background:var(--paper);border:1px solid var(--line);border-top:none}
.notes .nh{font-size:11px;letter-spacing:.18em;color:var(--mute);font-weight:600;padding:16px 22px 6px}
.note{display:grid;grid-template-columns:96px 1fr;gap:0 16px;padding:11px 22px;border-top:1px solid var(--line-2);align-items:baseline}
.note .tg{font-size:11px;font-weight:600;color:var(--acc);white-space:nowrap}
.note .tg.law{color:#fff;background:var(--acc);padding:1px 8px;border-radius:10px;justify-self:start}
.note a{color:var(--ink);text-decoration:none;font-size:14.5px;font-weight:500;line-height:1.5}
.note a:hover{text-decoration:underline;text-underline-offset:3px}
.note .sb{font-size:12px;color:var(--mute);margin-top:2px}
.note .mm{font-size:12.5px;color:var(--ink-2);margin-top:4px;padding:4px 10px;background:#f7f5f0;border-left:2px solid var(--line)}
.notes .none{padding:18px 22px 20px;font-size:13px;color:var(--mute);line-height:1.7;border-top:1px solid var(--line-2)}
.sec-t{font-size:11px;letter-spacing:.22em;color:var(--mute);font-weight:600;margin-bottom:14px}
.skel{color:var(--faint)}
@media print{.tiles{grid-template-columns:repeat(5,1fr)}.tile .v{font-size:32px}.grid,.lead,.sec-t,.foot{display:none}.wrap{padding:0}}
@media(max-width:700px){.wrap{padding:44px 16px 70px}h1{font-size:30px}.note{grid-template-columns:1fr}}
</style></head><body>
__NAV__
<div class="wrap">
  <div class="eyebrow">시몬스 연구소</div>
  <h1>__TITLE__</h1>
  <div class="lead">연구소가 매일 아침 자동으로 모은 것을 한 장으로 봅니다. 숫자를 누르면 그 화면으로 갑니다.</div>

  <div class="brief" id="brief">
    <div class="bhead"><div class="eyebrow">오늘의 브리핑</div><div class="bdate" id="bdate"></div></div>
    <div class="tiles" id="tiles"><div class="tile skel">읽는 중…</div></div>
    <div class="notes" id="notes"></div>
  </div>

  <div class="sec-t">프로그램</div>
  <div class="grid">__CARDS__</div>
  <div class="foot">사내망 전용입니다. 성적서와 측정 자료는 외부로 나가지 않습니다.</div>
</div>
<script>
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
(async()=>{
  let B; try{ B=await (await fetch('/홈/data')).json(); }catch(e){ document.getElementById('tiles').innerHTML='<div class="tile skel">보고판을 읽지 못했습니다. 잠시 뒤 새로고침하세요.</div>'; return; }
  const d=new Date(B.date+'T00:00:00'); const w='일월화수목금토'[d.getDay()];
  document.getElementById('bdate').innerHTML=`<b>${d.getMonth()+1}월 ${d.getDate()}일 (${w})</b>${B.last_run?` · 평일 아침 8시 자동 갱신, 마지막 ${esc(B.last_run)}`:''}`;
  document.getElementById('tiles').innerHTML=B.tiles.map(t=>`<a class="tile ${t.ok?'ok':''}" href="${esc(t.href)}"><span class="k">${esc(t.k)}</span><span class="v">${esc(t.v)}<small>${esc(t.u)}</small></span><span class="s">${esc(t.s)}</span></a>`).join('');
  let n=`<div class="nh">주목할 것</div>`;
  const SOFT={'많이 보도됨':1,'다음 전시회':1,'가격 변동':1};
  if(B.notes.length) n+=B.notes.map(x=>`<div class="note"><span class="tg ${x.tag==='법령 변경'||(x.tag==='인증 만료'&&/지남|오늘/.test(x.sub))?'law':''}" ${SOFT[x.tag]?'style="color:var(--mute)"':''}>${esc(x.tag)}</span><div><a href="${esc(x.href)}" ${x.href.startsWith('/')?'':'target="_blank" rel="noopener"'}>${esc(x.title)}</a><div class="sb">${esc(x.sub)}</div>${x.memo?`<div class="mm">${esc(x.memo)}</div>`:''}</div></div>`).join('');
  else n+=`<div class="none">이번 주에 올라온 것이 없습니다.</div>`;
  document.getElementById('notes').innerHTML=n;
})();
</script>
</body></html>"""
