# -*- coding: utf-8 -*-
"""전시회·학회·설명회 일정 — 침대·매트리스·수면·소재 분야.

  · 일정은 일정.json 한 파일. 화면에서 누구나 더하고 고칠 수 있고, 지우는 것만 관리 비밀번호를 묻는다.
  · 처음 깔릴 때 업계에서 해마다 열리는 전시회를 씨앗으로 넣어 둔다. 씨앗은 «날짜 확인 필요» 표시가 붙어 있다 —
    주최 측이 해마다 날짜를 바꾸므로 담당자가 공식 사이트에서 확인하고 고치면 표시가 사라진다.
  · 밖으로 나가는 요청은 없다. 링크는 눌렀을 때 사용자 브라우저가 연다.
"""
import os, io, json, datetime, threading, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "일정.json")
_lock = threading.Lock()
KINDS = ("전시회", "학회·컨퍼런스", "설명회·교육", "기타")

# 씨앗: (이름, 종류, 시작 YYYY-MM-DD, 끝 또는 "", 장소, 주기 설명, 공식 사이트, 왜 보는가)
# 날짜는 통상 열리는 달의 1일로 두고 tbc=True — 담당자가 확인해 고친다.
SEEDS = (
    ("High Point Market (가을)", "전시회", "2026-10-17", "2026-10-21", "미국 하이포인트", "매년 4월·10월",
     "https://www.highpointmarket.org", "북미 가구·침대 최대 시장. Serta Simmons·Tempur Sealy 신제품"),
    ("Heimtextil", "전시회", "2027-01-12", "2027-01-15", "독일 프랑크푸르트", "매년 1월",
     "https://heimtextil.messefrankfurt.com", "홈텍스타일·침구·매트리스 원단 트렌드"),
    ("imm cologne", "전시회", "2027-01-19", "2027-01-22", "독일 쾰른", "매년 1월 (개최 여부 확인)",
     "https://www.imm-cologne.com", "유럽 가구·침실 트렌드"),
    ("서울리빙디자인페어", "전시회", "2027-02-23", "2027-02-27", "서울 코엑스", "매년 2~3월",
     "https://www.livingdesignfair.co.kr", "국내 리빙 브랜드 신제품 — 시몬스·에이스·씰리 등 참가"),
    ("코리아빌드위크", "전시회", "2027-02-01", "", "고양 킨텍스", "매년 2월",
     "https://www.koreabuild.co.kr", "건축·인테리어·가구 자재"),
    ("Salone del Mobile.Milano", "전시회", "2027-04-13", "2027-04-18", "이탈리아 밀라노 피에라 로", "매년 4월",
     "https://www.salonemilano.it", "세계 최대 가구 디자인 전시 — 침실 디자인 흐름"),
    ("High Point Market (봄)", "전시회", "2027-04-10", "2027-04-14", "미국 하이포인트", "매년 4월·10월",
     "https://www.highpointmarket.org", "북미 가구·침대 최대 시장"),
    ("interzum", "전시회", "2027-05-11", "2027-05-14", "독일 쾰른", "홀수 해 5월 (2년마다)",
     "https://www.interzum.com", "가구 부자재·매트리스 소재(폼·스프링·원단·기계) 세계 최대 전시"),
    ("SLEEP (APSS 연례 학술대회)", "학회·컨퍼런스", "2027-06-06", "2027-06-09", "미국 덴버 콜로라도 컨벤션센터", "매년 6월",
     "https://www.sleepmeeting.org", "수면의학 최대 학회 — 수면 측정·슬립테크 연구"),
    ("KOFURN 한국국제가구 및 인테리어산업대전", "전시회", "2027-08-01", "", "고양 킨텍스", "매년 8~9월",
     "https://www.kofurn.or.kr", "국내 가구 산업 전시 — 중소 침대·매트리스 업체"),
    ("ISPA EXPO", "전시회", "2028-03-21", "2028-03-23", "미국 뉴올리언스", "짝수 해 3월 (2년마다)",
     "https://www.ispaexpo.com", "국제수면제품협회 — 매트리스 제조 설비·소재 전문 전시"),
    ("국가기술표준원 KS·KC 제도 설명회", "설명회·교육", "", "", "", "수시 — 국표원 공지 확인",
     "https://www.kats.go.kr", "안전기준·KS 개정 설명회. 날짜가 잡히면 여기 적는다"),
    ("대한수면학회 / 대한수면연구학회 학술대회", "학회·컨퍼런스", "", "", "", "봄·가을 — 학회 공지 확인",
     "", "국내 수면 연구 동향"),
)


def _load():
    if os.path.exists(FILE):
        try:
            return json.load(io.open(FILE, encoding="utf-8"))
        except Exception:
            pass
    return None


def _save(rows):
    with _lock:
        tmp = FILE + ".tmp"
        json.dump(rows, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, FILE)


def rows():
    r = _load()
    if r is None:
        # 시작·끝 날짜가 모두 적힌 씨앗은 공식 일정을 확인한 것(2026-10-06). 달만 아는 것은 tbc.
        r = [{"id": uuid.uuid4().hex[:10], "title": t, "kind": k, "start": a, "end": b, "place": p, "cycle": c,
              "link": l, "why": w, "note": "", "tbc": not (a and b), "seed": True} for t, k, a, b, p, c, l, w in SEEDS]
        _save(r)
    return r


def save(item):
    """더하거나 고친다. id 가 있으면 고침. 담당자가 날짜를 손대면 tbc 는 꺼진다."""
    r = rows()
    item = {k: (item.get(k) or "").strip() if isinstance(item.get(k), str) else item.get(k)
            for k in ("id", "title", "kind", "start", "end", "place", "cycle", "link", "why", "note")}
    if not item["title"]:
        raise ValueError("이름이 비었습니다")
    if item["kind"] not in KINDS:
        item["kind"] = "기타"
    for k in ("start", "end"):
        if item[k]:
            datetime.date.fromisoformat(item[k])          # 틀리면 ValueError
    if item["end"] and item["start"] and item["end"] < item["start"]:
        item["end"] = item["start"]
    old = next((x for x in r if x["id"] == item["id"]), None) if item["id"] else None
    if old:
        changed_date = old.get("start") != item["start"] or old.get("end") != item["end"]
        old.update(item)
        if changed_date:
            old["tbc"] = False
    else:
        item["id"] = uuid.uuid4().hex[:10]
        item["tbc"], item["seed"] = False, False
        r.append(item)
    _save(r)
    return item["id"]


def confirm(eid):
    r = rows()
    for x in r:
        if x["id"] == eid:
            x["tbc"] = False
    _save(r)


def delete(eid):
    r = [x for x in rows() if x["id"] != eid]
    _save(r)


def data():
    today = datetime.date.today().isoformat()
    r = sorted(rows(), key=lambda x: (not x["start"], x["start"] or "9999", x["title"]))
    for x in r:
        # 날짜 확인 전(tbc)인 것은 그 달이 다 지나야 지난 일정이다
        x["past"] = bool(x["start"]) and ((x["start"][:7] < today[:7]) if x.get("tbc") else (x["end"] or x["start"]) < today)
    return {"rows": r, "kinds": KINDS, "today": today, "tbc_n": sum(1 for x in r if x.get("tbc"))}


PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>전시회·학회 일정</title>
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
.status{font-size:12.5px;color:var(--mute);text-align:right;line-height:1.7}
.status button{font:inherit;font-size:12px;padding:6px 12px;border:1px solid var(--line);background:#fff;cursor:pointer;margin-left:10px}
.lead{font-size:14px;color:var(--ink-2);max-width:780px;margin:10px 0 24px;line-height:1.7}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:16px}
.chip{font-size:11.5px;padding:5px 10px;border:1px solid var(--line);background:#fff;cursor:pointer;color:var(--ink-2);border-radius:14px}
.chip.on{background:var(--black);border-color:var(--black);color:#fff}
.mon{font-size:11px;letter-spacing:.16em;color:var(--mute);font-weight:600;padding:18px 0 8px}
.mon:first-child{padding-top:0}
.ev{display:grid;grid-template-columns:92px 1fr auto;gap:0 18px;background:var(--paper);border:1px solid var(--line);border-top:none;padding:14px 20px;align-items:start}
.ev:first-of-type,.mon+.ev{border-top:1px solid var(--line)}
.ev.past{opacity:.55}
.ev .d{font-size:13px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.4}
.ev.past .d,.ev.past .t{text-decoration:line-through;text-decoration-color:var(--faint)}
.ev .d small{display:block;font-weight:500;color:var(--mute);font-size:11px}
.ev .t{font-size:15px;font-weight:600}
.ev .t a{color:inherit;text-decoration:none}
.ev .t a:hover{text-decoration:underline;text-underline-offset:3px}
.ev .m{font-size:12px;color:var(--mute);margin-top:2px;display:flex;flex-wrap:wrap;gap:4px 10px}
.ev .m b{color:var(--ink-2);font-weight:600}
.ev .w{font-size:12.5px;color:var(--ink-2);margin-top:5px;line-height:1.55}
.ev .note{font-size:12.5px;color:var(--ink-2);margin-top:5px;padding:4px 10px;background:#f7f5f0;border-left:2px solid var(--line);white-space:pre-wrap}
.tbc{font-size:10.5px;color:var(--acc);border:1px solid #e8c9c3;border-radius:10px;padding:0 7px}
.kind{font-size:10.5px;color:var(--mute);border:1px solid var(--line);border-radius:10px;padding:0 7px}
.act{display:flex;gap:6px;opacity:0}
.ev:hover .act{opacity:1}
.act button{font:inherit;font-size:11px;padding:3px 8px;border:1px solid var(--line);background:#fff;cursor:pointer;color:var(--ink-2)}
.card{background:var(--paper);border:1px solid var(--line);padding:22px 24px;margin-top:26px}
.card h2{font-size:15px;font-weight:700;margin:0 0 4px}
.card .hint{font-size:12.5px;color:var(--mute);margin-bottom:14px}
.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px 14px}
.form label{font-size:11px;letter-spacing:.08em;color:var(--mute);font-weight:600;display:block;margin-bottom:3px}
.form input,.form select,.form textarea{font:inherit;font-size:13px;padding:7px 9px;border:1px solid var(--line);background:#fff;width:100%}
.form .full{grid-column:1/-1}
.form button{font:inherit;font-size:12.5px;padding:8px 14px;background:var(--black);color:#fff;border:none;cursor:pointer}
.form button.ghost{background:#fff;color:var(--ink);border:1px solid var(--line);margin-left:8px}
.msg{font-size:12.5px;color:var(--ok);margin-left:10px}
.empty{padding:40px;text-align:center;color:var(--mute)}
@media print{.status button,.bar,.act,.card{display:none!important}.wrap{padding:0}body{background:#fff}}
@media(max-width:900px){.wrap{padding:28px 16px 70px}.ev{grid-template-columns:1fr}}
</style></head><body>
__NAV__
<div class="wrap">
<div class="head"><div><div class="eyebrow">시몬스 연구소</div><h1>전시회·학회 일정</h1></div><div class="status" id="status"></div></div>
<div class="lead">침대·매트리스·수면·소재 분야의 전시회·학회·설명회. <span class="tbc">날짜 확인 필요</span> 가 붙은 것은 열리는 달만 아는 것이라 공식 사이트에서 확인해 고쳐야 합니다.</div>
<div class="bar" id="kinds"></div>
<div id="list"></div>
<div class="card"><h2 id="formT">일정 더하기</h2><div class="hint">이름과 날짜만 있어도 됩니다. 고치려면 목록에서 「고치기」를 누르세요. 지우기는 관리 비밀번호를 묻습니다.</div>
  <div class="form"><input type="hidden" id="eid">
    <div class="full"><label>이름</label><input id="title" placeholder="예: interzum 2027"></div>
    <div><label>종류</label><select id="kind"></select></div>
    <div><label>시작</label><input type="date" id="start"></div>
    <div><label>끝 (하루면 비움)</label><input type="date" id="end"></div>
    <div><label>장소</label><input id="place" placeholder="도시·전시장"></div>
    <div><label>주기</label><input id="cycle" placeholder="매년 5월 / 2년마다"></div>
    <div class="full"><label>공식 사이트</label><input id="link" placeholder="https://"></div>
    <div class="full"><label>왜 보는가 · 메모</label><textarea id="why" rows="2" placeholder="우리가 챙겨야 할 이유, 참석자, 준비물"></textarea></div>
    <div class="full"><button id="save">저장</button><button class="ghost" id="reset">새로</button><span class="msg" id="msg"></span></div>
  </div></div>
</div>
<script>
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
let D=null, K='';
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
const fmt=d=>d?d.slice(5).replace('-','.'):'';
const dow=d=>'일월화수목금토'[new Date(d+'T00:00:00').getDay()];
async function load(){ D=await (await fetch('/일정/data')).json(); render(); }
function render(){
  const up=D.rows.filter(r=>!r.past&&r.start).length;
  $('#status').innerHTML=`앞으로 <b>${up}건</b>${D.tbc_n?` · 날짜 확인 필요 ${D.tbc_n}건`:''}<button onclick="window.print()">인쇄</button>`;
  $('#kinds').innerHTML=`<button class="chip ${K?'':'on'}" data-k="">전체</button>`+D.kinds.map(k=>`<button class="chip ${K===k?'on':''}" data-k="${esc(k)}">${esc(k)}</button>`).join('');
  $('#kind').innerHTML=D.kinds.map(k=>`<option>${esc(k)}</option>`).join('');
  const rows=D.rows.filter(r=>!K||r.kind===K);
  if(!rows.length){ $('#list').innerHTML='<div class="empty">일정이 없습니다.</div>'; return; }
  let out='', mon='';
  rows.forEach(r=>{
    const m=r.start?r.start.slice(0,7):'미정';
    if(m!==mon){ mon=m; out+=`<div class="mon">${m==='미정'?'날짜 미정':m.slice(0,4)+'년 '+(+m.slice(5))+'월'}</div>`; }
    const dcol=!r.start?'<small>날짜 미정</small>':r.tbc?`${+r.start.slice(5,7)}월 중<small>날짜 확인 필요</small>`:`${fmt(r.start)}${r.end&&r.end!==r.start?` ~ ${fmt(r.end)}`:''}<small>${dow(r.start)}요일${r.end&&r.end!==r.start?' 시작':''}</small>`;
    out+=`<div class="ev ${r.past?'past':''}" data-id="${r.id}"><div class="d">${dcol}</div>
      <div><div class="t">${r.link?`<a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.title)}</a>`:esc(r.title)}</div>
        <div class="m"><span class="kind">${esc(r.kind)}</span>${r.place?`<b>${esc(r.place)}</b>`:''}${r.cycle?`<span>${esc(r.cycle)}</span>`:''}</div>
        ${r.why?`<div class="w">${esc(r.why)}</div>`:''}${r.note?`<div class="note">${esc(r.note)}</div>`:''}</div>
      <div class="act"><button data-a="edit">고치기</button>${r.tbc?'<button data-a="ok">날짜 확인함</button>':''}<button data-a="del">지우기</button></div></div>`;
  });
  $('#list').innerHTML=out;
}
function fill(r){ $('#eid').value=r?r.id:''; $('#title').value=r?r.title:''; $('#kind').value=r?r.kind:D.kinds[0]; $('#start').value=r?r.start:''; $('#end').value=r?r.end:'';
  $('#place').value=r?r.place:''; $('#cycle').value=r?r.cycle:''; $('#link').value=r?r.link:''; $('#why').value=r?(r.why||'')+(r.note?'\n'+r.note:''):''; $('#formT').textContent=r?'일정 고치기 — '+r.title:'일정 더하기'; $('#msg').textContent=''; }
document.addEventListener('click',async e=>{
  const c=e.target.closest('#kinds .chip'); if(c){ K=c.dataset.k; render(); return; }
  const b=e.target.closest('.act button'); if(b){ const id=b.closest('.ev').dataset.id; const r=D.rows.find(x=>x.id===id);
    if(b.dataset.a==='edit'){ fill(r); $('#formT').scrollIntoView({behavior:'smooth'}); return; }
    if(b.dataset.a==='ok'){ await fetch('/일정/확인',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})}); load(); return; }
    if(b.dataset.a==='del'){ const pw=prompt('관리 비밀번호 — «'+r.title+'» 을 지웁니다'); if(pw===null) return;
      const res=await fetch('/일정/삭제',{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Pw':pw},body:JSON.stringify({id})}); if(!res.ok) alert('비밀번호가 틀립니다'); load(); return; } }
  if(e.target.id==='reset'){ fill(null); return; }
  if(e.target.id==='save'){ const body={id:$('#eid').value,title:$('#title').value,kind:$('#kind').value,start:$('#start').value,end:$('#end').value,place:$('#place').value,cycle:$('#cycle').value,link:$('#link').value,why:$('#why').value};
    const res=await fetch('/일정/저장',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); const r=await res.json();
    $('#msg').style.color=res.ok?'var(--ok)':'var(--acc)'; $('#msg').textContent=res.ok?'저장했습니다':(r.error||'저장하지 못했습니다'); if(res.ok){ fill(null); load(); } }
});
load();
</script></body></html>"""


def page(build=""):
    import portal
    return PAGE.replace("__NAV__", portal.nav("/일정", "", build)).replace("__NAVCSS__", portal.NAV_CSS)
