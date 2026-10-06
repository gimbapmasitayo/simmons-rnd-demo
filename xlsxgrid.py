# -*- coding: utf-8 -*-
"""엑셀 시트를 행 단위로 안전하게 늘리고 줄이는 엔진.

행을 넣거나 빼면 그 아래에 있는 모든 것이 같이 밀려야 한다.
이 모듈은 아래 항목을 한꺼번에 옮겨서 서식/이미지/인쇄설정이 깨지지 않게 한다.

  - 행과 셀 좌표      - 병합 셀        - 그림(이미지) 앵커
  - 페이지 나눔        - 인쇄 영역      - 조건부 서식
  - 데이터 유효성      - 하이퍼링크      - 사용자가 지정한 위치표시(landmark)
"""
import os, re, copy
from lxml import etree

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XDR  = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
M    = "{%s}" % MAIN
D    = "{%s}" % XDR

EMU_PER_PX = 9525
EMU_PER_PT = 12700

# 열 너비를 픽셀로 바꿀 때 쓰는 '숫자 한 글자 폭'(px).
# 글꼴에 따라 다르다. 맑은 고딕 11pt = 8px, Calibri 11pt = 7px.
MDW_BY_SIZE = {8: 6, 9: 6, 10: 7, 11: 8, 12: 9, 14: 10}
MDW_DEFAULT = 8

_REF = re.compile(r"(\$?)([A-Z]{1,3})(\$?)(\d+)")


def col_num(s):
    n = 0
    for ch in s:
        n = n * 26 + ord(ch) - 64
    return n


def col_name(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref):
    m = re.match(r"\$?([A-Z]{1,3})\$?(\d+)$", ref)
    return m.group(1), int(m.group(2))


def _shift_in_text(text, frm, delta):
    """D21:AJ21 또는 $A$1:$AU$148 같은 문자열 안의 행번호를 옮긴다."""
    def sub(m):
        d1, col, d2, row = m.groups()
        r = int(row)
        return "%s%s%s%d" % (d1, col, d2, r + delta if r >= frm else r)
    return _REF.sub(sub, text)


def _pair(ref):
    a, b = ref.split(":") if ":" in ref else (ref, ref)
    return a, b


# border 요소 안의 자식 순서 (OOXML 규격). 어기면 엑셀이 파일을 복구하며 서식을 버린다.
BORDER_ORDER = ["start", "end", "left", "right", "top", "bottom",
                "diagonal", "vertical", "horizontal"]
XF_ORDER = ["alignment", "protection", "extLst"]
FONT_ORDER = ["b", "i", "strike", "condense", "extend", "outline", "shadow", "u",
              "vertAlign", "sz", "color", "name", "family", "charset", "scheme"]


def _put_in_order(parent, child, order):
    """규격이 정한 순서에 맞는 자리에 child 를 넣는다."""
    name = etree.QName(child).localname
    try:
        want = order.index(name)
    except ValueError:
        parent.append(child)
        return
    for existing in parent:
        try:
            got = order.index(etree.QName(existing).localname)
        except ValueError:
            continue
        if got > want:
            existing.addprevious(child)
            return
    parent.append(child)


class Grid:
    """template 을 풀어놓은 폴더(work) 위에서 동작한다."""

    def __init__(self, work):
        self.work = work
        self.sheet_p = os.path.join(work, "xl", "worksheets", "sheet1.xml")
        self.sheet = etree.parse(self.sheet_p)
        self.root = self.sheet.getroot()
        self.sd = self.root.find(M + "sheetData")

        self.draw_p = os.path.join(work, "xl", "drawings", "drawing1.xml")
        self.draw = etree.parse(self.draw_p) if os.path.exists(self.draw_p) else None

        self.wb_p = os.path.join(work, "xl", "workbook.xml")
        self.wb = etree.parse(self.wb_p)

        self.styles_p = os.path.join(work, "xl", "styles.xml")
        self.styles = etree.parse(self.styles_p)

        fmt = self.root.find(M + "sheetFormatPr")
        self.def_h = float(fmt.get("defaultRowHeight", "20.1")) if fmt is not None else 20.1
        self.def_w = float(fmt.get("defaultColWidth", "8.43")) if fmt is not None else 8.43

        # 기본 글꼴 크기로 숫자 한 글자 폭을 정한다 (사진칸 크기 계산에 쓰인다)
        self.mdw = MDW_DEFAULT
        try:
            fonts = self.styles.getroot().find(M + "fonts")
            sz = fonts[0].find(M + "sz")
            if sz is not None:
                self.mdw = MDW_BY_SIZE.get(int(round(float(sz.get("val")))), MDW_DEFAULT)
        except Exception:
            pass

        self.colw = {}
        cols = self.root.find(M + "cols")
        if cols is not None:
            for c in cols:
                for i in range(int(c.get("min")), int(c.get("max")) + 1):
                    self.colw[i] = float(c.get("width"))

        self.marks = {}

    # ------------------------------------------------------------------ 조회
    def rowmap(self):
        return {int(r.get("r")): r for r in self.sd}

    def row_h(self, n):
        r = self.rowmap().get(n)
        if r is None or not r.get("ht"):
            return self.def_h
        return float(r.get("ht"))

    def span_h(self, a, b):
        rm = self.rowmap()
        t = 0.0
        for n in range(a, b + 1):
            r = rm.get(n)
            t += float(r.get("ht")) if (r is not None and r.get("ht")) else self.def_h
        return t

    def col_px(self, idx):
        """열 하나의 너비를 픽셀로. 좁은 열이 많아 반올림 오차가 쌓이므로 버리지 않는다."""
        w = self.colw.get(idx, self.def_w)
        m = self.mdw
        return (256 * w + int(128 / m)) / 256.0 * m

    def span_px(self, c1, c2):
        return sum(self.col_px(i) for i in range(c1, c2 + 1))

    def mark(self, name, row):
        self.marks[name] = row

    def at(self, name):
        return self.marks[name]

    # ------------------------------------------------------------------ 이동
    def _shift(self, frm, delta):
        """frm 행부터 아래 전부를 delta 만큼 이동."""
        if delta == 0:
            return
        for r in self.sd:
            n = int(r.get("r"))
            if n >= frm:
                r.set("r", str(n + delta))
                for c in r:
                    col, rw = split_ref(c.get("r"))
                    c.set("r", "%s%d" % (col, rw + delta))

        mc = self.root.find(M + "mergeCells")
        if mc is not None:
            for m in mc:
                m.set("ref", _shift_in_text(m.get("ref"), frm, delta))

        for cf in self.root.findall(M + "conditionalFormatting"):
            cf.set("sqref", _shift_in_text(cf.get("sqref"), frm, delta))

        for dv in self.root.iter(M + "dataValidation"):
            if dv.get("sqref"):
                dv.set("sqref", _shift_in_text(dv.get("sqref"), frm, delta))

        for hl in self.root.iter(M + "hyperlink"):
            if hl.get("ref"):
                hl.set("ref", _shift_in_text(hl.get("ref"), frm, delta))

        rb = self.root.find(M + "rowBreaks")
        if rb is not None:
            for b in rb:
                i = int(b.get("id"))
                if i >= frm:
                    b.set("id", str(i + delta))

        if self.draw is not None:
            for anc in self.draw.getroot():
                for tag in ("from", "to"):
                    e = anc.find(D + tag)
                    if e is None:
                        continue
                    rr = e.find(D + "row")
                    if rr is None:
                        continue
                    one = int(rr.text) + 1            # 그림 앵커는 0부터 시작
                    if one >= frm:
                        rr.text = str(one + delta - 1)

        for dn in self.wb.getroot().iter(M + "definedName"):
            if dn.text and "!" in dn.text:
                head, tail = dn.text.split("!", 1)
                dn.text = head + "!" + _shift_in_text(tail, frm, delta)

        for k, v in list(self.marks.items()):
            if v >= frm:
                self.marks[k] = v + delta

    def _sort_rows(self):
        for k in sorted(self.sd, key=lambda r: int(r.get("r"))):
            self.sd.append(k)

    # ------------------------------------------------------------------ 삭제
    def check(self):
        """저장하기 전 병합이 성한지 본다.

        행을 지울 때 병합의 한쪽 끝만 잘라내면 'A36:AV33' 처럼 뒤집힌 칸이
        남는다. 엑셀은 이런 파일을 아예 열지 못하고, 화면에는 원인을 알 수
        없는 오류만 뜬다. 여기서 미리 잡아 어디가 잘못됐는지 알려준다.
        """
        rows = set(self.rowmap())
        bad = []
        mc = self.root.find(M + "mergeCells")
        for m in (mc if mc is not None else []):
            a, b = _pair(m.get("ref"))
            r1, r2 = split_ref(a)[1], split_ref(b)[1]
            c1, c2 = col_num(split_ref(a)[0]), col_num(split_ref(b)[0])
            if r1 > r2 or c1 > c2:
                bad.append("%s (뒤집힘)" % m.get("ref"))
            elif r1 not in rows or r2 not in rows:
                bad.append("%s (없는 줄)" % m.get("ref"))
        if bad:
            raise ValueError("병합된 칸이 깨졌습니다. 행을 지울 때 병합을 반만 "
                             "잘라낸 것입니다: " + ", ".join(bad[:8]))
        return True

    def delete_rows(self, first, last):
        if last < first:
            return 0
        n = last - first + 1

        for r in list(self.sd):
            if first <= int(r.get("r")) <= last:
                self.sd.remove(r)

        mc = self.root.find(M + "mergeCells")
        if mc is not None:
            for m in list(mc):
                a, b = _pair(m.get("ref"))
                if split_ref(a)[1] >= first and split_ref(b)[1] <= last:
                    mc.remove(m)
            mc.set("count", str(len(mc)))

        rb = self.root.find(M + "rowBreaks")
        if rb is not None:
            for b in list(rb):
                if first <= int(b.get("id")) <= last:
                    rb.remove(b)

        if self.draw is not None:
            dr = self.draw.getroot()
            for anc in list(dr):
                f = anc.find(D + "from")
                if f is None:
                    continue
                t = anc.find(D + "to")
                r1 = int(f.find(D + "row").text) + 1
                r2 = (int(t.find(D + "row").text) + 1) if t is not None else r1
                if r1 >= first and r2 <= last:
                    dr.remove(anc)

        for cf in list(self.root.findall(M + "conditionalFormatting")):
            keep = []
            for part in cf.get("sqref").split():
                a, b = _pair(part)
                if not (split_ref(a)[1] >= first and split_ref(b)[1] <= last):
                    keep.append(part)
            if keep:
                cf.set("sqref", " ".join(keep))
            else:
                self.root.remove(cf)

        # 지워진 구간 안을 가리키던 위치표시는 구간 시작으로 모은다
        for k, v in list(self.marks.items()):
            if first <= v <= last:
                self.marks[k] = first

        self._shift(last + 1, -n)
        self._fix_breaks()
        return n

    def remove_merge(self, ref):
        mc = self.root.find(M + "mergeCells")
        if mc is None:
            return
        for m in list(mc):
            if m.get("ref") == ref:
                mc.remove(m)
        mc.set("count", str(len(mc)))

    def add_merge(self, ref):
        mc = self.root.find(M + "mergeCells")
        if mc is None:
            return
        e = etree.SubElement(mc, M + "mergeCell")
        e.set("ref", ref)
        mc.set("count", str(len(mc)))

    # ------------------------------------------------------------------ 복제
    def copy_rows(self, src_first, src_last, at, clear=True):
        """src_first~src_last 를 그대로 복제해 at 위치에 끼워넣는다."""
        n = src_last - src_first + 1
        rm = self.rowmap()
        snap = [copy.deepcopy(rm[i]) for i in range(src_first, src_last + 1) if i in rm]
        if len(snap) != n:
            raise ValueError("복제 원본 행이 없습니다: %d~%d" % (src_first, src_last))

        mc = self.root.find(M + "mergeCells")
        snapm = []
        if mc is not None:
            for m in mc:
                a, b = _pair(m.get("ref"))
                c1, r1 = split_ref(a)
                c2, r2 = split_ref(b)
                if r1 >= src_first and r2 <= src_last:
                    snapm.append((c1, r1 - src_first, c2, r2 - src_first))

        self._shift(at, n)

        for i, rw in enumerate(snap):
            new = at + i
            rw.set("r", str(new))
            for c in list(rw):
                col, _ = split_ref(c.get("r"))
                c.set("r", "%s%d" % (col, new))
                if clear:
                    for ch in list(c):
                        c.remove(ch)
                    c.attrib.pop("t", None)
            self.sd.append(rw)
        self._sort_rows()

        if mc is not None:
            for (c1, r1, c2, r2) in snapm:
                e = etree.SubElement(mc, M + "mergeCell")
                e.set("ref", "%s%d:%s%d" % (c1, at + r1, c2, at + r2))
            mc.set("count", str(len(mc)))
        return n

    # ------------------------------------------------------------------ 여백행
    def snapshot_row(self, row):
        """행 하나를 떠 둔다. 나중에 여백행으로 끼워 넣는 데 쓴다."""
        rm = self.rowmap()
        return copy.deepcopy(rm[row]) if row in rm else None

    def insert_filler(self, at, count, ht, snap=None):
        """at 위치에 여백행 count 개를 끼워넣고 높이를 ht 로 맞춘다.

        snap 이 있으면 그 행의 서식(틀선 등)을 그대로 쓰고,
        없으면 아무 서식 없는 완전히 빈 행을 넣는다.
        """
        if count <= 0:
            return 0
        self._shift(at, count)
        for i in range(count):
            if snap is not None:
                r = copy.deepcopy(snap)
                for c in list(r):
                    col, _ = split_ref(c.get("r"))
                    c.set("r", "%s%d" % (col, at + i))
                    for ch in list(c):
                        c.remove(ch)
                    c.attrib.pop("t", None)
            else:
                r = etree.Element(M + "row")
                r.set("spans", "1:55")
            r.set("r", str(at + i))
            r.set("ht", "%.2f" % ht)
            r.set("customHeight", "1")
            self.sd.append(r)
        self._sort_rows()
        return count

    def page_start(self, end_row):
        """end_row 가 속한 페이지가 어느 행에서 시작하는지."""
        prev = [b for b in self.breaks() if b < end_row]
        return (max(prev) + 1) if prev else 1

    # -------------------------------------------------- 그림 복제
    def copy_drawings(self, src_first, src_last, dst_first, uid=0):
        """src_first~src_last 행에 걸린 그림(선·도장 등)을 dst_first 로 복제한다.

        페이지가 넘어갈 때 이어지는 장에도 머리띠를 다시 얹으려면 필요하다.
        """
        if self.draw is None:
            return 0
        dr = self.draw.getroot()
        d = dst_first - src_first
        made = 0
        for anc in list(dr):
            f = anc.find(D + "from")
            if f is None:
                continue
            rr = f.find(D + "row")
            if rr is None:
                continue
            r1 = int(rr.text) + 1
            if not (src_first <= r1 <= src_last):
                continue
            new = copy.deepcopy(anc)
            for tag in ("from", "to"):
                e = new.find(D + tag)
                if e is None:
                    continue
                er = e.find(D + "row")
                if er is not None:
                    er.text = str(int(er.text) + d)
            for cn in new.iter(D + "cNvPr"):
                cn.set("id", str(20000 + uid * 20 + made))
            dr.append(new)
            made += 1
        return made

    # -------------------------------------------------- 블록 개수 맞추기
    def resize_blocks(self, first, block_rows, have, want, src_block=1):
        """first 에서 시작하는 block_rows 행짜리 블록이 have 개일 때 want 개로 맞춘다.

        src_block: 늘릴 때 복제할 기준 블록 번호(0부터). 보통 가운데 블록을 쓴다.
        """
        if want == have:
            return 0
        if want < have:
            drop = have - want
            start = first + want * block_rows
            self.delete_rows(start, start + drop * block_rows - 1)
            return -drop * block_rows
        add = want - have
        src = first + src_block * block_rows
        at = first + have * block_rows
        for _ in range(add):
            self.copy_rows(src, src + block_rows - 1, at)
            at += block_rows
        return add * block_rows

    # -------------------------------------------------- 서식(테두리) 입히기
    def snap_styles(self, row):
        r = self.rowmap().get(row)
        if r is None:
            return None
        return {"row": dict(r.attrib),
                "cells": {split_ref(c.get("r"))[0]: c.get("s") for c in r}}

    def apply_styles(self, row, snap, only=None):
        """snap 에 담긴 서식을 row 에 입힌다. only 를 주면 그 열들만."""
        if not snap:
            return
        r = self.rowmap().get(row)
        if r is None:
            return
        for k in ("s", "customFormat", "ht", "customHeight"):
            if k in snap["row"]:
                r.set(k, snap["row"][k])
        for c in r:
            col = split_ref(c.get("r"))[0]
            if only is not None and col not in only:
                continue
            s = snap["cells"].get(col)
            if s is not None:
                c.set("s", s)

    def shrink_style(self, base_s):
        """글자가 칸보다 길면 자동으로 줄여 넣는 서식을 만든다.

        표를 두 칸으로 나누면 시료명 칸이 좁아져 긴 이름이 잘릴 수 있다.
        """
        if base_s is None:
            return None
        cache = getattr(self, "_shrink_cache", None)
        if cache is None:
            cache = self._shrink_cache = {}
        if base_s in cache:
            return cache[base_s]
        root = self.styles.getroot()
        xfs = root.find(M + "cellXfs")
        nxf = copy.deepcopy(xfs[int(base_s)])
        al = nxf.find(M + "alignment")
        if al is None:
            al = etree.Element(M + "alignment")
            _put_in_order(nxf, al, XF_ORDER)
        al.set("shrinkToFit", "1")
        nxf.set("applyAlignment", "1")
        xfs.append(nxf)
        xfs.set("count", str(len(xfs)))
        cache[base_s] = str(len(xfs) - 1)
        return cache[base_s]

    def scaled_font_style(self, base_s, ratio, floor=6.5):
        """글자 크기를 ratio 배로 줄인 서식을 만든다.

        줄 높이를 줄여 한 장에 더 담을 때, 글자도 같이 줄이지 않으면
        위아래가 잘린다.
        """
        if base_s is None or ratio >= 0.999:
            return base_s
        cache = getattr(self, "_font_cache", None)
        if cache is None:
            cache = self._font_cache = {}
        root = self.styles.getroot()
        xfs = root.find(M + "cellXfs")
        fonts = root.find(M + "fonts")
        xf = xfs[int(base_s)]
        fid = int(xf.get("fontId", "0"))
        sz = fonts[fid].find(M + "sz")
        base = float(sz.get("val")) if sz is not None else 11.0
        new = max(floor, round(base * ratio, 1))
        if abs(new - base) < 0.05:
            return base_s
        key = (base_s, new)
        if key in cache:
            return cache[key]
        nf = copy.deepcopy(fonts[fid])
        nsz = nf.find(M + "sz")
        if nsz is None:
            nsz = etree.Element(M + "sz")
            _put_in_order(nf, nsz, FONT_ORDER)
        nsz.set("val", str(new))
        fonts.append(nf)
        fonts.set("count", str(len(fonts)))
        nxf = copy.deepcopy(xf)
        nxf.set("fontId", str(len(fonts) - 1))
        nxf.set("applyFont", "1")
        xfs.append(nxf)
        xfs.set("count", str(len(xfs)))
        cache[key] = str(len(xfs) - 1)
        return cache[key]

    def set_row_height(self, row, ht):
        r = self.rowmap().get(row)
        if r is None:
            return
        r.set("ht", "%.2f" % ht)
        r.set("customHeight", "1")

    def style_of(self, coord):
        col, row = split_ref(coord)
        r = self.rowmap().get(row)
        if r is None:
            return None
        for c in r:
            if split_ref(c.get("r"))[0] == col:
                return c.get("s")
        return None

    def combined_style(self, base_s, bottom_s):
        """base 서식에 bottom 의 아래 테두리만 얹은 새 서식을 만들어 번호를 돌려준다.

        표가 한 줄뿐일 때 '첫 줄이자 마지막 줄'을 표현하려면 필요하다.
        """
        root = self.styles.getroot()
        xfs = root.find(M + "cellXfs")
        bs = root.find(M + "borders")
        base_xf = xfs[int(base_s)]
        bot_xf = xfs[int(bottom_s)]
        nb = copy.deepcopy(bs[int(base_xf.get("borderId", "0"))])
        src_b = bs[int(bot_xf.get("borderId", "0"))].find(M + "bottom")
        old = nb.find(M + "bottom")
        if old is not None:
            nb.remove(old)
        new_b = copy.deepcopy(src_b) if src_b is not None else etree.Element(M + "bottom")
        # border 안의 자식 순서는 규격으로 정해져 있다.
        # left, right, top, bottom, diagonal, vertical, horizontal
        # 순서가 틀리면 엑셀이 파일을 복구하면서 서식을 전부 버린다.
        _put_in_order(nb, new_b, BORDER_ORDER)
        bs.append(nb)
        bs.set("count", str(len(bs)))
        nxf = copy.deepcopy(base_xf)
        nxf.set("borderId", str(len(bs) - 1))
        xfs.append(nxf)
        xfs.set("count", str(len(xfs)))
        return str(len(xfs) - 1)

    # -------------------------------------------------- 페이지 나눔
    def _breaks_el(self):
        rb = self.root.find(M + "rowBreaks")
        if rb is None:
            # 워크시트 XML 은 요소 순서가 정해져 있다. rowBreaks 는
            # headerFooter / pageSetup 뒤, colBreaks / drawing 앞에 와야 한다.
            rb = etree.Element(M + "rowBreaks")
            after = None
            for tag in ("headerFooter", "pageSetup", "pageMargins", "printOptions"):
                e = self.root.find(M + tag)
                if e is not None:
                    after = e
                    break
            if after is not None:
                after.addnext(rb)
            else:
                self.root.append(rb)
        return rb

    def add_break(self, after_row):
        rb = self._breaks_el()
        if any(int(b.get("id")) == after_row for b in rb):
            return
        b = etree.SubElement(rb, M + "brk")
        b.set("id", str(after_row))
        b.set("max", "16383")
        b.set("man", "1")
        self._fix_breaks()

    def remove_break(self, after_row):
        rb = self.root.find(M + "rowBreaks")
        if rb is None:
            return
        for b in list(rb):
            if int(b.get("id")) == after_row:
                rb.remove(b)
        self._fix_breaks()

    def _fix_breaks(self):
        rb = self.root.find(M + "rowBreaks")
        if rb is None:
            return
        seen = set()
        for b in list(rb):
            i = int(b.get("id"))
            if i in seen or i <= 0:
                rb.remove(b)
            else:
                seen.add(i)
        for k in sorted(rb, key=lambda b: int(b.get("id"))):
            rb.append(k)
        rb.set("count", str(len(rb)))
        rb.set("manualBreakCount", str(sum(1 for k in rb if k.get("man") == "1")))

    def breaks(self):
        rb = self.root.find(M + "rowBreaks")
        return sorted(int(b.get("id")) for b in rb) if rb is not None else []

    # -------------------------------------------------- 인쇄 영역
    def set_print_area(self, last_row):
        for dn in self.wb.getroot().iter(M + "definedName"):
            if dn.get("name") == "_xlnm.Print_Area" and dn.text:
                head, tail = dn.text.split("!", 1)
                a, b = _pair(tail)
                col_b = split_ref(b)[0]
                dn.text = "%s!$A$1:$%s$%d" % (head, col_b, last_row)

    # -------------------------------------------------- 마무리
    def set_dimension(self):
        rows = [int(r.get("r")) for r in self.sd]
        if not rows:
            return
        cols = [col_num(split_ref(c.get("r"))[0]) for r in self.sd for c in r]
        dim = self.root.find(M + "dimension")
        if dim is not None and cols:
            dim.set("ref", "A1:%s%d" % (col_name(max(cols)), max(rows)))

    def save(self):
        self.check()
        self.set_dimension()
        self._fix_breaks()
        self.sheet.write(self.sheet_p, xml_declaration=True, encoding="UTF-8", standalone=True)
        self.wb.write(self.wb_p, xml_declaration=True, encoding="UTF-8", standalone=True)
        self.styles.write(self.styles_p, xml_declaration=True, encoding="UTF-8", standalone=True)
        if self.draw is not None:
            self.draw.write(self.draw_p, xml_declaration=True, encoding="UTF-8", standalone=True)


def drop_calcchain(work):
    """수식 계산순서 캐시를 지운다.

    행이 움직인 뒤에도 옛 좌표가 남아 있으면 엑셀이 복구 안내창을 띄울 수 있다.
    지워도 엑셀이 열 때 다시 만든다.
    """
    p = os.path.join(work, "xl", "calcChain.xml")
    if os.path.exists(p):
        os.remove(p)

    ct = os.path.join(work, "[Content_Types].xml")
    t = etree.parse(ct)
    r = t.getroot()
    for o in list(r):
        if o.get("PartName") == "/xl/calcChain.xml":
            r.remove(o)
    t.write(ct, xml_declaration=True, encoding="UTF-8", standalone=True)

    rp = os.path.join(work, "xl", "_rels", "workbook.xml.rels")
    t = etree.parse(rp)
    r = t.getroot()
    for rel in list(r):
        if rel.get("Target") in ("calcChain.xml", "/xl/calcChain.xml"):
            r.remove(rel)
    t.write(rp, xml_declaration=True, encoding="UTF-8", standalone=True)
