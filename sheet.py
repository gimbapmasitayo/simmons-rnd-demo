# -*- coding: utf-8 -*-
"""성적서 종류와 상관없이 쓰는 공통 부분.

시몬스 성적서는 종류가 달라도 틀이 같다 — 같은 머리말 상자, 같은 표 테두리,
같은 붉은 꼬리말, 같은 직인. 그래서 어려운 일들(페이지 나눔, 인쇄 배율,
사진 자르기와 앉히기, 엑셀 XML 다루기)은 종류를 타지 않는다. 그 부분을
여기에 모아 두고, 성적서마다 다른 것(파일 읽기 · 계산 · 어느 칸에 쓰나)만
따로 쓴다.

라돈·토론 완제품  → core.py
라돈 원자재       → material.py
"""
import os, copy, zipfile, shutil, tempfile
from decimal import Decimal, ROUND_HALF_UP
from lxml import etree
from PIL import Image, ImageOps

import xlsxgrid as XG


# ═══════════════════════════════════════════════ 입력 검증
class InputError(Exception):
    """사용자에게 그대로 보여줄 입력 오류 메시지"""



def _round(x, nd=0):
    """사사오입. 파이썬 기본 round 는 2.5를 2로 내려서 성적서 관행과 다르다."""
    q = Decimal(1).scaleb(-nd)
    d = Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP)
    return int(d) if nd == 0 else float(d)

def read_text(fileobj):
    data = fileobj.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    return data


# ═══════════════════════════════════════════════ 사진
def save_photo(fileobj, out_path):
    """업로드된 사진을 그대로(회전만 바로잡아) 저장한다. 자르기는 성적서를 만들 때 한다."""
    try:
        im = Image.open(fileobj)
        im.load()
    except Exception:
        raise InputError("사진 파일을 열 수 없습니다. JPG 또는 PNG 로 올려주세요. "
                         "(아이폰 HEIC 사진은 '가장 호환성 높게' 로 저장하거나 JPG 로 "
                         "변환해주세요)")
    im = ImageOps.exif_transpose(im)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.save(out_path, "JPEG", quality=92)
    return out_path


PHOTO_ROI = (0.01, 0.22, 0.99, 0.80)   # 사람이 손대지 않았을 때 프로그램이 고르는 자리
PHOTO_ROI_FULL = (0.0, 0.0, 1.0, 1.0)  # 사람이 직접 자른 사진은 그대로 쓴다


def crop_to_box(src, out_path, box_aspect, roi=PHOTO_ROI, maxpx=1600):
    """사진칸 비율에 정확히 맞춰 자른다.

    roi 는 '보여주고 싶은 영역'(위아래 배경을 덜어낸 부분).
    그 영역을 칸 비율에 맞추되, 되도록 넓혀서(잘라내지 말고) 맞춘다.
    결과는 칸을 빈틈없이 채우고 찌그러지지 않는다.
    """
    im = Image.open(src)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    W, H = im.size
    l, t, r, b = roi
    x0, y0, x1, y1 = W * l, H * t, W * r, H * b
    cw, ch = max(1.0, x1 - x0), max(1.0, y1 - y0)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0

    if cw / ch < box_aspect:            # 가로가 모자람 -> 좌우로 넓힌다
        nh, nw = ch, ch * box_aspect
        if nw > W:
            nw, nh = float(W), W / box_aspect
    else:                               # 세로가 모자람 -> 위아래로 넓힌다
        nw, nh = cw, cw / box_aspect
        if nh > H:
            nh, nw = float(H), H * box_aspect
    if nw > W:
        nw, nh = float(W), W / box_aspect
    if nh > H:
        nh, nw = float(H), H * box_aspect

    px = max(0.0, min(cx - nw / 2.0, W - nw))
    py = max(0.0, min(cy - nh / 2.0, H - nh))
    im = im.crop((int(px), int(py), int(px + nw), int(py + nh)))
    if max(im.size) > maxpx:
        im.thumbnail((maxpx, maxpx))
    im.save(out_path, "JPEG", quality=88)
    return im.size


PAGE_TARGET = 690.0                   # (지금은 쓰지 않음) 마지막 장을 채울 때의 목표 높이
PRINT_LAST_COL = "AV"                 # 인쇄 영역 오른쪽 끝. 상자의 오른쪽 테두리가 AV 열에 있다
PRINT_SCALE = 98                      # 완성된 성적서들과 같은 인쇄 배율(%)
RULE_GAP = 9.0                        # 장마다 맨 아래에 두는 «막대 줄» 의 높이(pt).
                                      # 페이지 계산에서 미리 빼 두어야 막대를
                                      # 끼울 때 마지막 줄이 다음 장으로 안 밀린다.
FOOTER_RESERVE = 35.0                 # 아래 여백 위로 꼬리말이 더 차지하는 높이(pt).
                                      # 양식 꼬리말이 네 줄이라 여백만큼으로는 모자란다.
SUM_MIN_ROW_H = 9.0                   # 요약표 줄 높이 하한(pt)
SUM_MIN_FONT = 6.5                    # 요약표 글자 크기 하한(pt)
PAPER = {9: (595.28, 841.89),         # A4
         1: (612.0, 792.0),           # Letter
         8: (841.89, 1190.55)}        # A3


def page_budget(g, last_col=48):
    """한 장에 실제로 들어가는 높이(pt).

    이 양식은 '가로를 한 페이지에 맞춤' 설정이라, 내용이 인쇄 폭보다 좁으면
    엑셀이 인쇄를 확대한다. 확대되면 세로로 들어가는 양이 그만큼 줄어든다.
    이걸 계산에 넣지 않으면 표가 페이지 경계에서 잘린다.
    """
    ps = g.root.find(M + "pageSetup")
    pm = g.root.find(M + "pageMargins")
    pw, ph = PAPER.get(int(ps.get("paperSize", 9)) if ps is not None else 9,
                       PAPER[9])
    if ps is not None and ps.get("orientation") == "landscape":
        pw, ph = ph, pw

    def mg(name, dflt):
        try:
            return float(pm.get(name, dflt)) * 72.0
        except Exception:
            return dflt * 72.0

    avail_h = ph - mg("top", 0.75) - mg("bottom", 0.75)
    if g.root.find(M + "headerFooter") is not None:
        avail_h -= FOOTER_RESERVE
    avail_w = pw - mg("left", 0.7) - mg("right", 0.7)

    scale = 1.0
    if ps is not None and ps.get("fitToWidth") not in (None, "0"):
        content_w = g.span_px(1, last_col) * 0.75      # 96dpi 픽셀 -> 포인트
        if content_w > 1:
            scale = max(0.25, min(4.0, avail_w / content_w))
    elif ps is not None and ps.get("scale"):
        try:
            scale = float(ps.get("scale")) / 100.0
        except Exception:
            scale = 1.0
    return avail_h / scale - 6.0 - RULE_GAP            # 여유 6pt + 막대 줄 몫

MAIN = XG.MAIN
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
XDR = XG.XDR
M, D = XG.M, XG.D


# ═══════════════════════════════════════════════ 셀 쓰기
def _cell(grid, coord):
    col, row = XG.split_ref(coord)
    r = grid.rowmap().get(row)
    if r is None:
        return None
    want = XG.col_num(col)
    prev = None
    for c in r:
        n = XG.col_num(XG.split_ref(c.get("r"))[0])
        if n == want:
            return c
        if n < want:
            prev = c
    c = etree.Element(M + "c")
    c.set("r", coord)
    if prev is not None:
        prev.addnext(c)
    else:
        r.insert(0, c)
    return c


def _set(grid, coord, value, is_num=False):
    c = _cell(grid, coord)
    if c is None:
        return
    for ch in list(c):
        c.remove(ch)
    if value in (None, ""):
        c.attrib.pop("t", None)
        return
    if is_num:
        c.attrib.pop("t", None)
        v = etree.SubElement(c, M + "v")
        v.text = str(value)
    else:
        c.set("t", "inlineStr")
        s = etree.SubElement(c, M + "is")
        t = etree.SubElement(s, M + "t")
        t.text = str(value)
        if "\n" in str(value):
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


# ═══════════════════════════════════════════════ 사진 배치
def _box_emu(grid, col_a, col_b, img_row, img_rows):
    """사진칸의 실제 크기(EMU)를 잰다."""
    w = grid.span_px(col_a, col_b) * XG.EMU_PER_PX
    h = grid.span_h(img_row, img_row + img_rows - 1) * XG.EMU_PER_PT
    return w, h


PHOTO_PAD_EMU = 28000          # 사진과 칸 테두리 사이 여백 (약 3px)


def _add_photo(work, grid, media_name, col_a, col_b, img_row, img_rows, uid):
    """사진 한 장을 칸에 딱 맞게 앉힌다.

    두 셀 기준(twoCellAnchor)으로 걸어두면 열 너비를 픽셀로 환산하는 오차와
    무관하게 엑셀이 칸 크기에 정확히 맞춰준다. 사진은 미리 칸 비율로
    잘라두었으므로 늘어나거나 찌그러지지 않는다.
    """
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

    box_w, box_h = _box_emu(grid, col_a, col_b, img_row, img_rows)
    pad = PHOTO_PAD_EMU
    last_row = img_row + img_rows - 1
    end_col_emu = int(grid.col_px(col_b) * XG.EMU_PER_PX)
    end_row_emu = int(grid.row_h(last_row) * XG.EMU_PER_PT)
    ext_w, ext_h = max(1, int(box_w) - pad * 2), max(1, int(box_h) - pad * 2)

    dr = grid.draw.getroot()
    anc = etree.SubElement(dr, D + "twoCellAnchor")
    anc.set("editAs", "oneCell")
    frm = etree.SubElement(anc, D + "from")
    for tag, val in (("col", col_a - 1), ("colOff", pad),
                     ("row", img_row - 1), ("rowOff", pad)):
        e = etree.SubElement(frm, D + tag)
        e.text = str(val)
    to = etree.SubElement(anc, D + "to")
    for tag, val in (("col", col_b - 1), ("colOff", max(0, end_col_emu - pad)),
                     ("row", last_row - 1), ("rowOff", max(0, end_row_emu - pad))):
        e = etree.SubElement(to, D + tag)
        e.text = str(val)

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
    ex.set("cx", str(ext_w))
    ex.set("cy", str(ext_h))
    pg = etree.SubElement(spr, "{%s}prstGeom" % A_NS)
    pg.set("prst", "rect")
    etree.SubElement(pg, "{%s}avLst" % A_NS)
    etree.SubElement(anc, D + "clientData")


def _apply_print_scale(g, scale=PRINT_SCALE):
    """인쇄 배율을 고정한다. 완성된 성적서들과 같은 설정이다.
    (완제품 98%, 원자재 96% — 양식마다 다르다)

    '가로를 한 페이지에 맞춤' 으로 두면 엑셀이 내용을 임의로 확대해
    오른쪽이 종이 밖으로 밀려나고, 한 장에 들어가는 줄 수도 달라진다.
    페이지 계산이 이 설정에 좌우되므로 반드시 계산 전에 먼저 적용해야 한다.
    """
    ps = g.root.find(M + "pageSetup")
    if ps is not None:
        ps.attrib.pop("fitToWidth", None)
        ps.attrib.pop("fitToHeight", None)
        ps.set("scale", str(scale))
    sp = g.root.find(M + "sheetPr")
    if sp is not None:
        pu = sp.find(M + "pageSetUpPr")
        if pu is not None:
            pu.attrib.pop("fitToPage", None)
            if not pu.attrib:
                sp.remove(pu)


def _set_print_area(g, last_row):
    """인쇄 영역을 AV 열까지 잡는다.

    테두리 상자의 오른쪽 선이 AV 열에 있어서, AU 까지만 잡으면
    PDF 로 바꿀 때 오른쪽 세로선이 통째로 잘린다.
    """
    for dn in g.wb.getroot().iter(M + "definedName"):
        if dn.get("name") == "_xlnm.Print_Area" and dn.text and "!" in dn.text:
            head, _ = dn.text.split("!", 1)
            dn.text = "%s!$A$1:$%s$%d" % (head, PRINT_LAST_COL, last_row)


# ═══════════════════════════════════════════════ 페이지 테두리와 막대
# 성적서의 굵은 가로 막대(굵은 선 + 아래 얇은 선)는 셀 테두리가 아니라
# «도형» 이다. 페이지 머리의 막대와 붉은 꼬리말 위의 막대가 원래 같은 도형이라,
# 머리 막대를 한 벌 떠서 장마다 아래에 다시 깔면 둘이 저절로 똑같아진다.
#
# 걸 자리가 문제였다. 줄 «바닥» 에 걸면 엑셀이 그 점을 다음 장의 시작으로 보고
# 막대를 다음 장 맨 위로 넘겨 버린다. 그래서 장마다 얇은 빈 줄을 하나 끼우고
# 그 줄 «안» 에 건다. 빈 줄 몫은 page_budget 이 미리 빼 두므로 페이지가 밀리지
# 않는다.

def _rule_stencil(g, row):
    """그 줄에 걸린 막대 도형을 한 벌 떠 둔다. 없으면 None."""
    if g.draw is None:
        return None
    for anc in list(g.draw.getroot()):
        f = anc.find(D + "from")
        if f is None or anc.find(D + "sp") is None:     # 그림·직인은 건너뛴다
            continue
        rr = f.find(D + "row")
        if rr is not None and int(rr.text) + 1 == row:
            return copy.deepcopy(anc)
    return None


def _add_page_rules(g, stencil, last_row):
    """장마다 마지막 줄 뒤에 빈 줄을 하나 끼우고 그 줄에 막대를 건다.

    새 마지막 줄 번호를 돌려준다 — 인쇄 영역은 거기까지다.
    """
    if stencil is None or g.draw is None:
        return last_row
    dr = g.draw.getroot()
    ends = sorted(set([b for b in g.breaks() if b < last_row] + [last_row]))
    # 아래 장부터 처리해야 위쪽 줄번호가 안 밀린다.
    for i, end in enumerate(reversed(ends)):
        at = end + 1
        g.insert_filler(at, 1, RULE_GAP, None)
        if end in g.breaks():                 # 페이지 끝을 새 줄로 옮긴다
            g.remove_break(end)
            g.add_break(at)
        if end == last_row:
            # 줄번호를 그냥 들고 있으면 안 된다. 이 뒤 «위쪽» 장을 처리하면서
            # 이 줄이 그만큼 밀린다. 위치표시로 걸어 두고 끝에 다시 읽는다.
            g.mark("_RULE_LAST", at)
        new = copy.deepcopy(stencil)
        for tag in ("from", "to"):
            e = new.find(D + tag)
            if e is None:
                continue
            e.find(D + "row").text = str(at - 1)          # 0 부터 센다
            off = e.find(D + "rowOff")
            if off is not None:                            # 빈 줄 한가운데
                off.text = str(int(RULE_GAP * XG.EMU_PER_PT * 0.5))
        for cn in new.iter(D + "cNvPr"):
            cn.set("id", str(26000 + i))
        dr.append(new)
    return g.at("_RULE_LAST")


# ═══════════════════════════════════════════════ 페이지 바깥 테두리
FRAME_BORDER = "thin"           # 내용 상자와 같은 굵기

def _side_style(g, base_s, side, cache):
    """base 서식에 한쪽 테두리만 얹은 서식 번호를 돌려준다."""
    key = (base_s or "0", side)
    if key in cache:
        return cache[key]
    root = g.styles.getroot()
    xfs = root.find(M + "cellXfs")
    bs = root.find(M + "borders")
    base_xf = xfs[int(key[0])]
    nb = copy.deepcopy(bs[int(base_xf.get("borderId", "0"))])
    old = nb.find(M + side)
    if old is not None and old.get("style"):
        cache[key] = base_s                    # 이미 있으면 그대로 둔다
        return base_s
    if old is not None:
        nb.remove(old)
    e = etree.Element(M + side)
    e.set("style", FRAME_BORDER)
    etree.SubElement(e, M + "color").set("rgb", "FF000000")
    # border 안의 자식 순서는 규격으로 정해져 있다. 틀리면 엑셀이 파일을
    # '복구'하면서 서식을 전부 버린다.
    XG._put_in_order(nb, e, XG.BORDER_ORDER)
    bs.append(nb)
    bs.set("count", str(len(bs)))
    nxf = copy.deepcopy(base_xf)
    nxf.set("borderId", str(len(bs) - 1))
    nxf.set("applyBorder", "1")
    xfs.append(nxf)
    xfs.set("count", str(len(xfs)))
    cache[key] = str(len(xfs) - 1)
    return cache[key]


def _merge_heads(g):
    """«그 줄로 끝나는 병합» 의 머리 칸을 줄번호별로 모아 둔다.

    병합된 칸은 맨 왼쪽 위 칸의 서식으로 테두리를 그린다. 아랫줄 칸에만
    넣으면 엑셀이 그냥 무시한다.
    """
    heads = {}
    mc = g.root.find(M + "mergeCells")
    for m in (mc if mc is not None else []):
        a, b = XG._pair(m.get("ref"))
        heads.setdefault(XG.split_ref(b)[1], []).append(a)
    return heads


def _page_frame(g, top_row, bottom_row, last_col=None):
    """그 장을 감싸는 사각 테두리를 두른다 (왼쪽 · 오른쪽 · 아래)."""
    n = XG.col_num(last_col or PRINT_LAST_COL)
    right = XG.col_name(n)
    cache, heads = {}, _merge_heads(g)
    for r in range(top_row, bottom_row + 1):
        for coord, side in (("A%d" % r, "left"), ("%s%d" % (right, r), "right")):
            c = _cell(g, coord)
            if c is not None:
                c.set("s", _side_style(g, c.get("s"), side, cache))
    for coord in (["%s%d" % (XG.col_name(ci), bottom_row) for ci in range(1, n + 1)]
                  + heads.get(bottom_row, [])):
        c = _cell(g, coord)
        if c is not None:
            c.set("s", _side_style(g, c.get("s"), "bottom", cache))


def _pad_keep_shapes(g, end_mark, at_mark, target=PAGE_TARGET):
    """여백행을 넣되, 그 자리에 걸친 그림이 세로로 늘어나지 않게 한다.

    직인은 «시몬스 연구소» 글자에 겹쳐 놓느라 여러 줄에 걸쳐 있다. 그 사이에
    줄을 끼우면 아래쪽 끝만 밀려 도장이 길쭉하게 늘어난다. 걸쳐 있던 그림은
    아래쪽만 밀 게 아니라 «통째로» 내려야 글자와 계속 겹친다.
    """
    dr = g.draw.getroot() if g.draw is not None else None
    at = g.at(at_mark)
    spans = []
    if dr is not None:
        for anc in dr:
            f, t = anc.find(D + "from"), anc.find(D + "to")
            if f is None or t is None:
                continue
            spans.append((anc, int(f.find(D + "row").text),
                               int(t.find(D + "row").text)))
    n = _pad_page(g, end_mark, at_mark, None, target=target)
    if n and dr is not None:
        for anc, f0, t0 in spans:
            # 0 부터 세므로 at 은 0-기준으로 at-1. 끼운 자리를 «가로지르던»
            # 그림만 손본다. 아래끝은 이미 밀렸으니 위끝도 같이 내린다.
            if f0 < at - 1 <= t0:
                anc.find(D + "from").find(D + "row").text = str(f0 + n)
    return n


# ═══════════════════════════════════════════════ 페이지 나눔
def _paginate(g, page_top, hdr, blocks, suf_a_mark, suf_b_mark,
              budget=None, lead=("LEAD_A", "LEAD_B")):
    """표가 한 페이지를 넘으면 나눔을 넣고, 이어지는 페이지에 표 머리를 다시 얹는다.

    blocks: [(시작행, 행수)] — 한 덩어리가 페이지 사이에서 잘리지 않게 한다.
    """
    if not blocks:
        return
    if budget is None:
        budget = page_budget(g)
    # 표 머리와 페이지 머리띠는 '위치표시' 이름으로 받는다.
    # 나눔을 여러 번 넣는 동안 원본 줄이 밀리므로 그때그때 다시 읽어야 한다.
    h_hdr = g.span_h(g.at(hdr[0]), g.at(hdr[1])) if hdr else 0.0
    h_lead = g.span_h(g.at(lead[0]), g.at(lead[1])) if lead else 0.0
    h_pre = g.span_h(page_top, blocks[0][0] - 1)
    hs = [g.span_h(s, s + r - 1) for (s, r) in blocks]
    h_suf = g.span_h(g.at(suf_a_mark), g.at(suf_b_mark))

    used = h_pre
    starts = []
    for k, hb in enumerate(hs):
        if k > 0 and used + hb > budget:
            starts.append(k)
            used = h_lead + h_hdr + hb
        else:
            used += hb

    # 아래에서 위로 넣어야 위쪽 행번호가 그대로 유지된다
    for k in reversed(starts):
        row = blocks[k][0]
        n_lead = 0
        if lead:
            la, lb = g.at(lead[0]), g.at(lead[1])   # 매번 다시 읽는다
            n_lead = lb - la + 1
            g.copy_rows(la, lb, row, clear=False)                 # 머리띠 글자
            la2 = g.at(lead[0])                                   # 복제로 또 밀렸다
            g.copy_drawings(la2, la2 + n_lead - 1, row, uid=k + 1)  # 머리띠 선·표시
        if hdr:
            ha, hb = g.at(hdr[0]), g.at(hdr[1])     # 매번 다시 읽는다
            g.copy_rows(ha, hb, row + n_lead, clear=False)
        g.add_break(row - 1)

    # 표 뒤 주석·마감줄이 마지막 장에 안 들어가면 다음 장으로 넘긴다.
    # 그 장에도 페이지 머리띠를 얹어야 빈 종이처럼 보이지 않는다.
    if used + h_suf > budget:
        row = g.at(suf_a_mark)
        if lead:
            la, lb = g.at(lead[0]), g.at(lead[1])
            n_lead = lb - la + 1
            g.copy_rows(la, lb, row, clear=False)
            la2 = g.at(lead[0])
            g.copy_drawings(la2, la2 + n_lead - 1, row, uid=99)
        g.add_break(row - 1)


def _pad_page(g, end_mark, at_mark, snap, target=PAGE_TARGET,
              skip_if_at_top=False):
    """어느 면의 마지막 장이 짧으면 여백행을 넣어 종이 아래까지 채운다.

    표가 줄어들면 테두리 상자가 종이 중간에서 끝나 어색해지므로,
    남는 높이만큼 여백행을 끼워 원본 양식과 같은 높이로 맞춘다.
    """
    end = g.at(end_mark)
    start = g.page_start(end)
    if skip_if_at_top and start >= g.at(at_mark):
        return 0        # 그 장에 서명 블록만 있는 경우 - 위쪽에 붙여 둔다
    room = min(target, page_budget(g)) - g.span_h(start, end)
    if room < 3:
        return 0

    # 한 줄을 크게 늘리면 엑셀 화면에서 거대한 빈 줄로 보여 어색하다.
    # 원본 양식처럼 보통 높이의 줄 여러 개로 나눈다.
    unit = 15.0
    if snap is not None:
        try:
            unit = float(snap.get("ht") or unit)
        except (TypeError, ValueError):
            unit = 15.0
    unit = min(max(unit, 9.0), 24.0)
    n = max(1, int(round(room / unit)))
    n = min(n, 400)                                # 터무니없이 많아지지 않게
    at = g.at(at_mark)
    g.insert_filler(at, n, room / n, snap)
    return n

