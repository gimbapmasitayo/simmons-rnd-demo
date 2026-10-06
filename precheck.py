# -*- coding: utf-8 -*-
"""성적서 입력 이상치 점검 — 생성 단추를 누르기 전에 입력값을 훑어 경고를 돌려준다.

  · 경고가 있어도 생성은 된다. 화면에서 «확인했습니다» 를 받고, 발행기록에 warn_items 로 남는다.
  · 임계값은 점검설정.json 에서 바꾼다 (없으면 기본값으로 만들어 둔다).
  · 경고 문구는 세 요소: what(무엇이) · why(왜 이상한지) · how(어떻게 확인할지).
"""
import os, io, re, json, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "점검설정.json")
DEFAULT = {
    "radon_diff_pct": 30,          # RAD7 와 RD200 라돈값 차이 허용 비율(%)
    "radon_diff_min_abs": 20,      # 차이가 이 값(Bq/m³) 미만이면 비율이 커도 경고하지 않는다 (18 vs 36 처럼 작은 값끼리의 비율 과장 방지)
    "bg_over_warn": True,          # 배경농도 > 측정치 경고. 참고: 연구소 참고 자료(2026-07 특판 5종)도 배경 69 > 측정 18·36 이라 정상 측정에서도 뜰 수 있다
    "temp_min": 15, "temp_max": 30, # 시험환경 온도(℃)
    "humid_min": 30, "humid_max": 70,  # 습도(%)
    "photo_required": True,        # 시료 사진 없이 만들면 경고
}


def settings():
    s = dict(DEFAULT)
    if os.path.exists(FILE):
        try:
            s.update(json.load(io.open(FILE, encoding="utf-8")))
        except Exception:
            pass
    else:
        try:
            json.dump(DEFAULT, io.open(FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            pass
    return s


def _num(s):
    """'23℃' · '45 %' · '상온' → 23.0 · 45.0 · None"""
    m = re.search(r"-?\d+(?:\.\d+)?", str(s or ""))
    return float(m.group()) if m else None


def _date(s):
    import stats
    return stats.parse_issue_date(s)


def W(what, why, how):
    return {"what": what, "why": why, "how": how}


def common_checks(form, files, kind, cfg):
    """모든 종류에 공통 — 날짜 순서, 온습도, 사진."""
    out = []
    rq, isd = _date(form.get("request_date", "")), _date(form.get("issue_date", ""))
    if rq and isd and rq > isd:
        out.append(W("의뢰일자(%s)가 발급일자(%s)보다 늦습니다" % (rq, isd),
                     "성적서는 의뢰를 받은 뒤 발급되므로 순서가 뒤집힐 수 없습니다",
                     "두 날짜 중 잘못 적은 쪽을 고치세요. 소급 등록이면 발급일자가 실제 발급일인지 보세요"))
    t = _num(form.get("temp", ""))
    if t is not None and not (cfg["temp_min"] <= t <= cfg["temp_max"]):
        out.append(W("시험환경 온도 %g℃" % t, "설정 범위 %g~%g℃ 밖입니다" % (cfg["temp_min"], cfg["temp_max"]),
                     "측정실 온도계 기록과 대조하고, 단위나 자릿수 오타가 아닌지 보세요"))
    h = _num(form.get("humid", ""))
    if h is not None and not (cfg["humid_min"] <= h <= cfg["humid_max"]):
        out.append(W("시험환경 습도 %g%%" % h, "설정 범위 %g~%g%% 밖입니다" % (cfg["humid_min"], cfg["humid_max"]),
                     "습도계 기록과 대조하세요. 범위 밖이 맞으면 성적서에 그대로 두고 특이사항에 적습니다"))
    if cfg.get("photo_required"):
        has_photo = any(f and f.filename and k.startswith(("photo_", "kphoto_", "sphoto_")) for k, f in files.items())
        if not has_photo:
            out.append(W("시료 사진이 없습니다", "사진 칸이 빈 성적서는 시료를 확인할 수 없어 되돌아오는 일이 많습니다",
                         "시료 사진을 올리거나, 사진 없이 내는 성적서가 맞는지 확인하세요"))
    return out


def radon_checks(form, files, kind, cfg):
    """라돈 완제품(RAD7·RD200·FRD400) / 원자재(FRD400·RadonEye): 배경농도 > 측정치, 두 기기 차이."""
    import core, material
    mod = material if kind == "material" else core
    out = []
    try:
        n_runs = max(1, min(int(form.get("n_runs", 1)), mod.MAX_RUNS))
    except ValueError:
        n_runs = 1
    for ri in range(n_runs):
        tag = ("%d번째 측정: " % (ri + 1)) if n_runs > 1 else ""
        def get(key):
            f = files.get("%s_%d" % (key, ri))
            return f if (f and f.filename) else None
        try:
            if kind == "material":
                frd, eye = get("frd"), get("eye")
                if not (frd and eye):
                    continue
                v = mod.compute(mod.parse_upload(mod.read_text(frd), frd.filename, "FRD400"),
                                mod.parse_upload(mod.read_text(eye), eye.filename, "EYE"))
                bg, m = v.get("radon_bg"), v.get("radon")
                if cfg.get("bg_over_warn", True) and bg is not None and m is not None and bg > m:
                    out.append(W(tag + "배경농도 %s Bq/m³가 측정치 %s Bq/m³보다 높습니다" % (bg, m),
                                 "시료를 넣은 챔버가 빈 방보다 낮게 나올 수는 없어 파일이 바뀌었거나 측정 구간이 어긋났을 수 있습니다",
                                 "배경농도(FRD400) 파일과 측정(RadonEye) 파일을 서로 바꿔 올리지 않았는지, 측정 시각이 같은 구간인지 보세요"))
            else:
                r7, rd, frd = get("rad7"), get("rd200"), get("frd")
                if not (r7 and rd and frd):
                    continue
                v = mod.compute(mod.parse_upload(mod.read_text(r7), r7.filename, "RAD7"),
                                mod.parse_upload(mod.read_text(rd), rd.filename, "RD200"),
                                mod.parse_upload(mod.read_text(frd), frd.filename, "FRD400"))
                bg, a, b = v.get("radon_bg"), v.get("radon_rad7"), v.get("radon_rd200")
                if cfg.get("bg_over_warn", True) and bg is not None and a is not None and b is not None and bg > a and bg > b:
                    out.append(W(tag + "배경농도 %s Bq/m³가 RAD7 %s · RD200 %s 측정치보다 높습니다" % (bg, a, b),
                                 "순농도가 0으로 깎여 판정이 늘 «적합»이 되므로 파일이 바뀌었거나 구간이 어긋났을 가능성이 큽니다",
                                 "FRD400 파일이 정말 빈 방 배경 측정인지, 세 파일의 측정 시각이 같은 구간인지 보세요"))
                if a is not None and b is not None and max(a, b) > 0:
                    diff = 100.0 * abs(a - b) / max(a, b)
                    if diff >= float(cfg["radon_diff_pct"]) and abs(a - b) >= float(cfg.get("radon_diff_min_abs", 0)):
                        out.append(W(tag + "RAD7 %s 와 RD200 %s 라돈값이 %.0f%% 차이 납니다" % (a, b, diff),
                                     "같은 챔버의 두 기기는 보통 %g%% 안에서 맞습니다" % cfg["radon_diff_pct"],
                                     "기기 중 하나의 시각이 어긋났거나 다른 측정 파일을 올렸는지 확인하고, 맞으면 특이사항에 적으세요"))
        except Exception as e:
            out.append(W(tag + "측정 파일을 미리 읽지 못했습니다", "파일 종류가 칸과 맞지 않거나 내용이 다릅니다 (%s)" % str(e)[:60],
                         "RAD7·RD200·FRD400 칸에 각각 맞는 파일을 올렸는지 보세요. 그대로 만들면 같은 오류로 멈춥니다"))
    return out


def mattress_checks(form, files, kind, cfg):
    """KC/KS: 치수가 허용차 밖인데 판정이 «적합»."""
    import ks
    out = []
    if kind == "ks":
        dims = tuple(ks.clean_num(form.get(k, "").strip()) for k in ("ks_dim_w", "ks_dim_l", "ks_dim_t"))
        spec = {k: ks.clean_num(form.get("ks_spec_" + k, "").strip()) for k in ("w", "l", "t")}
        spec = {k: v for k, v in spec.items() if v not in ("", None)}
        judge = form.get("ks_dims_judge") or "자동"
        auto = ks.judge_dims(dims, spec) if spec else []
        if judge == "적합" and auto and "부적합" in auto:
            bad = [n for n, j in zip(("나비", "길이", "두께"), auto) if j == "부적합"]
            out.append(W("치수(%s)가 허용차를 벗어났는데 판정이 «적합»입니다" % "·".join(bad),
                         "KS G 4300 허용차(나비·길이 +30/−20, 두께 +20/−20 mm) 밖이면 «부적합»이어야 합니다",
                         "측정값·기준 치수의 오타인지 보고, 맞으면 치수 판정을 «자동»이나 «부적합»으로 바꾸세요"))
    elif kind == "kc":
        # KC 양식에는 기준 치수 칸이 없어 허용차 판정을 할 수 없다 — 값이 비정상 범위면만 짚는다
        vals = [ks.clean_num(form.get(k, "").strip()) for k in ("dim_w", "dim_l", "dim_t")]
        nums = [(_num(v)) for v in vals]
        if nums[0] and nums[1] and nums[2] and (nums[0] < 600 or nums[1] < 1500 or nums[2] < 100 or nums[2] > 600) \
                and form.get("judge_dims") == "적합":
            out.append(W("치수 %s × %s × %s 가 매트리스 통상 범위를 벗어났는데 판정이 «적합»입니다" % tuple(vals),
                         "단위(mm/cm) 혼동이나 자릿수 오타일 수 있습니다",
                         "mm 단위인지 확인하고, 맞으면 그대로 두세요"))
    return out


def run(form, files, kind):
    cfg = settings()
    out = common_checks(form, files, kind, cfg)
    if kind in ("finished", "material"):
        out += radon_checks(form, files, kind, cfg)
    else:
        out += mattress_checks(form, files, kind, cfg)
    return out
