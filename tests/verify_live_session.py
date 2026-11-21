"""실제 웨일에서 집중 세션 중 Instagram / YouTube 탭이 자동으로 닫히는지 확인.
임시 데이터·hosts·정책(HKCU 테스트 키) 사용, 카카오톡 종료는 끔."""
import os
import subprocess
import sys
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ["DD_HOSTS_PATH"] = os.path.join(tmp, "hosts")
os.environ["DD_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["DD_POLICY_TEST"] = "1"
open(os.environ["DD_HOSTS_PATH"], "w").write("127.0.0.1 localhost\n")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import uiautomation as auto  # noqa: E402

from engine import core  # noqa: E402
from engine.targets import TARGETS  # noqa: E402



def _close_button(tab, auto):
    for c, _d in auto.WalkControl(tab, maxDepth=3):
        if c.ControlTypeName == "ButtonControl" and "닫기" in (c.Name or ""):
            return c
    return None


WHALE = r"C:\Program Files\Naver\Naver Whale\Application\whale.exe"


def closable_matching(key):
    out = []
    for win in auto.GetRootControl().GetChildren():
        try:
            if win.ClassName != "Chrome_WidgetWin_1" or not win.Name.endswith("Whale"):
                continue
        except Exception:
            continue
        for c, _d in auto.WalkControl(win, maxDepth=14):
            if c.ControlTypeName == "TabItemControl" and TARGETS[key]["title"].search(c.Name or ""):
                if _close_button(c, auto) is not None:
                    out.append(c.Name)
    return out


e = core.Engine()
s = e.store.settings
s["focustodo_enabled"] = False
s["targets_enabled"]["kakaotalk"] = False
s["hosts_block"] = False
s["tab_guard"] = True
e.start()
e.start_session(5)
print("session active:", e.state()["active"])
results = {}
def tab_names():
    out = []
    for win in auto.GetRootControl().GetChildren():
        try:
            if win.ClassName == "Chrome_WidgetWin_1" and win.Name.endswith("Whale"):
                out += [c.Name for c, _d in auto.WalkControl(win, maxDepth=14) if c.ControlTypeName == "TabItemControl"]
        except Exception:
            pass
    return out


with auto.UIAutomationInitializerInThread():
    # 대조군: 막히지 않는 페이지는 탭이 열리고 UIA로 보여야 한다
    n0 = len(tab_names())
    subprocess.Popen([WHALE, "https://example.org/"])
    time.sleep(5)
    names = tab_names()
    print("control: tabs", n0, "->", len(names), "| example tab seen:", any("example" in (n or "").lower() for n in names))
    for win in auto.GetRootControl().GetChildren():
        if win.ClassName == "Chrome_WidgetWin_1" and win.Name.endswith("Whale"):
            for c, _d in auto.WalkControl(win, maxDepth=14):
                if c.ControlTypeName == "TabItemControl" and "example" in (c.Name or "").lower():
                    b = _close_button(c, auto)
                    if b:
                        b.GetLegacyIAccessiblePattern().DoDefaultAction()
                        print("closed control tab")
    for key, url in (("instagram", "https://www.instagram.com/"), ("youtube", "https://www.youtube.com/")):
        subprocess.Popen([WHALE, url])
        seen_open, t0 = False, time.time()
        while time.time() - t0 < 20:
            time.sleep(1)
            tabs = closable_matching(key)
            if tabs:
                seen_open = True
            elif seen_open:
                break
        results[key] = {"tab_appeared": seen_open, "closed_after_s": round(time.time() - t0, 1),
                        "still_open": closable_matching(key)}
        print(key, results[key])
print("blocked_hits:", e.store.day()["blocked_hits"])
e.store.settings["strict"] = False
e.stop_session()
e.shutdown()
log = os.path.join(os.environ["DD_DATA_DIR"], "log.txt")
print("--- engine log ---")
print(open(log, encoding="utf-8").read() if os.path.exists(log) else "(none)")
subprocess.run(["reg", "delete", r"HKCU\SOFTWARE\DopamineDetoxTest", "/f"], capture_output=True)
