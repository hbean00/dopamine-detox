"""실제 pywebview 창에서 대기/집중 화면을 캡처하고, AI 경고를 실제 맨 앞 창으로 몇 차례 돌린다.
임시 데이터·hosts·정책(HKCU 테스트 키) 사용, 카카오톡 종료 끔. 결과 이미지는 build/ 에 저장."""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

tmp = tempfile.mkdtemp()
os.environ["DD_HOSTS_PATH"] = os.path.join(tmp, "hosts")
os.environ["DD_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["DD_POLICY_TEST"] = "1"
os.environ["DD_NO_BROWSER_RESTART"] = "1"
os.environ["DD_NO_APPGUARD"] = "1"
open(os.environ["DD_HOSTS_PATH"], "w").write("127.0.0.1 localhost\n")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import webview  # noqa: E402
from PIL import ImageGrab  # noqa: E402

import app  # noqa: E402
from engine import core, winutil  # noqa: E402

AI_MINUTES = float(sys.argv[1]) if len(sys.argv) > 1 else 2.5
notes = []
e = core.Engine(notify=lambda t, m: notes.append((time.strftime("%H:%M:%S"), t, m)))
s = e.store.settings
s.update(focustodo_enabled=False, tab_guard=False, hosts_block=False,
         ai_warning=True, ai_interval_min=1, work_description="ASIC 설계 LAB3 보고서 작성과 도파민 디톡스 앱 개발")
s["targets_enabled"]["kakaotalk"] = False
e.start()
api = app.Api(e)
w = webview.create_window("dd-capture", app.resource("ui", "index.html"), js_api=api,
                          width=1000, height=680, background_color="#f2f1ec")
out = {}


def grab(name):
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, "dd-capture")
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.8)
    r = ctypes.wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r))
    img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
    path = os.path.join(ROOT, "build", f"shot-{name}.png")
    img.save(path)
    out[name] = {"path": path, "size": img.size}


def run():
    import ctypes.wintypes  # noqa: F401
    time.sleep(5)
    grab("idle")
    e.start_session(30)
    time.sleep(2.5)
    grab("locked")
    out["body_class"] = w.evaluate_js("document.body.className")
    w.minimize()  # AI 판정은 사용자의 실제 맨 앞 창으로
    t0 = time.time()
    seen = []
    while time.time() - t0 < AI_MINUTES * 60:
        time.sleep(5)
        last = e.ai.last
        if last and (not seen or seen[-1].get("at") != last.get("at")):
            seen.append(dict(last))
    out["ai_checks"] = seen
    out["ai_notifications"] = [n for n in notes if "업무" in n[1]]
    w.destroy()


threading.Thread(target=run, daemon=True).start()
webview.start(gui="edgechromium", private_mode=True)
e.store.settings["strict"] = False
e.stop_session()
e.shutdown()
subprocess.run(["reg", "delete", r"HKCU\SOFTWARE\DopamineDetoxTest", "/f"], capture_output=True)
print(json.dumps(out, ensure_ascii=False, indent=1))
