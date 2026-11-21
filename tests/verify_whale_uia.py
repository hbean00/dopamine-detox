"""실행 중인 웨일에서 정책 차단이 바로 먹히는지 — UI Automation으로 탭 이름을 읽어 판정.
policy-hold 가 instagram.com 을 막는 동안 https://www.instagram.com 을 열고:
  막힘 → 탭 이름이 'www.instagram.com' (오류 페이지)
  열림 → 탭 이름에 'Instagram'
끝나면 테스트 탭은 탭의 닫기 버튼으로 닫는다.
사용: python tests/verify_whale_uia.py <flag_path> <url> <keyword>
"""
import os
import subprocess
import sys
import time

import uiautomation as auto

sys.stdout.reconfigure(encoding="utf-8")
flag, url, kw = sys.argv[1], sys.argv[2], sys.argv[3].lower()
WHALE = r"C:\Program Files\Naver\Naver Whale\Application\whale.exe"


def whale_tabs():
    tabs = []
    for win in auto.GetRootControl().GetChildren():
        try:
            if win.ClassName != "Chrome_WidgetWin_1" or not win.Name.endswith("Whale"):
                continue
        except Exception:
            continue
        for c, _d in auto.WalkControl(win, maxDepth=14):
            if c.ControlTypeName == "TabItemControl" and kw in (c.Name or "").lower():
                tabs.append(c)
    return tabs


def close_tab(tab):
    for c, _d in auto.WalkControl(tab, maxDepth=3):
        if c.ControlTypeName == "ButtonControl" and ("닫기" in c.Name or "close" in c.Name.lower()):
            try:
                c.GetInvokePattern().Invoke()
            except Exception:
                c.GetLegacyIAccessiblePattern().DoDefaultAction()
            return True
    return False


with auto.UIAutomationInitializerInThread():
    before = [t.Name for t in whale_tabs()]
    print("tabs before:", before)
    t0 = time.time()
    while time.time() - t0 < 120:
        if os.path.exists(flag) and open(flag, encoding="utf-8").read().startswith(("ON", "ERR")):
            break
        time.sleep(0.5)
    txt = open(flag, encoding="utf-8").read() if os.path.exists(flag) else ""
    print("flag:", txt.strip() or "none")
    if not txt.startswith("ON"):
        sys.exit(1)
    time.sleep(3)
    subprocess.Popen([WHALE, url])
    time.sleep(8)
    tabs = whale_tabs()
    names = [t.Name for t in tabs]
    print("tabs DURING policy:", names)
    # 오류 페이지는 탭 이름이 호스트명(www.instagram.com 등)
    err_tabs = [t for t in tabs if "." in t.Name and " " not in t.Name.strip()]
    loaded_more = len(tabs) - len(err_tabs) > len(before)
    if err_tabs and not loaded_more:
        verdict = "BLOCKED"
    elif loaded_more:
        verdict = "NOT BLOCKED"
    else:
        verdict = "UNKNOWN (no new tab seen)"
    print("VERDICT running Whale:", verdict)
    for t in err_tabs:
        print("close test tab:", t.Name, close_tab(t))
    if loaded_more:  # 새로 열린 정상 탭: 닫기 버튼이 있는 마지막 것
        for t in reversed(tabs):
            if t not in err_tabs and close_tab(t):
                print("closed loaded test tab:", t.Name)
                break
