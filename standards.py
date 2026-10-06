# -*- coding: utf-8 -*-
"""시험 규격 요약집 — 우리가 성적서를 쓰는 규격의 핵심 수치를 한 장에.

  · 숫자는 성적서 프로그램 코드(kc.py · ks.py · core.py · material.py)에 박힌 값을 그대로 읽는다.
    그래서 프로그램이 판정에 쓰는 값과 여기 적힌 값이 어긋날 수 없다.
  · 법령의 공포·시행일은 R&D 동향의 법령 감시(규격상태.json)에서 가져온다.
  · 담당자가 덧붙이는 설명·추가 항목은 규격요약.json 에 저장한다 (관리 비밀번호).
  · 법 조문 수치(예: 연간 피폭선량)는 코드에 없으므로 «법령 원문 확인» 표시와 함께 적는다.
"""
import os, io, json, threading, html

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "규격요약.json")
_lock = threading.Lock()


def _code_values():
    """성적서 모듈에서 판정 기준을 읽는다. 모듈이 없거나 바뀌어도 화면은 떠야 하므로 하나씩 감싼다."""
    v = {}
    try:
        import kc
        v["kc"] = {"targets": kc.TARGETS, "min_load": kc.MIN_LOAD, "max_load": kc.MAX_LOAD, "cycles": kc.CYCLES_EXPECT,
                   "sag": kc.SAG_LIMIT, "d1": kc.D1_MAX, "d2": kc.D2_MIN, "method": kc.METHOD}
    except Exception:
        pass
    try:
        import ks
        v["ks"] = {"tol": ks.DIM_TOL, "items": ks.JUDGE_ITEMS, "default": ks.DIM_DEFAULT}
    except Exception:
        pass
    try:
        import core
        v["radon"] = {"limit": core.LIMIT}
    except Exception:
        pass
    try:
        import material
        v["material"] = {"limit": material.LIMIT}
    except Exception:
        pass
    return v


def _laws():
    try:
        import trend
        snap = trend._json_load(trend.LAWSTATE, {})
        out = {}
        for k, x in snap.items():
            if k.startswith("_"):
                continue
            out.setdefault(x.get("label", ""), []).append(
                {"name": x["name"], "kind": x.get("kind", ""), "promul": trend._d(x.get("promul")), "enforce": trend._d(x.get("enforce")),
                 "change": x.get("change", ""), "link": x.get("link", ""), "ministry": x.get("ministry", "")})
        return out
    except Exception:
        return {}


def _fmt_tol(t):
    hi, lo = t
    return "+%d / %d mm" % (hi, lo)


def standards():
    v = _code_values()
    kcv, ksv = v.get("kc", {}), v.get("ks", {})
    S = []
    # 1. KS G 4300
    rows = []
    if ksv:
        tol = ksv["tol"]
        rows += [("치수 허용차 — 나비", _fmt_tol(tol["w"]), "코드"), ("치수 허용차 — 길이", _fmt_tol(tol["l"]), "코드"),
                 ("치수 허용차 — 두께", _fmt_tol(tol["t"]), "코드"),
                 ("기준 치수", "제품마다 다름 — 성적서마다 입력 (양식 예시 %d × %d × %d)" % (ksv["default"]["w"], ksv["default"]["l"], ksv["default"]["t"]), "코드")]
        groups = {}
        for key, grp, label, short in ksv["items"]:
            groups.setdefault(grp, []).append(short)
        G = {"quality": "품질 (5항)", "durability": "내구성", "legs": "다리부의 강도", "fabric": "겉감의 품질", "structure": "구조 및 가공 (8항)"}
        for g, shorts in groups.items():
            rows.append(("판정 항목 — " + G.get(g, g), " · ".join(shorts) + " (각 적합/부적합)", "코드"))
    if kcv:
        rows.append(("내구성 시험 사이클", " → ".join(format(c, ",") for c in kcv["cycles"]) + " 회", "코드"))
    S.append({"id": "ks", "name": "KS G 4300 매트리스", "kind": "한국산업표준",
              "scope": "가정용 침대 매트리스의 치수·품질·내구성·구조. 우리 «KS 매트리스 성적서»의 근거.",
              "report": "KS 매트리스 성적서", "law_label": "", "rows": rows,
              "links": [("e나라표준인증 KS 검색", "https://standard.go.kr")]})
    # 2. KC 부속서 19
    rows = []
    if kcv:
        rows += [("변위를 읽는 하중", " · ".join("%g N" % t for t in kcv["targets"]), "코드"),
                 ("최소·최대 하중", "%g N · %g N" % (kcv["min_load"], kcv["max_load"]), "코드"),
                 ("내구성 사이클", " → ".join(format(c, ",") for c in kcv["cycles"]) + " 회", "코드"),
                 ("처짐 판정 d1·d2·d3", "모두 %g mm 이하" % kcv["sag"], "코드"),
                 ("D1 · D2 판정", "D1 ≤ %g mm, D2 ≥ %g mm" % (kcv["d1"], kcv["d2"]), "코드"),
                 ("시험 방법", kcv["method"], "코드")]
    S.append({"id": "kc", "name": "안전기준준수대상 생활용품 안전기준 — 부속서 19 침대 매트리스", "kind": "국가기술표준원 고시 (KC)",
              "scope": "전기용품 및 생활용품 안전관리법에 따른 침대 매트리스 안전기준. 우리 «KC 매트리스 성적서»의 근거.",
              "report": "KC 매트리스 성적서", "law_label": "안전기준준수대상 생활용품의 안전기준 (고시)", "rows": rows,
              "links": [("제품안전정보센터", "https://www.safetykorea.kr")]})
    # 3. 라돈·토론
    rows = []
    if "radon" in v:
        rows.append(("완제품 — 자사 판정 기준", "측정치 − 배경농도 ≤ %g Bq/m³ (RAD7·라돈아이·토론 모두)" % v["radon"]["limit"], "코드"))
    if "material" in v:
        rows.append(("원자재 — 자사 판정 기준", "측정치 − 배경농도 ≤ %g Bq/m³" % v["material"]["limit"], "코드"))
    rows += [("법정 기준 — 가공제품", "가공제품으로 인한 연간 피폭선량이 1 mSv 를 넘지 않을 것 (생활주변방사선 안전관리법 제15조)", "법령 원문 확인"),
             ("법정 기준 — 사용 금지", "침대·매트리스 등 신체 밀착 제품에 원료물질·공정부산물 사용 금지 (법 제15조의2, 2019 개정)", "법령 원문 확인")]
    S.append({"id": "radon", "name": "라돈·토론 — 생활주변방사선 안전관리법 · 가공제품 안전기준", "kind": "법률 · 원자력안전위원회 고시",
              "scope": "매트리스 완제품과 원자재의 라돈·토론 방출. 우리 «라돈·토론 완제품 성적서»와 «라돈 원자재 성적서»의 근거. 자사 기준은 법정 기준보다 보수적으로 둔 사내 값.",
              "report": "라돈·토론 완제품 · 라돈 원자재 성적서", "law_label": "생활주변방사선 안전관리법 (법·시행령·시행규칙)", "rows": rows,
              "links": [("원자력안전위원회 생활방사선", "https://www.nssc.go.kr"), ("가공제품 안전기준 고시", "https://www.law.go.kr")]})
    # 4. 어린이제품
    S.append({"id": "kids", "name": "어린이제품 공통안전기준", "kind": "국가기술표준원 고시",
              "scope": "어린이용 침대·매트리스에 적용되는 유해물질(폼알데하이드·프탈레이트·중금속 등) 기준. 우리 성적서 대상은 아니며 참고용.",
              "report": "—", "law_label": "어린이제품 공통안전기준 (고시)", "rows": [],
              "links": [("제품안전정보센터", "https://www.safetykorea.kr")]})
    # 5. 가구류 공급자적합성
    S.append({"id": "furn", "name": "공급자적합성확인대상 생활용품 안전기준 — 가구류", "kind": "국가기술표준원 고시 (KC)",
              "scope": "침대 프레임 등 가구류의 폼알데하이드 방출·구조 안전. 매트리스 외 침대 완제품에 해당.",
              "report": "—", "law_label": "공급자적합성확인대상 생활용품의 안전기준 (고시)", "rows": [],
              "links": [("제품안전정보센터", "https://www.safetykorea.kr")]})
    return S


def _notes():
    if os.path.exists(FILE):
        try:
            return json.load(io.open(FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_note(sid, note, extra):
    """담당자 설명과 추가 항목 [[항목, 값], ...]."""
    with _lock:
        n = _notes()
        n[sid] = {"note": (note or "").strip(), "extra": [[str(a).strip(), str(b).strip()] for a, b in (extra or []) if str(a).strip()]}
        tmp = FILE + ".tmp"
        json.dump(n, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, FILE)


def data():
    laws, notes = _laws(), _notes()
    out = []
    for s in standards():
        s = dict(s)
        s["laws"] = laws.get(s["law_label"], []) if s["law_label"] else []
        n = notes.get(s["id"], {})
        s["note"], s["extra"] = n.get("note", ""), n.get("extra", [])
        out.append(s)
    return {"standards": out}


PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>시험 규격 요약집</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" onerror="this.remove()">
<style>
:root{--ink:#0f0f11;--ink-2:#3a3a40;--mute:#84848a;--faint:#b4b4b9;--line:#e3e0d9;--line-2:#eeebe4;--paper:#fff;--bg:#f1efea;--black:#0a0a0b;--acc:#8c3325;--ok:#23573f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Pretendard Variable",Pretendard,"Malgun Gothic",system-ui,sans-serif}
__NAVCSS__
.wrap{max-width:1060px;margin:0 auto;padding:44px 40px 90px}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;flex-wrap:wrap;margin-bottom:8px}
.eyebrow{font-size:11px;letter-spacing:.2em;color:var(--mute);font-weight:600}
h1{font-size:30px;font-weight:700;letter-spacing:-.02em;margin:4px 0 0}
.status{font-size:12.5px;color:var(--mute)}
.status button{font:inherit;font-size:12px;padding:6px 12px;border:1px solid var(--line);background:#fff;cursor:pointer;margin-left:10px}
.lead{font-size:14px;color:var(--ink-2);max-width:800px;margin:10px 0 24px;line-height:1.7}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:22px}
.toc a{font-size:12px;padding:6px 12px;border:1px solid var(--line);background:#fff;color:var(--ink-2);text-decoration:none;border-radius:14px}
.toc a:hover{border-color:var(--black);color:var(--black)}
.std{background:var(--paper);border:1px solid var(--line);padding:24px 26px;margin-bottom:20px;break-inside:avoid}
.std .k{font-size:11px;letter-spacing:.14em;color:var(--mute);font-weight:600}
.std h2{font-size:18px;font-weight:700;margin:4px 0 6px;letter-spacing:-.01em}
.std .sc{font-size:13.5px;color:var(--ink-2);line-height:1.65;max-width:820px}
.std .rep{display:inline-block;font-size:11.5px;color:var(--acc);border:1px solid #e8c9c3;border-radius:10px;padding:0 8px;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:16px}
th{font-size:10.5px;letter-spacing:.1em;color:var(--mute);font-weight:600;text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
td{padding:8px;border-bottom:1px solid var(--line-2);vertical-align:top}
td.i{width:220px;font-weight:600;color:var(--ink-2)}
td.v{font-variant-numeric:tabular-nums}
td.src{width:110px;font-size:11px;color:var(--mute);white-space:nowrap}
td.src.code{color:var(--ok)}
td.src.law{color:var(--acc)}
.laws{margin-top:16px}
.laws .t{font-size:11px;letter-spacing:.14em;color:var(--mute);font-weight:600;margin-bottom:4px}
.law{display:grid;grid-template-columns:1fr 90px 110px 110px;gap:0 12px;font-size:12.5px;padding:6px 0;border-bottom:1px solid var(--line-2);align-items:baseline}
.law a{color:var(--ink);text-decoration:none}
.law a:hover{text-decoration:underline;text-underline-offset:3px}
.law span{color:var(--mute);font-size:11.5px;font-variant-numeric:tabular-nums}
.law small{display:block;color:var(--faint);font-size:10.5px}
.links{margin-top:12px;font-size:12px;color:var(--mute)}
.links a{color:var(--ink-2);margin-right:14px}
.note{margin-top:14px;padding:10px 14px;background:#f7f5f0;border-left:2px solid var(--line);font-size:13px;color:var(--ink-2);white-space:pre-wrap}
.note:empty{display:none}
.edit{margin-top:12px;font-size:12px}
.edit summary{cursor:pointer;color:var(--mute);list-style:none}
.edit summary::before{content:"▸ "}
.edit[open] summary::before{content:"▾ "}
.edit textarea{width:100%;font:inherit;font-size:13px;padding:8px;border:1px solid var(--line);margin-top:8px;min-height:70px}
.edit .ex{display:grid;grid-template-columns:1fr 2fr auto;gap:6px;margin-top:6px}
.edit input{font:inherit;font-size:12.5px;padding:6px 8px;border:1px solid var(--line)}
.edit button{font:inherit;font-size:12px;padding:6px 12px;background:var(--black);color:#fff;border:none;cursor:pointer}
.edit button.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
.msg{font-size:12px;color:var(--ok);margin-left:8px}
.empty{font-size:13px;color:var(--mute);padding:12px 0 0}
@media print{.status button,.toc,.edit{display:none!important}.wrap{padding:0}body{background:#fff}.std{border:none;padding:0 0 18px}}
@media(max-width:900px){.wrap{padding:28px 16px 70px}.law{grid-template-columns:1fr}td.i{width:auto}}
</style></head><body>
__NAV__
<div class="wrap">
<div class="head"><div><div class="eyebrow">시몬스 연구소</div><h1>시험 규격 요약집</h1></div><div class="status"><button onclick="window.print()">인쇄</button></div></div>
<div class="lead">우리가 성적서를 쓰는 규격의 핵심 수치를 한 장에 모았습니다. <b style="color:var(--ok)">코드</b> 표시가 붙은 값은 성적서 프로그램이 실제 판정에 쓰는 값을 그대로 읽은 것이라 어긋날 수 없습니다. <b style="color:var(--acc)">법령 원문 확인</b> 표시는 법 조문을 옮긴 것이니 인용 전에 원문을 확인하세요. 공포·시행일은 법령 감시가 매일 갱신합니다.</div>
<div class="toc" id="toc"></div>
<div id="list"></div>
</div>
<script>
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
let D=null;
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
async function load(){ D=await (await fetch('/규격/data')).json(); render(); }
function render(){
  $('#toc').innerHTML=D.standards.map(s=>`<a href="#s-${s.id}">${esc(s.name.split(' — ')[0])}</a>`).join('');
  $('#list').innerHTML=D.standards.map(s=>{
    const rows=[...s.rows.map(([i,v,src])=>({i,v,src})),...s.extra.map(([i,v])=>({i,v,src:'담당자 입력'}))];
    return `<div class="std" id="s-${s.id}"><div class="k">${esc(s.kind)}</div><h2>${esc(s.name)}</h2><div class="sc">${esc(s.scope)}</div>
      ${s.report!=='—'?`<span class="rep">우리 성적서: ${esc(s.report)}</span>`:''}
      ${rows.length?`<table><tr><th>항목</th><th>기준·값</th><th>출처</th></tr>${rows.map(r=>`<tr><td class="i">${esc(r.i)}</td><td class="v">${esc(r.v)}</td><td class="src ${r.src==='코드'?'code':r.src==='법령 원문 확인'?'law':''}">${esc(r.src)}</td></tr>`).join('')}</table>`:`<div class="empty">핵심 수치가 아직 없습니다. 아래 «덧붙이기» 에서 담당자가 적습니다.</div>`}
      ${s.laws.length?`<div class="laws"><div class="t">근거 법령 · 법령 감시가 매일 확인</div>${s.laws.map(l=>`<div class="law"><div><a href="${esc(l.link)}" target="_blank" rel="noopener">${esc(l.name)}</a><small>${esc(l.ministry)}</small></div><span>${esc(l.kind)}</span><span>공포 ${esc(l.promul)}</span><span>시행 ${esc(l.enforce)}</span></div>`).join('')}</div>`:''}
      <div class="note">${esc(s.note)}</div>
      <div class="links">${s.links.map(([n,u])=>`<a href="${esc(u)}" target="_blank" rel="noopener">${esc(n)} ↗</a>`).join('')}</div>
      <details class="edit" data-id="${s.id}"><summary>덧붙이기 (담당자 설명 · 추가 항목)</summary>
        <textarea class="nt" placeholder="시험할 때 유의점, 개정 이력, 인용 시 주의 등">${esc(s.note)}</textarea>
        <div class="exs">${s.extra.map(([i,v])=>`<div class="ex"><input class="ei" value="${esc(i)}" placeholder="항목"><input class="ev" value="${esc(v)}" placeholder="기준·값"><button class="ghost rm">빼기</button></div>`).join('')}</div>
        <div style="margin-top:8px"><button class="ghost add">항목 추가</button> <button class="save">저장</button><span class="msg"></span></div></details></div>`;
  }).join('');
}
document.addEventListener('click',async e=>{
  const ed=e.target.closest('.edit'); if(!ed) return;
  if(e.target.classList.contains('add')){ $('.exs',ed).insertAdjacentHTML('beforeend',`<div class="ex"><input class="ei" placeholder="항목"><input class="ev" placeholder="기준·값"><button class="ghost rm">빼기</button></div>`); return; }
  if(e.target.classList.contains('rm')){ e.target.closest('.ex').remove(); return; }
  if(e.target.classList.contains('save')){ const pw=prompt('관리 비밀번호'); if(pw===null) return;
    const extra=$$('.ex',ed).map(x=>[$('.ei',x).value,$('.ev',x).value]).filter(([a])=>a.trim());
    const res=await fetch('/규격/저장',{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Pw':pw},body:JSON.stringify({id:ed.dataset.id,note:$('.nt',ed).value,extra})});
    const m=$('.msg',ed); m.style.color=res.ok?'var(--ok)':'var(--acc)'; m.textContent=res.ok?'저장했습니다':'비밀번호가 틀리거나 저장하지 못했습니다'; if(res.ok) load(); }
});
load();
</script></body></html>"""


def page(build=""):
    import portal
    return PAGE.replace("__NAV__", portal.nav("/규격", "", build)).replace("__NAVCSS__", portal.NAV_CSS)
