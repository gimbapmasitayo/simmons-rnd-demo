# -*- coding: utf-8 -*-
"""라돈·토론 «완제품» 성적서 — 파일 읽기 · 계산 · 양식 채우기.

표는 시료 수에 맞춰 정확히 늘어나고 줄어든다. 빈 줄이 남지 않는다.
행 이동은 xlsxgrid.Grid 가, 성적서 종류를 안 타는 공통 부분은 sheet.py 가 맡는다.
라돈 «원자재» 성적서는 material.py 에 따로 있다.
"""
import os, re, math, zipfile, shutil, tempfile
from datetime import datetime

import xlsxgrid as XG
from sheet import (InputError, _round, read_text, save_photo, crop_to_box,
                   PHOTO_ROI, PHOTO_ROI_FULL, PAGE_TARGET, PRINT_LAST_COL,
                   PRINT_SCALE, FOOTER_RESERVE, SUM_MIN_ROW_H, SUM_MIN_FONT,
                   PAPER, page_budget, MAIN, A_NS, R_NS, PKG_RELS, XDR, M, D,
                   _cell, _set, _box_emu, PHOTO_PAD_EMU, _add_photo,
                   _apply_print_scale, _set_print_area, _paginate, _pad_page,
                   _rule_stencil, _add_page_rules, _page_frame,
                   _pad_keep_shapes)

MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
LIMIT = 10          # 자사 기준치: 측정치-배경농도 <= 10 이면 적합
MAX_SAMPLES = 200   # 안전 상한 (실제 표는 시료 수에 맞춰 늘어남)
MAX_RUNS = 20       # 한 성적서에 담을 측정 회차 상한


# ═══════════════════════════════════════════════ 장비 판별
def detect_device(text, filename=""):
    if "DURRIDGE" in text or "RAD7" in text or filename.lower().endswith(".r7cdt"):
        return "RAD7"
    if "FRD400" in text:
        return "FRD400"
    if "RadonEye" in text or "RD200" in text:
        return "RD200"
    return "UNKNOWN"


# ═══════════════════════════════════════════════ 파서
def parse_rad7(text):
    """RAD7 의 Data Print 블록(사람이 읽는 형태)을 읽는다.

        3001 12.5+-17.3 B Sniff
        0.00+-20.1 B Thoron
        THU 02-JUL-26 18:13
        26.7`C RH:53% B:7.00V
    """
    lines = text.replace("\r\n", "\n").split("\n")
    rs = re.compile(r'^\s*(\d{3,4})\s+([\d.]+)\+-([\d.]+)\s+B\s+(Sniff|Normal)')
    out = {}
    no = 0
    i = 0
    while i < len(lines):
        m = rs.match(lines[i])
        if m and i + 3 < len(lines):
            m2 = re.search(r'([\d.]+)\+-([\d.]+)\s+B\s+Thoron', lines[i + 1])
            m3 = re.search(r'(\d{2})-([A-Z]{3})-(\d{2})\s+(\d{2}):(\d{2})', lines[i + 2])
            if m2 and m3 and m3.group(2) in MONTHS:
                dd, mon, yy, hh, mm = m3.groups()
                key = "20%s-%02d-%s %s" % (yy, MONTHS[mon], dd, hh)
                # DATA No. 는 «3005» 처럼 회차번호가 앞에 붙어 나온다(회차 30의 5번).
                # 자릿수가 회차에 따라 달라지므로 읽은 순서로 센다 — 화면에 찍히는
                # 번호 순서와 같다. 원본 번호는 tag 에 그대로 남겨 둔다.
                no += 1
                out[key] = {"radon": float(m.group(2)), "thoron": float(m2.group(1)),
                            "no": no, "tag": m.group(1)}
            i += 4
        else:
            i += 1
    return out


def parse_ftlab(text):
    """FRD400 / RadonEye 의 탭 구분 텍스트를 읽는다.

    칸 구성:  No | 날짜시간 | 라돈 | ...
    줄 번호(No)도 같이 담아 둔다. 토론 배경농도를 구할 때 쓴다.
    """
    out = {}
    for ln in text.replace("\r\n", "\n").split("\n"):
        p = ln.split("\t")
        if len(p) >= 3 and p[0].strip().isdigit():
            try:
                dt = datetime.strptime(p[1].strip().replace(".", "-"), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            try:
                rec = {"radon": float(p[2].strip()), "no": int(p[0].strip())}
            except ValueError:
                continue
            out[dt.strftime("%Y-%m-%d %H")] = rec
    return out


THORON_ROWS = (5, 7)             # 토론 «측정치» 로 쓰는 RAD7 DATA No. 구간(양끝 포함)
THORON_BG_ROWS = (2, 3)          # 토론 배경농도로 쓰는 FRD400 줄 번호


def thoron_value(rad7, rows=THORON_ROWS):
    """토론 측정치 = RAD7 의 DATA No.5 ~ No.7 세 줄 평균.

    라돈은 측정 구간 전체를 평균내지만, 토론은 이 세 줄만 쓴다(측정실 규칙).
    """
    lo, hi = rows
    v = [r["thoron"] for r in rad7.values()
         if "thoron" in r and lo <= r.get("no", 0) <= hi]
    return sum(v) / len(v) if v else None


def thoron_background(frd_bg, rows=THORON_BG_ROWS):
    """토론 배경농도 = FRD400 파일의 No.2, No.3 두 줄의 라돈 칸 평균.

    라돈 배경농도는 측정 구간 전체 평균이지만, 토론 배경농도는
    측정 시작 직후 두 줄만 쓴다. FRD400 은 라돈 측정기인데 그 값을 토론
    배경으로 쓰는 것이 낯설어 보이지만, 측정실에서 맞다고 확인한
    규칙이다(2026-09-14). 고치지 말 것.
    """
    v = [r["radon"] for r in frd_bg.values()
         if r.get("no") in rows and "radon" in r]
    return sum(v) / len(v) if v else None




LABEL = {"RAD7": "RAD7", "FRD400": "FRD400(배경농도)", "RD200": "RD200(RadonEye)"}


def parse_upload(text, filename, expect):
    dev = detect_device(text, filename)
    if dev == "UNKNOWN":
        raise InputError("'%s' 은(는) 인식할 수 없는 파일입니다. %s 장비에서 내보낸 원본이 "
                         "맞는지 확인해주세요." % (filename, LABEL[expect]))
    if dev != expect:
        raise InputError("'%s' 은(는) %s 파일로 보입니다. %s 칸이 아니라 %s 칸에 올려주세요."
                         % (filename, LABEL[dev], LABEL[expect], LABEL[dev]))
    d = parse_rad7(text) if expect == "RAD7" else parse_ftlab(text)
    if not d:
        if expect == "RAD7":
            raise InputError("'%s' 에서 측정값을 찾지 못했습니다. CAPTURE로 내보낼 때 "
                             "'Data Print' 를 포함해 저장해주세요. "
                             "(Data Com 만 있으면 토론값이 없습니다)" % filename)
        raise InputError("'%s' 에서 측정값을 찾지 못했습니다. 파일이 비었거나 형식이 다릅니다."
                         % filename)
    return d


# ═══════════════════════════════════════════════ 계산
def _avg(dic, key, hours):
    v = [dic[h][key] for h in hours if h in dic and key in dic[h]]
    return sum(v) / len(v) if v else None



def compute(rad7, rd200, frd_bg):
    """세 장비 dict 을 받아 공통 시간구간 평균 · 배경차감 · 판정 계산"""
    hours = sorted(rad7.keys())                      # RAD7 측정구간 기준
    if not hours:
        raise InputError("RAD7 파일에서 측정값을 찾지 못했습니다.")

    def need(dic, key, label):
        v = _avg(dic, key, hours)
        if v is None:
            raise InputError("%s 파일에 RAD7 측정시간(%s시 ~ %s시)과 겹치는 데이터가 "
                             "없습니다. 같은 회차의 파일이 맞는지 확인해주세요."
                             % (label, hours[0], hours[-1]))
        return v

    bg = _round(need(frd_bg, "radon", "FRD400(배경농도)"))
    r_r7 = _round(need(rad7, "radon", "RAD7"))
    r_rd = _round(need(rd200, "radon", "RD200(RadonEye)"))
    # 토론 측정치만 규칙이 다르다 — 구간 전체가 아니라 DATA No.5~7 세 줄.
    t_raw = thoron_value(rad7)
    if t_raw is None:
        raise InputError("RAD7 파일에 DATA No.%d~%d 가 없습니다. 토론 측정치는 그 세 줄로 "
                         "냅니다. 지금 파일은 %d줄뿐입니다."
                         % (THORON_ROWS[0], THORON_ROWS[1], len(rad7)))
    t_r7 = _round(t_raw)              # 라돈과 같이 정수로 반올림한다 (6.73 -> 7)

    # 토론 배경농도는 FRD400 파일의 No.2, No.3 두 줄 평균으로 구한다.
    t_bg_raw = thoron_background(frd_bg)
    t_bg = _round(t_bg_raw, 1) if t_bg_raw is not None else 0.0

    net_r7 = max(0, r_r7 - bg)
    net_rd = max(0, r_rd - bg)
    net_t = _round(max(0.0, t_r7 - t_bg))

    # 판정은 배경을 뺀 값으로 한다 (실제 성적서와 동일)
    verdict = "적합" if (net_r7 <= LIMIT and net_rd <= LIMIT and net_t <= LIMIT) else "부적합"
    return {"hours": len(hours), "period": (hours[0], hours[-1]),
            "radon_bg": bg, "radon_rad7": r_r7, "radon_rad7_net": net_r7,
            "radon_rd200": r_rd, "radon_rd200_net": net_rd,
            "thoron_bg": t_bg, "thoron_rad7": t_r7, "thoron_net": net_t,
            "verdict": verdict}




# ═══════════════════════════════════════════════ 양식 좌표 (원본 기준)
class L:
    PAGE1 = 1
    SUM_TITLE, SUM_HDR = 19, 20
    SUM_FIRST, SUM_SLOTS, SUM_LAST = 21, 11, 31
    SUM_SUF_A, SUM_SUF_B = 32, 46
    ISSUE2 = 38                       # 서명란의 발급일자 칸 (AH38)
    P1_BOX_END = 36                   # 1면 테두리 상자의 마지막 줄
    P1_SIGN = 37                      # 서명 블록 시작 (상자 밖) — 여백을 넣는 자리
    P1_LAST = 44                      # 1면에서 내용이 끝나는 줄
    P1_TAIL_A, P1_TAIL_B = 45, 46     # 그 아래 남는 빈 줄
    HEAD_RULE = 51                    # 페이지 머리의 굵은 막대(도형)가 걸린 줄
    FRAME_TOP = 6                     # 1면 바깥 테두리가 시작하는 줄 (제목 막대 아래)
    # 요약표 열 구성.  한 칸일 때: 시료명 D~AJ, 결과 AK~AS
    # 두 칸으로 나눌 때: (시료명, 결과) x 2 — 테두리 서식은 이미 모든 칸에 같아서
    # 병합만 바꾸면 된다.
    SUM_1COL = (("D", "AJ"), ("AK", "AS"))
    SUM_2COL = ((("D", "R"), ("S", "X")), (("Y", "AM"), ("AN", "AS")))

    PAGE2 = 47
    LEAD_A, LEAD_B = 50, 54           # 2면 이후의 페이지 머리띠 (시험 결과 띠)
    DET_HDR_A, DET_HDR_B = 57, 60
    DET_FIRST, DET_SLOTS, DET_BLK = 61, 11, 2
    DET_SUF_A = 83
    P2_FILL_A, P2_FILL_B = 86, 92     # 2면 상자 안의 여백행
    P2_BOX_END = 93                   # 2면 상자의 마지막 줄
    P2_LAST = 93
    P2_TAIL_A, P2_TAIL_B = 94, 98

    PAGE3 = 99
    PHO_FIRST, PHO_SLOTS, PHO_BLK = 106, 4, 9
    PHO_IMG_ROWS, PHO_CAP_OFF = 7, 7
    PHO_SUF_A = 142
    P3_FILL_A, P3_FILL_B = 142, 142   # 3면 상자 안의 여백행
    P3_BOX_END = 143
    P3_LAST = 143
    P3_TAIL_A, P3_TAIL_B = 144, 148


BOX_FILL_MAX = 10000.0                # 상자를 늘릴 때는 종이 한 장 분량이 한계다
PHOTO_COLS = ((2, 24), (25, 47))      # 왼쪽 B..X / 오른쪽 Y..AU
PHOTO_FULL = (2, 47)                  # 한 장만 있을 때 B..AU


# ═══════════════════════════════════════════════ 성적서 만들기
def build_report(template_path, header, batches, out_path):
    """header: 머리말 dict
       batches: [{'values', 'samples':[(모델명, 사이즈)], 'photo': 경로|None, 'caption'}]
    """
    warnings = []
    flat = []
    for b in batches:
        for (nm, size) in b["samples"]:
            flat.append((nm, size, b["values"]))
    if not flat:
        raise InputError("성적서에 넣을 시료가 없습니다.")
    if len(flat) > MAX_SAMPLES:
        warnings.append("시료 %d종 중 %d종만 넣었습니다." % (len(flat), MAX_SAMPLES))
        flat = flat[:MAX_SAMPLES]
    n = len(flat)

    photos = [b for b in batches if b.get("photo")]
    n_pho = math.ceil(len(photos) / 2)
    odd_last = (len(photos) % 2 == 1)

    work = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(template_path) as z:
            z.extractall(work)
        g = XG.Grid(work)
        for name in ("PAGE1", "SUM_TITLE", "SUM_HDR", "SUM_FIRST", "SUM_LAST",
                     "SUM_SUF_A", "ISSUE2", "P1_BOX_END", "P1_SIGN", "P1_LAST",
                     "P1_TAIL_A", "P1_TAIL_B",
                     "PAGE2", "LEAD_A", "LEAD_B",
                     "DET_HDR_A", "DET_HDR_B", "DET_FIRST", "DET_SUF_A",
                     "P2_FILL_A", "P2_FILL_B", "P2_BOX_END", "P2_LAST",
                     "P2_TAIL_A", "P2_TAIL_B",
                     "PAGE3", "PHO_FIRST", "PHO_SUF_A", "P3_FILL_A", "P3_FILL_B",
                     "P3_BOX_END", "P3_LAST", "P3_TAIL_A", "P3_TAIL_B"):
            g.mark(name, getattr(L, name))

        # 페이지 머리의 굵은 막대를 한 벌 떠 둔다. 장마다 맨 아래에 같은 것을
        # 깔아야 위아래 막대가 똑같아진다.
        rule = _rule_stencil(g, L.HEAD_RULE)

        # 마지막 줄 테두리를 나중에 다시 입히려고 미리 떠 둔다
        s_first = g.snap_styles(L.SUM_FIRST)
        s_last = g.snap_styles(L.SUM_LAST)
        d_first1 = g.snap_styles(L.DET_FIRST)
        d_first2 = g.snap_styles(L.DET_FIRST + 1)
        d_last1 = g.snap_styles(L.DET_FIRST + (L.DET_SLOTS - 1) * L.DET_BLK)
        d_last2 = g.snap_styles(L.DET_FIRST + (L.DET_SLOTS - 1) * L.DET_BLK + 1)

        # 인쇄 배율을 먼저 확정한다. 페이지 계산이 여기에 좌우된다.
        _apply_print_scale(g)

        # ── 0. 요약표를 한 칸으로 두면 한 장을 넘는지 미리 본다.
        #    넘으면 시료명 칸을 좌우 두 칸으로 나눠 한 장에 담는다.
        budget0 = page_budget(g)
        h_pre0 = g.span_h(L.PAGE1, L.SUM_FIRST - 1)
        h_suf0 = g.span_h(L.SUM_SUF_A, L.P1_LAST)
        row_h0 = g.row_h(L.SUM_FIRST) or 17.1
        cap1 = max(1, int((budget0 - h_pre0 - h_suf0) // row_h0))
        two_col = n > cap1
        sum_rows = int(math.ceil(n / 2.0)) if two_col else n

        # ── 1. 표 크기를 시료 수에 맞춘다 (아래쪽부터)
        if n_pho == 0:
            g.remove_break(g.at("PAGE3") - 1)
            g.delete_rows(g.at("PAGE3"), g.at("P3_TAIL_B"))
        else:
            g.resize_blocks(g.at("PHO_FIRST"), L.PHO_BLK, L.PHO_SLOTS, n_pho, src_block=1)
        g.resize_blocks(g.at("DET_FIRST"), L.DET_BLK, L.DET_SLOTS, n, src_block=1)
        g.resize_blocks(g.at("SUM_FIRST"), 1, L.SUM_SLOTS, sum_rows, src_block=1)

        # ── 2. 첫 줄 / 마지막 줄 테두리 다시 입히기
        sum_first = g.at("SUM_FIRST")
        if sum_rows == 1:
            g.apply_styles(sum_first, s_first)
            cache = {}
            row = g.rowmap()[sum_first]
            for c in row:
                col = XG.split_ref(c.get("r"))[0]
                a, b = s_first["cells"].get(col), s_last["cells"].get(col)
                if a is None or b is None:
                    continue
                key = (a, b)
                if key not in cache:
                    cache[key] = g.combined_style(a, b)
                c.set("s", cache[key])
        else:
            g.apply_styles(sum_first, s_first)
            g.apply_styles(sum_first + sum_rows - 1, s_last)

        det_first = g.at("DET_FIRST")
        g.apply_styles(det_first, d_first1)
        g.apply_styles(det_first + 1, d_first2)
        last_blk = det_first + (n - 1) * L.DET_BLK
        if n > 1:
            g.apply_styles(last_blk, d_last1)
        g.apply_styles(last_blk + 1, d_last2)

        # ── 3. 사진칸 배치 정하기
        #    한 줄에 두 장. 마지막 한 장이 짝이 없으면 가로 전체로 넓히고
        #    높이도 두 배로 키워, 납작하게 잘리지 않고 칸을 꽉 채우게 한다.
        slots = []          # (이미지 시작행, 이미지 행수, 설명행, 시작열, 끝열)
        if n_pho:
            pf = g.at("PHO_FIRST")
            for k in range(len(photos)):
                ir = pf + (k // 2) * L.PHO_BLK
                if odd_last and k == len(photos) - 1:
                    ie = ir + L.PHO_IMG_ROWS - 1
                    g.copy_rows(ir, ie, ie + 1)               # 이미지 영역을 한 배 더
                    ie2 = ie + L.PHO_IMG_ROWS
                    for ref in ("B%d:X%d" % (ir, ie), "Y%d:AU%d" % (ir, ie),
                                "B%d:X%d" % (ie + 1, ie2), "Y%d:AU%d" % (ie + 1, ie2)):
                        g.remove_merge(ref)
                    g.add_merge("B%d:AU%d" % (ir, ie2))
                    cap = ie2 + 1
                    g.remove_merge("B%d:X%d" % (cap, cap + 1))
                    g.remove_merge("Y%d:AU%d" % (cap, cap + 1))
                    g.add_merge("B%d:AU%d" % (cap, cap + 1))
                    slots.append((ir, L.PHO_IMG_ROWS * 2, cap) + PHOTO_FULL)
                else:
                    slots.append((ir, L.PHO_IMG_ROWS, ir + L.PHO_CAP_OFF)
                                 + PHOTO_COLS[k % 2])
            for i, s in enumerate(slots):
                g.mark("PHO_SLOT_%d" % i, s[0])

        # ── 4. 머리말
        if header.get("report_no"):
            _set(g, "AN6", "성적서번호\n" + header["report_no"])
        _set(g, "H9", header.get("sample_title", ""))
        _set(g, "H10", header.get("test_date", ""))
        _set(g, "AE9", header.get("request_date", ""))
        _set(g, "AE10", header.get("purpose", "품질 테스트"))
        _set(g, "AE11", header.get("place", "라돈 측정실"))
        _set(g, "M11", header.get("temp", "상온"))
        _set(g, "M12", header.get("humid", "-"))
        if header.get("method"):
            _set(g, "H13", header["method"])
        if header.get("issue_date"):
            _set(g, "AE12", header["issue_date"])
            _set(g, "AH%d" % g.at("ISSUE2"), header["issue_date"])

        # ── 4-2. 시료가 많으면 요약표를 좌우 두 칸으로 나눈다
        if two_col:
            hdr_row = g.at("SUM_HDR")
            for r in [hdr_row] + [sum_first + i for i in range(sum_rows)]:
                for (a, b) in L.SUM_1COL:
                    g.remove_merge("%s%d:%s%d" % (a, r, b, r))
                for half in L.SUM_2COL:
                    for (a, b) in half:
                        g.add_merge("%s%d:%s%d" % (a, r, b, r))
            _set(g, "%s%d" % (L.SUM_2COL[0][0][0], hdr_row), "시 료 명")
            _set(g, "%s%d" % (L.SUM_2COL[0][1][0], hdr_row), "결 과")
            _set(g, "%s%d" % (L.SUM_2COL[1][0][0], hdr_row), "시 료 명")
            _set(g, "%s%d" % (L.SUM_2COL[1][1][0], hdr_row), "결 과")
            # 이름 칸이 좁아졌으니 긴 이름은 자동으로 줄여 넣는다
            for i in range(sum_rows):
                r = sum_first + i
                for half in L.SUM_2COL:
                    coord = "%s%d" % (half[0][0], r)
                    c = _cell(g, coord)
                    if c is not None:
                        sh = g.shrink_style(c.get("s"))
                        if sh:
                            c.set("s", sh)

        # ── 4-3. 그래도 한 장을 넘으면 줄 높이와 글자를 함께 줄여 맞춘다.
        #    서명·직인이 다음 장으로 넘어가지 않게 하려는 것이다.
        avail = budget0 - h_pre0 - h_suf0 - 1.0   # 경계에 딱 걸리지 않게 1pt 뺀다
        if sum_rows * row_h0 > avail + 0.5:
            new_h = max(SUM_MIN_ROW_H, avail / sum_rows)
            ratio = new_h / row_h0
            for i in range(sum_rows):
                r = sum_first + i
                g.set_row_height(r, new_h)
                row = g.rowmap().get(r)
                if row is None:
                    continue
                for c in row:
                    if XG.col_num(XG.split_ref(c.get("r"))[0]) > 48:
                        continue
                    ns = g.scaled_font_style(c.get("s"), ratio, floor=SUM_MIN_FONT)
                    if ns:
                        c.set("s", ns)
            if sum_rows * new_h > avail + 0.5:
                warnings.append("시료 %d종은 시료명 표가 첫 장을 넘습니다. "
                                "성적서를 나눠 만드시는 편이 좋습니다." % n)

        # ── 5. 표 채우기 (페이지 나눔 전에 채워야 값이 같이 밀린다)
        for i, (nm, size, v) in enumerate(flat):
            sr = sum_first + i
            dr = det_first + i * L.DET_BLK
            if two_col:
                half = 0 if i < sum_rows else 1
                sr = sum_first + (i if half == 0 else i - sum_rows)
                name_col = L.SUM_2COL[half][0][0]
                res_col = L.SUM_2COL[half][1][0]
            else:
                name_col, res_col = "D", "AK"
            _set(g, "%s%d" % (name_col, sr), nm)
            _set(g, "%s%d" % (res_col, sr), v["verdict"])
            _set(g, "B%d" % dr, i + 1, True)
            _set(g, "F%d" % dr, nm)
            _set(g, "P%d" % dr, size)
            _set(g, "S%d" % dr, v["radon_bg"], True)
            _set(g, "W%d" % dr, v["radon_rad7"], True)
            _set(g, "Z%d" % dr, v["radon_rad7_net"], True)
            _set(g, "AC%d" % dr, v["radon_rd200"], True)
            _set(g, "AF%d" % dr, v["radon_rd200_net"], True)
            _set(g, "AI%d" % dr, v.get("thoron_bg", 0.0), True)
            _set(g, "AM%d" % dr, v["thoron_rad7"], True)
            _set(g, "AP%d" % dr, v.get("thoron_net", v["thoron_rad7"]), True)
            _set(g, "AS%d" % dr, v["verdict"])

        # ── 6. 사진 설명
        for k, bat in enumerate(photos):
            _, _, cap_row, c_a, _ = slots[k]
            text = bat.get("caption") or ", ".join(nm for nm, _ in bat["samples"])
            _set(g, "%s%d" % (XG.col_name(c_a), cap_row), text)

        # ── 7. 원본 양식이 갖고 있던 여백행과 맨 아래 빈 줄을 걷어낸다.
        #    (페이지를 계산한 뒤, 마지막 장에 필요한 만큼만 다시 넣는다)
        # 여백행 서식(상자 좌우 세로선)을 지우기 전에 떠 둔다.
        # 페이지가 다 정해진 뒤 마지막 장에 필요한 만큼만 다시 끼운다.
        snap2 = g.snapshot_row(g.at("P2_FILL_A"))
        snap3 = g.snapshot_row(g.at("P3_FILL_A")) if n_pho else None
        if n_pho:
            g.delete_rows(g.at("P3_TAIL_A"), g.at("P3_TAIL_B"))
            g.delete_rows(g.at("P3_FILL_A"), g.at("P3_FILL_B"))
        g.delete_rows(g.at("P2_TAIL_A"), g.at("P2_TAIL_B"))
        g.delete_rows(g.at("P2_FILL_A"), g.at("P2_FILL_B"))
        g.delete_rows(g.at("P1_TAIL_A"), g.at("P1_TAIL_B"))
        g.add_break(g.at("P1_LAST"))                  # 빈 줄과 함께 지워진 나눔을 되살린다
        if n_pho:
            g.add_break(g.at("P2_LAST"))

        # ── 8. 페이지 나눔 (아래쪽부터)
        if n_pho:
            # 위치표시로 현재 행을 읽는다. slots 에 담긴 값은 그 뒤 여백행을
            # 걷어내면서 이미 밀렸으므로 그대로 쓰면 안 된다.
            pho_blocks = []
            for b in range(n_pho):
                s = slots[b * 2]
                pho_blocks.append((g.at("PHO_SLOT_%d" % (b * 2)), s[1] + 2))
            _paginate(g, g.at("PAGE3"), None, pho_blocks,
                      "PHO_SUF_A", "P3_LAST")
        det_first = g.at("DET_FIRST")
        _paginate(g, g.at("PAGE2"), ("DET_HDR_A", "DET_HDR_B"),
                  [(det_first + i * L.DET_BLK, L.DET_BLK) for i in range(n)],
                  "DET_SUF_A", "P2_LAST")
        sum_first = g.at("SUM_FIRST")
        # 1면은 주석까지는 표와 같은 장에 붙여두고(상자를 닫아야 하므로),
        # 서명·직인 블록만 자리가 없으면 다음 장으로 넘긴다.
        _paginate(g, g.at("PAGE1"), ("SUM_TITLE", "SUM_HDR"),
                  [(sum_first + i, 1) for i in range(sum_rows)],
                  "SUM_SUF_A", "P1_BOX_END")
        end = g.at("P1_LAST")
        if g.span_h(g.page_start(end), end) > page_budget(g) + 0.5:
            row = g.at("P1_SIGN")
            la, lb = g.at("LEAD_A"), g.at("LEAD_B")
            g.copy_rows(la, lb, row, clear=False)
            la2 = g.at("LEAD_A")
            g.copy_drawings(la2, la2 + (lb - la), row, uid=98)
            g.add_break(row - 1)


        # ── 10. 사진 넣기 (행이 모두 확정된 뒤의 실제 위치에)
        for k, bat in enumerate(photos):
            _, img_rows, _, c_a, c_b = slots[k]
            img_row = g.at("PHO_SLOT_%d" % k)
            box_w, box_h = _box_emu(g, c_a, c_b, img_row, img_rows)
            media = "photo%d.jpeg" % k
            dest = os.path.join(work, "xl", "media", media)
            roi = PHOTO_ROI_FULL if bat.get("cropped") else PHOTO_ROI
            crop_to_box(bat["photo"], dest, box_w / float(box_h), roi=roi)
            _add_photo(work, g, media, c_a, c_b, img_row, img_rows, k)

        # ── 10-2. 상자를 종이 아래까지 늘린다.
        #    표가 짧으면 테두리가 종이 중간에서 끊겨 어색하다. 발행된 성적서는
        #    표가 몇 줄이든 상자가 꼬리말 바로 위까지 내려온다.
        #    사진을 다 앉힌 «뒤» 에 해야 한다. 먼저 하면 여백행이 사진칸
        #    한가운데로 들어가 사진이 설명 줄을 덮는다. 아래 면부터 채워야
        #    위쪽 줄번호가 안 밀린다.
        if n_pho:
            # 넣는 자리는 «상자 마지막 줄 바로 앞». 양식의 여백행 자리표시를
            # 쓰면 사진칸 한가운데로 들어가 사진이 설명 줄을 덮는다.
            _pad_page(g, "P3_BOX_END", "P3_BOX_END", snap3, target=BOX_FILL_MAX)
        _pad_page(g, "P2_BOX_END", "P2_BOX_END", snap2, target=BOX_FILL_MAX)

        # ── 11. 마무리
        # 1면도 종이 아래까지 늘린다. 그래야 세 장의 아래 막대가 같은 높이에
        # 온다. 여백은 «결과 상자와 서명 블록 사이» 에 넣는다 — 그래야
        # 발급일자·직인·안내문구가 시료 수와 상관없이 늘 같은 자리에 온다.
        # (P1_LAST 앞에 넣으면 서명 블록이 표를 따라 위아래로 움직인다.)
        # 넣는 자리는 «발급일자 줄 앞»(ISSUE2). 그 한 줄 위(P1_SIGN)에 넣으면
        # 상자 아래 테두리가 깨진다 — 아래선이 두 줄에 나뉘어 그려져 있어서,
        # 가운데 몇 칸은 그 줄의 «윗 테두리» 로 되어 있기 때문이다.
        _pad_keep_shapes(g, "P1_LAST", "ISSUE2", target=BOX_FILL_MAX)
        # 1면은 양식에 바깥 테두리가 없다. 2·3면과 같아 보이게 여기서 두른다.
        _page_frame(g, L.FRAME_TOP, g.at("P1_LAST"))
        last = g.at("P3_LAST") if n_pho else g.at("P2_LAST")
        last = _add_page_rules(g, rule, last)   # 장마다 꼬리말 위 이중 막대
        _set_print_area(g, last)
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


def photo_box_aspect(template_path):
    """성적서 사진칸의 가로세로 비율을 양식에서 직접 잰다.

    사진이 짝수 장이면 한 줄에 두 장씩(좁은 칸), 홀수 장이면 마지막 한 장만
    가로 전체를 쓰는 넓은 칸에 들어간다. 넓은 칸은 가로도 세로도 꼭 두 배라
    두 칸의 모양은 사실상 같다(2.076 : 2.069). 그래서 하나만 돌려준다.
    화면의 사진 편집기가 이 비율로 자르기 틀을 잡아, 사용자가 고른 자리가
    성적서에 그대로 들어간다.
    """
    work = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(template_path) as z:
            z.extractall(work)
        g = XG.Grid(work)
        ir = L.PHO_FIRST
        h = g.span_h(ir, ir + L.PHO_IMG_ROWS - 1) * XG.EMU_PER_PT
        return round(g.span_px(*PHOTO_COLS[0]) * XG.EMU_PER_PX / h, 4)
    finally:
        shutil.rmtree(work, ignore_errors=True)
