"""차단 엔진: 1초마다 '지금 막아야 하나'를 판단하고 hosts / 프로세스 / 탭을 맞춘다."""
import datetime as dt
import os
import threading
import time

import psutil

from . import browserpolicy, hosts, winutil
from .aiguard import SKIP_EXES, AIGuard
from .focustodo import FocusToDoWatcher
from .store import Store, today_key
from .targets import (BROWSER_SUFFIX, BROWSERS, TARGET_KEYS, TARGETS, all_policy_patterns,
                      domains_for, policy_patterns_for)

DAY_NAMES = "월화수목금토일"


def log(msg):
    """%APPDATA%/DopamineDetox/log.txt — 문제 진단용 (1MB 넘으면 새로 시작)."""
    from .store import DATA_DIR
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "log.txt")
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def schedule_window(sch, now_ts):
    """지금이 이 일정 안이면 (start_ts, end_ts), 아니면 None. 자정 넘김 지원."""
    now = dt.datetime.fromtimestamp(now_ts)
    st, en = _hm(sch["start"]), _hm(sch["end"])
    for back in (0, 1):  # 오늘 시작 / 어제 시작해 자정을 넘긴 일정
        day = (now - dt.timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        if day.weekday() not in sch["days"]:
            continue
        s = day + dt.timedelta(minutes=st)
        e = day + dt.timedelta(minutes=en if en > st else en + 1440)
        if s <= now < e:
            return s.timestamp(), e.timestamp()
    return None


def next_schedule(schedules, now_ts):
    now = dt.datetime.fromtimestamp(now_ts)
    best = None
    for sch in schedules:
        if not sch.get("enabled", True) or not sch["days"]:
            continue
        st = _hm(sch["start"])
        for add in range(0, 8):
            day = (now + dt.timedelta(days=add)).replace(hour=0, minute=0, second=0, microsecond=0)
            if day.weekday() not in sch["days"]:
                continue
            s = day + dt.timedelta(minutes=st)
            if s > now:
                if best is None or s < best[0]:
                    best = (s, sch)
                break
    if not best:
        return None
    s, sch = best
    return {"label": f"{DAY_NAMES[s.weekday()]} {sch['start']}–{sch['end']}", "starts_at": s.timestamp()}


class Engine:
    def __init__(self, notify=None):
        self.store = Store()
        self.notify = notify or (lambda title, msg: None)
        self.ftd = FocusToDoWatcher(on_change=lambda old, new, info: log(
            f"Focus To-Do 상태: {old} → {new}" + (f" ({info})" if info else "")))
        self.ftd.enabled = self.store.settings["focustodo_enabled"]
        self.lock = threading.RLock()
        self.active = False
        self.source = None
        self.ends_at = None
        self.started_at = None
        self.hosts_error = None
        self._applied = None
        self._last_verify = 0
        self._policy_applied = None
        self._policy_verify = 0
        self.policy_error = None
        self.hosts_restored = 0
        self._last_kill = 0
        self._last_close = {}
        self._last_tick = time.time()
        self._stop = threading.Event()
        self.admin = winutil.is_admin()
        self.last_fg = None   # 이 앱이 아닌 마지막 맨 앞 창 (title, exe) — AI 판정용
        self.ai = AIGuard(self, log, self.notify)

    # ------------------------------------------------------------ lifecycle
    def start(self):
        self.ftd.start()
        self.ai.start()
        # 지난번 비정상 종료로 남은 블록 정리 → 첫 tick이 올바른 상태로 다시 씀
        self._sync_hosts(set(), force=True)
        self._sync_policy(set(), force=True)
        threading.Thread(target=self._loop, name="engine", daemon=True).start()

    def shutdown(self):
        self._stop.set()
        self.ftd.stop()
        self.ai.stop()
        try:
            self._sync_hosts(set(), force=True)
            self._sync_policy(set(), force=True)
        finally:
            self.store.save(force=True)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                self.hosts_error = f"엔진 오류: {e}"
            self._stop.wait(1.0)

    # ------------------------------------------------------------ decision
    def _decide(self, now):
        d = self.store.data
        s = self.store.settings
        sess = d.get("session")
        if sess and now < sess["ends_at"]:
            return "manual", sess["started_at"], sess["ends_at"]
        if sess and now >= sess["ends_at"]:
            d["session"] = None
            self.store.touch()
            self.notify("집중 시간 끝", "수고했어요. 차단을 풀었습니다.")
        sup = d.setdefault("suppress", {})
        for sch in d["schedules"]:
            if not sch.get("enabled", True):
                continue
            w = schedule_window(sch, now)
            if w and now >= sup.get("schedule_until", 0):
                return "schedule", w[0], w[1]
        if s["focustodo_enabled"]:
            st = self.ftd.status
            on = st == "focus" or (st == "break" and s["block_during_break"])
            if not on:
                sup["focustodo"] = False
            elif not sup.get("focustodo"):
                return "focustodo", None, None
        return None, None, None

    def tick(self):
        now = time.time()
        with self.lock:
            elapsed = min(5.0, now - self._last_tick)
            self._last_tick = now
            s = self.store.settings
            self.ftd.enabled = s["focustodo_enabled"]
            # 허용 만료
            allows = self.store.data.setdefault("allows", {})
            for k in list(allows):
                if now >= allows[k]["until"]:
                    del allows[k]
                    self.store.touch()
                    if self.active:
                        self.notify(f"{TARGETS[k]['label']} 다시 차단", "허용 시간이 끝났어요.")
            source, started, ends = self._decide(now)
            was = self.active
            self.active = source is not None
            if self.active != was:
                log(f"차단 {'시작' if self.active else '해제'} (source={source}, focustodo={self.ftd.status})")
            if self.active and not was:
                self.started_at = started or now
                self.notify("집중 시작", "딴짓 사이트를 막았습니다.")
            if not self.active:
                self.started_at = None
            elif started:
                self.started_at = started
            self.source, self.ends_at = source, ends
            if self.active:
                self.store.add_focus(elapsed)

            blocked = self._blocked_targets(now)
            want = set()
            if s.get("hosts_block", False):
                for k in blocked:
                    if TARGETS[k]["domains"]:
                        want |= domains_for(k, s["extra_domains"].get(k))
            self._sync_hosts(want)
            pol = set()
            if s.get("browser_policy", True):
                for k in blocked:
                    pol |= policy_patterns_for(k, s["extra_domains"].get(k))
            self._sync_policy(pol)
            if "kakaotalk" in blocked:
                self._kill_processes(TARGETS["kakaotalk"]["processes"], now)
            fg_hwnd, fg_exe, fg_title = winutil.foreground()
            if fg_title and fg_exe not in SKIP_EXES:
                self.last_fg = (fg_title, fg_exe)
            if self.active and s["tab_guard"]:
                self._tab_guard(blocked, now)
            self.store.save()

    def _blocked_targets(self, now):
        if not self.active:
            return set()
        s = self.store.settings
        allows = self.store.data.get("allows", {})
        return {k for k in TARGET_KEYS
                if s["targets_enabled"].get(k, True) and not (k in allows and allows[k]["until"] > now)}

    # ------------------------------------------------------------ actuators
    def _sync_hosts(self, want, force=False):
        now = time.time()
        if not force and want == self._applied:
            # 다른 프로그램(VPN 클라이언트, 제조사 서비스 등)이 hosts를 통째로 다시 써서
            # 블록을 지우는 일이 실제로 있었다 → 3초마다 확인하고 다시 쓴다.
            if now - self._last_verify < 3:
                return
            self._last_verify = now
            if hosts.current_domains() == want:
                return
            self.hosts_restored += 1
            log(f"hosts 블록이 외부에서 바뀜 → 다시 씀 (누적 {self.hosts_restored}회)")
        try:
            changed = hosts.apply(want)
            self._applied = set(want)
            if changed:
                log(f"hosts 갱신: 도메인 {len(want)}개")
            self.hosts_error = None
        except OSError as e:
            self._applied = None if force else self._applied
            msg = ("관리자 권한이 없어 사이트 차단을 못 했습니다."
                   if isinstance(e, PermissionError) else f"hosts 수정 실패: {e}")
            if msg != self.hosts_error:
                log(f"{msg} ({type(e).__name__}: {e})")
            self.hosts_error = msg

    def _policy_managed(self):
        s = self.store.settings
        return all_policy_patterns(s["extra_domains"]) | set(self.store.data.get("policy_applied") or [])

    def _sync_policy(self, want, force=False):
        """브라우저 URLBlocklist 정책 — hosts를 되돌리는 보안 프로그램이 있어도 동작하는 두 번째 차단."""
        now = time.time()
        if not force and want == self._policy_applied:
            if now - self._policy_verify < 5:
                return
            self._policy_verify = now
            try:
                if browserpolicy.current(self._policy_managed()) == want:
                    return
            except OSError:
                return
            log("브라우저 정책이 외부에서 바뀜 → 다시 씀")
        try:
            browserpolicy.apply(want, self._policy_managed() | want)
            if want != self._policy_applied:
                log(f"브라우저 정책 갱신: 패턴 {len(want)}개")
            self._policy_applied = set(want)
            self.store.data["policy_applied"] = sorted(want)
            self.store.touch()
            self.policy_error = None
        except OSError as e:
            msg = f"브라우저 정책 쓰기 실패: {e}"
            if msg != self.policy_error:
                log(msg)
            self.policy_error = msg

    def _kill_processes(self, names, now):
        if now - self._last_kill < 2:
            return
        self._last_kill = now
        killed = 0
        for p in psutil.process_iter(["name"]):
            try:
                if (p.info["name"] or "").lower() in names:
                    p.kill()
                    killed += 1
            except psutil.Error:
                pass
        if killed:
            log(f"프로세스 종료: {names} x{killed}")
            self.store.add_hit()
            self.notify("카카오톡 차단 중", "공부 목적이면 앱에서 '잠깐 열기'를 누르세요.")

    def _tab_guard(self, blocked, now):
        hwnd, exe, title = winutil.foreground()
        if not hwnd or exe not in BROWSERS or not title:
            return
        clean = BROWSER_SUFFIX.sub("", title).strip()
        for k in blocked:
            pat = TARGETS[k]["title"]
            if pat and pat.search(clean):
                if now - self._last_close.get(hwnd, 0) < 1.5:
                    return
                self._last_close[hwnd] = now
                winutil.send_ctrl_w()
                log(f"맨 앞 탭 닫음({TARGETS[k]['label']}): {clean}")
                self.store.add_hit()
                self.notify(f"{TARGETS[k]['label']} 차단", "집중 시간이라 탭을 닫았어요.")
                return

    # ------------------------------------------------------------ state for UI
    def state(self):
        now = time.time()
        with self.lock:
            s = self.store.settings
            allows = self.store.data.get("allows", {})
            blocked = self._blocked_targets(now)
            targets = {}
            for k in TARGET_KEYS:
                a = allows.get(k)
                targets[k] = {
                    "label": TARGETS[k]["label"],
                    "enabled": s["targets_enabled"].get(k, True),
                    "blocked": k in blocked,
                    "allowable": TARGETS[k]["allowable"],
                    "allow_until": a["until"] if a else None,
                    "allow_reason": a["reason"] if a else None,
                }
            day = self.store.day()
            ftd = self.ftd.snapshot()
            return {
                "now": now,
                "active": self.active,
                "source": self.source,
                "started_at": self.started_at,
                "ends_at": self.ends_at,
                "targets": targets,
                "focustodo": {"enabled": s["focustodo_enabled"], "status": ftd["status"], "timer": ftd["timer"]},
                "next_schedule": next_schedule(self.store.schedules(), now),
                "strict": s["strict"],
                "strict_phrase": s["strict_phrase"],
                "stats_today": {
                    "focus_minutes": int(day["focus_seconds"] // 60),
                    "blocked_hits": day["blocked_hits"],
                    "allows": day["allows"],
                },
                "ai": {"enabled": bool(s.get("ai_warning")), "last": self.ai.last,
                       "warnings_today": len(day.get("ai_warnings", []))},
                "allows_left": (max(0, int(s.get("allow_daily_limit", 3)) - len(day["allows"]))
                                if int(s.get("allow_daily_limit", 3) or 0) else None),
                "is_admin": self.admin and not (self.hosts_error or self.policy_error),
                "error": self.hosts_error or self.policy_error,
            }

    # ------------------------------------------------------------ commands
    def start_session(self, minutes):
        now = time.time()
        minutes = max(1, min(600, int(minutes)))
        with self.lock:
            sess = self.store.data.get("session")
            if sess and sess["ends_at"] > now:
                sess["ends_at"] = max(sess["ends_at"], now + minutes * 60)
            else:
                self.store.data["session"] = {"started_at": now, "ends_at": now + minutes * 60}
            self.store.touch()
            self.store.save(force=True)
        self.tick()

    def extend_session(self, minutes):
        now = time.time()
        with self.lock:
            sess = self.store.data.get("session")
            if sess and sess["ends_at"] > now:
                sess["ends_at"] += int(minutes) * 60
            elif self.active and self.ends_at:  # 일정 중 연장 → 일정 끝 이후로 수동 세션
                self.store.data["session"] = {"started_at": now, "ends_at": self.ends_at + int(minutes) * 60}
            else:
                self.store.data["session"] = {"started_at": now, "ends_at": now + int(minutes) * 60}
            self.store.touch()
            self.store.save(force=True)
        self.tick()

    def stop_session(self, phrase=""):
        s = self.store.settings
        if s["strict"] and (phrase or "").strip() != s["strict_phrase"]:
            return {"ok": False, "error": "문장이 정확히 일치해야 멈출 수 있어요."}
        now = time.time()
        with self.lock:
            d = self.store.data
            d["session"] = None
            if self.source == "schedule" and self.ends_at:
                d.setdefault("suppress", {})["schedule_until"] = self.ends_at
            if self.source == "focustodo" or self.ftd.status in ("focus", "break"):
                d.setdefault("suppress", {})["focustodo"] = True
            self.store.touch()
            self.store.save(force=True)
        self.tick()
        return {"ok": True}

    def allow_temporarily(self, target, minutes, reason):
        if target not in TARGETS or not TARGETS[target]["allowable"]:
            return {"ok": False, "error": "이 항목은 잠깐 열기를 지원하지 않아요."}
        reason = (reason or "").strip()
        if len(reason) < 2:
            return {"ok": False, "error": "어떤 공부에 쓰는지 적어주세요."}
        limit = int(self.store.settings.get("allow_daily_limit", 3) or 0)
        if limit and len(self.store.day()["allows"]) >= limit:
            return {"ok": False, "error": f"오늘 잠깐 열기 {limit}회를 모두 썼어요. 내일 다시 쓸 수 있어요."}
        minutes = max(1, min(180, int(minutes)))
        now = time.time()
        with self.lock:
            self.store.data.setdefault("allows", {})[target] = {
                "until": now + minutes * 60, "reason": reason, "minutes": minutes}
            self.store.day()["allows"].append(
                {"target": target, "reason": reason, "minutes": minutes, "at": now})
            self.store.touch()
            self.store.save(force=True)
        self.tick()
        return {"ok": True}

    def revoke_allow(self, target):
        with self.lock:
            self.store.data.setdefault("allows", {}).pop(target, None)
            self.store.touch()
            self.store.save(force=True)
        self.tick()

    def history(self, days=7):
        out = []
        base = dt.date.today()
        for i in range(days - 1, -1, -1):
            key = (base - dt.timedelta(days=i)).isoformat()
            h = self.store.data["history"].get(key, {})
            out.append({"date": key, "focus_minutes": int(h.get("focus_seconds", 0) // 60),
                        "blocked_hits": h.get("blocked_hits", 0)})
        return out
