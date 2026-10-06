# -*- coding: utf-8 -*-
"""KC «매트리스 내구시험» 성적서 — CSV 읽기 · 계산 · 양식 채우기.

시험기(Mattress Endurance Tester Operation Program Ver.2.8.1)가 내보낸 CSV 한 개로
성적서 한 장을 만든다. 라돈과 달리 표가 늘고 줄지 않는다 — 양식은 38행에서
나뉘는 고정 2쪽이고, 정해진 칸에 값만 써 넣는다. 그래서 페이지 나눔 엔진은
쓰지 않고, 사진 앉히기와 셀 쓰기만 sheet.py 에서 가져온다.

계산 규칙은 자료/KC/KC_내구시험_사양서.md 에 있고, 완성본 1건과 11개 값이
전부 맞는 것을 test_kc.py 가 확인한다.
"""
import os, re, zipfile, tempfile, shutil, datetime

import xlsxgrid as XG
from sheet import (InputError, _round, read_text, save_photo, crop_to_box,
                   PHOTO_ROI_FULL, _cell, _set, _box_emu, _add_photo)

MAX_RUNS = 1                          # KC 는 시험 1건 = 성적서 1장

# ═══════════════════════════════════════════════ 시험 조건 (이 값이 아니면 다른 규격)
TARGETS = (147.0, 343.0, 784.0, 980.0)    # 변위를 읽는 하중(N)
MIN_LOAD, MAX_LOAD = 4.90, 980.0
CYCLES_EXPECT = (0, 200, 10000, 80000, 150000)
LAST_CHOICES = (80000, 150000)            # 성적서 넷째 줄에 실을 수 있는 사이클

# 판정 기준 — 양식 AI52 · AI56 에 적힌 그대로
SAG_LIMIT = 40.0          # d1, d2, d3 모두 40mm 이하
D1_MAX, D2_MIN = 45.0, 5.0  # D1 ≤ 45, D2 ≥ 5

METHOD = ("안전기준준수대상 생활용품 부속서 19 (침대 매트리스), "
          "침대/매트리스 내구성시험기 시험방법(S-QI-L05)")


# ═══════════════════════════════════════════════ 파서
def detect(text):
    """시험기 CSV 인지. 첫 줄이 OPT 로 시작하고 RST 줄이 있으면 맞다."""
    head = text.lstrip("﻿")[:4000]
    return bool(re.match(r"\s*OPT,\d+,\d+,", head)) and ("RST," in text)


def parse_csv(text):
    """OPT / ITEM / RAW / RST 네 종류 줄을 나눠 담는다.

    · OPT : 첫 블록(150줄)만 쓴다. 뒤에 한 번 더 나오지만 같은 내용이다.
    · RAW : 스텝 index 가 0부터다 (RST·OPT 의 스텝 번호는 1부터). 여기서 +1 해서
            전부 1부터로 맞춰 둔다.
    · RST : 덩어리가 스텝마다 하나씩 누적으로 쌓인다. n번째 덩어리엔 1~n 스텝만
            채워져 있으므로 «마지막 덩어리» 만 읽는다.
    """
    text = text.lstrip("﻿")
    lines = [l.strip() for l in text.replace("\r\n", "\n").split("\n") if l.strip()]
    opt, raw, rst_blocks, cur = {}, {}, [], None
    for l in lines:
        p = l.split(",")
        tag = p[0]
        if tag == "OPT":
            if len(p) < 4:
                continue
            st, it = int(p[1]), int(p[2])
            if st not in opt or it not in opt[st]:           # 첫 블록만
                opt.setdefault(st, {})[it] = ",".join(p[3:]).strip()
        elif tag == "RAW":
            if len(p) < 4:
                continue
            try:
                st = int(float(p[1])) + 1
                raw.setdefault(st, []).append((float(p[2]), float(p[3])))
            except ValueError:
                continue
        elif tag == "RST":
            if len(p) < 4:
                continue
            st, it = int(p[1]), int(p[2])
            if st == 1 and it == 1:                            # 새 덩어리 시작
                cur = {}
                rst_blocks.append(cur)
            if cur is not None:
                cur.setdefault(st, {})[it] = ",".join(p[3:]).strip()
    if not opt or not raw or not rst_blocks:
        raise InputError("내구시험기 CSV 가 아닙니다. OPT · RAW · RST 줄이 있어야 합니다.")
    return {"opt": opt, "raw": raw, "rst": rst_blocks[-1], "n_steps": len(raw)}


def parse_upload(text, filename):
    if not detect(text):
        raise InputError("'%s' 은(는) 매트리스 내구시험기 CSV 로 보이지 않습니다. "
                         "시험기 프로그램에서 저장한 원본 CSV 를 올려주세요." % filename)
    return parse_csv(text)


# ═══════════════════════════════════════════════ 계산
def _f(s, default=None):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return default


def first_over(samples, target):
    """하중이 기준값을 «처음으로» 넘는 샘플의 변위. 보간하지 않는다."""
    for load, disp in samples:
        if load >= target:
            return disp
    return None


def cumulative_cycles(opt, n_steps):
    """OPT 7번 항목은 이름이 '누적횟수' 지만 실제로는 «증분» 이다. 누적합을 만든다."""
    out, acc = [], 0.0
    for st in range(1, n_steps + 1):
        acc += _f(opt.get(st, {}).get(7), 0.0) or 0.0
        out.append(int(round(acc)))
    return out


def check_conditions(opt):
    """시험 조건이 KC 규격 그대로인지. 다르면 다른 시험이니 경고를 돌려준다."""
    o = opt.get(1, {})
    bad = []
    if _f(o.get(3)) != MIN_LOAD:
        bad.append("최소하중 %s (기준 %.2f)" % (o.get(3), MIN_LOAD))
    if _f(o.get(4)) != MAX_LOAD:
        bad.append("최대하중 %s (기준 %.0f)" % (o.get(4), MAX_LOAD))
    got = tuple(_f(o.get(i)) for i in (8, 9, 10, 11))
    if got != TARGETS:
        bad.append("하중 %s (기준 147·343·784·980)" % "·".join(str(x) for x in got))
    return bad


def compute(data, last_cycle=80000):
    """스텝별 변위 4개 · D1 · D2 · 누적 처짐을 구하고, 성적서 4줄을 고른다.

    last_cycle: 성적서 넷째 줄에 실을 사이클 (80,000 또는 150,000).
    """
    opt, raw, rst, n = data["opt"], data["raw"], data["rst"], data["n_steps"]
    warnings = []
    for b in check_conditions(opt):
        warnings.append("시험 조건이 KC 규격과 다릅니다 — " + b)

    cycles = cumulative_cycles(opt, n)
    steps = []
    for st in range(1, n + 1):
        disp = [first_over(raw[st], t) for t in TARGETS]
        if any(d is None for d in disp):
            raise InputError("%d번째 스텝의 하중이 %.0fN 까지 오르지 않았습니다. 측정이 "
                             "중간에 끊긴 파일입니다." % (st, MAX_LOAD))
        D1, D2 = disp[1] - disp[0], disp[3] - disp[2]
        r = rst.get(st, {})
        sag = _f(r.get(2))
        if sag is None:
            raise InputError("RST 에 %d번째 스텝의 누적 처짐이 없습니다." % st)
        # 장비가 스스로 계산해 둔 값과 맞춰 본다 — 안 맞으면 파일이 다른 형식이거나 손상
        dev = [(abs(disp[i] - (_f(r.get(3 + i)) or 0)), TARGETS[i]) for i in range(4)]
        dev += [(abs(D1 - (_f(r.get(7)) or 0)), "D1"), (abs(D2 - (_f(r.get(8)) or 0)), "D2")]
        off = [str(lab) for d, lab in dev if d > 0.011]
        if off:
            warnings.append("%d번째 스텝: RAW 로 다시 계산한 값이 장비 결과(RST)와 다릅니다 "
                            "(%s). 파일이 손상되었거나 다른 장비 형식입니다."
                            % (st, ", ".join(off)))
        steps.append({"step": st, "cycle": cycles[st - 1], "disp": disp,
                      "D1": D1, "D2": D2, "sag": sag})

    if tuple(cycles[:len(CYCLES_EXPECT)]) != CYCLES_EXPECT[:len(cycles)]:
        warnings.append("누적 사이클이 %s 입니다. KC 는 0·200·10,000·80,000·150,000 입니다."
                        % " / ".join("{:,}".format(c) for c in cycles))

    if last_cycle not in LAST_CHOICES:
        last_cycle = LAST_CHOICES[0]
    try:
        last = next(s for s in steps if s["cycle"] == last_cycle)
    except StopIteration:
        raise InputError("이 파일에는 {:,}회 스텝이 없습니다 (있는 것: {}). 넷째 줄 사이클을 "
                         "다시 골라주세요.".format(
                             last_cycle, ", ".join("{:,}".format(c) for c in cycles)))
    if len(steps) < 3:
        raise InputError("스텝이 %d개뿐입니다. 성적서에는 0·200·10,000회와 마지막 한 줄, "
                         "네 스텝이 필요합니다." % len(steps))
    rows_src = steps[:3] + [last]

    rows = []
    for s in rows_src:
        D1, D2 = _round(s["D1"]), _round(s["D2"])
        rows.append({"cycle": s["cycle"], "D1": D1, "D2": D2,
                     "verdict": "적합" if (D1 <= D1_MAX and D2 >= D2_MIN) else "부적합"})
    d = [_round(steps[1]["sag"]), _round(steps[2]["sag"]), _round(last["sag"])]
    sag_verdict = "적합" if all(x <= SAG_LIMIT for x in d) else "부적합"
    return {"rows": rows, "d": d, "sag_verdict": sag_verdict,
            "cycles": cycles, "steps": steps, "last_cycle": last_cycle,
            "warnings": warnings}


# ═══════════════════════════════════════════════ 양식 좌표
class L:
    REPORT_NO = "AN6"
    SAMPLE, REQ_DATE, TEST_DATE, PURPOSE = "H9", "AE9", "H10", "AE10"
    TEMP, PLACE, HUMID, ISSUE, METHOD = "M11", "AE11", "M12", "AE12", "H13"
    ISSUE2 = "AH30"                        # 1쪽 서명란의 발급일자
    SUMMARY = ("AN21", "AN22", "AN23", "AN24", "AN25", "AN26")   # 겉모양·치수·재료·내구성·수직하중·겉감
    DIMS = ("H47", "H48", "H49")           # 나비 · 길이 · 두께
    SAG = ("K52", "R52", "Y52")            # d1 · d2 · d3
    SAG_VERDICT = "AB52"
    ROW_LABEL = ("H56", "H57", "H58", "H59")
    ROW_D1 = ("P56", "P57", "P58", "P59")
    ROW_D2 = ("X56", "X57", "X58", "X59")
    ROW_VERDICT = ("AB56", "AB57", "AB58", "AB59")
    FABRIC = "H60"
    # 육안 검사 판정 칸 — 묶음별. 53~55행은 «내구성» 의 육안 항목이다
    # (6.1 (2) 겉감 닳음·풀림·찢어짐 / (3) 내용물 이동·뭉침·빠짐 / (4) 용수철 끊어짐·빠짐)
    JUDGE = {"appearance": ("AB45", "AB46"),
             "dims": ("AB47", "AB48", "AB49"),
             "material": ("AB50", "AB51"),
             "durability": ("AB53", "AB54", "AB55")}
    # 사진 줄과 그 줄의 세 칸 (열 번호, 1부터, 양끝 포함)
    PHOTO_ROWS = (45, 46, 53, 54, 55)
    PHOTO_COLS = ((8, 13), (14, 20), (21, 27))       # H..M / N..T / U..AA


PHOTO_ROW_NAMES = {45: "겉모양 · 겉감 (4.1.1)", 46: "겉모양 · 봉제 (4.1.2)",
                   53: "내구성 · 겉감 닳음·풀림·찢어짐 (6.1-2)",
                   54: "내구성 · 내용물 이동·뭉침·빠짐 (6.1-3)",
                   55: "내구성 · 용수철 끊어짐·빠짐 (6.1-4)"}


def to_serial(s):
    """'2026년 08월 24일' · '2026-08-24' · '2026.8.24' 를 엑셀 날짜 일련번호로. 못 읽으면 None."""
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", str(s or ""))
    if not m:
        return None
    try:
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return (d - datetime.date(1899, 12, 30)).days


def _set_date(g, coord, text):
    """날짜 칸은 엑셀 날짜 서식(yyyy년 m월 d일)이라 일련번호로 써야 서식이 살아난다."""
    n = to_serial(text)
    if n is None:
        _set(g, coord, text)
    else:
        _set(g, coord, n, is_num=True)


def photo_box_aspect(template_path):
    """사진칸(H..M, 45행)의 가로세로 비율을 양식에서 직접 잰다."""
    work = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(template_path) as z:
            z.extractall(work)
        g = XG.Grid(work)
        a, b = L.PHOTO_COLS[0]
        w = g.span_px(a, b)
        h = g.row_h(L.PHOTO_ROWS[0]) * 96.0 / 72.0
        return w / h if h else 1.1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_report(template_path, header, values, photos, out_path):
    """header : 머리말 dict (report_no, sample_title, request_date, test_date, purpose,
               temp, place, humid, issue_date, dims=(나비,길이,두께), fabric,
               judge={'appearance'|'dims'|'material'|'fabric': '적합'|'부적합'})
       values : compute() 결과
       photos : {행번호: [{'path', 'cropped'}, ...]}  (행마다 최대 3장)
    """
    warnings = list(values.get("warnings", []))
    work = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(template_path) as z:
            z.extractall(work)
        g = XG.Grid(work)

        # ── 머리말
        if header.get("report_no"):
            _set(g, L.REPORT_NO, "성적서번호\n" + header["report_no"])
        _set(g, L.SAMPLE, header.get("sample_title", ""))
        _set_date(g, L.REQ_DATE, header.get("request_date", ""))
        _set(g, L.TEST_DATE, header.get("test_date", ""))
        _set(g, L.PURPOSE, header.get("purpose") or "매트리스 품질관리용")
        _set(g, L.TEMP, header.get("temp") or "상  온")
        _set(g, L.PLACE, header.get("place") or "내구성 테스트실")
        _set(g, L.HUMID, header.get("humid") or "-")
        _set_date(g, L.ISSUE, header.get("issue_date", ""))
        _set_date(g, L.ISSUE2, header.get("issue_date", ""))
        _set(g, L.METHOD, METHOD)

        # ── 치수 · 겉감
        dims = header.get("dims") or ("", "", "")
        for coord, v in zip(L.DIMS, dims):
            v = str(v).strip()
            if v:
                _set(g, coord, float(v), is_num=True) if re.fullmatch(r"\d+(\.\d+)?", v) \
                    else _set(g, coord, v)
        if header.get("fabric"):
            _set(g, L.FABRIC, "공인기관 성적서 참조\n(%s)" % header["fabric"])

        # ── 육안 검사 판정 (사람이 정한 것)
        judge = header.get("judge") or {}
        for grp, cells in L.JUDGE.items():
            for c in cells:
                _set(g, c, judge.get(grp) or "적합")

        # ── 내구성 · 수직하중 (자동)
        for coord, v in zip(L.SAG, values["d"]):
            _set(g, coord, v, is_num=True)
        _set(g, L.SAG_VERDICT, values["sag_verdict"])
        for i, row in enumerate(values["rows"]):
            _set(g, L.ROW_LABEL[i], "{:,}회".format(row["cycle"]))
            _set(g, L.ROW_D1[i], row["D1"], is_num=True)
            _set(g, L.ROW_D2[i], row["D2"], is_num=True)
            _set(g, L.ROW_VERDICT[i], row["verdict"])

        # ── 요약 결과 (1쪽 표) — 항목 순서: 겉모양 · 치수 · 재료 · 내구성 · 수직하중 · 겉감
        row_ok = all(r["verdict"] == "적합" for r in values["rows"])
        dur_ok = values["sag_verdict"] == "적합" and (judge.get("durability") or "적합") == "적합"
        summ = [judge.get("appearance") or "적합", judge.get("dims") or "적합",
                judge.get("material") or "적합", "적합" if dur_ok else "부적합",
                "적합" if row_ok else "부적합", judge.get("fabric") or "적합"]
        for coord, v in zip(L.SUMMARY, summ):
            _set(g, coord, "기준 " + v)

        # ── 사진 (줄마다 최대 3장, 왼쪽부터)
        uid = 0
        for row in L.PHOTO_ROWS:
            for k, ph in enumerate((photos or {}).get(row, [])[:3]):
                if not ph or not ph.get("path"):
                    continue
                c_a, c_b = L.PHOTO_COLS[k]
                box_w, box_h = _box_emu(g, c_a, c_b, row, 1)
                media = "kcphoto%d.jpeg" % uid
                dest = os.path.join(work, "xl", "media", media)
                # 매트리스 사진은 라돈처럼 위아래를 버릴 이유가 없다. 폰 사진(4:3)을
                # 거의 정사각인 칸에 넣으려면 «가운데 기준으로 좌우만» 잘라야 한다.
                roi = PHOTO_ROI_FULL
                crop_to_box(ph["path"], dest, box_w / float(box_h), roi=roi)
                _add_photo(work, g, media, c_a, c_b, row, 1, 1000 + uid)
                uid += 1

        g.save()
        XG.drop_calcchain(work)
        if os.path.exists(out_path):
            os.remove(out_path)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(work):
                for fn in files:
                    full = os.path.join(root, fn)
                    zf.write(full, os.path.relpath(full, work).replace(os.sep, "/"))
        return warnings
    finally:
        shutil.rmtree(work, ignore_errors=True)
