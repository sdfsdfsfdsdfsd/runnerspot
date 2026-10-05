"""
러너스팟 대회 수집기

1) 마라톤온라인(roadrun.co.kr) 연간 일정에서 대회 목록을 받아온다
2) 기존 data/races.json 과 합친다 (이미 채운 상세 정보는 유지)
3) 다가오는 대회 중 상세 정보가 없는 대회는 공식 홈페이지를 읽어서
   소개·참가비·접수기간·출발시간·시간표·포스터를 Claude API로 정리한다 (ANTHROPIC_API_KEY 있을 때)
4) 장소를 카카오 로컬 API로 좌표 변환한다 (KAKAO_REST_KEY 있을 때)
5) 접수 상태를 날짜로 다시 계산해서 저장한다

GitHub Actions 에서 매주 자동 실행된다. 로컬에서도 `python scripts/collect.py` 로 돌릴 수 있다.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import subprocess
import sys
import time
from difflib import SequenceMatcher
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "races.json"
POSTERS = ROOT / "posters"
KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).date()

UA = "Mozilla/5.0 (compatible; RunnerSpotCollector/1.0)"
ROADRUN = "http://www.roadrun.co.kr/schedule/list.php"

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
KAKAO_KEY = os.environ.get("KAKAO_REST_KEY", "").strip()
MODEL = os.environ.get("ENRICH_MODEL", "claude-haiku-4-5-20251001")
ENRICH_LIMIT = int(os.environ.get("ENRICH_LIMIT", "80"))      # 한 번에 상세 정리할 최대 대회 수
REFRESH_DAYS = int(os.environ.get("REFRESH_DAYS", "21"))      # 이 기간이 지나면 상세 정보를 다시 확인

GROUP = {"서울": "서울", "경기": "경기·인천", "인천": "경기·인천", "강원": "강원",
         "대전": "충청", "세종": "충청", "충북": "충청", "충남": "충청",
         "부산": "경상", "대구": "경상", "울산": "경상", "경북": "경상", "경남": "경상",
         "광주": "전라", "전북": "전라", "전남": "전라", "제주": "제주"}

# 장소·주최 글자로 시도를 추정 (카카오 좌표 변환이 되면 그 결과로 덮어씀)
SIDO_KEYS = [
    ("서울", "서울"), ("여의도", "서울"), ("상암", "서울"), ("광화문", "서울"), ("잠실", "서울"), ("한강", "서울"), ("올림픽공원", "서울"), ("안양천", "서울"),
    ("인천", "인천"), ("영종", "인천"), ("송도", "인천"), ("연수", "인천"),
    ("부산", "부산"), ("해운대", "부산"), ("다대포", "부산"), ("대구", "대구"), ("달서", "대구"), ("울산", "울산"), ("태화강", "울산"),
    ("광주", "광주"), ("대전", "대전"), ("갑천", "대전"), ("세종", "세종"), ("제주", "제주"), ("서귀포", "제주"),
    ("춘천", "강원"), ("강릉", "강원"), ("원주", "강원"), ("홍천", "강원"), ("정선", "강원"), ("인제", "강원"), ("속초", "강원"), ("강원", "강원"),
    ("청주", "충북"), ("충주", "충북"), ("무심천", "충북"), ("제천", "충북"), ("영동", "충북"), ("충북", "충북"),
    ("천안", "충남"), ("아산", "충남"), ("서산", "충남"), ("당진", "충남"), ("홍성", "충남"), ("공주", "충남"), ("부여", "충남"), ("태안", "충남"), ("금산", "충남"), ("충남", "충남"),
    ("전주", "전북"), ("군산", "전북"), ("익산", "전북"), ("김제", "전북"), ("완주", "전북"), ("진안", "전북"), ("무주", "전북"), ("남원", "전북"), ("고창", "전북"), ("정읍", "전북"), ("전북", "전북"),
    ("목포", "전남"), ("여수", "전남"), ("순천", "전남"), ("나주", "전남"), ("고흥", "전남"), ("해남", "전남"), ("화순", "전남"), ("무안", "전남"), ("전남", "전남"),
    ("포항", "경북"), ("경주", "경북"), ("안동", "경북"), ("구미", "경북"), ("문경", "경북"), ("상주", "경북"), ("김천", "경북"), ("영천", "경북"), ("청도", "경북"), ("울릉", "경북"), ("경북", "경북"),
    ("창원", "경남"), ("진주", "경남"), ("김해", "경남"), ("양산", "경남"), ("거제", "경남"), ("사천", "경남"), ("진해", "경남"), ("통영", "경남"), ("경남", "경남"),
    ("수서", "서울"), ("광평교", "서울"), ("대모산", "서울"), ("신정교", "서울"), ("뚝섬", "서울"), ("반포", "서울"), ("청계광장", "서울"),
    ("조선대", "광주"), ("무등산", "광주"), ("담양", "전남"), ("영광", "전남"), ("보성", "전남"), ("완도", "전남"), ("장흥", "전남"), ("광양", "전남"),
    ("청송", "경북"), ("영주", "경북"), ("영덕", "경북"), ("의성", "경북"), ("칠곡", "경북"), ("밀양", "경남"), ("남해", "경남"), ("거창", "경남"), ("하동", "경남"), ("함안", "경남"), ("통영", "경남"),
    ("청양", "충남"), ("보령", "충남"), ("논산", "충남"), ("예산", "충남"), ("증평", "충북"), ("단양", "충북"), ("괴산", "충북"), ("음성", "충북"), ("옥천", "충북"),
    ("동해", "강원"), ("삼척", "강원"), ("평창", "강원"), ("횡성", "강원"), ("철원", "강원"), ("양양", "강원"), ("태백", "강원"),
    ("남한산성", "경기"), ("청계산", "경기"), ("가평", "경기"), ("양평", "경기"), ("이천", "경기"), ("오산", "경기"), ("군포", "경기"), ("부천", "경기"), ("구리", "경기"), ("남양주", "경기"),
    ("수원", "경기"), ("성남", "경기"), ("고양", "경기"), ("일산", "경기"), ("용인", "경기"), ("하남", "경기"), ("미사", "경기"), ("파주", "경기"), ("임진각", "경기"),
    ("광명", "경기"), ("시흥", "경기"), ("안산", "경기"), ("안양", "경기"), ("평택", "경기"), ("화성", "경기"), ("의정부", "경기"), ("양주", "경기"), ("동두천", "경기"),
    ("포천", "경기"), ("과천", "경기"), ("여주", "경기"), ("안성", "경기"), ("탄천", "경기"), ("김포", "경기"), ("경기", "경기"),
]


# ---------------------------------------------------------------- helpers
LOG_LINES: list[str] = []


def log(*a):
    line = " ".join(str(x) for x in a)
    LOG_LINES.append(line)
    print(line, flush=True)


def http(url: str, data: bytes | None = None, headers: dict | None = None, timeout=30) -> bytes:
    h = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def decode(raw: bytes) -> str:
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def clean(fragment: str) -> str:
    fragment = re.sub(r"<(?:br|/p|/div|/li|/tr)\b[^>]*>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(fragment)).strip()


def norm_name(name: str) -> str:
    n = re.sub(r"\(.*?\)|\[.*?\]", "", name)
    n = re.sub(r"20\d\d|제\s*\d+\s*회|대회|마라톤|러닝|run|race|\s|[^\w가-힣]", "", n, flags=re.I)
    return n.lower()


def key_of(r: dict) -> str:
    return r["date"] + "|" + norm_name(r["name"])


def guess_sido(*texts: str) -> str | None:
    t = " ".join(x for x in texts if x)
    for k, v in SIDO_KEYS:
        if k in t:
            return v
    return None


def norm_dist(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if re.fullmatch(r"[\d\s:]+", raw) and raw.count(":") >= 1:      # "37: 20:11" → 37, 20, 11
        raw = raw.replace(":", ",")
    elif re.fullmatch(r"\d+(\.\d+){2,}", raw):                      # "109.50.30.20.15"
        raw = raw.replace(".", ",")
    else:
        raw = re.sub(r"(?<![\d.])\d{1,2}:\d{2}(?![\d])", "", raw)      # 출발 시각 같은 건 빼기
    out = []
    for p in re.split(r"\s*[,/·]\s*", raw):
        p = p.strip(" ()")
        if re.fullmatch(r"\d+(\.\d+)?", p):
            p = p + "km"
        p = p.strip()
        if not p:
            continue
        q = p.lower().replace(" ", "")
        if q in ("풀", "풀코스", "full", "마라톤", "42.195km"):
            out.append("Full")
        elif q in ("하프", "하프코스", "half", "21.0975km", "21.1km"):
            out.append("Half")
        elif q in ("10km", "10k"):
            out.append("10K")
        elif q in ("5km", "5k"):
            out.append("5K")
        else:
            out.append(re.sub(r"(?i)km", "K", p))
    order = {"Full": 0, "Half": 1, "10K": 2, "5K": 3}
    return sorted(dict.fromkeys(out), key=lambda x: order.get(x, 4))


def kind_of(name: str, dists: list[str]) -> str:
    if re.search(r"트레일|trail", name, re.I):
        return "트레일"
    if re.search(r"업힐|계단|걷기대회", name):
        return "기타"
    for d in dists:
        m = re.match(r"([\d.]+)K$", d)
        if m and float(m.group(1)) > 42.3:
            return "울트라"
    return "로드"


# ---------------------------------------------------------------- 1. roadrun
def fetch_roadrun(year: int) -> list[dict]:
    body = urllib.parse.urlencode({"syear_key": str(year), "search": "submit"}).encode("ascii")
    raw = http(ROADRUN, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=60)
    doc = raw.decode("euc-kr", errors="replace")
    log(f"roadrun {year}: 응답 {len(raw):,}바이트, 표 행 {len(re.findall(r'<tr', doc, re.I))}개")
    races, seen = [], set()
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", doc, flags=re.I | re.S):
        # 올해 대회는 날짜 칸에 연도가 없고, 다른 해 대회만 연도가 찍혀 나와요
        other = re.search(r">\s*(20\d\d)\s*<br", row)
        if other and int(other.group(1)) != year:
            continue
        sid = re.search(r"view\.php\?no=(\d+)", row, flags=re.I)
        if not sid or sid.group(1) in seen:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        if len(cells) < 4:
            continue
        dm = re.search(r"(\d{1,2})/(\d{1,2})", clean(cells[0]))
        nm = re.search(rf"<a[^>]+view\.php\?no={sid.group(1)}[^>]*>(.*?)</a>", cells[1], flags=re.I | re.S)
        if not dm or not nm:
            continue
        name = clean(nm.group(1))
        course = re.search(r"<font[^>]+color=[\"']?#990000[\"']?[^>]*>(.*?)</font>", cells[1], flags=re.I | re.S)
        place = clean(cells[2]) or None
        host_txt = clean(cells[3])
        phone = re.search(r"☎\s*([^\s]+(?:\s*/\s*[^\s]+)*)", host_txt)
        host = re.sub(r"\s*☎.*$", "", host_txt).strip() or None
        site = re.search(r"<a\s+href=[\"']([^\"']+)[\"'][^>]*>\s*<img[^>]+src=[\"']?image/home\.gif", cells[3], flags=re.I | re.S)
        dists = norm_dist(clean(course.group(1)) if course else "")
        sido = guess_sido(place or "", host or "", name)
        races.append({
            "id": "rr" + sid.group(1),
            "date": f"{year:04d}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}",
            "name": name,
            "dist": dists,
            "sido": sido or "기타",
            "region": GROUP.get(sido or "", "기타"),
            "place": place,
            "host": host,
            "phone": phone.group(1).strip() if phone else None,
            "site": (html.unescape(site.group(1)).strip() or None) if site else None,
            "status": None,
            "kind": kind_of(name, dists),
        })
        seen.add(sid.group(1))
    return races


# ---------------------------------------------------------------- 2. merge
KEEP = ("enrichedBy", "regStartTime", "regNote", "manager", "memo", "desc", "price", "regStart", "regEnd", "startTime", "schedule", "souvenir", "scale",
        "poster", "address", "lat", "lng", "instagram", "enrichedAt", "geoAt", "status")


def merge(old: list[dict], new: list[dict]) -> list[dict]:
    by_key = {key_of(r): r for r in old}
    by_id = {r["id"]: r for r in old}
    out, used = [], set()
    for r in new:
        prev = by_id.get(r["id"]) or by_key.get(key_of(r))
        if prev:
            used.add(prev["id"])
            for k in KEEP:
                if prev.get(k) not in (None, "", [], {}):
                    r[k] = prev[k]
            if prev.get("sido") not in (None, "기타") and r.get("sido") == "기타":
                r["sido"], r["region"] = prev["sido"], prev["region"]
            if prev["id"] != r["id"] and prev.get("poster"):
                r["poster"] = prev["poster"]
        out.append(r)
    # roadrun 에 없는 기존 대회(다른 출처로 넣은 것)는 아직 안 지났으면 유지
    for r in old:
        if r["id"] not in used and date.fromisoformat(r["date"]) >= TODAY - timedelta(days=60):
            out.append(r)
    out.sort(key=lambda r: (r["date"], r["name"]))
    return out


def similar(a: str, b: str) -> bool:
    x, y = norm_name(a), norm_name(b)
    if not x or not y:
        return False
    return x in y or y in x or SequenceMatcher(None, x, y).ratio() >= 0.6


def dedupe(races: list[dict]) -> list[dict]:
    """같은 날짜에 이름이 비슷한 대회가 여러 출처로 겹치면 마라톤온라인(rr) 쪽을 남긴다"""
    by_date: dict[str, list[dict]] = {}
    for r in races:
        by_date.setdefault(r["date"], []).append(r)
    out = []
    for r in races:
        if not r["id"].startswith("rr"):
            twin = next((x for x in by_date[r["date"]] if x["id"].startswith("rr") and similar(x["name"], r["name"])), None)
            if twin:
                for k in KEEP:
                    if twin.get(k) in (None, "", [], {}) and r.get(k) not in (None, "", [], {}):
                        twin[k] = r[k]
                continue
        out.append(r)
    return out


def fix_regions(races: list[dict]) -> None:
    for r in races:
        if r.get("sido") in (None, "기타"):
            sido = guess_sido(r.get("address") or "", r.get("place") or "", r.get("host") or "", r["name"])
            if sido:
                r["sido"], r["region"] = sido, GROUP[sido]


# ---------------------------------------------------------------- 3. enrich (공식 홈페이지 → Claude)
PROMPT = """아래는 한국 마라톤 대회 "{name}" ({date} 개최)의 공식 홈페이지 내용이야.
이 페이지 글과 함께 첨부한 이미지(포스터·요강)도 읽고, 확인되는 정보만 뽑아서 JSON 하나로만 답해. 페이지에 없는 값은 null. 추측해서 채우지 마.

{{
  "desc": "대회를 2~3문장으로 소개 (러너에게 말하듯 자연스러운 한국어, ~해요체)",
  "price": {{"종목명(예: 풀코스, 하프, 10km, 5km)": 참가비 원 단위 정수}},
  "regStart": "YYYY-MM-DD 접수 시작일",
  "regStartTime": "HH:MM 접수 시작 시각",
  "regEnd": "YYYY-MM-DD 접수 마감일",
  "regNote": "접수 마감 방식 등 짧은 메모 (예: 선착순 마감, 정원 도달 시 조기 마감)",
  "startTime": "HH:MM 첫 출발 시각",
  "schedule": [{{"time": "HH:MM", "text": "당일 일정 내용"}}],
  "souvenir": "기념품 (쉼표로 나열)",
  "organizer": "주최",
  "manager": "주관",
  "memo": "러너가 알아야 할 참고사항 한두 문장 (예: 대체공휴일, 셔틀버스, 주차 불가 등)",
  "scale": 참가 규모 인원 정수,
  "address": "집결지/출발지 도로명 주소 또는 장소명",
  "posterUrl": "대회 포스터로 보이는 이미지의 절대 URL",
  "instagram": "대회 공식 인스타그램 아이디(@ 없이)"
}}

페이지에서 찾은 이미지 후보:
{images}

페이지 본문:
{text}"""


def page_digest(url: str) -> tuple[str, list[str]]:
    raw = http(url, timeout=25)
    doc = decode(raw)
    imgs = []
    og = re.search(r"<meta[^>]+property=[\"']og:image[\"'][^>]+content=[\"']([^\"']+)", doc, re.I)
    if og:
        imgs.append(urllib.parse.urljoin(url, og.group(1)))
    for m in re.finditer(r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>", doc, re.I):
        src = m.group(1)
        if re.search(r"logo|icon|btn|banner_s|blank|spacer|\.gif$", src, re.I):
            continue
        imgs.append(urllib.parse.urljoin(url, src))
    doc = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", doc, flags=re.I | re.S)
    return clean(doc)[:14000], list(dict.fromkeys(imgs))[:25]


def ask_claude(prompt: str, images: list[str] | None = None) -> dict | None:
    def call(imgs):
        content = [{"type": "image", "source": {"type": "url", "url": u}} for u in imgs]
        content.append({"type": "text", "text": prompt})
        body = json.dumps({"model": MODEL, "max_tokens": 1500,
                           "messages": [{"role": "user", "content": content}]}).encode()
        return http("https://api.anthropic.com/v1/messages", data=body, timeout=120, headers={
            "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    imgs = [u for u in (images or []) if re.search(r"\.(jpe?g|png|webp)(\?|$)", u, re.I)][:3]
    try:
        raw = call(imgs)
    except Exception:
        if not imgs:
            raise
        raw = call([])          # 이미지 주소를 못 읽으면 글만으로 다시
    text = "".join(b.get("text", "") for b in json.loads(raw)["content"])
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def save_poster(rid: str, url: str) -> str | None:
    try:
        from PIL import Image
        raw = http(url, timeout=30)
        if len(raw) < 8000:          # 아이콘 같은 작은 이미지는 건너뜀
            return None
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        if im.width < 200 or im.height < 200:
            return None
        im.thumbnail((720, 1080))
        POSTERS.mkdir(exist_ok=True)
        path = POSTERS / f"{rid}.webp"
        im.save(path, "WEBP", quality=78)
        return f"posters/{rid}.webp"
    except Exception as e:
        log("   포스터 저장 실패:", e)
        return None


def valid_date(s) -> str | None:
    try:
        return date.fromisoformat(str(s)).isoformat()
    except Exception:
        return None


DIST_PAT = r"(풀\s*코스|풀|full|하프\s*코스|하프|half|10\s*km|10\s*k|5\s*km|5\s*k)"
DATE_PAT = r"(?:(20\d\d)\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})"


def dist_label(t: str) -> str:
    t = t.lower().replace(" ", "")
    return "풀코스" if t.startswith(("풀", "full")) else "하프" if t.startswith(("하프", "half")) else "10km" if t.startswith("10") else "5km"


def to_date(y, m, d, race_date: str) -> str | None:
    try:
        yy = int(y) if y else int(race_date[:4])
        v = date(yy, int(m), int(d))
        # 연도 없이 쓰인 접수일이 대회일보다 뒤면 전년도
        if not y and v > date.fromisoformat(race_date):
            v = date(yy - 1, int(m), int(d))
        return v.isoformat()
    except Exception:
        return None


def heuristic(r: dict, text: str, imgs: list[str]) -> dict:
    """API 키가 없을 때: 홈페이지 글에서 참가비·접수기간·출발시각을 직접 찾는다"""
    info: dict = {}
    price = {}
    i = text.find("참가비")
    zone = text[i:i + 600] if i >= 0 else text
    for m in re.finditer(DIST_PAT + r"[^0-9가-힣]{0,12}(\d{1,3}(?:,\d{3})+|\d{4,6})\s*원", zone, re.I):
        v = int(m.group(2).replace(",", ""))
        if 5000 <= v <= 300000:
            price.setdefault(dist_label(m.group(1)), v)
    if price:
        info["price"] = price
    j = re.search(r"(접수\s*기간|접수\s*일정|참가\s*접수|신청\s*기간)", text)
    if j:
        seg = text[j.end():j.end() + 120]
        ds = re.findall(DATE_PAT, seg)
        if len(ds) >= 2:
            info["regStart"] = to_date(*ds[0], r["date"])
            info["regEnd"] = to_date(*ds[1], r["date"])
    k = re.search(r"(출발|스타트|start)[^0-9]{0,10}(\d{1,2})\s*[:시]\s*(\d{2})?", text, re.I)
    if k and 5 <= int(k.group(2)) <= 20:
        info["startTime"] = f"{int(k.group(2)):02d}:{k.group(3) or '00'}"
    if imgs:
        info["posterUrl"] = imgs[0]
    return info


def apply_info(r: dict, info: dict) -> None:
    if info.get("desc"):
        r["desc"] = str(info["desc"]).strip()
    price = {str(k): int(v) for k, v in (info.get("price") or {}).items()
             if isinstance(v, (int, float)) and 0 < v < 1_000_000}
    if price:
        r["price"] = price
    for k in ("regStart", "regEnd"):
        if valid_date(info.get(k)):
            r[k] = valid_date(info[k])
    if info.get("startTime") and re.match(r"^\d{1,2}:\d{2}$", str(info["startTime"])):
        r["startTime"] = info["startTime"]
    sch = [x for x in (info.get("schedule") or []) if isinstance(x, dict) and x.get("text")]
    if sch:
        r["schedule"] = [{"time": str(x.get("time") or ""), "text": str(x["text"])} for x in sch[:12]]
    if info.get("regStartTime") and re.match(r"^\d{1,2}:\d{2}$", str(info["regStartTime"])):
        r["regStartTime"] = info["regStartTime"]
    if info.get("organizer") and not r.get("host"):
        r["host"] = str(info["organizer"]).strip()
    for k in ("souvenir", "address", "instagram", "regNote", "manager", "memo"):
        if info.get(k):
            r[k] = str(info[k]).strip().lstrip("@")
    if isinstance(info.get("scale"), (int, float)) and info["scale"] > 0:
        r["scale"] = int(info["scale"])
    if info.get("posterUrl") and not r.get("poster"):
        p = save_poster(r["id"], urllib.parse.urljoin(r["site"], info["posterUrl"]))
        if p:
            r["poster"] = p


def save(races: list[dict]) -> None:
    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps({"updated": TODAY.isoformat(), "count": len(races), "races": races},
                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def publish(msg: str) -> None:
    """GitHub Actions 안에서 돌 때만: 지금까지 모은 걸 바로 저장소에 올려서 사이트에 반영"""
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    try:
        subprocess.run(["git", "add", "data", "posters"], cwd=ROOT, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
            return
        subprocess.run(["git", "commit", "-qm", msg], cwd=ROOT, check=True)
        subprocess.run(["git", "pull", "-q", "--rebase", "-X", "theirs", "origin", "main"], cwd=ROOT)
        subprocess.run(["git", "push", "-q"], cwd=ROOT, check=True)
        log("   중간 저장 완료:", msg)
    except Exception as e:
        log("   중간 저장 실패:", e)


def enrich(races: list[dict]) -> None:
    if not ANTHROPIC_KEY:
        log("ANTHROPIC_API_KEY 없음 → 홈페이지 글에서 직접 찾는 방식으로 진행")
    horizon = TODAY + timedelta(days=200)
    todo = [r for r in races if r.get("site")
            and TODAY <= date.fromisoformat(r["date"]) <= horizon
            and (not r.get("enrichedAt")
                 or date.fromisoformat(r["enrichedAt"]) < TODAY - timedelta(days=REFRESH_DAYS)
                 or (ANTHROPIC_KEY and r.get("enrichedBy") != "claude"))]
    todo.sort(key=lambda r: (bool(r.get("enrichedAt")), r["date"]))
    log(f"상세 정리 대상 {len(todo)}개 중 {min(len(todo), ENRICH_LIMIT)}개 진행")
    done = 0
    for r in todo[:ENRICH_LIMIT]:
        log(" -", r["date"], r["name"])
        try:
            text, imgs = page_digest(r["site"])
            if len(text) < 80:
                r["enrichedAt"] = TODAY.isoformat()
                continue
            if ANTHROPIC_KEY:
                info = ask_claude(PROMPT.format(name=r["name"], date=r["date"], text=text,
                                                images="\n".join(imgs) or "(없음)"), imgs) or {}
            else:
                info = heuristic(r, text, imgs)
        except Exception as e:
            log("   실패:", repr(e)[:120])
            continue
        apply_info(r, info)
        r["enrichedBy"] = "claude" if ANTHROPIC_KEY else "text"
        done += 1
        if done % 25 == 0:
            update_status(races)
            save(races)
            publish(f"대회 상세 정보 {done}개 반영")
        got = [k for k in ("price", "regStart", "startTime", "poster", "desc") if r.get(k)]
        log("   →", ", ".join(got) or "찾은 정보 없음")
        r["enrichedAt"] = TODAY.isoformat()
        time.sleep(1)


# ---------------------------------------------------------------- 4. geocode (카카오)
def kakao(path: str, query: str) -> list:
    url = f"https://dapi.kakao.com/v2/local/search/{path}.json?query={urllib.parse.quote(query)}&size=1"
    return json.loads(http(url, headers={"Authorization": f"KakaoAK {KAKAO_KEY}"}, timeout=15)).get("documents", [])


def geocode(races: list[dict]) -> None:
    if not KAKAO_KEY:
        log("KAKAO_REST_KEY 없음 → 좌표 변환 건너뜀")
        return
    todo = [r for r in races if r.get("lat") is None and not r.get("geoAt")
            and date.fromisoformat(r["date"]) >= TODAY and (r.get("address") or r.get("place"))]
    log(f"좌표 변환 {len(todo)}개")
    for r in todo[:150]:
        r["geoAt"] = TODAY.isoformat()
        queries = [q for q in (r.get("address"), r.get("place"),
                               f'{r["sido"]} {r["place"]}' if r.get("place") else None) if q]
        for q in queries:
            try:
                docs = kakao("address", q) or kakao("keyword", q)
            except Exception as e:
                log("   좌표 실패:", e)
                docs = []
            if docs:
                d = docs[0]
                r["lat"], r["lng"] = round(float(d["y"]), 6), round(float(d["x"]), 6)
                addr = d.get("road_address_name") or d.get("address_name") or ""
                if addr and not r.get("address"):
                    r["address"] = addr
                sido = guess_sido(addr.split(" ")[0] if addr else "")
                if sido and r.get("sido") in (None, "기타"):
                    r["sido"], r["region"] = sido, GROUP[sido]
                break
        time.sleep(0.2)


# ---------------------------------------------------------------- 5. status
def update_status(races: list[dict]) -> None:
    for r in races:
        s, e = r.get("regStart"), r.get("regEnd")
        if e and date.fromisoformat(e) < TODAY:
            r["status"] = "closed"
        elif s and date.fromisoformat(s) > TODAY:
            r["status"] = "soon"
        elif s and (not e or date.fromisoformat(e) >= TODAY):
            r["status"] = "open"


# ---------------------------------------------------------------- main
def main() -> None:
    old = json.loads(DATA.read_text(encoding="utf-8"))["races"] if DATA.exists() else []
    new = []
    for y in (TODAY.year, TODAY.year + 1):
        try:
            got = fetch_roadrun(y)
            log(f"roadrun {y}: {len(got)}개")
            new += got
        except Exception as e:
            log(f"roadrun {y} 수집 실패:", repr(e))
    if not new and not old:
        sys.exit("수집된 대회가 없어요")
    races = merge(old, new) if new else old
    # 너무 오래 지난 대회는 정리 (1년)
    races = [r for r in races if date.fromisoformat(r["date"]) >= TODAY - timedelta(days=365)]
    races = dedupe(races)
    fix_regions(races)
    update_status(races)
    save(races)
    publish("대회 목록 업데이트")
    enrich(races)
    geocode(races)
    update_status(races)
    save(races)
    log(f"저장 완료: {len(races)}개 대회")
    (ROOT / "data" / "last_run.log").write_text(
        f"{datetime.now(KST):%Y-%m-%d %H:%M} 실행\n" + "\n".join(LOG_LINES) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
