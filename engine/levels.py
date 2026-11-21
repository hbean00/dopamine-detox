"""v2 집중 강도 — 서로 배타적인 4단계 사다리.

단계 하나 = 규칙 묶음 하나. 높은 단계는 낮은 단계가 막는 것을 전부 포함해 더 막는다.
사용자가 고칠 수 있는 목록은 의미 있는 단계에서만 쓰인다:
  잠깐 열기 → 1단계만 / 허용 사이트 → 3단계만 / 허용 앱 → 3·4단계만 / AI 경고 → 1·2단계만
"""
import re

from .targets import TARGETS, domains_for

CLAUDE_SITES = ["claude.ai", "claude.com", "anthropic.com"]

# 2단계에서 추가로 막는 묶음 (도메인 → 브라우저 정책, 제목 패턴 → 실행 중인 브라우저 탭 닫기)
PRESETS = {
    "sns": {
        "label": "SNS",
        "domains": ["facebook.com", "x.com", "twitter.com", "tiktok.com", "threads.net", "threads.com",
                    "band.us", "pinterest.com", "reddit.com"],
        "title": r"facebook|페이스북|twitter|트위터|(^|\s)/?\s?x$|tiktok|틱톡|threads|스레드|reddit|pinterest",
    },
    "news": {
        "label": "뉴스",
        "domains": ["news.naver.com", "n.news.naver.com", "news.daum.net", "v.daum.net", "news.nate.com",
                    "yna.co.kr", "chosun.com", "joongang.co.kr", "donga.com", "hani.co.kr", "khan.co.kr",
                    "mk.co.kr", "hankyung.com", "sbs.co.kr", "imbc.com", "kbs.co.kr", "ytn.co.kr"],
        "title": r"네이버\s*뉴스|다음\s*뉴스|네이트\s*뉴스|연합뉴스|조선일보|중앙일보|동아일보|한겨레|경향신문|매일경제|한국경제",
    },
    "shopping": {
        "label": "쇼핑",
        "domains": ["coupang.com", "11st.co.kr", "gmarket.co.kr", "auction.co.kr", "musinsa.com", "ssg.com",
                    "29cm.co.kr", "a-bly.com", "zigzag.kr", "shopping.naver.com", "aliexpress.com",
                    "temu.com", "kream.co.kr", "ohou.se"],
        "title": r"쿠팡|coupang|11번가|g마켓|gmarket|옥션|무신사|musinsa|ssg|29cm|에이블리|지그재그|알리익스프레스|aliexpress|테무|temu|kream|오늘의집",
    },
    "ott": {
        "label": "OTT·방송",
        "domains": ["netflix.com", "tving.com", "wavve.com", "coupangplay.com", "disneyplus.com", "watcha.com",
                    "laftel.net", "chzzk.naver.com", "sooplive.co.kr", "afreecatv.com", "twitch.tv"],
        "title": r"netflix|넷플릭스|tving|티빙|wavve|웨이브|쿠팡플레이|disney\+|디즈니\+|왓챠|watcha|라프텔|치지직|chzzk|soop|아프리카tv|twitch",
    },
    "community": {
        "label": "커뮤니티",
        "domains": ["dcinside.com", "fmkorea.com", "theqoo.net", "instiz.net", "ruliweb.com", "clien.net",
                    "ppomppu.co.kr", "pann.nate.com", "bobaedream.co.kr", "mlbpark.donga.com", "todayhumor.co.kr",
                    "inven.co.kr", "arca.live"],
        "title": r"디시인사이드|dcinside|에펨코리아|fmkorea|더쿠|theqoo|인스티즈|루리웹|클리앙|뽐뿌|네이트\s*판|보배드림|mlbpark|오늘의유머|인벤|아카라이브",
    },
}
for _p in PRESETS.values():
    _p["title_re"] = re.compile(_p["title"], re.I)

LEVEL1_APPS = ["kakaotalk.exe"]
MESSENGER_APPS = ["kakaotalk.exe", "discord.exe", "telegram.exe", "line.exe", "whatsapp.exe"]
CLAUDE_APPS = ["claude.exe"]

# 허용 앱 모드에서도 항상 살려 두는 것 (시스템·이 앱·연동 대상·브라우저)
ESSENTIAL_APPS = {
    "explorer.exe", "dopaminedetox.exe", "dopaminedetox_test.exe", "python.exe", "pythonw.exe",
    "focustodo.exe", "msedgewebview2.exe", "applicationframehost.exe", "shellexperiencehost.exe",
    "startmenuexperiencehost.exe", "searchhost.exe", "searchapp.exe", "textinputhost.exe", "lockapp.exe",
    "systemsettings.exe", "taskmgr.exe", "ctfmon.exe", "rundll32.exe", "dwm.exe", "consent.exe",
    "whale.exe", "chrome.exe", "msedge.exe", "firefox.exe",
}

DEFAULT_ALLOWED_APPS = [
    # VS Code
    "code.exe",
    # Word·한글·PDF
    "winword.exe", "hwp.exe", "hword.exe", "acrord32.exe", "acrobat.exe", "sumatrapdf.exe", "foxitpdfreader.exe",
    # Notion·Obsidian
    "notion.exe", "obsidian.exe",
    # 터미널
    "windowsterminal.exe", "openconsole.exe", "wt.exe", "powershell.exe", "pwsh.exe", "cmd.exe",
    "conhost.exe", "mintty.exe",
]

LEVELS = {
    1: {"name": "가벼운 집중", "short": "딴짓 사이트만 막기",
        "rules": ["Instagram·YouTube·웹툰 차단", "카카오톡 종료", "YouTube·카카오톡 공부용 잠깐 열기 가능"]},
    2: {"name": "깊은 집중", "short": "SNS·뉴스·쇼핑까지 막기",
        "rules": ["1단계 차단 전부", "SNS·뉴스·쇼핑·OTT·커뮤니티 차단", "메신저 종료", "예외(잠깐 열기) 없음"]},
    3: {"name": "Claude만", "short": "Claude와 허용 사이트·앱만",
        "rules": ["웹은 Claude와 허용 사이트만", "허용 앱 밖의 창은 닫음", "예외 없음"]},
    4: {"name": "오프라인", "short": "웹·Claude 모두 끄기",
        "rules": ["모든 웹사이트 차단", "Claude 웹·앱 차단", "허용 앱 밖의 창은 닫음", "예외 없음"]},
}


def level_list():
    return [{"id": i, **LEVELS[i]} for i in sorted(LEVELS)]


def clamp_level(v, default=1):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return v if v in LEVELS else default


def base_block_domains(extra_map):
    """1단계 차단 도메인 (Instagram·YouTube·웹툰 + 사용자 추가)."""
    out = set()
    for k, t in TARGETS.items():
        if t["domains"]:
            out |= domains_for(k, (extra_map or {}).get(k))
    return out


def preset_domains():
    out = set()
    for p in PRESETS.values():
        out |= set(p["domains"])
    return out


def _covers(blocked, domain):
    """blocked 집합의 어떤 도메인이 domain과 같거나 그 상위/하위 도메인이면 True."""
    d = domain.lower()
    for b in blocked:
        if d == b or d.endswith("." + b) or b.endswith("." + d):
            return True
    return False


def normalize_domain(s):
    s = (s or "").strip().lower()
    s = re.sub(r"^https?://", "", s).split("/")[0]
    if s.startswith("www."):
        s = s[4:]
    return s if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", s) else None


def validate_allowed_sites(sites, extra_map):
    """3단계 허용 사이트 — 1·2단계 차단 대상은 넣을 수 없다(배타성). (정리된 목록, 오류 문구|None)"""
    blocked = base_block_domains(extra_map) | preset_domains()
    clean, bad = [], []
    for s in sites or []:
        d = normalize_domain(s)
        if not d or d in CLAUDE_SITES or d in clean:
            continue
        if _covers(blocked, d):
            bad.append(d)
        else:
            clean.append(d)
    if bad:
        return clean, f"{', '.join(bad[:3])}은(는) 1·2단계 차단 대상이라 허용 사이트에 넣을 수 없어요."
    return clean, None


def normalize_apps(apps):
    out = []
    for a in apps or []:
        a = (a or "").strip().lower().split("\\")[-1]
        if not a:
            continue
        if not a.endswith(".exe"):
            a += ".exe"
        if a not in out:
            out.append(a)
    return out


def plan(level, settings):
    """단계 → 실제로 적용할 규칙.
    반환: {block: set[str], allow: set[str], kill: set[exe], allowlist_apps: set[exe]|None,
           title_res: [regex], temp_allow: bool, ai: bool, needs_restart: bool}"""
    extra = settings.get("extra_domains") or {}
    enabled = settings.get("targets_enabled") or {}
    p = {"block": set(), "allow": set(), "kill": set(), "allowlist_apps": None,
         "title_res": [], "temp_allow": False, "ai": False, "needs_restart": False}
    if level is None:
        return p
    if level in (1, 2):
        for k, t in TARGETS.items():
            if not enabled.get(k, True) and level == 1:
                continue  # 1단계에서만 대상별 끄기 허용 (2단계 이상은 전부 차단)
            if t["domains"]:
                p["block"] |= domains_for(k, extra.get(k))
            if t["title"]:
                p["title_res"].append((k, t["title"]))
        p["kill"] |= set(LEVEL1_APPS) if (level == 2 or enabled.get("kakaotalk", True)) else set()
        p["temp_allow"] = level == 1
        p["ai"] = True
    if level == 2:
        p["block"] |= preset_domains()
        p["title_res"] += [(name, pr["title_re"]) for name, pr in PRESETS.items()]
        p["kill"] |= set(MESSENGER_APPS)
    if level == 3:
        p["block"] = {"*"}
        sites, _ = validate_allowed_sites(settings.get("allowed_sites"), extra)
        p["allow"] = set(CLAUDE_SITES) | set(sites)
        p["allowlist_apps"] = ESSENTIAL_APPS | set(normalize_apps(settings.get("allowed_apps"))) | set(CLAUDE_APPS)
        p["needs_restart"] = True
    if level == 4:
        p["block"] = {"*"}
        apps = set(normalize_apps(settings.get("allowed_apps"))) - set(CLAUDE_APPS)
        p["allowlist_apps"] = ESSENTIAL_APPS | apps
        p["kill"] |= set(CLAUDE_APPS)
        p["needs_restart"] = True
    return p


def rules_now(level, settings):
    if level is None:
        return []
    r = list(LEVELS[level]["rules"])
    if level == 3:
        sites, _ = validate_allowed_sites(settings.get("allowed_sites"), settings.get("extra_domains"))
        r[0] = f"웹은 Claude와 허용 사이트 {len(sites)}곳만" if sites else "웹은 Claude만"
    if level in (3, 4):
        n = len(normalize_apps(settings.get("allowed_apps")))
        r = [x if "허용 앱" not in x else f"허용 앱 {n}개 밖의 창은 닫음" for x in r]
    return r
