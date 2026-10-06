# -*- coding: utf-8 -*-
"""KS «가정용 일반침대 (KS G 4300)» 매트리스 성적서 — CSV 읽기 · 계산 · 양식 채우기.

측정 파일은 KC 와 같은 내구시험기(Mattress Endurance Tester) CSV 다. 그래서 파서와
변위 계산은 kc.py 것을 그대로 쓰고, 여기서는 KS 양식에 맞는 것만 다르다.

  · 다섯 스텝을 전부 싣는다 (0 · 200 · 10,000 · 80,000 · 150,000회) — 고르지 않는다
  · 간격의 양 d1~d4 네 개 (2~5번째 스텝의 누적 처짐), 모두 40mm 이하
  · 수직하중 D1 ≤ 45, D2 ≥ 5 (KC 와 같다)
  · 치수는 규격 4.2.3 허용차로 자동 판정 — 나비·길이 (+30, −20), 두께 (±20)
  · 육안·공인기관 항목(품질 9 · 내구성 3 · 다리부 1 · 구조 4 · 겉감)은 사람이 정한다

양식은 3쪽 고정이다. 빈 양식 그대로 인쇄하면 엑셀이 38·64행에서 자동으로 나눠 4쪽이
되고 수직하중 표가 두 쪽에 걸쳐 잘린다. 그래서 양식의 가로줄(39/43 · 68/70행)이 뜻하는
대로 42·69행 뒤에 나눔을 박고, 위아래 여백을 조금 줄여 한 쪽에 들어가게 한다.
"""
import os, re, zipfile, tempfile, shutil

from lxml import etree

import xlsxgrid as XG
import kc
from kc import (InputError, _round, read_text, save_photo, crop_to_box,   # noqa: F401
                PHOTO_ROI_FULL, _set, to_serial, _set_date, _f,
                first_over, cumulative_cycles, check_conditions,
                TARGETS, MAX_LOAD, CYCLES_EXPECT, SAG_LIMIT, D1_MAX, D2_MIN)
from sheet import A_NS, R_NS, PKG_RELS, M, D

MAX_RUNS = 1

detect = kc.detect
parse_csv = kc.parse_csv
parse_upload = kc.parse_upload

METHOD = ("가정용 일반침대(KS G 4300:2020), "
          "침대/매트리스 내구성시험기 시험방법(S-QI-L05)")

# 치수 허용차 — 양식 AI86 «4.2.3 매트리스의 제작 허용차»
DIM_TOL = {"w": (30, -20), "l": (30, -20), "t": (20, -20)}
DIM_DEFAULT = {"w": 1500, "l": 2000, "t": 340}     # 빈 양식에 적힌 기준 치수 (화면의 회색 안내글로만 쓴다)

PHOTO_ASPECT = 4.0 / 3.0       # 사진은 4:3 으로 잘라 칸 안에 세로 가운데로 앉힌다


# ═══════════════════════════════════════════════ 계산
def compute(data):
    """다섯 스텝의 D1·D2 와 d1~d4 를 구한다. 스텝이 모자라면 있는 만큼만 채우고 알린다."""
    opt, raw, rst, n = data["opt"], data["raw"], data["rst"], data["n_steps"]
    warnings = []
    for b in check_conditions(opt):
        warnings.append("시험 조건이 KS 규격과 다릅니다 — " + b)

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
        warnings.append("누적 사이클이 %s 입니다. KS 는 0·200·10,000·80,000·150,000 입니다."
                        % " / ".join("{:,}".format(c) for c in cycles))
    if len(steps) < 3:
        raise InputError("스텝이 %d개뿐입니다. 성적서에는 최소 0·200·10,000회 세 스텝이 "
                         "필요합니다." % len(steps))
    if len(steps) < len(CYCLES_EXPECT):
        missing = CYCLES_EXPECT[len(steps):]
        warnings.append("이 파일에는 %s 스텝이 없어 그 줄은 비워 두었습니다. 성적서를 열어 "
                        "직접 채우거나, 시험을 끝까지 마친 CSV 를 올리세요."
                        % " · ".join("{:,}회".format(c) for c in missing))

    rows = []
    for s in steps[:5]:
        D1, D2 = _round(s["D1"]), _round(s["D2"])
        rows.append({"cycle": s["cycle"], "D1": D1, "D2": D2,
                     "verdict": "적합" if (D1 <= D1_MAX and D2 >= D2_MIN) else "부적합"})
    d = [_round(s["sag"]) for s in steps[1:5]]           # d1~d4 = 2~5번째 스텝
    sag_verdict = "적합" if all(x <= SAG_LIMIT for x in d) else "부적합"
    return {"rows": rows, "d": d, "sag_verdict": sag_verdict, "cycles": cycles,
            "steps": steps, "complete": len(steps) >= 5, "warnings": warnings}


def clean_num(v):
    """'1,485' · '1982mm' · ' 405 ' 처럼 사람이 적은 치수를 숫자 글자만 남긴다."""
    return re.sub(r"(?i)mm|,|\s", "", str(v or ""))


def judge_dims(dims, spec):
    """치수 (나비·길이·두께) 를 기준치와 허용차로 판정. 잰 값이나 기준 치수가 없으면 None.
    기준 치수는 제품마다 달라 기본값을 넣지 않는다 — 모르고 넘어가면 엉뚱한 판정이 나간다."""
    out = []
    for key, v in zip(("w", "l", "t"), dims):
        v = _f(clean_num(v))
        base = _f(clean_num((spec or {}).get(key)))
        if v is None or base is None:
            out.append(None)
            continue
        hi, lo = DIM_TOL[key]
        out.append("적합" if (base + lo) <= v <= (base + hi) else "부적합")
    return out


def dim_spec_text(spec):
    """AI86 검사기준 문구를 기준 치수에 맞춰 다시 쓴다. 비운 것은 양식 숫자를 그대로 둔다."""
    g = lambda k: int(_f(clean_num((spec or {}).get(k))) or DIM_DEFAULT[k])
    return ("4.2.3 매트리스의 제작 허용차\n나비 : {:,} (+30,-20)\n길이 : {:,} (+30,-20), \n"
            "두께 : {:,}  (±20)".format(g("w"), g("l"), g("t")))


# ═══════════════════════════════════════════════ 양식 좌표
class L:
    REPORT_NO = "AN6"
    SAMPLE, REQ_DATE, TEST_DATE, PURPOSE = "H9", "AE9", "H10", "AE10"
    TEMP, PLACE, HUMID, ISSUE, METHOD = "M11", "AE11", "M12", "AE12", "H13"
    ISSUE2 = "AH31"
    # 1쪽 요약: 품질 · 내구성 · 수직하중 · 다리부의 강도 · 겉감의 품질 · 매트리스 치수 · 구조 및 가공
    SUMMARY = ("X21", "X22", "X23", "X24", "X25", "X26", "X27")
    SAG = ("J57", "O57", "T57", "Y57")            # d1~d4
    SAG_VERDICT = "AB57"
    ROW_LABEL = ("H61", "H62", "H63", "H64", "H65")
    ROW_D1 = ("P61", "P62", "P63", "P64", "P65")
    ROW_D2 = ("X61", "X62", "X63", "X64", "X65")
    ROW_VERDICT = ("AB61", "AB62", "AB63", "AB64", "AB65")
    FABRIC = "H77"
    DIMS = ("H86", "H87", "H88")
    DIM_VERDICT = ("AB86", "AB87", "AB88")
    DIM_SPEC = "AI86"
    # 사람이 정하는 판정 칸 — 항목 하나에 칸 하나 (JUDGE_ITEMS 와 순서가 같다)
    JUDGE = {"q_a": "AB48", "q_b": "AB49", "q_c": "AB50", "q_d": "AB51", "q_e": "AB52",
             "q_f": "AB53", "q_g": "AB54", "q_h": "AB55", "q_i": "AB56",
             "dur_b": "AB58", "dur_c": "AB59", "dur_d": "AB60",
             "legs": "AB75",
             "st_a": "AB89", "st_b": "AB90", "st_c": "AB91", "st_d": "AB92"}
    # 사진 묶음: (첫 행, 행 수). 세 칸의 열은 KC 와 같다
    PHOTO_BLOCKS = ((49, 2), (52, 3), (55, 2), (58, 1), (59, 1), (60, 1), (75, 2), (90, 2))
    PHOTO_COLS = ((8, 13), (14, 20), (21, 27))    # H..M / N..T / U..AA
    PAGE_BREAKS = (42, 69)                        # 이 행 «뒤» 에서 쪽이 바뀐다
    MARGIN_TB = 0.5                               # 위·아래 여백(inch). 0.75 면 2쪽이 넘친다
    SCALE = 94                                    # 인쇄 배율(%). 1·2쪽이 각각 한 장에 들어가는 값


PHOTO_ROWS = tuple(b[0] for b in L.PHOTO_BLOCKS)
PHOTO_ROW_NAMES = {49: "품질 · 가공·소음·안정성 (5.a~c)",
                   52: "품질 · 다듬질·안전·겉감 (5.d~f)",
                   55: "품질 · 봉제·금속부·도막 (5.g~i)",
                   58: "내구성 · 겉감 닳음·풀림·찢어짐 (b)",
                   59: "내구성 · 내용물 이동·뭉침·빠짐 (c)",
                   60: "내구성 · 용수철 끊어짐·빠짐 (d)",
                   75: "다리부의 강도",
                   90: "구조 및 가공 (8.a~d)"}
# 화면에 늘어놓는 판정 항목: (키, 묶음, 짧은 이름). 묶음은 1쪽 요약 한 줄에 해당한다.
JUDGE_ITEMS = (
    ("q_a", "quality", "5.a 봉제·못질·접착·용접 가공, 흠·균열·변형 없음", "5.a"),
    ("q_b", "quality", "5.b 삐걱거림·이상음 없음", "5.b"),
    ("q_c", "quality", "5.c 바닥면에 안정, 바닥 손상 없음", "5.c"),
    ("q_d", "quality", "5.d 다듬질 양호, 예리한 돌기·거스러미 없음", "5.d"),
    ("q_e", "quality", "5.e 유해 가스·불쾌한 냄새 없음", "5.e"),
    ("q_f", "quality", "5.f 겉감 강도, 색 빠짐·퇴색·얼룩 없음", "5.f"),
    ("q_g", "quality", "5.g 봉제 땀 간격 일정, 실 끊어짐·풀림 없음", "5.g"),
    ("q_h", "quality", "5.h 금속부 곰팡이 없음", "5.h"),
    ("q_i", "quality", "5.i 도막 벗겨짐·균열·색 얼룩 없음", "5.i"),
    ("dur_b", "durability", "내구성 (b) 겉감 닳음·풀림·찢어짐 없음", "내구성(b)"),
    ("dur_c", "durability", "내구성 (c) 내용물 이동·뭉침·빠짐 없음", "내구성(c)"),
    ("dur_d", "durability", "내구성 (d) 용수철 끊어짐·빠짐 없음", "내구성(d)"),
    ("legs", "legs", "다리부의 강도 — 헐거움·흔들거림·변형 없음", "다리부"),
    ("fabric", "fabric", "겉감의 품질 — 공인기관 성적서 기준 충족", "겉감"),
    ("st_a", "structure", "8.a 구조 강도·안정성, 공작 확실", "8.a"),
    ("st_b", "structure", "8.b 목질재 갈라짐·어긋남·벌레먹음 없음", "8.b"),
    ("st_c", "structure", "8.c 접착·용접 확실, 접합면 다듬질", "8.c"),
    ("st_d", "structure", "8.d 나사류 결합부 헐거움 없음", "8.d"),
)
VERDICTS = ("적합", "부적합")
GROUP_NAMES = {"quality": "품질", "durability": "내구성 (육안)", "legs": "다리부의 강도",
               "fabric": "겉감의 품질", "structure": "구조 및 가공"}


def photo_box_aspect(template_path):
    return PHOTO_ASPECT


# ═══════════════════════════════════════════════ 사진: 칸 안에 4:3 으로 가운데 앉히기
def _add_photo_fit(work, g, media_name, col_a, col_b, row, n_rows, aspect, uid):
    """칸 폭에 맞춘 4:3 사진을 묶음 높이의 세로 가운데에 놓는다 (oneCellAnchor).
    KC 처럼 칸을 꽉 채우면 3줄짜리 묶음(52~54행)이 세로로 길어져 매트리스 사진이 어색하다."""
    relp = os.path.join(work, "xl", "drawings", "_rels", "drawing1.xml.rels")
    rt = etree.parse(relp)
    rr = rt.getroot()
    rid = "rIdPhoto%d" % uid
    if not any(x.get("Id") == rid for x in rr):
        rel = etree.SubElement(rr, "{%s}Relationship" % PKG_RELS)
        rel.set("Id", rid)
        rel.set("Type", R_NS + "/image")
        rel.set("Target", "../media/" + media_name)
        rt.write(relp, xml_declaration=True, encoding="UTF-8", standalone=True)

    pad = 28000
    box_w = g.span_px(col_a, col_b) * XG.EMU_PER_PX - pad * 2
    box_h = g.span_h(row, row + n_rows - 1) * XG.EMU_PER_PT - pad * 2
    # 세 칸의 열 수가 6·7·7 로 달라 폭이 다르다. 가장 좁은 칸에 맞춰 셋을 같은 크기로
    w = min(g.span_px(a, b) for a, b in L.PHOTO_COLS) * XG.EMU_PER_PX - pad * 2
    h = w / aspect
    if h > box_h:
        h = box_h
        w = h * aspect
    x_off = pad + (box_w - w) / 2.0
    y_off = pad + (box_h - h) / 2.0
    # y_off 가 어느 행 안에 떨어지는지 찾는다
    r = row
    while r < row + n_rows - 1 and y_off >= g.row_h(r) * XG.EMU_PER_PT:
        y_off -= g.row_h(r) * XG.EMU_PER_PT
        r += 1

    dr = g.draw.getroot()
    anc = etree.SubElement(dr, D + "oneCellAnchor")
    frm = etree.SubElement(anc, D + "from")
    for tag, val in (("col", col_a - 1), ("colOff", int(x_off)),
                     ("row", r - 1), ("rowOff", int(y_off))):
        e = etree.SubElement(frm, D + tag)
        e.text = str(val)
    ext = etree.SubElement(anc, D + "ext")
    ext.set("cx", str(int(w)))
    ext.set("cy", str(int(h)))
    pic = etree.SubElement(anc, D + "pic")
    nv = etree.SubElement(pic, D + "nvPicPr")
    cn = etree.SubElement(nv, D + "cNvPr")
    cn.set("id", str(5000 + uid))
    cn.set("name", media_name)
    etree.SubElement(nv, D + "cNvPicPr")
    bf = etree.SubElement(pic, D + "blipFill")
    b = etree.SubElement(bf, "{%s}blip" % A_NS, nsmap={"r": R_NS})
    b.set("{%s}embed" % R_NS, rid)
    st = etree.SubElement(bf, "{%s}stretch" % A_NS)
    etree.SubElement(st, "{%s}fillRect" % A_NS)
    spr = etree.SubElement(pic, D + "spPr")
    xf = etree.SubElement(spr, "{%s}xfrm" % A_NS)
    of = etree.SubElement(xf, "{%s}off" % A_NS)
    of.set("x", "0")
    of.set("y", "0")
    ex = etree.SubElement(xf, "{%s}ext" % A_NS)
    ex.set("cx", str(int(w)))
    ex.set("cy", str(int(h)))
    pg = etree.SubElement(spr, "{%s}prstGeom" % A_NS)
    pg.set("prst", "rect")
    etree.SubElement(pg, "{%s}avLst" % A_NS)
    etree.SubElement(anc, D + "clientData")


def _fit_pages(g):
    """42·69행 뒤에서 쪽을 나누고, 위아래 여백을 줄여 세 쪽이 딱 맞게 한다."""
    for b in list(g.breaks()):
        g.remove_break(b)
    for b in L.PAGE_BREAKS:
        g.add_break(b)
    pm = g.root.find(M + "pageMargins")
    if pm is not None:
        pm.set("top", "%.2f" % L.MARGIN_TB)
        pm.set("bottom", "%.2f" % L.MARGIN_TB)
    ps = g.root.find(M + "pageSetup")
    if ps is not None:
        ps.set("scale", str(L.SCALE))
        ps.attrib.pop("fitToHeight", None)
        ps.attrib.pop("fitToWidth", None)


# ═══════════════════════════════════════════════ 양식 채우기
def build_report(template_path, header, values, photos, out_path):
    """header : report_no, sample_title, request_date, test_date, purpose, temp, place, humid,
               issue_date, dims=(나비,길이,두께), dim_spec={'w','l','t'} 기준 치수, fabric,
               judge={'quality'|'durability'|'legs'|'fabric'|'structure': '적합'|'부적합'},
               dims_judge='자동'|'적합'|'부적합'
       values : compute() 결과
       photos : {첫 행: [{'path', 'cropped'}, ...]}  (묶음마다 최대 3장)
    """
    warnings = list(values.get("warnings", []))
    work = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(template_path) as z:
            z.extractall(work)
        g = XG.Grid(work)

        # ── 머리말
        _set(g, L.REPORT_NO, "성적서번호\n" + (header.get("report_no") or ""))
        if not header.get("report_no"):
            warnings.append("성적서번호가 비어 있습니다.")
        _set(g, L.SAMPLE, header.get("sample_title", ""))
        for lab, key in (("의뢰일자", "request_date"), ("발급일자", "issue_date")):
            if header.get(key) and to_serial(header[key]) is None:
                warnings.append("%s '%s' 를 날짜로 읽지 못해 글자 그대로 넣었습니다. "
                                "'2026년 04월 20일' 처럼 연·월·일을 다 적으세요." % (lab, header[key]))
        _set_date(g, L.REQ_DATE, header.get("request_date", ""))
        _set(g, L.TEST_DATE, header.get("test_date", ""))
        _set(g, L.PURPOSE, header.get("purpose") or "매트리스 품질관리용")
        _set(g, L.TEMP, header.get("temp") or "상  온")
        _set(g, L.PLACE, header.get("place") or "내구성 테스트실")
        _set(g, L.HUMID, header.get("humid") or "-")
        _set_date(g, L.ISSUE, header.get("issue_date", ""))
        _set_date(g, L.ISSUE2, header.get("issue_date", ""))
        _set(g, L.METHOD, METHOD)

        # ── 겉감
        if header.get("fabric"):
            _set(g, L.FABRIC, "공인기관 성적서 참조\n(%s)" % header["fabric"])

        # ── 치수 (자동 판정)
        dims = tuple(clean_num(v) for v in (header.get("dims") or ("", "", "")))
        spec = header.get("dim_spec") or {}
        if any(_f(spec.get(k)) is not None for k in ("w", "l", "t")):
            _set(g, L.DIM_SPEC, dim_spec_text(spec))
        dj = judge_dims(dims, spec)
        force = header.get("dims_judge") or "자동"
        for coord, v in zip(L.DIMS, dims):
            if re.fullmatch(r"\d+", v):
                _set(g, coord, int(v), is_num=True)
            elif re.fullmatch(r"\d+\.\d+", v):
                _set(g, coord, float(v), is_num=True)
            elif v:
                _set(g, coord, v)
        for coord, j in zip(L.DIM_VERDICT, dj):
            if force != "자동":
                _set(g, coord, force)
            elif j is not None:
                _set(g, coord, j)
        if force != "자동":
            dims_ok = force == "적합"
            if not any(dims):
                warnings.append("치수를 적지 않고 치수 판정만 «%s» 으로 정했습니다." % force)
        else:
            dims_ok = all(j == "적합" for j in dj if j is not None)
            if any(j is None for j in dj):
                blank = [n for n, j in zip(("나비", "길이", "두께"), dj) if j is None]
                why = "잰 값이나 기준 치수가" if any(_f(v) is not None for v in dims) else "잰 값이"
                warnings.append("치수 %s 의 %s 비어 있어 그 줄 판정을 비워 두었습니다."
                                % (" · ".join(blank), why))
            elif not dims_ok:
                warnings.append("치수가 허용차를 벗어나 «부적합» 으로 판정했습니다. 기준 치수가 "
                                "다른 제품이면 나비·길이·두께 기준을 바꿔 다시 만드세요.")

        # ── 육안 검사 판정
        judge = header.get("judge") or {}
        for key, c in L.JUDGE.items():
            _set(g, c, judge.get(key) or "적합")

        # ── 내구성 · 수직하중 (자동)
        for coord, v in zip(L.SAG, values["d"]):
            _set(g, coord, v, is_num=True)
        _set(g, L.SAG_VERDICT, values["sag_verdict"])
        for i, row in enumerate(values["rows"]):
            _set(g, L.ROW_LABEL[i], "{:,}회".format(row["cycle"]))
            _set(g, L.ROW_D1[i], row["D1"], is_num=True)
            _set(g, L.ROW_D2[i], row["D2"], is_num=True)
            _set(g, L.ROW_VERDICT[i], row["verdict"])

        # ── 1쪽 요약
        # 묶음의 항목이 하나라도 부적합이면 그 줄은 부적합
        ok = lambda grp: all((judge.get(k) or "적합") == "적합"
                             for k, gname, _, _ in JUDGE_ITEMS if gname == grp)
        row_ok = all(r["verdict"] == "적합" for r in values["rows"])
        dims_blank = force == "자동" and any(j is None for j in dj)   # 판정 못 했으면 요약도 비운다
        summ = [ok("quality"),
                values["sag_verdict"] == "적합" and ok("durability"),
                row_ok, ok("legs"), ok("fabric"), None if dims_blank else dims_ok, ok("structure")]
        for coord, v in zip(L.SUMMARY, summ):
            if v is None:
                continue
            _set(g, coord, "기준 " + ("적합" if v else "부적합"))

        # ── 사진
        uid = 0
        for row, n_rows in L.PHOTO_BLOCKS:
            for k, ph in enumerate((photos or {}).get(row, [])[:3]):
                if not ph or not ph.get("path"):
                    continue
                c_a, c_b = L.PHOTO_COLS[k]
                media = "ksphoto%d.jpeg" % uid
                dest = os.path.join(work, "xl", "media", media)
                crop_to_box(ph["path"], dest, PHOTO_ASPECT, roi=PHOTO_ROI_FULL)
                _add_photo_fit(work, g, media, c_a, c_b, row, n_rows, PHOTO_ASPECT, 2000 + uid)
                uid += 1

        _fit_pages(g)
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
