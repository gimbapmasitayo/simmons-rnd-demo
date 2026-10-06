# -*- coding: utf-8 -*-
"""Vercel 진입점 (평평한 구조) — 시몬스 R&D 포털 «읽기 전용 쇼케이스».

  · 모든 파일이 저장소 루트에 있다. 켜질 때 이 폴더를 /tmp 로 복사해 두고 거기서 모듈을 읽는다
    (Vercel 은 배포 폴더가 읽기 전용이라, 모듈이 쓰는 백업·상태 파일이 /tmp 에 떨어졌다 사라지게).
  · 모든 POST 는 «데모 버전에서는 저장되지 않습니다» 로 막는다.
  · 실적은 ?demo=1 더미를 항상 쓴다. 인증 현황은 익명화한 더미 파일. 아침 8시 스케줄러는 돌지 않는다.
"""
import os, sys, shutil

SRC = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(os.environ.get("TMPDIR") or "/tmp", "rndhub-demo")
if not os.path.isdir(DST):
    shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "node_modules", ".vercel"))
    rep = os.path.join(DST, "보고서")
    os.makedirs(rep, exist_ok=True)
    for f in os.listdir(DST):                       # 평평하게 올라간 주간보고 PDF 를 보고서/ 로
        if f.lower().endswith(".pdf"):
            shutil.move(os.path.join(DST, f), os.path.join(rep, f))
sys.path.insert(0, DST)
os.environ.setdefault("RNDHUB_NO_BROWSER", "1")
os.environ.setdefault("PORTAL_SHOW_SOON", "0")

from flask import request, jsonify, redirect   # noqa: E402
import server, stats                             # noqa: E402

SNAPSHOT = os.environ.get("DEMO_SNAPSHOT_DATE", "")


class _DecodePath:
    """Vercel 은 한글 주소(/성적서)를 %EC%84%B1… 그대로 넘긴다. WSGI 규약대로 풀어서 Flask 가 라우트를 찾게 한다."""
    def __init__(self, wsgi):
        self.wsgi = wsgi

    def __call__(self, environ, start_response):
        from urllib.parse import unquote
        p = environ.get("PATH_INFO", "")
        if "%" in p:
            try:
                environ["PATH_INFO"] = unquote(p, encoding="utf-8", errors="strict").encode("utf-8").decode("latin-1")
            except Exception:
                pass
        return self.wsgi(environ, start_response)


server.app.wsgi_app = _DecodePath(server.app.wsgi_app)
app = server.app

_demo_rows, _demo_settings = stats.demo_rows()
stats.load = lambda: list(_demo_rows)
stats.settings = lambda: dict(_demo_settings)
_orig_data_for = stats.data_for


def _data_for(args):
    a = dict(args.items()) if hasattr(args, "items") else dict(args)
    a["demo"] = "1"
    return _orig_data_for(a)


stats.data_for = _data_for


@app.before_request
def _demo_guard():
    if request.method == "POST":
        return jsonify(ok=False, error="데모 버전에서는 저장되지 않습니다. 사내 포털에서 해 주세요."), 403
    if request.path.startswith("/실적/엑셀") and request.args.get("demo") != "1":
        return redirect("/실적/엑셀?demo=1")


_BAR = ('<div id="demo-ribbon" style="position:fixed;left:50%%;bottom:14px;transform:translateX(-50%%);z-index:9999;'
        'background:#0a0a0b;color:#fff;font:12px/1 \'Pretendard Variable\',Pretendard,\'Malgun Gothic\',system-ui,sans-serif;'
        'padding:9px 16px;border-radius:999px;letter-spacing:.02em;box-shadow:0 6px 24px rgba(0,0,0,.18);white-space:nowrap">'
        '데모 · 공개용 쇼케이스%s · 뉴스·제품·일정·규격은 수집 스냅샷, 성적서 실적·인증 현황은 가상 자료 · 저장 기능 꺼짐</div>')


@app.after_request
def _demo_ribbon(resp):
    try:
        if resp.content_type and resp.content_type.startswith("text/html") and not resp.direct_passthrough:
            body = resp.get_data(as_text=True)
            i = body.find("<body")
            if i >= 0:
                j = body.find(">", i)
                body = body[:j + 1] + (_BAR % ((" · %s 기준" % SNAPSHOT) if SNAPSHOT else "")) + body[j + 1:]
                resp.set_data(body)
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    except Exception:
        pass
    return resp
