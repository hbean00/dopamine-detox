"""실제 pywebview 창에서 UI ↔ 엔진 연결 확인 (임시 hosts/데이터 사용)."""
import os, sys, tempfile, time, threading, json
tmp = tempfile.mkdtemp()
os.environ["DD_HOSTS_PATH"] = os.path.join(tmp, "hosts")
os.environ["DD_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["DD_POLICY_TEST"] = "1"
open(os.environ["DD_HOSTS_PATH"], "w").write("127.0.0.1 localhost\n")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import webview
import app
from engine.core import Engine
from engine import hosts

e = Engine(); e.store.settings["targets_enabled"]["kakaotalk"] = False; e.store.settings["tab_guard"] = False
e.store.settings["hosts_block"] = True
e.start()
api = app.Api(e)
w = webview.create_window("dd-test", app.resource("ui", "index.html"), js_api=api, width=1000, height=680)
res = {}
def run():
    time.sleep(6)
    res["mock_label"] = w.evaluate_js("document.body.innerText.includes('가짜 데이터')")
    res["state_via_js"] = w.evaluate_js("window.pywebview && !!window.pywebview.api && typeof window.pywebview.api.get_state")
    e.start_session(25); time.sleep(2.5)
    res["locked_class"] = w.evaluate_js("document.body.className")
    res["hosts_has_youtube"] = "www.youtube.com" in hosts.current_domains()
    res["text_sample"] = w.evaluate_js("document.body.innerText.slice(0,300)")
    e.store.settings["strict"] = False; e.stop_session(""); time.sleep(2)
    res["after_stop_class"] = w.evaluate_js("document.body.className")
    res["hosts_after"] = sorted(hosts.current_domains())
    w.destroy()
threading.Thread(target=run, daemon=True).start()
webview.start(gui="edgechromium", private_mode=True)
e.shutdown()
print(json.dumps(res, ensure_ascii=False, indent=1))
