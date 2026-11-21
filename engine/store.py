"""설정·일정·세션·기록을 %APPDATA%\\DopamineDetox\\data.json 에 저장."""
import copy
import json
import os
import threading
import time
import uuid

from .levels import DEFAULT_ALLOWED_APPS
from .targets import TARGET_KEYS

DATA_DIR = os.environ.get("DD_DATA_DIR") or os.path.join(os.environ.get("APPDATA", "."), "DopamineDetox")
DATA_FILE = os.path.join(DATA_DIR, "data.json")

DEFAULT_SETTINGS = {
    "targets_enabled": {k: True for k in TARGET_KEYS},
    "extra_domains": {"instagram": [], "youtube": [], "webtoon": []},
    "strict": True,
    "strict_phrase": "나는 지금 집중을 포기합니다",
    "block_during_break": False,
    "autostart": False,
    "focustodo_enabled": True,
    "tab_guard": True,
    "browser_policy": True,
    "hosts_block": False,   # AhnLab Safe Transaction 등이 hosts를 복원하며 경고를 띄워 기본 끔
    "allow_default_minutes": 15,
    "allow_daily_limit": 3,      # YouTube·카카오톡 잠깐 열기 합산, 0이면 제한 없음 (사용자 결정 2026-11-18)
    "ai_warning": False,         # AI 업무 관련성 경고 (Claude CLI haiku, 기본 끔 — 창 제목이 외부로 전송됨)
    "ai_interval_min": 5,
    "work_description": "",
    "last_level": 1,             # v2: 홈에서 기본으로 고른 집중 단계
    "focustodo_level": 1,        # v2: 포모도로가 시작될 때 쓸 단계
    "allowed_sites": [],         # v2: 3단계 허용 사이트 (Claude는 항상 허용)
    "allowed_apps": list(DEFAULT_ALLOWED_APPS),  # v2: 3·4단계 허용 앱
}

DEFAULT = {
    "settings": DEFAULT_SETTINGS,
    "schedules": [],
    "session": None,             # {"started_at", "ends_at"}
    "allows": {},                # target -> {"until", "reason", "minutes"}
    "suppress": {},              # {"schedule_until": epoch, "focustodo": bool}
    "history": {},               # "YYYY-MM-DD" -> {"focus_seconds", "blocked_hits", "allows": [...]}
}


def today_key(ts=None):
    return time.strftime("%Y-%m-%d", time.localtime(ts or time.time()))


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULT)
        self._dirty = False
        self._last_save = 0
        self.load()

    def load(self):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError):
            return
        with self.lock:
            for k, v in loaded.items():
                self.data[k] = v
            s = copy.deepcopy(DEFAULT_SETTINGS)
            s.update(self.data.get("settings") or {})
            for sub in ("targets_enabled", "extra_domains"):
                merged = copy.deepcopy(DEFAULT_SETTINGS[sub])
                merged.update((self.data.get("settings") or {}).get(sub) or {})
                s[sub] = merged
            self.data["settings"] = s

    def save(self, force=False):
        with self.lock:
            if not force and not self._dirty:
                return
            if not force and time.time() - self._last_save < 10:
                return
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = DATA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, DATA_FILE)
            self._dirty = False
            self._last_save = time.time()

    def touch(self):
        self._dirty = True

    # ---- settings ----
    @property
    def settings(self):
        return self.data["settings"]

    def set_settings(self, new):
        with self.lock:
            s = copy.deepcopy(DEFAULT_SETTINGS)
            s.update(self.data["settings"])
            for k, v in (new or {}).items():
                if k in s:
                    s[k] = v
            for k in TARGET_KEYS:
                s["targets_enabled"][k] = bool(s["targets_enabled"].get(k, True))
            for k in list(s["extra_domains"].keys()):
                v = s["extra_domains"][k]
                if isinstance(v, str):
                    v = v.splitlines()
                s["extra_domains"][k] = [x.strip() for x in v if x and x.strip()]
            try:
                s["allow_default_minutes"] = max(1, min(180, int(s["allow_default_minutes"])))
            except (TypeError, ValueError):
                s["allow_default_minutes"] = 15
            s["strict_phrase"] = (s.get("strict_phrase") or DEFAULT_SETTINGS["strict_phrase"]).strip()
            self.data["settings"] = s
            self.touch()
            self.save(force=True)

    # ---- schedules ----
    def schedules(self):
        return self.data["schedules"]

    def add_schedule(self, days, start, end, level=1):
        with self.lock:
            days = sorted({int(d) for d in days if 0 <= int(d) <= 6})
            self.data["schedules"].append({
                "id": uuid.uuid4().hex[:8], "days": days, "start": start, "end": end, "enabled": True,
                "level": int(level) if str(level).isdigit() and 1 <= int(level) <= 4 else 1,
            })
            self.touch()
            self.save(force=True)

    def remove_schedule(self, sid):
        with self.lock:
            self.data["schedules"] = [s for s in self.data["schedules"] if s["id"] != sid]
            self.touch()
            self.save(force=True)

    def toggle_schedule(self, sid, enabled):
        with self.lock:
            for s in self.data["schedules"]:
                if s["id"] == sid:
                    s["enabled"] = bool(enabled)
            self.touch()
            self.save(force=True)

    # ---- history ----
    def day(self, key=None):
        key = key or today_key()
        h = self.data["history"].setdefault(key, {"focus_seconds": 0, "blocked_hits": 0, "allows": []})
        return h

    def add_focus(self, seconds):
        with self.lock:
            self.day()["focus_seconds"] += seconds
            self.touch()

    def add_hit(self, n=1):
        with self.lock:
            self.day()["blocked_hits"] += n
            self.touch()
