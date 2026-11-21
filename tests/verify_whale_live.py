"""실행 중인 웨일이 정책 변경을 바로 반영하는지: example.org 를 열어 창 제목 확인.
막히면 'example.org - Whale', 열리면 'Example Domain - Whale'."""
import os, sys, time, subprocess, ctypes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
from engine import winutil
flag = sys.argv[1]
WHALE = r"C:\Program Files\Naver\Naver Whale\Application\whale.exe"
def whale_titles():
    out = []
    P = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _l):
        if ctypes.windll.user32.IsWindowVisible(h):
            t = winutil.window_title(h)
            if t.endswith("Whale"): out.append(t)
        return True
    ctypes.windll.user32.EnumWindows(P(cb), 0)
    return out
t0 = time.time()
while time.time() - t0 < 120:
    if os.path.exists(flag) and open(flag, encoding="utf-8").read().startswith(("ON", "ERR")): break
    time.sleep(0.5)
txt = open(flag, encoding="utf-8").read() if os.path.exists(flag) else ""
print("flag:", txt.strip() or "none")
if not txt.startswith("ON"): sys.exit(1)
time.sleep(3)
subprocess.Popen([WHALE, "https://example.org/"])
time.sleep(6)
print("running whale titles DURING policy:", whale_titles())
h, exe, title = winutil.foreground()
if exe == "whale.exe" and "example" in title.lower():
    winutil.send_ctrl_w(); print("closed test tab")
