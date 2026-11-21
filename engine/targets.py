"""Block targets: domains, title patterns, processes."""
import re

TARGETS = {
    "instagram": {
        "label": "Instagram",
        "allowable": False,
        "domains": [
            "instagram.com", "www.instagram.com", "i.instagram.com", "l.instagram.com",
            "graph.instagram.com", "api.instagram.com", "help.instagram.com",
            "static.cdninstagram.com", "scontent.cdninstagram.com", "instagr.am",
        ],
        "title": re.compile(r"instagram|instagr\.am", re.I),
        "processes": [],
    },
    "youtube": {
        "label": "YouTube",
        "allowable": True,
        "domains": [
            "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
            "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
            "youtubei.googleapis.com", "youtube.googleapis.com", "i.ytimg.com", "s.ytimg.com",
            "yt3.ggpht.com", "studio.youtube.com", "shorts.youtube.com",
        ],
        # "영상 제목 - YouTube", "YouTube", 연결 실패 페이지 "www.youtube.com"
        "title": re.compile(r"(-\s*youtube(\s+music)?$)|(^\(\d+\)\s*youtube$)|(^youtube(\s+music)?$)|youtube\.com|youtu\.be", re.I),
        "processes": [],
    },
    "kakaotalk": {
        "label": "카카오톡",
        "allowable": True,
        "domains": [],
        "title": None,
        "processes": ["kakaotalk.exe"],
    },
    "webtoon": {
        "label": "웹툰",
        "allowable": False,
        "domains": [
            "comic.naver.com", "m.comic.naver.com", "webtoon.naver.com",
            "webtoon.kakao.com", "page.kakao.com", "m.page.kakao.com",
            "webtoons.com", "www.webtoons.com", "m.webtoons.com",
            "lezhin.com", "www.lezhin.com", "bomtoon.com", "www.bomtoon.com",
            "toomics.com", "www.toomics.com", "toptoon.com", "www.toptoon.com",
            "series.naver.com", "m.series.naver.com",
        ],
        "title": re.compile(
            r"네이버\s*웹툰|naver\s*webtoon|카카오\s*웹툰|kakao\s*webtoon|카카오페이지|"
            r"webtoons\.com|comic\.naver\.com|webtoon\.kakao\.com|page\.kakao\.com|"
            r"레진코믹스|lezhin|봄툰|bomtoon|투믹스|toomics|탑툰|toptoon|네이버\s*시리즈",
            re.I,
        ),
        "processes": [],
    },
}

TARGET_KEYS = list(TARGETS.keys())

BROWSERS = {
    "whale.exe", "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
    "opera.exe", "vivaldi.exe", "iexplore.exe",
}

# 브라우저가 창 제목 끝에 붙이는 이름 제거용
BROWSER_SUFFIX = re.compile(
    r"\s*[-—–]\s*(naver whale|whale|google chrome|chrome|microsoft​? edge|microsoft edge|"
    r"mozilla firefox|firefox|brave|opera|vivaldi)\s*$",
    re.I,
)


def domains_for(key, extra=None):
    out = set(TARGETS[key]["domains"])
    for d in extra or []:
        d = d.strip().lower()
        d = re.sub(r"^https?://", "", d).split("/")[0]
        if not d or not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", d):
            continue
        out.add(d)
        if not d.startswith("www."):
            out.add("www." + d)
    return out


def policy_patterns_for(key, extra=None):
    """브라우저 URLBlocklist용: 상위 도메인이 이미 있으면 하위 도메인은 뺀다 ('instagram.com'이 www.까지 막음)."""
    doms = domains_for(key, extra)
    return {d for d in doms if not any(d != p and d.endswith("." + p) for p in doms)}


def all_policy_patterns(extra_map):
    out = set()
    for k in TARGET_KEYS:
        out |= policy_patterns_for(k, (extra_map or {}).get(k))
    return out
