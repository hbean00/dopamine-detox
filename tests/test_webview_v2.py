"""실제 pywebview 창에서 v2 단계 UI ↔ 엔진 연결 확인 (임시 데이터, 웨일 재시작·창 닫기·종료 금지)."""
import os, sys, tempfile, time, threading, json, subprocess
tmp = tempfile.mkdtemp()
os.environ.update(DD_HOSTS_PATH=os.path.join(tmp, "hosts"), DD_DATA_DIR=os.path.join(tmp, "data"),
                  DD_POLICY_TEST="1", DD_NO_BROWSER_RESTART="1", DD_NO_APPGUARD="1")
open(os.environ["DD_HOSTS_PATH"], "w").write("127.0.0.1 localhost\n")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import webview
import app
from engine.core import Engine
from engine import browserpolicy as bp

e = Engine()
e._kill_processes = lambda names, now: None
s = e.store.settings
s.update(focustodo_enabled=False, tab_guard=False, strict=False)
e.start()
api = app.Api(e)
w = webview.create_window("dd-v2", app.resource("ui", "index.html"), js_api=api, width=1000, height=680)
res = {}
def js(code):
    return w.evaluate_js(code)
def run():
    time.sleep(6)
    res["mock"] = js("document.body.innerText.includes('가짜 데이터')")
    res["level_buttons"] = js("document.querySelectorAll('#levelPicker .level').length")
    js("document.querySelector('#levelPicker .level[data-level=\"2\"]').click()")
    time.sleep(1.5)
    res["last_level_saved"] = e.store.settings.get("last_level")
    res["start_label"] = js("document.querySelector('#btnStart').textContent.trim()")
    js("document.querySelector('#btnStart').click()")
    time.sleep(2.5)
    res["engine_level"] = e.level
    res["status_text"] = js("(document.querySelector('#statusText')||{}).textContent")
    res["policy_has_coupang"] = "coupang.com" in bp._read_list(bp.VENDORS[0])
    res["allow_buttons"] = js("document.querySelectorAll('[data-allow]').length")
    e.stop_session(); time.sleep(1.5)
    # 배타성 오류가 UI까지 오는지
    r = api.save_settings(dict(e.store.settings, allowed_sites=["youtube.com"]))
    res["reject_youtube"] = r
    # 일정 단계
    api.add_schedule([0], "09:00", "10:00", 3)
    res["schedule_level"] = e.store.schedules()[-1]["level"]
    res["running_apps_n"] = len(api.list_running_apps())
    w.destroy()
threading.Thread(target=run, daemon=True).start()
webview.start(gui="edgechromium", private_mode=True)
e.shutdown()
subprocess.run(["reg", "delete", r"HKCU\SOFTWARE\DopamineDetoxTest", "/f"], capture_output=True)
print(json.dumps(res, ensure_ascii=False, indent=1))
