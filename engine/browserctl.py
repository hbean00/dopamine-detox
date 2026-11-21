"""웨일 재시작 — 실행 중인 웨일은 브라우저 정책 변경을 바로 반영하지 않으므로(실측),
3·4단계를 시작할 때 웨일을 닫았다가, 세션 파일에서 읽은 탭 주소로 다시 연다.

이 앱은 관리자 권한으로 돈다. 웨일을 관리자 권한으로 띄우면 안 되므로,
탐색기(일반 권한)를 통해 실행하는 Shell.Application 방식으로 다시 연다.
"""
import ctypes
import os
import subprocess
import time

import psutil

WHALE = r"C:\Program Files\Naver\Naver Whale\Application\whale.exe"
WM_CLOSE = 0x0010
user32 = ctypes.windll.user32


def whale_procs(match=None):
    out = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower() != "whale.exe":
                continue
            if match and not any(match in a for a in (p.info["cmdline"] or [])):
                continue
            out.append(p)
        except psutil.Error:
            pass
    return out


def is_running(match=None):
    return bool(whale_procs(match))


def _close_windows(pids):
    from .appguard import app_windows
    n = 0
    for h, pid, exe, _t in app_windows():
        if pid in pids and exe == "whale.exe":
            user32.PostMessageW(h, WM_CLOSE, 0, 0)
            n += 1
    return n


def launch_unelevated(path, args=""):
    """관리자 프로세스에서 일반 권한으로 프로그램 실행 (탐색기의 ShellExecute 사용)."""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
        shell.ShellExecute(path, args, "", "open", 1)
        return True
    except Exception:
        pass
    try:  # 대체: explorer 로 실행 (인자는 못 넘김)
        subprocess.Popen(["explorer.exe", path])
        return True
    except OSError:
        return False


def restart_whale(match=None, extra_args="", timeout=8.0, elevated=None, user_data_dir=None):
    """웨일을 닫고 → 세션 파일의 탭 주소로 다시 실행. match/user_data_dir: 테스트용 프로필 지정.
    반환: {"was_running", "closed_windows", "killed", "tabs", "relaunched"}"""
    procs = whale_procs(match)
    res = {"was_running": bool(procs), "closed_windows": 0, "killed": 0, "relaunched": False}
    if not procs:
        return res
    pids = {p.pid for p in procs}
    res["closed_windows"] = _close_windows(pids)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not [p for p in procs if p.is_running()]:
            break
        time.sleep(0.3)
    for p in procs:
        try:
            if p.is_running():
                p.kill()
                res["killed"] += 1
        except psutil.Error:
            pass
    time.sleep(0.8)
    # 실측: 웨일은 --restore-last-session 으로 탭을 복원하지 않고, 실행 중엔 세션 파일이 잠겨 있다.
    # → 종료된 지금 세션 파일에서 탭 주소를 읽어 그 주소들로 다시 연다.
    from . import whalesession
    urls = whalesession.current_tab_urls(user_data_dir)[:40]
    res["tabs"] = len(urls)
    argv = extra_args.split() + urls
    if elevated is None:
        from . import winutil
        elevated = winutil.is_admin()
    if elevated:
        res["relaunched"] = launch_unelevated(WHALE, subprocess.list2cmdline(argv))
    else:
        try:
            subprocess.Popen([WHALE] + argv)
            res["relaunched"] = True
        except OSError:
            res["relaunched"] = False
    return res


if os.environ.get("DD_NO_BROWSER_RESTART"):  # 단위 테스트에서 실제 웨일을 건드리지 않게
    def restart_whale(*_a, **_k):  # noqa: F811
        return {"was_running": False, "closed_windows": 0, "killed": 0, "relaunched": False, "skipped": True}
