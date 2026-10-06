# -*- coding: utf-8 -*-
"""라돈 «원자재» 성적서 — 파일 읽기 · 계산 · 양식 채우기.

완제품 성적서(core.py)와 다른 점
  · 라돈만 잰다. 토론은 없다.
  · 장비가 FRD400(배경농도)과 RadonEye Plus(측정)뿐이다. RAD7 을 쓰지 않는다.
  · 챔버 두 개에 서로 다른 자재를 넣고 동시에 잰다. 배경농도 파일은 하나를
    같이 쓰고, 측정치만 챔버마다 따로 나온다.
  · 앞장 요약표가 좌우 세 벌(시료가 많으면 네 벌)로 늘어선다.

틀을 다루는 어려운 일들(페이지 나눔·인쇄 배율·사진)은 sheet.py 가 맡는다.
"""
import os, math, zipfile, shutil, tempfile
from datetime import datetime

import xlsxgrid as XG
from sheet import (InputError, _round, read_text, save_photo, crop_to_box,
                   PHOTO_ROI, PHOTO_ROI_FULL, SUM_MIN_ROW_H, SUM_MIN_FONT,
                   page_budget, _cell, _set, _box_emu, _add_photo,
                   _apply_print_scale, _set_print_area, _paginate, _pad_page,
                   _rule_stencil, _add_page_rules, _page_frame,
                   _pad_keep_shapes)

LIMIT = 10           # 자사 기준치: 측정치 - 배경농도 <= 10 이면 적합
MAX_SAMPLES = 200
MAX_RUNS = 40        # 챔버 하나가 «측정» 한 건이라 완제품보다 많이 잡는다

SKIP_HOURS = 4       # 배경농도 파일 앞부분을 버리는 시간
WINDOW_HOURS = 24    # 그다음 이만큼을 평균낸다


# ═══════════════════════════════════════════════ 장비 판별
def detect_device(text, filename=""):
    if "FRD400" in text:
        return "FRD400"
    if "Radon Eye Plus" in text or "RadonEye Plus" in text:
        return "EYE"
    if "RadonEye" in text or "RD200" in text:
        return "EYE"
    return "UNKNOWN"


LABEL = {"FRD400": "FRD400(배경농도)", "EYE": "RadonEye Plus(측정)"}


# ═══════════════════════════════════════════════ 파서
def parse_ftlab(text):
    """FTLab 계측기(FRD400 · RadonEye Plus)의 탭 구분 텍스트를 읽는다.

    두 장비의 줄 모양이 조금 다르다. 둘 다 받아들인다.
        FRD400          1<탭>2026.03.03 18:16:59<탭> 39<탭>...
        RadonEye Plus   1)<탭>2026-02-26 19:28:55<탭> 29<탭>...
    시각은 시(hour)까지만 남긴다. 두 장비의 분·초가 서로 달라
    그대로 두면 같은 시간대끼리 짝지을 수 없다.
    """
    out = {}
    for ln in text.replace("\r\n", "\n").split("\n"):
        p = ln.split("\t")
        if len(p) < 3:
            continue
        no = p[0].strip().rstrip(")")
        if not no.isdigit():
            continue
        try:
            dt = datetime.strptime(p[1].strip().replace(".", "-"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        try:
            val = float(p[2].strip())
        except ValueError:
            continue
        out[dt.strftime("%Y-%m-%d %H")] = {"radon": val, "no": int(no)}
    return out


def parse_upload(text, filename, expect):
    dev = detect_device(text, filename)
    if dev == "UNKNOWN":
        raise InputError("'%s' 은(는) 인식할 수 없는 파일입니다. %s 장비에서 내보낸 "
                         "원본이 맞는지 확인해주세요." % (filename, LABEL[expect]))
    if dev != expect:
        raise InputError("'%s' 은(는) %s 파일로 보입니다. %s 칸에 올려주세요."
                         % (filename, LABEL[dev], LABEL[dev]))
    d = parse_ftlab(text)
    if not d:
        raise InputError("'%s' 에서 측정값을 찾지 못했습니다. 파일이 비었거나 "
                         "형식이 다릅니다." % filename)
    return d


# ═══════════════════════════════════════════════ 계산
def window_hours(frd_bg, skip=SKIP_HOURS, span=WINDOW_HOURS):
    """측정 구간을 배경농도 파일에서 잡는다.

    배경 측정기를 먼저 켜 두고 얼마 뒤에 시료를 챔버에 넣기 때문에,
    파일 앞의 skip 시간은 시료가 없는 동안이다. 그 뒤 span 시간이
    성적서에 쓰는 구간이다. 성적서에 «24시간 이상 측정(1시간 단위)»
    이라고 적히는 그 구간이다.

    완성된 성적서 12회차 중 10회차가 이 규칙으로 세 값(배경·챔버 둘)이
    모두 정확히 맞았다. 나머지 2회차는 한쪽 챔버만 1~2 Bq 어긋나는데,
    그 파일 안 어떤 구간으로도 재현되지 않아 원본이 빠진 것으로 본다.
    """
    hrs = sorted(frd_bg.keys())
    if len(hrs) < skip + span:
        raise InputError("배경농도 파일이 짧습니다. 앞 %d시간을 뺀 뒤 %d시간이 "
                         "필요한데 %d시간뿐입니다." % (skip, span, len(hrs)))
    return hrs[skip:skip + span]


def _avg(dic, hours):
    v = [dic[h]["radon"] for h in hours if h in dic and "radon" in dic[h]]
    return sum(v) / len(v) if v else None


def compute(frd_bg, eye, skip=SKIP_HOURS, span=WINDOW_HOURS):
    """배경농도 파일이 시간의 기준이다. 측정치도 같은 구간으로 평균낸다."""
    hrs = window_hours(frd_bg, skip, span)
    bg_raw = _avg(frd_bg, hrs)
    m_raw = _avg(eye, hrs)
    if m_raw is None:
        raise InputError("RadonEye 파일에 측정 구간(%s시 ~ %s시)과 겹치는 값이 "
                         "없습니다. 같은 회차의 파일이 맞는지 확인해주세요."
                         % (hrs[0], hrs[-1]))
    missing = span - len([h for h in hrs if h in eye])
    bg = _round(bg_raw)
    measured = _round(m_raw)
    net = max(0, measured - bg)
    return {"period": (hrs[0], hrs[-1]), "hours": span, "missing": missing,
            "radon_bg": bg, "radon": measured, "radon_net": net,
            "verdict": "적합" if net <= LIMIT else "부적합"}


# ═══════════════════════════════════════════════ 양식 좌표 (원본 기준)
class L:
    PAGE1 = 1
    SUM_TITLE, SUM_HDR = 19, 20
    SUM_FIRST, SUM_SLOTS, SUM_LAST = 21, 9, 29
    SUM_SUF_A = 30                    # 표 아래 주석부터 상자 끝까지
    ISSUE2 = 35                       # 서명란의 발급일자 (AH35)
    P1_BOX_END = 33
    P1_SIGN = 34                      # 서명·직인 블록 시작 (상자 밖)
    P1_LAST = 40
    # 46까지 — A44:AV46 병합이 페이지 경계(45)를 가로질러 있어서,
    # 45에서 끊으면 병합이 뒤집힌다. 46은 원래 빈 줄이라 지워도 된다.
    P1_TAIL_A, P1_TAIL_B = 41, 46
    HEAD_RULE = 48                    # 페이지 머리의 굵은 막대(도형)가 걸린 줄
    FRAME_TOP = 6                     # 1면 바깥 테두리가 시작하는 줄 (제목 막대 아래)

    # 요약표 열 구성. 기본 세 벌, 시료가 많으면 네 벌.
    SUM_3COL = ((("D", "M"), ("N", "Q")),
                (("R", "AA"), ("AB", "AE")),
                (("AF", "AO"), ("AP", "AS")))
    SUM_4COL = ((("C", "I"), ("J", "M")),
                (("N", "T"), ("U", "X")),
                (("Y", "AE"), ("AF", "AI")),
                (("AJ", "AP"), ("AQ", "AT")))

    PAGE2 = 46
    # 48부터인 이유: 페이지 머리의 굵은 가로선(도형)이 48줄에 걸려 있다.
    # 49부터 잡으면 표가 이어지는 장에 그 선이 복제되지 않아 머리가 허전해진다.
    LEAD_A, LEAD_B = 48, 53           # 이어지는 장의 머리띠
    DET_HDR_A, DET_HDR_B = 54, 55
    DET_FIRST, DET_SLOTS, DET_BLK = 56, 17, 2
    DET_SUF_A = 90                    # 표 아래 주석
    P2_BOX_END, P2_LAST = 91, 91
    P2_TAIL_A, P2_TAIL_B = 92, 95     # 95까지 — A94:AV95 병합을 통째로 지우려고

    # 양식에 측정 결과 페이지가 두 장 들어 있다. 뒷장은 지우고,
    # 표가 길어지면 페이지 나눔이 알아서 다시 만든다.
    # 96부터인 이유: 95는 윗줄과 병합(A94:AV95)되어 있어 여기서 자르면
    # 병합이 뒤집힌 채 남고, 엑셀이 파일을 아예 열지 못한다.
    DUP_A, DUP_B = 96, 144

    PAGE3 = 145                       # 사진 면
    PHO_FIRST, PHO_SLOTS, PHO_BLK = 154, 4, 7
    PHO_IMG_ROWS = 7
    PHO_SUF_A = 182
    P3_FILL_A, P3_FILL_B = 182, 183
    P3_BOX_END, P3_LAST = 184, 184
    P3_TAIL_A, P3_TAIL_B = 185, 189


BOX_FILL_MAX = 10000.0                # 상자를 늘릴 때는 종이 한 장 분량이 한계다
PRINT_SCALE = 96                      # 완성된 원자재 성적서들과 같은 인쇄 배율
PHOTO_COLS = ((6, 24), (25, 43))      # 왼쪽 F..X / 오른쪽 Y..AQ
PHOTO_FULL = (6, 43)                  # 마지막 한 장이 짝이 없을 때 F..AQ

# 측정 결과표에서 값을 쓰는 칸 (병합의 첫 칸)
DET_COL = {"no": "B", "name": "F", "measured": "AB",
           "bg": "AG", "net": "AL", "verdict": "AQ"}


def _style_at(grid, coord):
    c = _cell(grid, coord)
    return None if c is None else c.get("s")


def _put_style(grid, coord, style):
    if style is None:
        return
    c = _cell(grid, coord)
    if c is not None:
        c.set("s", style)


# ═══════════════════════════════════════════════ 성적서 만들기
def build_report(template_path, header, batches, out_path):
    """header: 머리말 dict
       batches: [{'values', 'samples':[(자재명, 비고)], 'photo': 경로|None}]
       한 batch 가 챔버 하나(= 측정 한 건)다.
    """
    warnings = []
    flat = []
    for b in batches:
        for s in b["samples"]:
            nm = s[0] if isinstance(s, (tuple, list)) else s
            flat.append((nm, b["values"]))
    if not flat:
        raise InputError("성적서에 넣을 시료가 없습니다.")
    if len(flat) > MAX_SAMPLES:
        warnings.append("시료 %d종 중 %d종만 넣었습니다." % (len(flat), MAX_SAMPLES))
        flat = flat[:MAX_SAMPLES]
    n = len(flat)

    photos = [b for b in batches if b.get("photo")]
    n_pho = math.ceil(len(photos) / 2)          # 사진 줄 수 (한 줄에 두 장)
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
                     "P2_BOX_END", "P2_LAST", "P2_TAIL_A", "P2_TAIL_B",
                     "DUP_A", "DUP_B",
                     "PAGE3", "PHO_FIRST", "PHO_SUF_A", "P3_FILL_A", "P3_FILL_B",
                     "P3_BOX_END", "P3_LAST", "P3_TAIL_A", "P3_TAIL_B"):
            g.mark(name, getattr(L, name))

        s_first = g.snap_styles(L.SUM_FIRST)
        s_last = g.snap_styles(L.SUM_LAST)
        d_first1 = g.snap_styles(L.DET_FIRST)
        d_first2 = g.snap_styles(L.DET_FIRST + 1)
        d_last1 = g.snap_styles(L.DET_FIRST + (L.DET_SLOTS - 1) * L.DET_BLK)
        d_last2 = g.snap_styles(L.DET_FIRST + (L.DET_SLOTS - 1) * L.DET_BLK + 1)

        _apply_print_scale(g, PRINT_SCALE)

        # ── 0. 양식에 들어 있는 둘째 측정 결과 페이지를 걷어낸다.
        #    표가 길어지면 8단계의 페이지 나눔이 똑같은 장을 다시 만든다.
        g.delete_rows(g.at("DUP_A"), g.at("DUP_B"))   # 나눔도 같이 지워진다

        # ── 0-2. 요약표를 세 벌로 두면 첫 장을 넘는지 미리 본다.
        budget0 = page_budget(g)
        h_pre0 = g.span_h(g.at("PAGE1"), g.at("SUM_FIRST") - 1)
        h_suf0 = g.span_h(g.at("SUM_SUF_A"), g.at("P1_LAST"))
        row_h0 = g.row_h(g.at("SUM_FIRST")) or 21.95
        cap = max(1, int((budget0 - h_pre0 - h_suf0) // row_h0))
        cols = 3 if int(math.ceil(n / 3.0)) <= cap else 4
        layout = L.SUM_3COL if cols == 3 else L.SUM_4COL
        sum_rows = int(math.ceil(float(n) / cols))

        # ── 1. 표 크기를 시료 수에 맞춘다 (아래쪽부터)
        if n_pho == 0:
            g.remove_break(g.at("PAGE3") - 1)
            g.delete_rows(g.at("PAGE3"), g.at("P3_TAIL_B"))
        else:
            g.resize_blocks(g.at("PHO_FIRST"), L.PHO_BLK, L.PHO_SLOTS, n_pho,
                            src_block=1)
        g.resize_blocks(g.at("DET_FIRST"), L.DET_BLK, L.DET_SLOTS, n, src_block=1)
        g.resize_blocks(g.at("SUM_FIRST"), 1, L.SUM_SLOTS, sum_rows, src_block=1)

        # ── 2. 첫 줄 / 마지막 줄 테두리 다시 입히기
        sum_first = g.at("SUM_FIRST")
        if sum_rows == 1:
            g.apply_styles(sum_first, s_first)
            cache = {}
            for c in g.rowmap()[sum_first]:
                col = XG.split_ref(c.get("r"))[0]
                a, b = s_first["cells"].get(col), s_last["cells"].get(col)
                if a is None or b is None:
                    continue
                if (a, b) not in cache:
                    cache[(a, b)] = g.combined_style(a, b)
                c.set("s", cache[(a, b)])
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

        # ── 3. 사진칸 배치. 한 줄에 두 장, 마지막 한 장이 짝이 없으면
        #    가로 전체로 넓히고 높이도 두 배로 키운다.
        slots = []                    # (시작행, 행수, 시작열, 끝열)
        if n_pho:
            pf = g.at("PHO_FIRST")
            for k in range(len(photos)):
                ir = pf + (k // 2) * L.PHO_BLK
                if odd_last and k == len(photos) - 1:
                    ie = ir + L.PHO_IMG_ROWS - 1
                    g.copy_rows(ir, ie, ie + 1)
                    ie2 = ie + L.PHO_IMG_ROWS
                    for ref in ("F%d:X%d" % (ir, ie), "Y%d:AQ%d" % (ir, ie),
                                "F%d:X%d" % (ie + 1, ie2), "Y%d:AQ%d" % (ie + 1, ie2)):
                        g.remove_merge(ref)
                    g.add_merge("F%d:AQ%d" % (ir, ie2))
                    slots.append((ir, L.PHO_IMG_ROWS * 2) + PHOTO_FULL)
                else:
                    slots.append((ir, L.PHO_IMG_ROWS) + PHOTO_COLS[k % 2])
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

        # ── 4-2. 요약표를 네 벌로 나눌 때는 병합을 다시 짜고 서식을 옮겨 심는다.
        #    새 병합의 첫 칸(C·N·Y·AJ)은 원래 세 벌짜리에서 안 쓰던 자리라
        #    서식이 비어 있다. 그대로 두면 그 칸만 글자가 크고 바탕색이 없다.
        if cols == 4:
            hdr_row = g.at("SUM_HDR")
            for r in [hdr_row] + [sum_first + i for i in range(sum_rows)]:
                name_s = _style_at(g, "%s%d" % (L.SUM_3COL[0][0][0], r))
                res_s = _style_at(g, "%s%d" % (L.SUM_3COL[0][1][0], r))
                for pair in L.SUM_3COL:
                    for (a, b) in pair:
                        g.remove_merge("%s%d:%s%d" % (a, r, b, r))
                for pair in L.SUM_4COL:
                    for (a, b) in pair:
                        g.add_merge("%s%d:%s%d" % (a, r, b, r))
                narrow = name_s if r == hdr_row else (g.shrink_style(name_s) or name_s)
                for pair in L.SUM_4COL:
                    _put_style(g, "%s%d" % (pair[0][0], r), narrow)
                    _put_style(g, "%s%d" % (pair[1][0], r), res_s)
            for pair in L.SUM_4COL:
                _set(g, "%s%d" % (pair[0][0], hdr_row), "시 료 명")
                _set(g, "%s%d" % (pair[1][0], hdr_row), "결 과")

        # ── 4-3. 그래도 첫 장을 넘으면 줄 높이와 글자를 함께 줄인다.
        #    서명·직인이 다음 장으로 넘어가지 않게 하려는 것이다.
        avail = budget0 - h_pre0 - h_suf0 - 1.0
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

        # ── 5. 표 채우기 (요약표는 «세로로» 채운다 — 첫 칸을 다 채우고 다음 칸)
        for i, (nm, v) in enumerate(flat):
            pair = layout[i // sum_rows] if sum_rows else layout[0]
            sr = sum_first + (i % sum_rows)
            _set(g, "%s%d" % (pair[0][0], sr), nm)
            _set(g, "%s%d" % (pair[1][0], sr), v["verdict"])

            dr = det_first + i * L.DET_BLK
            _set(g, "%s%d" % (DET_COL["no"], dr), i + 1, True)
            _set(g, "%s%d" % (DET_COL["name"], dr), nm)
            _set(g, "%s%d" % (DET_COL["measured"], dr), v["radon"], True)
            _set(g, "%s%d" % (DET_COL["bg"], dr), v["radon_bg"], True)
            _set(g, "%s%d" % (DET_COL["net"], dr), v["radon_net"], True)
            _set(g, "%s%d" % (DET_COL["verdict"], dr), v["verdict"])

        # ── 7. 원본 양식의 여백행과 맨 아래 빈 줄을 걷어낸다
        # 여백행 서식(상자 좌우 세로선)을 지우기 전에 떠 둔다.
        # 2면은 양식에 여백행 자리가 없어 상자 마지막 줄 바로 위를 쓴다.
        # 페이지 머리의 굵은 막대를 한 벌 떠 둔다 (장마다 아래에 같은 것을 깐다)
        rule = _rule_stencil(g, L.HEAD_RULE)
        snap2 = g.snapshot_row(g.at("P2_BOX_END") - 1)
        snap3 = g.snapshot_row(g.at("P3_FILL_A")) if n_pho else None
        if n_pho:
            g.delete_rows(g.at("P3_TAIL_A"), g.at("P3_TAIL_B"))
            g.delete_rows(g.at("P3_FILL_A"), g.at("P3_FILL_B"))
        g.delete_rows(g.at("P2_TAIL_A"), g.at("P2_TAIL_B"))
        g.delete_rows(g.at("P1_TAIL_A"), g.at("P1_TAIL_B"))
        g.add_break(g.at("P1_LAST"))
        if n_pho:
            g.add_break(g.at("P2_LAST"))

        # ── 8. 페이지 나눔 (아래쪽부터)
        if n_pho:
            pho_blocks = []
            for b in range(n_pho):
                pho_blocks.append((g.at("PHO_SLOT_%d" % (b * 2)), slots[b * 2][1]))
            _paginate(g, g.at("PAGE3"), None, pho_blocks, "PHO_SUF_A", "P3_LAST")
        det_first = g.at("DET_FIRST")
        _paginate(g, g.at("PAGE2"), ("DET_HDR_A", "DET_HDR_B"),
                  [(det_first + i * L.DET_BLK, L.DET_BLK) for i in range(n)],
                  "DET_SUF_A", "P2_LAST")
        sum_first = g.at("SUM_FIRST")
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
            _, img_rows, c_a, c_b = slots[k]
            img_row = g.at("PHO_SLOT_%d" % k)
            box_w, box_h = _box_emu(g, c_a, c_b, img_row, img_rows)
            media = "photo%d.jpeg" % k
            dest = os.path.join(work, "xl", "media", media)
            roi = PHOTO_ROI_FULL if bat.get("cropped") else PHOTO_ROI
            crop_to_box(bat["photo"], dest, box_w / float(box_h), roi=roi)
            _add_photo(work, g, media, c_a, c_b, img_row, img_rows, k)

        # ── 10-2. 상자를 종이 아래까지 늘린다 (사진을 앉힌 뒤, 아래 면부터)
        if n_pho:
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
    """사진칸의 가로세로 비율(약 1.378). 화면의 사진 편집기가 이 모양으로 자른다."""
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
