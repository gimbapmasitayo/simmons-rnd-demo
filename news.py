# -*- coding: utf-8 -*-
"""경쟁사 뉴스 클리핑 — 네이버 뉴스 검색으로 평일 아침 8시에 모아 두고, /뉴스 에서 본다.

  · 네이버 뉴스 검색 API (developers.naver.com 에서 애플리케이션 등록 → Client ID · Secret) 를
    화면 «가져오는 곳» 에 넣으면 네이버로 가져온다. 열쇠가 없는 동안은 구글 뉴스 RSS 가 임시로 채운다.

  · 가져오기만 한다. 사내 자료는 아무것도 내보내지 않는다 (검색어만 구글에 보낸다).
  · 기사는 뉴스기록.jsonl 에 한 줄씩 쌓인다 (같은 기사는 한 번만). 중요 표시·메모는 뉴스표시.json.
  · 스케줄러는 서버 안의 실(thread) 하나. 1분마다 «평일 · 8시 지남 · 오늘 아직 안 함» 이면 돈다.
    8시에 서버가 꺼져 있었으면 켜지는 순간 그날치를 가져온다. 화면의 «지금 가져오기» 도 같다.
  · 경쟁사와 검색어는 COMPANIES 에 있다. 가구사·렌탈사는 침대·매트리스가 들어간 기사만 남긴다.
"""
import os, io, re, json, time, html, hashlib, datetime, threading, calendar
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "뉴스기록.jsonl")
ARCHIVE_DIR = os.path.join(HERE, "보관")          # 90일 지난 기사는 월별 파일로 옮긴다
KEEP_DAYS = 90
MARKS = os.path.join(HERE, "뉴스표시.json")
STATE = os.path.join(HERE, "뉴스상태.json")
SETTINGS = os.path.join(HERE, "뉴스설정.json")      # 네이버 열쇠 · 가져오는 곳
_lock = threading.Lock()

RUN_HOUR = 8                   # 평일 이 시각 이후 하루 한 번
DAYS_BACK = 7                  # 검색 범위 (지난 n일)
TIMEOUT = 15

# (묶음, 회사 표시 이름, 검색어 목록, 본문에 꼭 있어야 하는 말 — 없으면 전부 허용)
BED = ("침대", "매트리스", "수면", "토퍼", "베딩", "프레임")
COMPANIES = (
    ("자사", "시몬스", ("시몬스 침대", "시몬스 매트리스", "시몬스 테라스"), ()),
    ("국내 침대·매트리스", "에이스침대", ("에이스침대",), ()),
    ("국내 침대·매트리스", "씰리코리아", ("씰리코리아", "씰리 침대", "씰리 매트리스"), ()),
    ("국내 침대·매트리스", "템퍼코리아", ("템퍼 매트리스", "템퍼코리아", "템퍼 침대"), ()),
    ("국내 침대·매트리스", "에몬스", ("에몬스 침대", "에몬스가구"), ()),
    ("국내 침대·매트리스", "장인가구", ("장인가구",), BED),
    ("국내 침대·매트리스", "보루네오", ("보루네오 가구", "보루네오 침대"), BED),
    ("국내 침대·매트리스", "파로마", ("파로마 침대", "파로마 가구"), BED),
    ("국내 침대·매트리스", "삼분의일", ("삼분의일 매트리스",), ()),
    ("국내 침대·매트리스", "슬로우", ("슬로우 매트리스",), ()),
    ("국내 침대·매트리스", "소프라움", ("소프라움",), ()),
    ("렌탈·케어", "코웨이 (비렉스)", ("코웨이 매트리스", "비렉스", "코웨이 침대"), BED),
    ("렌탈·케어", "청호나이스", ("청호나이스 매트리스",), BED),
    ("렌탈·케어", "교원 웰스", ("웰스 매트리스", "교원 매트리스"), BED),
    ("렌탈·케어", "바디프랜드", ("바디프랜드 매트리스", "바디프랜드 침대"), BED),
    ("렌탈·케어", "SK매직", ("SK매직 매트리스",), BED),
    ("종합 가구", "한샘", ("한샘 침대", "한샘 매트리스"), BED),
    ("종합 가구", "현대리바트", ("현대리바트 침대", "리바트 매트리스"), BED),
    ("종합 가구", "일룸·데스커", ("일룸 침대", "일룸 매트리스", "데스커 침대"), BED),
    ("종합 가구", "까사미아", ("까사미아 침대", "까사미아 매트리스"), BED),
    ("종합 가구", "이케아", ("이케아 매트리스", "이케아 침대"), BED),
    ("종합 가구", "지누스", ("지누스",), ()),
    ("침구·라텍스", "알레르망", ("알레르망",), ()),
    ("침구·라텍스", "이브자리", ("이브자리",), ()),
    ("침구·라텍스", "세사리빙", ("세사리빙",), ()),
    ("침구·라텍스", "던롭필로", ("던롭필로",), ()),
    ("해외", "Tempur Sealy", ("Tempur Sealy", "Somnigroup"), ()),
    ("해외", "Serta Simmons", ("Serta Simmons Bedding",), ()),
    ("해외", "Sleep Number", ("Sleep Number",), ()),
    ("해외", "Purple", ("Purple mattress",), ()),
    ("해외", "Casper", ("Casper Sleep", "Casper mattress"), ()),
    ("해외", "Saatva", ("Saatva",), ()),
    ("해외", "airweave", ("에어위브", "airweave"), ()),
    ("해외", "니시카와", ("니시카와 침구", "Nishikawa"), BED),
    ("해외", "프랑스베드", ("프랑스베드", "France Bed"), ()),
    ("업계", "매트리스 업계", ("매트리스 업계", "침대 업계", "수면 산업", "슬립테크"), BED),
)
GROUPS = ("자사", "국내 침대·매트리스", "렌탈·케어", "종합 가구", "침구·라텍스", "해외", "업계")

# R&D 가 보고 싶은 것 — 제목에 이 말이 있으면 태그
TAGS = (
    ("신제품·기술", ("신제품", "출시", "론칭", "런칭", "신기술", "기술", "개발", "혁신", "스마트", "AI", "센서", "슬립테크", "라인업")),
    ("특허·인증·시험", ("특허", "인증", "KC", "KS", "시험", "성적서", "품질인증", "라돈", "친환경 인증", "그린가드", "오코텍스")),
    ("품질·안전", ("리콜", "결함", "불량", "안전", "유해", "라돈", "폼알데하이드", "화재", "소송", "분쟁", "환불")),
    ("소재·공급망", ("소재", "원단", "폼", "라텍스", "스프링", "포켓스프링", "메모리폼", "공장", "생산", "협력사", "원자재")),
    ("실적·투자", ("매출", "영업이익", "실적", "투자", "인수", "합병", "상장", "IPO", "지분", "유상증자", "적자", "흑자")),
    ("매장·채널", ("매장", "오픈", "입점", "플래그십", "쇼룸", "체험", "온라인", "라이브커머스", "렌탈", "구독", "백화점")),
    ("마케팅·브랜드", ("캠페인", "광고", "모델", "브랜드", "콜라보", "협업", "팝업", "전시", "ESG", "기부")),
)
DROP = ("주가", "목표주가", "증권", "공매도", "시황", "특징주", "급등", "급락", "로또", "별세", "부고")   # 제목에 있으면 뺀다

# 구글 뉴스 RSS 에는 한국어 낱말을 끼워 넣은 도박·코인 스팸 사이트가 섞여 나온다.
# 제목에 이 말이 있으면 기사도 버리고 그 매체도 차단 목록(뉴스상태.json → blocked_sources)에 올린다.
SPAM_STRONG = ("토토", "카지노", "슬롯", "바카라", "도박", "룰렛", "홀덤", "파워볼", "먹튀", "보증업체",
               "추천인 코드", "비아그라", "출장안마", "해외배팅")        # 이 말이 있으면 기사도 빼고 매체도 차단
SPAM = SPAM_STRONG + ("배팅", "베팅", "포커", "경마", "사다리", "블록 체인", "블록체인", "비트코인", "자산 배분",
                      "Market 크기", "크기 상위")                        # 이 말은 기사만 뺀다 (정상 매체도 쓸 수 있는 말)
SPAM_SOURCES = ("Calgary Roughnecks", "Histoire pour Tous", "IndexBox", "Spherical Insights",
                "openPR", "EIN Presswire", "Market Research")      # 처음부터 막아 두는 매체
GENERIC = {"침대", "매트리스", "가구", "침구", "mattress", "bedding", "sleep", "bed"}   # 브랜드 말이 아닌 검색어 조각


def _brand_words(queries):
    """검색어에서 회사 이름 조각만 뽑는다. ("시몬스 침대", "시몬스 테라스") → {"시몬스", "테라스"}"""
    out = set()
    for q in queries:
        for w in q.split():
            if w.lower() not in GENERIC and len(w) >= 2:
                out.add(w.lower())
                for g in GENERIC:                       # "에이스침대" → "에이스"
                    if w.lower().endswith(g) and len(w) - len(g) >= 2:
                        out.add(w.lower()[:-len(g)])
    return out


def _relevant(title, queries, need):
    """제목에 회사 이름이나 침대 관련 말이 하나는 있어야 한다. 스팸은 둘 다 없다."""
    t = title.lower()
    if any(w in t for w in _brand_words(queries)):
        return True
    return any(w in title for w in (need or BED))


def is_spam(title, source, blocked=()):
    return any(w.lower() in title.lower() for w in SPAM) or source in SPAM_SOURCES or source in blocked


# ═══════════════════════════════════════════════ 설정 (네이버 열쇠)
def settings():
    """열쇠는 .env(NAVER_CLIENT_ID · NAVER_CLIENT_SECRET). 옛 뉴스설정.json 값은 .env 에 없을 때만."""
    import config
    s = {"source": "naver", "client_id": "", "client_secret": ""}
    if os.path.exists(SETTINGS):
        try:
            s.update(json.load(io.open(SETTINGS, encoding="utf-8")))
        except Exception:
            pass
    s["client_id"] = config.get("NAVER_CLIENT_ID") or s.get("client_id", "")
    s["client_secret"] = config.get("NAVER_CLIENT_SECRET") or s.get("client_secret", "")
    return s


def save_settings(patch):
    import config
    env = {}
    for k, name in (("client_id", "NAVER_CLIENT_ID"), ("client_secret", "NAVER_CLIENT_SECRET")):
        if k in patch:
            env[name] = str(patch[k] or "").strip()
    if env:
        config.set_many(env)
    s = {"source": "naver"}
    if os.path.exists(SETTINGS):
        try:
            s.update(json.load(io.open(SETTINGS, encoding="utf-8")))
        except Exception:
            pass
    if patch.get("source") in ("naver", "google"):
        s["source"] = patch["source"]
    s["client_id"], s["client_secret"] = "", ""          # JSON 에는 열쇠를 두지 않는다
    with _lock:
        tmp = SETTINGS + ".tmp"
        json.dump(s, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, SETTINGS)
    return settings()


def has_naver_key():
    s = settings()
    return bool(s["client_id"] and s["client_secret"])


def active_source():
    """실제로 쓰는 곳. 네이버를 골랐어도 열쇠가 없으면 구글."""
    s = settings()
    return "naver" if (s["source"] == "naver" and has_naver_key()) else "google"


# 네이버는 매체 이름을 주지 않는다 — 원문 주소의 도메인으로 알아낸다
DOMAINS = {"chosun.com": "조선일보", "donga.com": "동아일보", "joongang.co.kr": "중앙일보", "hani.co.kr": "한겨레",
           "khan.co.kr": "경향신문", "mk.co.kr": "매일경제", "hankyung.com": "한국경제", "sedaily.com": "서울경제",
           "edaily.co.kr": "이데일리", "mt.co.kr": "머니투데이", "asiae.co.kr": "아시아경제", "fnnews.com": "파이낸셜뉴스",
           "etnews.com": "전자신문", "news1.kr": "뉴스1", "newsis.com": "뉴시스", "yna.co.kr": "연합뉴스", "ytn.co.kr": "YTN",
           "heraldcorp.com": "헤럴드경제", "biz.chosun.com": "조선비즈", "kmib.co.kr": "국민일보", "segye.com": "세계일보",
           "munhwa.com": "문화일보", "seoul.co.kr": "서울신문", "dt.co.kr": "디지털타임스", "zdnet.co.kr": "지디넷코리아",
           "inews24.com": "아이뉴스24", "ajunews.com": "아주경제", "newspim.com": "뉴스핌", "thebell.co.kr": "더벨",
           "sisajournal.com": "시사저널", "ohmynews.com": "오마이뉴스", "nocutnews.co.kr": "노컷뉴스", "sbs.co.kr": "SBS",
           "kbs.co.kr": "KBS", "imbc.com": "MBC", "jtbc.co.kr": "JTBC", "mbn.co.kr": "MBN", "tvchosun.com": "TV조선",
           "wowtv.co.kr": "한국경제TV", "etoday.co.kr": "이투데이", "ekn.kr": "에너지경제", "g-enews.com": "글로벌이코노믹",
           "econovill.com": "이코노믹리뷰", "bizwatch.co.kr": "비즈워치", "ceoscoredaily.com": "CEO스코어데일리",
           "mtn.co.kr": "머니투데이방송", "apparelnews.co.kr": "어패럴뉴스", "fashionbiz.co.kr": "패션비즈",
           "kfurniture.or.kr": "가구신문", "furniturenews.co.kr": "가구뉴스", "livingtrend.co.kr": "리빙트렌드",
           "dailian.co.kr": "데일리안", "news2day.co.kr": "뉴스투데이", "sportsseoul.com": "스포츠서울",
           "kukinews.com": "쿠키뉴스", "newsway.co.kr": "뉴스웨이", "viva100.com": "브릿지경제", "ebn.co.kr": "EBN"}


def _source_of(url):
    m = re.search(r"https?://([^/]+)", url)
    host = (m.group(1) if m else "").lower()
    host = re.sub(r"^(www|news|biz|m|view|n|v|economy|it)\.", "", host)
    for dom, name in DOMAINS.items():
        if host == dom or host.endswith("." + dom):
            return name
    return host


def _fetch_naver(query):
    s = settings()
    url = "https://openapi.naver.com/v1/search/news.json?query=%s&display=100&sort=date" % urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"X-Naver-Client-Id": s["client_id"],
                                               "X-Naver-Client-Secret": s["client_secret"]})
    data = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8"))
    since = datetime.datetime.now() - datetime.timedelta(days=DAYS_BACK)
    out = []
    for it in data.get("items", []):
        title = html.unescape(re.sub(r"</?b>", "", it.get("title", ""))).strip()
        try:
            dt = datetime.datetime.strptime(it.get("pubDate", "")[:25], "%a, %d %b %Y %H:%M:%S")
        except ValueError:
            dt = None
        if dt and dt < since:
            continue
        link = it.get("originallink") or it.get("link") or ""
        out.append({"title": title, "link": link, "source": _source_of(link),
                    "date": dt.strftime("%Y-%m-%d %H:%M") if dt else ""})
    return out


# ═══════════════════════════════════════════════ 가져오기 (구글 RSS — 열쇠 없을 때 임시)
def _fetch_rss(query):
    q = urllib.parse.quote(query + " when:%dd" % DAYS_BACK)
    url = "https://news.google.com/rss/search?q=%s&hl=ko&gl=KR&ceid=KR:ko" % q
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (R&D news clipping)"})
    data = urllib.request.urlopen(req, timeout=TIMEOUT).read()
    root = ET.fromstring(data)
    out = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        # 구글은 제목 끝에 " - 매체" 를 붙인다
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3].strip()
        elif " - " in title:
            title, _, src2 = title.rpartition(" - ")
            source = source or src2.strip()
        pub = it.findtext("pubDate") or ""
        try:
            dt = datetime.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
            dt = dt + datetime.timedelta(hours=9)       # GMT → KST
            date = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            date = ""
        out.append({"title": title, "link": (it.findtext("link") or "").strip(),
                    "source": source, "date": date})
    return out


def _norm(t):
    return re.sub(r"[\s\W]+", "", t.lower())


def tag_of(title):
    tags = []
    for name, words in TAGS:
        if any(w.lower() in title.lower() for w in words):
            tags.append(name)
    return tags


def collect(progress=None):
    """모든 검색어를 돌려 새 기사만 뉴스기록.jsonl 에 더한다. (새 기사 수, 오류 목록) 을 돌려준다."""
    seen = {r["key"] for r in load()}
    seen_titles = set()          # 이번 수집에서 회사 이름으로 이미 잡힌 기사 — «업계» 묶음에는 다시 넣지 않는다
    new, errors = [], []
    st0 = state()
    blocked = set(st0.get("blocked_sources") or [])
    dropped = 0
    src = active_source()
    fetch = _fetch_naver if src == "naver" else _fetch_rss
    for grp, company, queries, need in COMPANIES:
        got = {}
        for q in queries:
            try:
                for a in fetch(q):
                    got.setdefault(_norm(a["title"])[:60], a)
            except urllib.error.HTTPError as e:
                errors.append("%s «%s»: HTTP %s%s" % (company, q, e.code,
                              " (네이버 열쇠가 틀렸습니다)" if e.code in (401, 403) else ""))
            except Exception as e:
                errors.append("%s «%s»: %s" % (company, q, type(e).__name__))
            time.sleep(0.15 if src == "naver" else 0.4)
        for key, a in got.items():
            t = a["title"]
            if not t or any(d in t for d in DROP):
                continue
            if is_spam(t, a["source"], blocked):
                if a["source"] and a["source"] not in SPAM_SOURCES and any(w.lower() in t.lower() for w in SPAM_STRONG):
                    blocked.add(a["source"])          # 스팸 낱말을 쓴 매체는 앞으로 통째로 막는다
                dropped += 1
                continue
            if need and not any(w in t for w in need):
                continue
            if not _relevant(t, queries, need):
                dropped += 1
                continue
            if grp == "업계" and key in seen_titles:
                continue
            seen_titles.add(key)
            k = hashlib.md5((company + "|" + key).encode("utf-8")).hexdigest()[:16]
            if k in seen:
                continue
            seen.add(k)
            new.append({"key": k, "group": grp, "company": company, "title": t, "link": a["link"],
                        "source": a["source"], "date": a["date"], "via": src,
                        "fetched": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "tags": tag_of(t)})
        if progress:
            progress(company)
    if new:
        with _lock:
            with io.open(LOG, "a", encoding="utf-8") as f:
                for r in new:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    st = state()
    st.update({"last_run": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "last_source": src,
               "last_new": len(new), "last_errors": errors[:20], "last_day": datetime.date.today().isoformat(),
               "last_dropped": dropped, "blocked_sources": sorted(blocked)})
    save_state(st)
    try:
        archive_old()
    except Exception:
        pass
    return len(new), errors


def purge_spam():
    """이미 쌓인 기록에서 지금 규칙으로 걸러지는 기사를 뺀다. 뺀 수를 돌려준다."""
    st = state()
    blocked = set(st.get("blocked_sources") or [])
    by_company = {c: (q, n) for _, c, q, n in COMPANIES}
    keep, gone = [], []
    for r in _read_jl(LOG):
        q, n = by_company.get(r["company"], ((), ()))
        bad = (is_spam(r["title"], r["source"], blocked)
               or (q and not _relevant(r["title"], q, n)))
        if bad and r["source"] and any(w.lower() in r["title"].lower() for w in SPAM_STRONG):
            blocked.add(r["source"])
        (gone if bad else keep).append(r)
    if gone:
        with _lock:
            tmp = LOG + ".tmp"
            with io.open(tmp, "w", encoding="utf-8") as f:
                for r in keep:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            os.replace(tmp, LOG)
    st["blocked_sources"] = sorted(blocked)
    save_state(st)
    return len(gone), gone


def _read_jl(path):
    out = []
    if os.path.exists(path):
        with io.open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue        # 반쯤 쓰인 줄은 건너뛴다
    return out


def load(days=None):
    """최근 기록. days 가 KEEP_DAYS 를 넘으면 보관 폴더의 월별 파일도 같이 읽는다."""
    out = _read_jl(LOG)
    if days is not None and days > KEEP_DAYS and os.path.isdir(ARCHIVE_DIR):
        since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m")
        for fn in sorted(os.listdir(ARCHIVE_DIR)):
            m = re.match(r"뉴스기록_(\d{4}-\d{2})\.jsonl$", fn)
            if m and m.group(1) >= since:
                out += _read_jl(os.path.join(ARCHIVE_DIR, fn))
    return out


def archive_old():
    """KEEP_DAYS 지난 기사를 보관/뉴스기록_YYYY-MM.jsonl 로 옮긴다. 수집 끝에 한 번 부른다."""
    rows = _read_jl(LOG)
    cut = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    old = [r for r in rows if (r.get("date") or r.get("fetched") or "")[:10] < cut]
    if not old:
        return 0
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with _lock:
        by_month = {}
        for r in old:
            by_month.setdefault((r.get("date") or r.get("fetched"))[:7], []).append(r)
        for mon, lst in by_month.items():
            with io.open(os.path.join(ARCHIVE_DIR, "뉴스기록_%s.jsonl" % mon), "a", encoding="utf-8") as f:
                for r in lst:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        keep = [r for r in rows if (r.get("date") or r.get("fetched") or "")[:10] >= cut]
        tmp = LOG + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, LOG)
    return len(old)


def state():
    if os.path.exists(STATE):
        try:
            return json.load(io.open(STATE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(st):
    with _lock:
        tmp = STATE + ".tmp"
        json.dump(st, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STATE)


def marks():
    if os.path.exists(MARKS):
        try:
            return json.load(io.open(MARKS, encoding="utf-8"))
        except Exception:
            pass
    return {}


def set_mark(key, star=None, memo=None, hide=None):
    m = marks()
    cur = m.get(key, {})
    if star is not None:
        cur["star"] = bool(star)
    if memo is not None:
        cur["memo"] = str(memo)[:300]
    if hide is not None:
        cur["hide"] = bool(hide)
    m[key] = cur
    with _lock:
        tmp = MARKS + ".tmp"
        json.dump(m, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, MARKS)
    return cur


# ═══════════════════════════════════════════════ 스케줄러
_running = {"busy": False, "now": ""}
AFTER_COLLECT = []          # 뉴스 수집이 끝나면 차례로 부른다 (동향 수집 등)


def due():
    """평일이고 8시가 지났고 오늘 아직 안 돌았으면 True."""
    now = datetime.datetime.now()
    if now.weekday() >= 5 or now.hour < RUN_HOUR:
        return False
    return state().get("last_day") != now.date().isoformat()


def run_now():
    if _running["busy"]:
        return None
    _running["busy"] = True
    try:
        return collect(progress=lambda c: _running.__setitem__("now", c))
    finally:
        _running["busy"] = False
        _running["now"] = ""


def start_scheduler(app_logger=None):
    def loop():
        while True:
            try:
                if due():
                    run_now()
                    for fn in AFTER_COLLECT:
                        fn()
            except Exception:
                if app_logger:
                    app_logger.exception("뉴스 수집 실패")
            time.sleep(60)
    t = threading.Thread(target=loop, name="news-scheduler", daemon=True)
    t.start()
    return t


# ═══════════════════════════════════════════════ 같은 기사 묶기
STOP = {"매트리스", "침대", "출시", "진행", "개최", "오픈", "선보여", "선보인다", "밝혔다", "위해", "통해", "대한", "관련",
        "최대", "할인", "행사", "기념", "국내", "제품", "브랜드", "업계", "것", "수", "등", "및", "더", "첫"}


def _tokens(title):
    """제목을 비교용 낱말 집합으로. 괄호·따옴표·기호를 떼고 2글자 이상 낱말만 남긴다."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】", " ", title)
    t = re.sub(r"[^\w가-힣]+", " ", t.lower())
    out = set()
    for w in t.split():
        # 조사 떼기: 코웨이가 → 코웨이, 매트리스를 → 매트리스
        w = re.sub(r"(은|는|이|가|을|를|의|에|에서|으로|로|와|과|도|만)$", "", w) if len(w) > 2 else w
        if len(w) >= 2 and w not in STOP:
            out.add(w)
    return out


def _same_story(a, b):
    """두 기사가 같은 소식인가. 3일 안쪽이고 낱말 셋 이상을 같이 쓰며 겹침 비율이 충분하면 같다."""
    da, db = (a.get("date") or a.get("fetched") or "")[:10], (b.get("date") or b.get("fetched") or "")[:10]
    if da and db and abs((datetime.date.fromisoformat(da) - datetime.date.fromisoformat(db)).days) > 3:
        return False
    ta, tb = a["_tok"], b["_tok"]
    if not ta or not tb:
        return False
    common = len(ta & tb)
    return common >= 3 and common / float(min(len(ta), len(tb))) >= 0.5


def cluster(rows):
    """같은 회사 안에서 같은 소식을 하나로 묶는다. 대표 기사(★이 있으면 그것, 아니면 가장 먼저 난 것)에
    others=[{source,link,title,date}] 와 n_src(매체 수)를 붙여 돌려준다. 입력은 날짜 내림차순."""
    for r in rows:
        r["_tok"] = _tokens(r["title"])
    out = []
    by_co = {}
    for r in rows:
        by_co.setdefault(r["company"], []).append(r)
    for co, lst in by_co.items():
        groups = []
        for r in lst:
            for g in groups:
                if _same_story(g[0], r):
                    g.append(r)
                    break
            else:
                groups.append([r])
        for g in groups:
            # 대표: ★ 달린 것 > 가장 먼저 난 것
            rep = next((x for x in g if x.get("star")), None) or min(g, key=lambda x: x.get("date") or x.get("fetched") or "")
            rep = dict(rep)
            rep["others"] = [{"source": x["source"], "link": x["link"], "title": x["title"], "date": (x.get("date") or "")[:10], "key": x["key"]}
                             for x in g if x["key"] != rep["key"]]
            rep["n_src"] = len(g)
            rep["memo"] = rep.get("memo") or next((x.get("memo") for x in g if x.get("memo")), "")
            rep["date"] = max(x.get("date") or "" for x in g) or rep.get("date", "")   # 목록 정렬은 가장 최근 보도 기준
            rep.pop("_tok", None)
            out.append(rep)
    # 회사 간 중복: 같은 소식이 여러 회사에 걸리면(비교 기사 등) 제목에 그 회사 이름이 든 쪽에만 남긴다.
    # 어느 회사 이름도 없으면 처음 걸린 회사 하나에만. «업계» 는 회사 소식과 같으면 늘 뺀다.
    brands = {c: _brand_words(q) for _, c, q, _ in COMPANIES}
    for r in out:
        r["_tok"] = _tokens(r["title"])
    groups = []                                   # 회사를 넘나드는 같은 소식 묶음
    for r in out:
        for g in groups:
            if _same_story(g[0], r):
                g.append(r)
                break
        else:
            groups.append([r])
    final = []
    for g in groups:
        if len(g) == 1:
            final.append(g[0])
            continue
        named = [r for r in g if r["group"] != "업계" and any(b in r["title"].lower() for b in brands.get(r["company"], ()))]
        if named:
            final.extend(named)                   # 제목에 이름이 든 회사들에만 남긴다 (비교 기사는 여럿 가능)
        else:
            co = [r for r in g if r["group"] != "업계"] or g
            final.append(min(co, key=lambda r: r.get("fetched") or ""))
    out = final
    for r in out + rows:
        r.pop("_tok", None)
    out.sort(key=lambda r: (r.get("date") or r.get("fetched") or ""), reverse=True)
    return out


# ═══════════════════════════════════════════════ 조회
def query(days=7, group="", company="", tag="", star_only=False, q=""):
    since = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    m = marks()
    rows = []
    for r in load(days):
        d = r.get("date") or r.get("fetched") or ""
        if d[:10] < since:
            continue
        mk = m.get(r["key"], {})
        if mk.get("hide"):
            continue
        if group and r["group"] != group:
            continue
        if company and r["company"] != company:
            continue
        if tag and tag not in r.get("tags", []):
            continue
        if star_only and not mk.get("star"):
            continue
        if q and q.lower() not in (r["title"] + r["company"] + r["source"]).lower():
            continue
        rr = dict(r)
        rr["star"] = bool(mk.get("star"))
        rr["memo"] = mk.get("memo", "")
        rows.append(rr)
    rows.sort(key=lambda r: (r.get("date") or r.get("fetched") or ""), reverse=True)
    raw_n = len(rows)
    rows = cluster(rows)
    # 회사별 건수 — 같은 소식은 하나로 (필터 전 기준, days 만 적용)
    allrows = []
    for r in load(days):
        d = r.get("date") or r.get("fetched") or ""
        if d[:10] >= since and not m.get(r["key"], {}).get("hide"):
            rr = dict(r)
            rr["star"] = bool(m.get(r["key"], {}).get("star"))
            allrows.append(rr)
    counts = {}
    for r in cluster(allrows):
        counts[r["company"]] = counts.get(r["company"], 0) + 1
    st = settings()
    return {"rows": rows[:400], "raw_n": raw_n, "counts": counts, "since": since, "state": state(),
            "source": active_source(), "has_key": has_naver_key(),
            "client_id": st["client_id"], "has_secret": bool(st["client_secret"]),
            "busy": _running["busy"], "now": _running["now"],
            "companies": [(g, c) for g, c, _, _ in COMPANIES], "groups": GROUPS,
            "tags": [t for t, _ in TAGS]}


# ═══════════════════════════════════════════════ 화면
PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>경쟁사 뉴스 클리핑</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" onerror="this.remove()">
<style>
:root{--ink:#0f0f11;--ink-2:#3a3a40;--mute:#84848a;--faint:#b4b4b9;--line:#e3e0d9;--line-2:#eeebe4;--paper:#fff;--bg:#f1efea;--black:#0a0a0b;--acc:#8c3325;--acc-soft:#f3e4e0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Pretendard Variable",Pretendard,"Malgun Gothic",system-ui,sans-serif}
__NAVCSS__
.wrap{max-width:1120px;margin:0 auto;padding:44px 40px 90px}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;flex-wrap:wrap;margin-bottom:8px}
.eyebrow{font-size:11px;letter-spacing:.2em;color:var(--mute);font-weight:600}
h1{font-size:30px;font-weight:700;letter-spacing:-.02em;margin:4px 0 0}
.status{font-size:12.5px;color:var(--mute);text-align:right;line-height:1.7}
.status b{color:var(--ink-2);font-weight:600}
.status button{font:inherit;font-size:12px;padding:6px 12px;border:1px solid var(--line);background:#fff;cursor:pointer;margin-left:10px}
.status button:hover{border-color:var(--black)}
.status button[disabled]{color:var(--faint);cursor:default}
.lead{font-size:14px;color:var(--ink-2);max-width:760px;margin:10px 0 26px;line-height:1.7}
.layout{display:grid;grid-template-columns:230px 1fr;gap:26px;align-items:start}
.panel{background:var(--paper);border:1px solid var(--line);padding:16px 0;position:sticky;top:20px;max-height:calc(100vh - 40px);overflow:auto}
.panel .sec{font-size:10.5px;letter-spacing:.18em;color:var(--mute);font-weight:600;padding:10px 18px 6px}
.panel a{display:flex;justify-content:space-between;align-items:center;padding:7px 18px;color:var(--ink-2);text-decoration:none;font-size:13px;cursor:pointer}
.panel a:hover{background:#faf9f6;color:var(--ink)}
.panel a.on{color:var(--ink);font-weight:600;border-left:3px solid var(--acc);padding-left:15px;background:#faf9f6}
.panel a .n{font-size:11px;color:var(--faint);font-variant-numeric:tabular-nums}
.panel a.zero{color:var(--faint)}
.bar{display:flex;flex-wrap:wrap;gap:8px 10px;align-items:center;margin-bottom:14px}
.seg{display:inline-flex;border:1px solid var(--line);background:#fff}
.seg button{font:inherit;font-size:12px;padding:6px 12px;background:transparent;border:none;border-right:1px solid var(--line);cursor:pointer;color:var(--ink-2)}
.seg button:last-child{border-right:none}
.seg button.on{background:var(--black);color:#fff}
.bar input[type=search]{font:inherit;font-size:12.5px;padding:7px 10px;border:1px solid var(--line);background:#fff;min-width:200px;flex:1}
.chip{font-size:11.5px;padding:5px 10px;border:1px solid var(--line);background:#fff;cursor:pointer;color:var(--ink-2);border-radius:14px}
.chip.on{background:var(--acc);border-color:var(--acc);color:#fff}
.list{background:var(--paper);border:1px solid var(--line)}
.day{font-size:11px;letter-spacing:.16em;color:var(--mute);font-weight:600;padding:14px 20px 6px;border-bottom:1px solid var(--line-2);background:#faf9f6}
.item{display:grid;grid-template-columns:28px 1fr auto;gap:0 14px;padding:13px 20px;border-bottom:1px solid var(--line-2);align-items:start}
.item:hover{background:#fcfbf9}
.item.star{background:#fdf7f5}
.st{font-size:17px;line-height:1.2;cursor:pointer;color:var(--faint);user-select:none;padding-top:2px}
.item.star .st{color:var(--acc)}
.t{font-size:14.5px;font-weight:500;line-height:1.5}
.t a{color:var(--ink);text-decoration:none}
.t a:hover{text-decoration:underline;text-underline-offset:3px}
.meta{font-size:12px;color:var(--mute);margin-top:3px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.meta b{color:var(--ink-2);font-weight:600}
.tag{font-size:10.5px;padding:1px 7px;border:1px solid var(--line);border-radius:10px;color:var(--mute)}
.tag.rd{border-color:#e8c9c3;color:var(--acc)}
.memo{font-size:12.5px;color:var(--ink-2);margin-top:6px;padding:6px 10px;background:#f7f5f0;border-left:2px solid var(--line);white-space:pre-wrap}
.memo:empty{display:none}
.more{font-size:11.5px;color:var(--mute);cursor:pointer;border:1px solid var(--line);border-radius:10px;padding:0 8px;white-space:nowrap}
.more:hover{border-color:var(--black);color:var(--black)}
.others{font-size:12.5px;color:var(--ink-2);margin-top:6px;padding-left:10px;border-left:2px solid var(--line-2);display:none}
.others.open{display:block}
.others a{color:var(--ink-2);text-decoration:none;display:block;padding:2px 0}
.others a:hover{text-decoration:underline}
.others a small{color:var(--mute);margin-left:6px}
.act{display:flex;gap:6px;opacity:0;transition:opacity .12s}
.item:hover .act{opacity:1}
.act button{font:inherit;font-size:11px;padding:3px 8px;border:1px solid var(--line);background:#fff;cursor:pointer;color:var(--ink-2)}
.act button:hover{border-color:var(--black);color:var(--black)}
.empty{padding:50px 20px;text-align:center;color:var(--mute);line-height:1.8}
.foot{font-size:11.5px;color:var(--faint);margin-top:22px;line-height:1.7}
.src{margin-top:22px;border:1px solid var(--line);background:var(--paper);font-size:12.5px}
.src summary{cursor:pointer;list-style:none;padding:12px 18px;font-weight:600;display:flex;gap:12px;align-items:center}
.src summary::-webkit-details-marker{display:none}
.src summary::before{content:"▸";font-size:10px;color:var(--mute)}
.src[open] summary::before{content:"▾"}
.src summary span{font-weight:400;color:var(--mute)}
.src summary span.warn{color:var(--acc)}
.src .in{padding:0 18px 16px;color:var(--ink-2);line-height:1.7}
.src .row{display:flex;flex-wrap:wrap;gap:8px 10px;align-items:center;margin-top:8px}
.src .row label{font-size:11px;letter-spacing:.1em;color:var(--mute);font-weight:600}
.src .row input{font:inherit;font-size:12.5px;padding:6px 9px;border:1px solid var(--line);background:#fff;min-width:220px}
.src .row button{font:inherit;font-size:12px;padding:6px 12px;background:var(--black);color:#fff;border:none;cursor:pointer}
.src .row span{font-size:12px;color:#23573f}
/* 브리핑 보기 */
.mode{display:inline-flex;border:1px solid var(--line);background:#fff;margin-left:12px;vertical-align:middle}
.mode button{font:inherit;font-size:12px;padding:6px 12px;background:transparent;border:none;border-right:1px solid var(--line);cursor:pointer;color:var(--ink-2)}
.mode button:last-child{border-right:none}.mode button.on{background:var(--black);color:#fff}
.hidden{display:none!important}
.bsum{display:flex;gap:28px;flex-wrap:wrap;align-items:flex-end;background:var(--paper);border:1px solid var(--line);padding:20px 24px;margin-bottom:18px}
.bsum .big{font-size:40px;font-weight:700;letter-spacing:-.03em;line-height:1;font-variant-numeric:tabular-nums}
.bsum .big small{font-size:13px;font-weight:500;color:var(--mute);margin-left:4px;letter-spacing:0}
.bsum .lab{font-size:12px;color:var(--mute);font-weight:600;margin-bottom:6px}
.bsum .txt{font-size:13px;color:var(--ink-2);line-height:1.6;flex:1;min-width:240px}
.bsec{font-size:11px;letter-spacing:.18em;color:var(--mute);font-weight:600;margin:26px 0 10px}
.bstars{background:var(--paper);border:1px solid var(--line)}
.bstars .item{grid-template-columns:1fr auto}
.bstars .item .t{font-size:15px}
.bsum .sub{font-size:11.5px;color:var(--mute);margin-top:4px}
.corows{background:var(--paper);border:1px solid var(--line)}
.corow{display:grid;grid-template-columns:150px 1fr;gap:0 20px;padding:12px 20px;border-top:1px solid var(--line-2)}
.corow:first-child{border-top:none}
.corow .who b{font-size:14px;display:block}
.corow .who span{font-size:11.5px;color:var(--mute)}
.corow .tl a{display:block;color:var(--ink);text-decoration:none;font-size:13.5px;line-height:1.5;padding:2px 0}
.corow .tl a:hover{text-decoration:underline;text-underline-offset:3px}
.corow .tl a.star::before{content:"★ ";color:var(--acc)}
.corow .tl a small{color:var(--mute);font-size:11px;margin-left:6px;white-space:nowrap}
.corow .rest{display:block;font-size:11.5px;color:var(--faint);padding-top:2px}
@media(max-width:700px){.corow{grid-template-columns:1fr}}
.bnote{font-size:12px;color:var(--mute);margin-top:18px;line-height:1.7}
@media print{.status button,.mode,.act,#full,.lead{display:none!important}.wrap{padding:0}.bsum{border:none;padding:0 0 14px}.corow{break-inside:avoid}body{background:#fff}}
@media(max-width:900px){.layout{grid-template-columns:1fr}.panel{position:static;max-height:none}.wrap{padding:28px 16px 70px}}
</style></head><body>
__NAV__
<div class="wrap">
<div class="head">
  <div><div class="eyebrow">시몬스 연구소</div><h1>경쟁사 뉴스 클리핑</h1></div>
  <div class="status" id="status"></div>
</div>
<div class="lead" id="lead"></div>

<div class="bar" style="margin-bottom:18px"><span class="seg" id="days"><button data-d="1">오늘</button><button data-d="7" class="on">7일</button><button data-d="30">30일</button><button data-d="90">90일</button></span>
  <span class="mode" id="mode"><button data-m="brief" class="on">브리핑</button><button data-m="full">전체 목록·설정</button></span>
  <button class="chip" id="print" style="margin-left:auto">인쇄</button></div>

<div id="brief"></div>

<div class="layout hidden" id="full">
  <div class="panel" id="panel"></div>
  <div>
    <div class="bar">
      <button class="chip" id="starOnly">★ 중요만</button>
      <input type="search" id="q" placeholder="제목·회사·매체 검색">
    </div>
    <div class="bar" id="tags"></div>
    <div class="list" id="list"></div>
    <details class="src" id="src"><summary>가져오는 곳 <span id="srcSum"></span></summary>
      <div class="in">
        <p>네이버 뉴스 검색 API 열쇠를 넣으면 네이버로 가져옵니다. 발급 방법은 README.md 의 «네이버 열쇠» 항목에 있습니다. 열쇠는 서버의 .env 에 저장됩니다. 열쇠가 없는 동안은 구글 뉴스 RSS 로 받습니다.</p>
        <div class="row"><label>Client ID</label><input id="cid" autocomplete="off"><label>Client Secret</label><input id="csec" type="password" autocomplete="off" placeholder="저장된 값은 보이지 않습니다"><button id="saveKey">저장</button><span id="keyMsg"></span></div>
        <p style="margin:8px 0 0;font-size:11.5px;color:var(--mute)">저장할 때 관리 비밀번호를 묻습니다 (포털설정.json 의 admin_pw).</p>
      </div></details>
    <div class="foot">기사 제목과 링크는 뉴스 검색이 제공한 그대로이며, 누르면 원문 매체로 갑니다. 한 소식이 여러 매체에 실리면 먼저 난 기사 하나만 보이고 「외 N개 매체」를 누르면 나머지가 펼쳐집니다. 잘못 잡힌 기사는 「숨기기」로 치웁니다.</div>
  </div>
</div>
</div>
<script>
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
let F={days:7,group:'',company:'',tag:'',star:false,q:''}, D=null;
let MODE=(()=>{try{return localStorage.getItem('newsMode')||'brief'}catch(e){return 'brief'}})();
const SRC=()=>D&&D.source==='naver'?'네이버 뉴스 검색':'구글 뉴스';
const LEAD={brief:'평일 아침 8시에 모은 경쟁사·업계 기사를 회사별로 간추렸습니다. ★는 담당자가 고른 기사입니다.',
            full:'제목만 보고 중요한 것에 ★을 켜고 한 줄 메모를 남기면, 브리핑 보기와 첫 화면 보고판에 올라갑니다. 월말에는 «★ 중요만» 으로 모아 보고 자료로 씁니다. 가져오기만 하고 사내 자료는 보내지 않습니다.'};
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
async function load(){
  const brief=MODE==='brief';
  const p=new URLSearchParams(brief?{days:F.days}:{days:F.days,group:F.group,company:F.company,tag:F.tag,star:F.star?1:0,q:F.q});
  D=await (await fetch('/뉴스/data?'+p)).json(); render();
}
function renderStatus(st){
  $('#status').innerHTML=`${D.busy?`<b>가져오는 중…</b> ${esc(D.now)}`:st.last_run?`마지막 수집 <b>${esc(st.last_run)}</b> · 새 기사 ${st.last_new??0}건${MODE==='full'&&st.last_dropped?` · 스팸·무관 ${st.last_dropped}건 거름`:''}${(st.last_errors||[]).length?` · <span style="color:var(--acc)">오류 ${st.last_errors.length}</span>`:''}`:'아직 한 번도 가져오지 않았습니다'}
    <button id="run" ${D.busy?'disabled':''}>지금 가져오기</button>`;
}
const PERIOD={1:'오늘',7:'지난 7일',30:'지난 30일',90:'지난 90일'};
function renderBrief(){
  const rows=D.rows, stars=rows.filter(r=>r.star);
  const cos=new Map(); rows.forEach(r=>{ if(!cos.has(r.company)) cos.set(r.company,[]); cos.get(r.company).push(r); });
  const order=D.companies.map(([,c])=>c).filter(c=>cos.has(c)); const grp=Object.fromEntries(D.companies);
  const byN=order.slice().sort((a,b)=>(a==='매트리스 업계')-(b==='매트리스 업계')||cos.get(b).length-cos.get(a).length);   // 업계 일반 소식은 맨 아래
  let h=`<div class="bsum"><div><div class="lab">${PERIOD[F.days]||''} 소식</div><div class="big">${rows.length}<small>건</small></div><div class="sub">기사 ${D.raw_n}건 → 같은 소식 묶음</div></div>
    <div><div class="lab">중요 표시 ★</div><div class="big">${stars.length}<small>건</small></div><div class="sub">${stars.length?'담당자가 고른 것':'아직 없음'}</div></div>
    <div class="txt">${rows.length?`소식이 많은 곳은 <b>${esc(byN.filter(c=>c!=='매트리스 업계').slice(0,3).join(' · '))}</b>${cos.has('매트리스 업계')?`, 업계 일반 소식 ${cos.get('매트리스 업계').length}건`:''}.`:'이 기간에 모인 기사가 없습니다.'}${stars.length?'':' 각 회사에서 많이 보도된 순으로 3건씩 보입니다.'}</div></div>`;
  if(stars.length){ h+=`<div class="bsec">중요 기사 ★</div><div class="bstars">`+stars.map(r=>`<div class="item star" data-k="${r.key}"><div><div class="t"><a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.title)}</a></div>
      <div class="meta"><b>${esc(r.company)}</b><span>${esc(r.source)}</span><span>${esc((r.date||'').slice(0,10))}</span>${(r.tags||[]).map(t=>`<span class="tag rd">${esc(t)}</span>`).join('')}</div><div class="memo">${esc(r.memo)}</div></div><div></div></div>`).join('')+`</div>`; }
  if(order.length){ h+=`<div class="bsec">회사별 소식 <span style="font-weight:500;letter-spacing:0;color:var(--faint)">— 많이 보도된 순 3건, 매체 수 함께</span></div><div class="corows">`+byN.map(c=>{const l=cos.get(c); const top=l.slice().sort((a,b)=>(b.star?1:0)-(a.star?1:0)||b.n_src-a.n_src).slice(0,3);
      return `<div class="corow"><div class="who"><b>${esc(c)}</b><span>${l.length}건</span></div><div class="tl">${top.map(r=>`<a class="${r.star?'star':''}" href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.title)}<small>${esc(r.source)}${r.n_src>1?` 외 ${r.n_src-1}곳`:''} · ${esc((r.date||'').slice(5,10).replace('-','.'))}</small></a>`).join('')}${l.length>3?`<span class="rest">외 ${l.length-3}건</span>`:''}</div></div>`;}).join('')+`</div>`; }
  h+=`<div class="bnote">${D.source==='naver'?'네이버 뉴스 검색':'구글 뉴스'}에서 평일 아침 8시에 모읍니다. 한 소식이 여러 매체에 실리면 하나로 묶고 매체 수를 적습니다. 기사 본문은 저장하지 않고 제목과 링크만 둡니다.</div>`;
  $('#brief').innerHTML=h;
}
function render(){
  const st=D.state||{};
  $('#lead').textContent=LEAD[MODE];
  $$('#mode button').forEach(b=>b.classList.toggle('on',b.dataset.m===MODE));
  $('#brief').classList.toggle('hidden',MODE!=='brief'); $('#full').classList.toggle('hidden',MODE==='brief');
  if(MODE==='brief'){ renderStatus(st); renderBrief(); return; }
  renderStatus(st);

  // 왼쪽: 묶음 → 회사
  let p=`<a class="${!F.group&&!F.company?'on':''}" data-g="" data-c="">전체 <span class="n">${Object.values(D.counts).reduce((a,b)=>a+b,0)}</span></a>`;
  D.groups.forEach(g=>{
    const cs=D.companies.filter(([gg])=>gg===g); const n=cs.reduce((a,[,c])=>a+(D.counts[c]||0),0);
    p+=`<div class="sec">${esc(g)}</div>`;
    cs.forEach(([,c])=>{const k=D.counts[c]||0; p+=`<a class="${F.company===c?'on':''} ${k?'':'zero'}" data-g="${esc(g)}" data-c="${esc(c)}">${esc(c)} <span class="n">${k||''}</span></a>`;});
  });
  $('#panel').innerHTML=p;
  $('#tags').innerHTML=D.tags.map(t=>`<button class="chip ${F.tag===t?'on':''}" data-t="${esc(t)}">${esc(t)}</button>`).join('');
  $('#starOnly').classList.toggle('on',F.star);
  $('#srcSum').textContent=D.source==='naver'?'네이버 뉴스 검색':'구글 뉴스 (임시 — 네이버 열쇠를 넣으면 바뀝니다)';
  $('#srcSum').className=D.source==='naver'?'':'warn';
  if(document.activeElement!==$('#cid')) $('#cid').value=D.client_id||'';
  if(!D.rows.length){ $('#list').innerHTML=`<div class="empty">${st.last_run?'이 조건에 맞는 기사가 없습니다.':'아직 기사가 없습니다.<br>오른쪽 위 «지금 가져오기» 를 누르면 지난 7일치를 모읍니다.'}</div>`; return; }
  let out='', day='';
  D.rows.forEach(r=>{
    const d=(r.date||r.fetched||'').slice(0,10);
    if(d!==day){ day=d; out+=`<div class="day">${esc(dayLabel(d))}</div>`; }
    out+=`<div class="item ${r.star?'star':''}" data-k="${r.key}">
      <span class="st" title="중요 표시">★</span>
      <div><div class="t"><a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.title)}</a></div>
        <div class="meta"><b>${esc(r.company)}</b><span>${esc(r.source)}</span><span>${esc((r.date||'').slice(11,16))}</span>
          ${(r.tags||[]).map(t=>`<span class="tag rd">${esc(t)}</span>`).join('')}${r.n_src>1?`<span class="more" data-a="others">외 ${r.n_src-1}개 매체</span>`:''}</div>
        ${r.n_src>1?`<div class="others">${r.others.map(o=>`<a href="${esc(o.link)}" target="_blank" rel="noopener">${esc(o.title)}<small>${esc(o.source)} ${esc(o.date.slice(5))}</small></a>`).join('')}</div>`:''}
        <div class="memo">${esc(r.memo)}</div></div>
      <div class="act"><button data-a="memo">메모</button><button data-a="hide">숨기기</button></div></div>`;
  });
  $('#list').innerHTML=out;
}
function dayLabel(d){ const t=new Date(); const td=t.toISOString().slice(0,10); const y=new Date(t-864e5).toISOString().slice(0,10);
  const w='일월화수목금토'[new Date(d+'T00:00:00').getDay()]; return (d===td?'오늘 · ':d===y?'어제 · ':'')+d.slice(5).replace('-','.')+' ('+w+')'; }
document.addEventListener('click',async e=>{
  const a=e.target.closest('#panel a'); if(a){ F.group=a.dataset.g; F.company=a.dataset.c; load(); return; }
  const b=e.target.closest('#days button'); if(b){ F.days=+b.dataset.d; $$('#days button').forEach(x=>x.classList.toggle('on',x===b)); load(); return; }
  const mb=e.target.closest('#mode button'); if(mb){ MODE=mb.dataset.m; try{localStorage.setItem('newsMode',MODE)}catch(e){} load(); return; }
  if(e.target.closest('#print')){ window.print(); return; }
  const t=e.target.closest('#tags .chip'); if(t){ F.tag=F.tag===t.dataset.t?'':t.dataset.t; load(); return; }
  if(e.target.closest('#starOnly')){ F.star=!F.star; load(); return; }
  if(e.target.closest('#saveKey')){ const pw=prompt('관리 비밀번호'); if(pw===null) return;
    const body={client_id:$('#cid').value}; if($('#csec').value) body.client_secret=$('#csec').value;
    const res=await fetch('/뉴스/설정',{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Pw':pw},body:JSON.stringify(body)}); const r=await res.json();
    $('#keyMsg').textContent=!res.ok?(r.error||'저장하지 못했습니다'):r.has_key?'저장했습니다. 다음 수집부터 네이버로 가져옵니다.':'Client ID와 Secret이 둘 다 있어야 합니다.'; $('#csec').value=''; load(); return; }
  if(e.target.closest('#run')){ e.target.disabled=true; e.target.textContent='가져오는 중…'; await fetch('/뉴스/수집',{method:'POST'}); setTimeout(load,800); return; }
  const mo=e.target.closest('.more[data-a="others"]'); if(mo){ const o=$('.others',mo.closest('.item')); if(o) o.classList.toggle('open'); return; }
  const st=e.target.closest('.item .st'); if(st){ const it=st.closest('.item'); const on=!it.classList.contains('star');
    await fetch('/뉴스/표시',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:it.dataset.k,star:on})}); it.classList.toggle('star',on); return; }
  const ab=e.target.closest('.act button'); if(ab){ const it=ab.closest('.item');
    if(ab.dataset.a==='hide'){ await fetch('/뉴스/표시',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:it.dataset.k,hide:true})}); it.remove(); return; }
    const cur=$('.memo',it).textContent; const m=prompt('한 줄 메모 (비우면 지움)',cur); if(m===null) return;
    await fetch('/뉴스/표시',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:it.dataset.k,memo:m})}); $('.memo',it).textContent=m; return; }
});
let qt; $('#q').addEventListener('input',e=>{clearTimeout(qt); qt=setTimeout(()=>{F.q=e.target.value.trim(); load();},300);});
load(); setInterval(()=>{ if(D&&D.busy) load(); },4000);
</script></body></html>"""


def page(build=""):
    import portal
    return PAGE.replace("__NAV__", portal.nav("/뉴스", "", build)).replace("__NAVCSS__", portal.NAV_CSS)
