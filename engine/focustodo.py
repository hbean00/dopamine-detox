"""Focus To-Do 포모도로 감지 (UI Automation).

공개 API가 없으므로 FocusToDo.exe 창 안의 웹 콘텐츠를 UIA로 읽는다. 실측(7.2.2) 화면 두 가지:

1) 하단 플로팅 타이머 — 버튼 CSS 클래스로 상태가 드러남, 숫자는 분 단위('29')
     대기 FloatTimer-start / 진행 FloatTimer-pause / 일시정지 start+stop / 휴식 FloatTimer-completeRest
2) 전체 화면 타이머(FullscreenTimer-*) — 버튼 클래스는 상태와 무관(actionWithoutBackground),
     대신 버튼 글자 '일시정지'가 보이면 진행 중, 카운트다운은 'mm:ss'로 매초 바뀜

2026-11-18 실사용에서 전체 화면 모드로 바꾸자 감지가 'idle'로 멈춘 문제가 있었다:
 - 카운트다운이 매초 다시 그려져, 2~3초 걸리는 트리 탐색 도중 요소가 사라지면 COM 오류로 회차 전체가 실패
 - 한 번의 잘못된 판독으로 곧바로 차단을 풀었음
그래서: 요소 단위로 오류를 삼키는 탐색 + 불필요한 큰 하위 트리 건너뛰기 + 해제는 연속 판독으로만
+ 탐색 스레드가 멈추면 새로 띄우는 watchdog + 상태 변화 로그.
"""
import re
import threading
import time

import psutil

TIMER_RE = re.compile(r"^\s*(?:(\d{1,2})\s*:\s*)?(\d{1,3})\s*:\s*([0-5]\d)\s*$")
BREAK_RE = re.compile(r"휴식|short break|long break|^break$|take a break", re.I)
PAUSE_WORDS = {"일시정지", "일시 정지", "pause", "暂停", "一時停止"}   # 진행 중일 때 보이는 버튼
RESUME_WORDS = {"계속", "재개", "시작", "resume", "continue", "start", "继续", "開始"}
PROC = "focustodo.exe"
# 상태 판정과 무관하고 요소가 많은 하위 트리(눈금 120개, 통계 위젯, 프로젝트·작업 목록)
PRUNE = ("DialView-scales", "WidgetView-root", "ProjectRegion-root", "TaskRegion-root", "HomeHeader-root")
ACTIVE = ("focus", "break")


def _ftd_pids():
    pids = set()
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == PROC:
                pids.add(p.pid)
        except (psutil.Error, TypeError):
            pass
    return pids


def _walk(auto, ctrl, depth, out, max_depth=40, limit=3000):
    """요소 하나가 사라져도(COM 오류) 나머지 탐색은 계속하는 DFS."""
    if depth > max_depth or len(out) > limit:
        return
    try:
        nm = ctrl.Name or ""
        cn = ctrl.ClassName or ""
    except Exception:
        return
    out.append((nm.strip(), cn))
    if any(cn.startswith(p) or (" " + p) in cn for p in PRUNE):
        return
    try:
        child = ctrl.GetFirstChildControl()
    except Exception:
        return
    while child is not None:
        _walk(auto, child, depth + 1, out, max_depth, limit)
        try:
            child = child.GetNextSiblingControl()
        except Exception:
            break


class FocusToDoWatcher:
    def __init__(self, interval=2.0, on_change=None):
        self.interval = interval
        self.on_change = on_change or (lambda old, new, info: None)
        self.status = "not_running"  # focus | break | paused | idle | not_running
        self.timer = None
        self.texts = []
        self.found_window = False
        self.last_error = None
        self.raw_status = None
        self._prev = {}
        self._pending = None          # (raw_status, count) — 해제 방향 변화는 연속 확인
        self._expected_end = None     # 마지막으로 읽은 카운트다운 기준 예상 종료 시각
        self.hidden = False           # Focus To-Do 창이 최소화돼 내용을 못 읽는 중
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.enabled = True
        self._beat = time.time()
        self._gen = 0
        self.restarts = 0

    # ---------- public ----------
    def start(self):
        self._spawn()
        threading.Thread(target=self._watchdog, name="focustodo-watchdog", daemon=True).start()

    def stop(self):
        self._stop.set()

    def snapshot(self):
        with self._lock:
            return {
                "found_window": self.found_window,
                "timer": self.timer,
                "status": self.status,
                "raw_status": self.raw_status,
                "texts": list(self.texts[:40]),
                "error": self.last_error,
                "restarts": self.restarts,
                "hidden": self.hidden,
                "expected_end": self._expected_end,
            }

    # ---------- threads ----------
    def _spawn(self):
        self._gen += 1
        self._beat = time.time()
        threading.Thread(target=self._run, args=(self._gen,), name=f"focustodo-{self._gen}", daemon=True).start()

    def _watchdog(self):
        """UIA 호출이 응답 없이 멈추면(드물게 Chromium 쪽에서 발생) 새 탐색 스레드를 띄운다."""
        while not self._stop.wait(5):
            if time.time() - self._beat > max(25.0, self.interval * 10):
                self.restarts += 1
                self.last_error = f"탐색 스레드 응답 없음 → 다시 시작 ({self.restarts}회)"
                self.on_change(self.status, self.status, self.last_error)
                self._spawn()

    def _run(self, gen):
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread(debug=False):
            while not self._stop.is_set() and gen == self._gen:
                self._beat = time.time()
                if self.enabled:
                    try:
                        self._poll(auto)
                        self.last_error = None
                    except Exception as e:  # 회차 실패는 직전 상태 유지
                        self.last_error = f"{type(e).__name__}: {e}"
                else:
                    self._set("idle", None, [], False)
                self._beat = time.time()
                self._stop.wait(self.interval)

    # ---------- polling ----------
    def _collect(self, auto, pids):
        """(texts, classes, timer_minutes, readable)
        실측: Focus To-Do 창을 최소화하면 웹 내용이 UIA에 노출되지 않는다(창 버튼 몇 개만 보임)."""
        import ctypes
        items = []
        readable = False
        for win in auto.GetRootControl().GetChildren():
            try:
                if win.ProcessId not in pids:
                    continue
                iconic = bool(ctypes.windll.user32.IsIconic(win.NativeWindowHandle))
            except Exception:
                continue
            before = len(items)
            _walk(auto, win, 0, items)
            if not iconic and len(items) - before > 20:
                readable = True
        texts = [nm for nm, _ in items if nm and len(nm) <= 60]
        classes = [cn for _, cn in items if "Timer" in cn]
        minutes = None
        for nm, cn in items:
            if "FloatTimer-timer" in cn and nm.isdigit():
                minutes = int(nm)
        return texts, classes, minutes, readable

    def _poll(self, auto):
        pids = _ftd_pids()
        if not pids:
            self._prev = {}
            self._pending = None
            self._set("not_running", None, [], False)
            return
        texts, classes, minutes, readable = self._collect(auto, pids)
        self.apply_reading(texts, classes, minutes, readable)

    def apply_reading(self, texts, classes, minutes, readable, now=None):
        now = now or time.time()
        if not readable:
            # 창이 최소화돼 못 읽음 → 마지막 카운트다운이 끝날 때까지 직전 상태 유지
            self.hidden = True
            self.raw_status = "hidden"
            if self.status in ACTIVE and self._expected_end and now < self._expected_end + 20:
                left = max(0, int(self._expected_end - now))
                self._set(self.status, f"{left // 60:02d}:{left % 60:02d}", texts, True)
            else:
                self._expected_end = None
                self._set("idle", None, texts, bool(texts))
            return
        self.hidden = False
        raw, timer = classify(texts, classes, minutes, self._prev, now)
        self.raw_status = raw
        new = self._debounce(raw)
        if new in ACTIVE:
            secs = remaining_seconds(timer)
            if secs is not None:
                self._expected_end = now + secs
        self._set(new, timer, texts, bool(texts))

    def _debounce(self, raw):
        """차단을 '거는' 변화(→focus/break)는 즉시, '푸는' 변화(focus/break→그 외)는 2회 연속 확인."""
        cur = self.status
        if raw in ACTIVE or cur not in ACTIVE or raw == "not_running":
            self._pending = None
            return raw
        if self._pending and self._pending[0] == raw:
            self._pending = (raw, self._pending[1] + 1)
        else:
            self._pending = (raw, 1)
        return raw if self._pending[1] >= 2 else cur

    def _set(self, status, timer, texts, found):
        with self._lock:
            old = self.status
            self.status, self.timer, self.texts, self.found_window = status, timer, texts, found
        if old != status:
            self.on_change(old, status, timer)


def remaining_seconds(label):
    """'16:43' / '1:02:03' / '29분' → 남은 초 (분 단위 표시는 넉넉히 +59초)."""
    if not label:
        return None
    m = TIMER_RE.match(label)
    if m:
        return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    m = re.match(r"^(\d+)분$", label)
    if m:
        return int(m.group(1)) * 60 + 59
    return None


def classify(texts, classes, minutes, prev, now=None):
    """화면 내용 → (status, timer 문자열). prev는 회차 간 상태 보관용 dict."""
    now = now or time.time()
    joined = " ".join(classes)
    is_break = bool(re.search(r"Timer-\w*(rest|break|relax)", joined, re.I)) or any(BREAK_RE.search(t) for t in texts)
    timer = f"{minutes}분" if minutes is not None else None

    # 1) 하단 플로팅 타이머: 버튼 클래스
    if re.search(r"Timer-completeRest", joined):
        return "break", timer
    if re.search(r"FloatTimer-pause", joined):
        return ("break" if is_break else "focus"), timer
    if re.search(r"FloatTimer-stop", joined):
        return "paused", timer

    # mm:ss 카운트다운 (전체 화면 타이머 등)
    timers = []
    for t in texts:
        m = TIMER_RE.match(t)
        if m:
            h = int(m.group(1) or 0)
            timers.append((t.replace(" ", ""), h * 3600 + int(m.group(2)) * 60 + int(m.group(3))))
    cur = {i: secs for i, (_, secs) in enumerate(timers)}
    changed = next((i for i, v in cur.items() if i in prev.get("cur", {}) and prev["cur"][i] != v), None)
    if changed is not None:
        prev["last_change"] = now
    prev["cur"] = cur
    label = timers[changed if changed is not None else 0][0] if timers else timer
    ticking = bool(timers) and now - prev.get("last_change", 0) <= 6.0

    # 2) 전체 화면 타이머: 버튼 글자
    if "FullscreenTimer" in joined:
        low = {t.lower() for t in texts}
        if low & PAUSE_WORDS or ticking:
            return ("break" if is_break else "focus"), label
        if low & RESUME_WORDS or timers:
            return "paused", label
        return "idle", label

    # 3) 플로팅 타이머 대기
    if re.search(r"FloatTimer-start", joined):
        return "idle", timer

    # 4) 그 밖의 화면: 숫자가 줄어드는지로만 판단
    if not timers:
        return "idle", timer
    return (("break" if is_break else "focus") if ticking else "paused"), label


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    w = FocusToDoWatcher(interval=2.0, on_change=lambda o, n, i: print(f"  [change] {o} -> {n} ({i})"))
    w.start()
    for _ in range(int(sys.argv[1]) if len(sys.argv) > 1 else 6):
        time.sleep(2)
        s = w.snapshot()
        print(s["status"], s["raw_status"], s["timer"], s["found_window"], s["error"])
