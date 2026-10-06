# -*- coding: utf-8 -*-
"""계산 검증 — 과거에 사람이 발행한 성적서 4종의 값과 프로그램 계산값을 항목별로 대조한다.

  · 정답은 test_regression.py · test_material.py · test_kc.py · test_ks.py 에 적힌 것과 같은 값이다
    (그 파일들의 KNOWN/EXPECTED 를 그대로 읽어 쓴다 — 한 곳에서만 고치면 된다).
  · 엑셀을 열거나 파일을 만들지는 않는다. 계산만 하므로 몇 초면 끝난다.
  · 결과는 검증결과.json 에 남기고 실적 화면 «계산 검증» 에서 보여준다.
"""
import os, io, sys, json, glob, datetime, threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "검증결과.json")
_busy = {"on": False}


def _row(group, item, human, program):
    return {"group": group, "item": item, "human": human, "program": program,
            "ok": _norm(human) == _norm(program)}


def _norm(v):
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


def check_finished():
    """라돈·토론 완제품 — samples/ 원본 3종 vs sample_result.xlsx 정답 (test_regression.EXPECTED)."""
    import core, test_regression as T
    rad7, rde, frd = T.find_samples()
    if not (rad7 and rde and frd):
        return [], "samples/ 에 측정 원본 3종이 없어 건너뜀"
    rd = lambda p: open(p, encoding="utf-8", errors="replace").read()
    got = core.compute(core.parse_rad7(rd(rad7)), core.parse_ftlab(rd(rde)), core.parse_ftlab(rd(frd)))
    LABEL = {"hours": "측정 시간(h)", "period": "측정 구간", "radon_bg": "라돈 배경농도", "radon_rad7": "라돈 RAD7 측정치",
             "radon_rad7_net": "라돈 RAD7 순농도", "radon_rd200": "라돈 RD200 측정치", "radon_rd200_net": "라돈 RD200 순농도",
             "thoron_rad7": "토론 RAD7 측정치", "thoron_bg": "토론 배경농도", "verdict": "판정"}
    rows = [_row("라돈·토론 완제품 (2026-07-02 특판 5종)", LABEL.get(k, k), list(v) if isinstance(v, tuple) else v,
                 list(got.get(k)) if isinstance(got.get(k), tuple) else got.get(k)) for k, v in T.EXPECTED.items()]
    return rows, ""


def check_material():
    """라돈 원자재 — L-26-033 원단 27종 네 회차 (test_material.KNOWN)."""
    import material, test_material as T
    eyes = T.load_eyes()
    if not eyes:
        return [], "자료/라돈_원자재/측정원본 이 없어 건너뜀"
    rows = []
    for fn, sn, want_bg, want_m in T.KNOWN:
        path = os.path.join(T.RAW, fn)
        if not os.path.exists(path) or sn not in eyes:
            continue
        v = material.compute(material.parse_ftlab(T._read(path)), eyes[sn])
        tag = "%s · %s" % (fn[:17], sn[-5:])
        rows.append(_row("라돈 원자재 (L-26-033 원단 27종)", tag + " 배경농도", want_bg, v["radon_bg"]))
        rows.append(_row("라돈 원자재 (L-26-033 원단 27종)", tag + " 측정치", want_m, v["radon"]))
    return rows, ""


def check_kc():
    """매트리스 KC — 샘플 1번 (test_kc.KNOWN)."""
    import kc, test_kc as T
    if not os.path.exists(T.CSV):
        return [], "자료/KC/측정원본 CSV 가 없어 건너뜀"
    data = kc.parse_upload(open(T.CSV, encoding="utf-8-sig").read(), os.path.basename(T.CSV))
    v = kc.compute(data)                      # test_kc 와 같은 기본 사이클(80,000)
    got = {"d": v["d"], "D1": [r["D1"] for r in v["rows"]], "D2": [r["D2"] for r in v["rows"]], "cycles": v["cycles"]}
    L = {"d": "처짐 d1·d2·d3 (mm)", "D1": "D1 (mm) 다섯 줄", "D2": "D2 (mm) 다섯 줄", "cycles": "사이클"}
    g = "매트리스 KC (샘플 1번)"
    rows = [_row(g, L[k], T.KNOWN[k], got[k]) for k in ("d", "D1", "D2", "cycles") if k in T.KNOWN]
    rows.append(_row(g, "판정", "적합", v.get("sag_verdict", "적합")))
    return rows, ""


def check_ks():
    """매트리스 KS — 샘플 2번 (test_ks.KNOWN) + 완성본 셀 14개."""
    import ks, test_ks as T
    from test_kc import cells, num
    if not os.path.exists(T.CSV):
        return [], "자료/KS/측정원본 CSV 가 없어 건너뜀"
    data = ks.parse_upload(open(T.CSV, encoding="utf-8-sig").read(), os.path.basename(T.CSV))
    v = ks.compute(data)
    got = {"d": v["d"], "D1": [r["D1"] for r in v["rows"]], "D2": [r["D2"] for r in v["rows"]], "cycles": v["cycles"]}
    L = {"d": "처짐 d1~d4 (mm)", "D1": "D1 (mm) 다섯 줄", "D2": "D2 (mm) 다섯 줄", "cycles": "사이클"}
    g = "매트리스 KS (샘플 2번 · L-26-043)"
    rows = [_row(g, L[k], T.KNOWN[k], got[k]) for k in ("d", "D1", "D2", "cycles")]
    rows.append(_row(g, "판정", "적합", v["sag_verdict"]))
    if os.path.exists(T.DONE):
        done, _ = cells(T.DONE)
        want = {"J57": 5, "O57": 11, "T57": 16, "Y57": 18, "P61": 42, "P62": 42, "P63": 41, "P64": 42, "P65": 41,
                "X61": 25, "X62": 22, "X63": 21, "X64": 19, "X65": 18}
        prog = {"J57": v["d"][0], "O57": v["d"][1], "T57": v["d"][2], "Y57": v["d"][3]}
        for i, r in enumerate(v["rows"]):
            prog["P%d" % (61 + i)] = r["D1"]
            prog["X%d" % (61 + i)] = r["D2"]
        for cell, w in want.items():
            rows.append(_row(g, "완성본 셀 %s" % cell, num(done.get(cell)), prog.get(cell)))
    return rows, ""


def run():
    """네 종류를 전부 돌려 검증결과.json 에 쓴다."""
    if _busy["on"]:
        return None
    _busy["on"] = True
    try:
        groups = []
        for name, fn in (("finished", check_finished), ("material", check_material), ("kc", check_kc), ("ks", check_ks)):
            try:
                rows, note = fn()
                groups.append({"kind": name, "rows": rows, "note": note, "error": ""})
            except Exception as e:
                groups.append({"kind": name, "rows": [], "note": "", "error": "%s: %s" % (type(e).__name__, str(e)[:160])})
        allrows = [r for g in groups for r in g["rows"]]
        res = {"at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "groups": groups,
               "n": len(allrows), "ok": sum(1 for r in allrows if r["ok"]),
               "code_mtime": max(os.path.getmtime(os.path.join(HERE, f)) for f in ("core.py", "material.py", "kc.py", "ks.py"))}
        tmp = OUT + ".tmp"
        json.dump(res, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, OUT)
        return res
    finally:
        _busy["on"] = False


def result():
    try:
        r = json.load(io.open(OUT, encoding="utf-8"))
    except Exception:
        r = {"at": "", "groups": [], "n": 0, "ok": 0, "code_mtime": 0}
    # 계산 코드가 검증 뒤에 바뀌었으면 알려준다
    try:
        now = max(os.path.getmtime(os.path.join(HERE, f)) for f in ("core.py", "material.py", "kc.py", "ks.py"))
        r["stale"] = bool(r.get("at")) and now > float(r.get("code_mtime") or 0) + 1
    except Exception:
        r["stale"] = False
    r["busy"] = _busy["on"]
    return r


def run_async():
    if _busy["on"]:
        return False
    threading.Thread(target=run, daemon=True).start()
    return True


if __name__ == "__main__":
    r = run()
    for g in r["groups"]:
        print("==", g["kind"], g["note"] or g["error"])
        for x in g["rows"]:
            print("  %s %-28s 사람 %-24s 프로그램 %s" % ("OK " if x["ok"] else "다름", x["item"], x["human"], x["program"]))
    print("%d / %d 일치" % (r["ok"], r["n"]))
