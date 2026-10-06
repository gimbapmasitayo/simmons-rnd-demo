# -*- coding: utf-8 -*-
"""열쇠·비밀번호는 .env 에서 읽는다.

  · 프로젝트 폴더의 .env 파일(KEY=값 한 줄씩)을 읽고, 같은 이름의 OS 환경변수가 있으면 그것이 우선한다.
  · 옛 JSON 설정(뉴스설정.json · 특허설정.json · 포털설정.json)에 값이 남아 있으면 .env 에 없을 때만 그것을 쓴다.
    화면에서 열쇠를 저장하면 .env 에 쓴다 — JSON 에는 더 이상 열쇠를 남기지 않는다.
  · .env 는 외부로 나가지 않는다. 백업할 때도 이 파일은 빼는 것이 맞다.

쓰는 이름:
  ADMIN_PW             관리 비밀번호 (열쇠 저장·삭제에 묻는다)
  NAVER_CLIENT_ID      네이버 뉴스 검색 API
  NAVER_CLIENT_SECRET
  KIPRIS_SERVICE_KEY   KIPRIS Plus 특허 검색 API
  PORTAL_SHOW_SOON     1 이면 «준비 중» 메뉴(R&D 과제 탐색)를 보여준다
"""
import os, io, re, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, ".env")
_lock = threading.Lock()
_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _read():
    out = {}
    if os.path.exists(ENV):
        for line in io.open(ENV, encoding="utf-8"):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            m = _LINE.match(line)
            if m:
                v = m.group(2)
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                out[m.group(1)] = v
    return out


def get(name, default=""):
    """OS 환경변수 → .env → 기본값."""
    v = os.environ.get(name)
    if v is not None and v != "":
        return v
    return _read().get(name, default) or default


def set_many(values):
    """.env 에 값을 쓴다(없으면 만들고, 있으면 그 줄만 바꾼다). 빈 값은 줄을 지운다."""
    with _lock:
        lines = io.open(ENV, encoding="utf-8").read().splitlines() if os.path.exists(ENV) else []
        done = set()
        out = []
        for line in lines:
            m = _LINE.match(line)
            if m and m.group(1) in values and not line.lstrip().startswith("#"):
                k = m.group(1)
                done.add(k)
                if values[k]:
                    out.append("%s=%s" % (k, values[k]))
                continue
            out.append(line)
        for k, v in values.items():
            if k not in done and v:
                out.append("%s=%s" % (k, v))
        tmp = ENV + ".tmp"
        io.open(tmp, "w", encoding="utf-8", newline="\n").write("\n".join(out).rstrip("\n") + "\n")
        os.replace(tmp, ENV)
