"""관리자 policy-hold 실행 중에 실제 브라우저(Edge headless, 웨일)가 example.com을 막는지 확인.
사용: python tests/verify_policy_live.py <flag_path>
"""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
from engine import winutil  # noqa: E402

flag = sys.argv[1]
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
WHALE = r"C:\Program Files\Naver\Naver Whale\Application\whale.exe"


def edge_dump():
    ud = tempfile.mkdtemp(prefix="dd-edge-")
    r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={ud}",
                        "--dump-dom", "https://example.com"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    out = r.stdout or ""
    return "Example Domain" in out, len(out)


def whale_titles():
    import ctypes
    found = []
    P = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, _l):
        t = winutil.window_title(h)
        if "example" in t.lower():
            found.append(t)
        return True
    ctypes.windll.user32.EnumWindows(P(cb), 0)
    return found


t0 = time.time()
while time.time() - t0 < 120:
    if os.path.exists(flag) and open(flag, encoding="utf-8").read().startswith(("ON", "ERR")):
        break
    time.sleep(0.5)
print("flag:", open(flag, encoding="utf-8").read().strip() if os.path.exists(flag) else "none (UAC 미승인?)")
if not os.path.exists(flag) or not open(flag, encoding="utf-8").read().startswith("ON"):
    sys.exit(1)
time.sleep(2)
print("edge during policy -> page loaded:", edge_dump())

subprocess.Popen([WHALE, "https://example.com/?dd-check"])
time.sleep(6)
titles = whale_titles()
print("whale titles during policy:", titles)


def close_example_tabs():
    """웨일에 남은 example.com 테스트 탭을 닫는다 (창을 앞으로 가져와 Ctrl+W)."""
    import ctypes
    u = ctypes.windll.user32
    for _ in range(4):
        hw = []
        P = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def cb(h, _l):
            t = winutil.window_title(h).lower()
            if ("example" in t) and t.endswith("whale"):
                hw.append(h)
            return True
        u.EnumWindows(P(cb), 0)
        if not hw:
            return
        u.ShowWindow(hw[0], 9)
        u.SetForegroundWindow(hw[0])
        time.sleep(0.6)
        h, exe, title = winutil.foreground()
        if exe == "whale.exe" and "example" in title.lower():
            winutil.send_ctrl_w()
            print("closed whale test tab:", title)
            time.sleep(0.8)
        else:
            print("could not focus whale test tab; please close it:", title)
            return


close_example_tabs()

while "OFF" not in open(flag, encoding="utf-8").read():
    time.sleep(1)
print("flag end:", open(flag, encoding="utf-8").read().strip().splitlines()[-1])
time.sleep(2)
print("edge after policy removed -> page loaded:", edge_dump())
