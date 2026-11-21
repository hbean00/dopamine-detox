"""3·4단계 '허용 앱만' — 창이 있는 프로그램 중 허용 목록 밖이면 닫는다.

먼저 창에 정상 닫기(WM_CLOSE)를 보내고, GRACE초 뒤에도 남아 있으면 프로세스를 종료한다.
(저장 안 한 문서가 있으면 앱이 저장 여부를 묻는 동안 GRACE가 지날 수 있어, 그 경우에도 종료됨)
"""
import ctypes
import ctypes.wintypes as wt
import os
import time

import psutil

from . import winutil

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
GW_OWNER = 4
GRACE = 10.0


def app_windows():
    """[(hwnd, pid, exe_lower, title)] — 작업 표시줄에 보일 만한 최상위 창."""
    out = []
    P = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(h, _l):
        try:
            if not user32.IsWindowVisible(h) or user32.GetWindow(h, GW_OWNER):
                return True
            if user32.GetWindowLongW(h, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            title = winutil.window_title(h)
            if not title:
                return True
            pid = winutil.window_pid(h)
            exe = os.path.basename(winutil.process_path(pid)).lower()
            if exe:
                out.append((h, pid, exe, title))
        except Exception:
            pass
        return True
    user32.EnumWindows(P(cb), 0)
    return out


def running_apps():
    """설정 화면의 '열린 앱 불러오기'용: exe별 대표 제목 하나."""
    seen = {}
    for _h, _pid, exe, title in app_windows():
        seen.setdefault(exe, title)
    return [{"exe": e, "title": t[:60]} for e, t in sorted(seen.items())]


def decide(windows, allowed):
    """닫을 창 목록 (순수 함수, 테스트용)."""
    return [w for w in windows if w[2] not in allowed]


class AppGuard:
    def __init__(self, on_close=None):
        self.on_close = on_close or (lambda exe, title: None)
        self._pending = {}   # pid -> (exe, first_close_time)

    def enforce(self, allowed, now=None):
        """allowed: 허용 exe 집합. 허용 밖 창에 닫기 요청, 오래 버티면 종료. 닫은 수 반환."""
        if os.environ.get("DD_NO_APPGUARD"):  # 테스트: 실제 창은 건드리지 않고 기록만
            self.calls = getattr(self, "calls", []) + [set(allowed)]
            return 0
        now = now or time.time()
        closed = 0
        alive = set()
        for h, pid, exe, title in decide(app_windows(), allowed):
            alive.add(pid)
            if pid not in self._pending:
                self._pending[pid] = (exe, now)
                user32.PostMessageW(h, WM_CLOSE, 0, 0)
                self.on_close(exe, title)
                closed += 1
            elif now - self._pending[pid][1] > GRACE:
                try:
                    psutil.Process(pid).kill()
                except psutil.Error:
                    pass
                self._pending.pop(pid, None)
        for pid in list(self._pending):
            if pid not in alive:
                self._pending.pop(pid, None)
        return closed

    def reset(self):
        self._pending.clear()
