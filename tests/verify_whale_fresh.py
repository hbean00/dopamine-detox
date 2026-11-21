"""정책이 켜진 동안 '새로 시작한' 웨일(별도 프로필)이 example.com 을 막는지 확인.
막히면 제목이 'example.com - Whale'(오류 페이지), 안 막히면 'Example Domain - Whale'.
사용: python tests/verify_whale_fresh.py <flag_path>
"""
import ctypes
import os
import subprocess
import sys
import tempfile
import time

import psutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
from engine import winutil  # noqa: E402

flag = sys.argv[1]
WHALE = r"C:\Program Files\Naver\Naver Whale\Application\whale.exe"


def titles_for(pids):
    out = []
    P = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, _l):
        if winutil.window_pid(h) in pids:
            t = winutil.window_title(h)
            if t and ctypes.windll.user32.IsWindowVisible(h):
                out.append(t)
        return True
    ctypes.windll.user32.EnumWindows(P(cb), 0)
    return out


def fresh_whale_title(tag):
    ud = tempfile.mkdtemp(prefix="dd-whale-")
    p = subprocess.Popen([WHALE, f"--user-data-dir={ud}", "--no-first-run", "--no-default-browser-check",
                          "--new-window", f"https://example.com/?{tag}"])
    time.sleep(9)
    procs = []  # 런처는 바로 끝나고 다른 프로세스로 다시 뜨므로 user-data-dir 로 찾는다
    for q in psutil.process_iter(["name", "cmdline"]):
        try:
            if (q.info["name"] or "").lower() == "whale.exe" and any(ud in a for a in (q.info["cmdline"] or [])):
                procs.append(q)
        except psutil.Error:
            pass
    pids = {q.pid for q in procs}
    t = titles_for(pids)
    for q in procs:
        try:
            q.kill()
        except psutil.Error:
            pass
    return t


t0 = time.time()
while time.time() - t0 < 120:
    if os.path.exists(flag) and open(flag, encoding="utf-8").read().startswith(("ON", "ERR")):
        break
    time.sleep(0.5)
txt = open(flag, encoding="utf-8").read() if os.path.exists(flag) else ""
print("flag:", txt.strip() or "none (UAC 미승인?)")
if not txt.startswith("ON"):
    sys.exit(1)
time.sleep(2)
print("fresh whale DURING policy:", fresh_whale_title("during"))
while "OFF" not in open(flag, encoding="utf-8").read():
    time.sleep(1)
time.sleep(2)
print("fresh whale AFTER policy removed:", fresh_whale_title("after"))
