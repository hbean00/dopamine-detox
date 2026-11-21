"""차단 엔진: 1초마다 '지금 막아야 하나'를 판단하고 hosts / 프로세스 / 탭을 맞춘다."""
import datetime as dt
import os
import threading
import time

import psutil

from . import browserctl, browserpolicy, hosts, levels, winutil
from .appguard import AppGuard
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
        self.level = None     # v2: 지금 적용 중인 집중 단계 (1~4)
        self.plan = levels.plan(None, self.store.settings)
        self._restart_level = None   # 웨일을 마지막으로 재시작했을 때 적용한 3·4단계
        self._last_app_enforce = 0
        self.appguard = AppGuard(on_close=self._on_app_closed)
        self.ai = AIGuard(self, log, self.notify)

    # ------------------------------------------------------------ lifecycle
    def start(self):
        self.ftd.start()
        self.ai.start()
        # 지난번 비정상 종료로 남은 블록 정리 → 첫 tick이 올바른 상태로 다시 씀
        left_strict = "*" in (self.store.data.get("policy_applied") or [])
        self._sync_hosts(set(), force=True)
        self._sync_policy(set(), set(), force=True)
        if left_strict:  # 지난번에 3·4단계 정책이 남은 채 꺼졌다 → 실행 중인 웨일이 계속 막혀 있으니 재시작
            self._restart_whale_async("지난 실행에서 남은 3·4단계 차단 정리")
        threading.Thread(target=self._loop, name="engine", daemon=True).start()

    def shutdown(self):
        self._stop.set()
        self.ftd.stop()
        self.ai.stop()
        try:
            self._sync_hosts(set(), force=True)
            self._sync_policy(set(), set(), force=True)
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
        """(source, started, ends, level) — 겹치면 가장 엄격한 단계가 이긴다."""
        d = self.store.data
        s = self.store.settings
        cands = []
        sess = d.get("session")
        if sess and now < sess["ends_at"]:
            cands.append(("manual", sess["started_at"], sess["ends_at"], levels.clamp_level(sess.get("level"), 1)))
        elif sess and now >= sess["ends_at"]:
            d["session"] = None
            self.store.touch()
            self.notify("집중 시간 끝", "수고했어요. 차단을 풀었습니다.")
        sup = d.setdefault("suppress", {})
        for sch in d["schedules"]:
            if not sch.get("enabled", True):
                continue
            w = schedule_window(sch, now)
            if w and now >= sup.get("schedule_until", 0):
                cands.append(("schedule", w[0], w[1], levels.clamp_level(sch.get("level"), 1)))
                break
        if s["focustodo_enabled"]:
            st = self.ftd.status
            on = st == "focus" or (st == "break" and s["block_during_break"])
            if not on:
                sup["focustodo"] = False
            elif not sup.get("focustodo"):
                cands.append(("focustodo", None, None, levels.clamp_level(s.get("focustodo_level"), 1)))
        if not cands:
            return None, None, None, None
        order = {"manual": 0, "schedule": 1, "focustodo": 2}
        return max(cands, key=lambda c: (c[3], -order[c[0]]))

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
            source, started, ends, level = self._decide(now)
            was, was_level = self.active, self.level
            self.active = source is not None
            self.level = level if self.active else None
            if self.active != was or self.level != was_level:
                self._last_app_enforce = 0  # 단계가 바뀌면 허용 앱 검사를 바로 다시
                name = levels.LEVELS[self.level]["name"] if self.level else "-"
                what = "시작" if (self.active and not was) else ("해제" if not self.active else "단계 변경")
                log(f"차단 {what} (source={source}, level={self.level} {name}, focustodo={self.ftd.status})")
            if self.active and not was:
                self.started_at = started or now
                self.notify("집중 시작", levels.LEVELS[self.level]["name"] + " — 딴짓을 막았습니다.")
            if not self.active:
                self.started_at = None
                self.appguard.reset()
            elif started:
                self.started_at = started
            self.source, self.ends_at = source, ends
            if self.active:
                self.store.add_focus(elapsed)

            p = levels.plan(self.level, s)
            # 1단계 '잠깐 열기' 중인 대상은 이번만 빼 준다
            if p["temp_allow"]:
                for k in list(allows):
                    if allows[k]["until"] > now:
                        p["block"] -= domains_for(k, s["extra_domains"].get(k))
                        p["title_res"] = [(kk, rr) for kk, rr in p["title_res"] if kk != k]
                        p["kill"] -= set(TARGETS[k]["processes"])
            self.plan = p

            want = set()
            if s.get("hosts_block", False) and "*" not in p["block"]:
                want = set(p["block"])
            self._sync_hosts(want)
            if s.get("browser_policy", True):
                self._sync_policy(_minimize(p["block"]), set(p["allow"]))
            else:
                self._sync_policy(set(), set())
            # 실행 중인 웨일은 정책 변경을 바로 반영하지 않는다(실측) → 3·4단계에 들어갈 때·바꿀 때·나올 때 재시작
            target = self.level if p["needs_restart"] else None
            if target != self._restart_level:
                why = (levels.LEVELS[self.level]["name"] + " 정책 적용") if target else "3·4단계 차단 해제"
                self._restart_whale_async(why)
                self._restart_level = target
            if p["kill"]:
                self._kill_processes(p["kill"], now)
            if p["allowlist_apps"] is not None and now - self._last_app_enforce >= 2:
                self._last_app_enforce = now
                self.appguard.enforce(p["allowlist_apps"], now)
            fg_hwnd, fg_exe, fg_title = winutil.foreground()
            if fg_title and fg_exe not in SKIP_EXES:
                self.last_fg = (fg_title, fg_exe)
            if self.active and s["tab_guard"] and p["title_res"]:
                self._tab_guard(p["title_res"], now)
            self.store.save()

    def _blocked_targets(self, now):
        if not self.active:
            return set()
        if self.level and self.level >= 2:
            return set(TARGET_KEYS)  # 2단계 이상은 예외 없이 전부
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
        block = (all_policy_patterns(s["extra_domains"]) | levels.preset_domains() | {"*"}
                 | set(self.store.data.get("policy_applied") or []))
        allow = (set(levels.CLAUDE_SITES) | {levels.normalize_domain(x) or "" for x in s.get("allowed_sites") or []}
                 | set(self.store.data.get("policy_allow_applied") or [])) - {""}
        return block, allow

    def _sync_policy(self, want, want_allow=frozenset(), force=False):
        """브라우저 정책: URLBlocklist(+3단계 URLAllowlist). 원래 있던 항목은 건드리지 않는다."""
        now = time.time()
        key = (frozenset(want), frozenset(want_allow))
        mb, ma = self._policy_managed()
        if not force and key == self._policy_applied:
            if now - self._policy_verify < 5:
                return
            self._policy_verify = now
            try:
                if (browserpolicy.current(mb) == set(want)
                        and browserpolicy.current(ma, browserpolicy.ALLOW) == set(want_allow)):
                    return
            except OSError:
                return
            log("브라우저 정책이 외부에서 바뀜 → 다시 씀")
        try:
            browserpolicy.apply(want, mb | set(want), want_allow, ma | set(want_allow))
            if key != self._policy_applied:
                log(f"브라우저 정책 갱신: 차단 {len(want)}개" + (f", 허용 {len(want_allow)}개" if want_allow else ""))
            self._policy_applied = key
            self.store.data["policy_applied"] = sorted(want)
            self.store.data["policy_allow_applied"] = sorted(want_allow)
            self.store.touch()
            self.policy_error = None
        except OSError as e:
            msg = f"브라우저 정책 쓰기 실패: {e}"
            if msg != self.policy_error:
                log(msg)
            self.policy_error = msg

    def _restart_whale_async(self, why):
        def run():
            try:
                if not browserctl.is_running():
                    return
                r = browserctl.restart_whale()
                log(f"웨일 재시작({why}): {r}")
                self.notify("웨일을 다시 열었어요", why + " — 탭은 복원됩니다.")
            except Exception as e:
                log(f"웨일 재시작 실패: {e}")
        threading.Thread(target=run, name="whale-restart", daemon=True).start()

    def _on_app_closed(self, exe, title):
        self.store.add_hit()
        log(f"허용 앱 밖이라 닫음: {exe} — {title[:60]}")
        self.notify("허용 앱만 쓸 수 있어요", exe + " 창을 닫았어요.")

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
            msg = ("공부 목적이면 앱에서 '잠깐 열기'를 누르세요." if self.plan.get("temp_allow")
                   else "이 단계에서는 쓸 수 없어요.")
            self.notify("메신저 차단 중", msg)

    def _tab_guard(self, title_res, now):
        hwnd, exe, title = winutil.foreground()
        if not hwnd or exe not in BROWSERS or not title:
            return
        clean = BROWSER_SUFFIX.sub("", title).strip()
        for k, pat in title_res:
            if pat.search(clean):
                if now - self._last_close.get(hwnd, 0) < 1.5:
                    return
                self._last_close[hwnd] = now
                winutil.send_ctrl_w()
                label = TARGETS[k]["label"] if k in TARGETS else levels.PRESETS[k]["label"]
                log(f"맨 앞 탭 닫음({label}): {clean}")
                self.store.add_hit()
                self.notify(f"{label} 차단", "집중 시간이라 탭을 닫았어요.")
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
                    "allowable": TARGETS[k]["allowable"] and self.level in (None, 1),
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
                "level": self.level,
                "level_name": levels.LEVELS[self.level]["name"] if self.level else None,
                "levels": levels.level_list(),
                "rules_now": levels.rules_now(self.level, s),
                "whale_running": browserctl.is_running(),
                "is_admin": self.admin and not (self.hosts_error or self.policy_error),
                "error": self.hosts_error or self.policy_error,
            }

    # ------------------------------------------------------------ commands
    def start_session(self, minutes, level=None):
        now = time.time()
        minutes = max(1, min(600, int(minutes)))
        s = self.store.settings
        level = levels.clamp_level(level if level is not None else s.get("last_level", 1), 1)
        with self.lock:
            sess = self.store.data.get("session")
            if self.active and self.level and level < self.level and s["strict"]:
                return {"ok": False, "error": f"엄격 모드: 집중 중에는 더 약한 단계로 바꿀 수 없어요 (지금 {self.level}단계)."}
            if sess and sess["ends_at"] > now:
                sess["ends_at"] = max(sess["ends_at"], now + minutes * 60)
                sess["level"] = level
            else:
                self.store.data["session"] = {"started_at": now, "ends_at": now + minutes * 60, "level": level}
            s["last_level"] = level
            self.store.touch()
            self.store.save(force=True)
        self.tick()
        return {"ok": True}

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
        if self.active and self.level and self.level != 1:
            return {"ok": False, "error": levels.LEVELS[self.level]["name"] + " 단계에는 잠깐 열기가 없어요."}
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


def _minimize(domains):
    """정책용: 상위 도메인이 있으면 하위 도메인은 뺀다 ('instagram.com'이 www.까지 막음). '*'는 그대로."""
    doms = set(domains)
    if "*" in doms:
        return {"*"}
    return {d for d in doms if not any(d != p and d.endswith("." + p) for p in doms)}
