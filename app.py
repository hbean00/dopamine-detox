"""도파민 디톡스 — 진입점. pywebview 창 + 트레이 + 차단 엔진."""
import os
import sys
import threading

import webview

from engine import winutil
from engine.autostart import set_autostart
from engine import levels
from engine.appguard import running_apps
from engine.core import Engine


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


class Api:
    """JS에서 window.pywebview.api.<name>() 으로 부른다. 전부 JSON으로 돌려준다."""

    def __init__(self, engine):
        self._e = engine
        self._window = None

    def get_state(self):
        return self._e.state()

    def start_session(self, minutes, level=None):
        r = self._e.start_session(minutes, level)
        if r and not r.get("ok", True):
            return r
        return self._e.state()

    def get_levels(self):
        return levels.level_list()

    def list_running_apps(self):
        return running_apps()

    def extend_session(self, minutes):
        self._e.extend_session(minutes)
        return self._e.state()

    def stop_session(self, phrase=""):
        return self._e.stop_session(phrase)

    def allow_temporarily(self, target, minutes, reason):
        return self._e.allow_temporarily(target, minutes, reason)

    def revoke_allow(self, target):
        self._e.revoke_allow(target)
        return self._e.state()

    def get_schedules(self):
        return self._e.store.schedules()

    def add_schedule(self, days, start, end, level=1):
        if not days:
            return self._e.store.schedules()
        self._e.store.add_schedule(days, start, end, level)
        return self._e.store.schedules()

    def remove_schedule(self, sid):
        self._e.store.remove_schedule(sid)
        return self._e.store.schedules()

    def toggle_schedule(self, sid, enabled):
        self._e.store.toggle_schedule(sid, enabled)
        return self._e.store.schedules()

    def get_settings(self):
        return self._e.store.settings

    def save_settings(self, settings):
        old = self._e.store.settings
        # v2 배타성: 1·2단계 차단 대상은 3단계 허용 사이트에 넣을 수 없다
        if "allowed_sites" in settings:
            sites, err = levels.validate_allowed_sites(settings.get("allowed_sites") or [],
                                                       settings.get("extra_domains") or old.get("extra_domains"))
            if err:
                return {"ok": False, "error": err}
            settings = dict(settings, allowed_sites=sites)
        if "allowed_apps" in settings:
            settings = dict(settings, allowed_apps=levels.normalize_apps(settings.get("allowed_apps") or []))
        for k in ("last_level", "focustodo_level"):
            if k in settings:
                settings[k] = levels.clamp_level(settings[k], old.get(k, 1))
        if self._e.active and old.get("strict"):
            # 집중 중에는 차단을 약하게 만드는 변경을 막는다
            more_sites = set(settings.get("allowed_sites", [])) - set(old.get("allowed_sites") or [])
            more_apps = set(settings.get("allowed_apps", [])) - set(old.get("allowed_apps") or [])
            weaker = (any(old["targets_enabled"].get(k) and not settings.get("targets_enabled", {}).get(k, True)
                          for k in old["targets_enabled"])
                      or (old["strict"] and not settings.get("strict", True))
                      or (old["tab_guard"] and not settings.get("tab_guard", True))
                      or (self._e.level in (3, 4) and (more_sites or more_apps))
                      or (self._e.source == "focustodo"
                          and settings.get("focustodo_level", 1) < old.get("focustodo_level", 1)))
            if weaker:
                return {"ok": False, "error": "엄격 모드: 집중 중에는 차단을 끄는 설정을 바꿀 수 없어요."}
        if bool(settings.get("autostart")) != bool(old.get("autostart")):
            r = set_autostart(bool(settings.get("autostart")))
            if not r["ok"]:
                return r
        self._e.store.set_settings(settings)
        return {"ok": True}

    def ai_check_now(self):
        return self._e.ai.check_now()

    def focustodo_diagnose(self):
        return self._e.ftd.snapshot()

    def get_history(self, days=7):
        return self._e.history(int(days))

    def hide_window(self):
        if self._window:
            self._window.hide()


def make_tray(window, engine, quit_cb):
    try:
        import pystray
        from PIL import Image
    except ImportError:
        return None
    img = Image.open(resource("assets", "icon.png"))

    def show(icon=None, item=None):
        window.show()
        window.restore()

    def quit_(icon, item):
        if engine.active:
            winutil.message_box("집중 중에는 종료할 수 없어요.\n앱에서 '그만하기'로 먼저 멈춰주세요.")
            show()
            return
        icon.stop()
        quit_cb()

    menu = pystray.Menu(
        pystray.MenuItem("열기", show, default=True),
        pystray.MenuItem("30분 집중 시작 (마지막 단계)", lambda i, it: engine.start_session(30)),
        pystray.MenuItem("종료", quit_),
    )
    icon = pystray.Icon("DopamineDetox", img, "도파민 디톡스", menu)
    icon.run_detached()
    return icon


def _can_import(mod):
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def selftest(out_path):
    """빌드된 exe가 UIA·hosts 읽기·UI 파일 번들을 제대로 갖췄는지 확인 (창 없음)."""
    import json
    import time
    from engine import hosts
    from engine.focustodo import FocusToDoWatcher
    w = FocusToDoWatcher(interval=1.0)
    w.start()
    time.sleep(4)
    res = {
        "focustodo": w.snapshot(),
        "ui_exists": os.path.exists(resource("ui", "index.html")),
        "icon_exists": os.path.exists(resource("assets", "icon.png")),
        "hosts_readable": bool(hosts._read()[0]),
        "hosts_block": sorted(hosts.current_domains()),
        "is_admin": winutil.is_admin(),
        "webview_version": getattr(webview, "__version__", "?"),
        "win32com": _can_import("win32com.client"),
        "levels": [lv["name"] for lv in levels.level_list()],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


def hosts_selftest(out_path, seconds=45):
    """관리자 권한에서 실제 hosts 차단이 유지되는지 확인 (카카오톡 종료·탭 닫기 없음).
    Instagram 도메인만 잠깐 막고, 외부 덮어쓰기 복구 + 실제 DNS 결과를 기록한 뒤 지운다."""
    import json
    import socket
    import time
    from engine import hosts
    from engine.targets import domains_for
    want = domains_for("instagram") | {"dopamine-selftest.test"}
    res = {"is_admin": winutil.is_admin(), "events": [], "restored": 0, "resolve": []}

    def resolve():
        try:
            return sorted({a[4][0] for a in socket.getaddrinfo("www.instagram.com", 443)})
        except OSError as e:
            return [f"ERR {e}"]
    res["resolve_before"] = resolve()
    try:
        hosts.apply(want)
        res["events"].append([0, "applied"])
        t0 = time.time()
        while time.time() - t0 < seconds:
            time.sleep(1)
            if hosts.current_domains() != want:
                res["restored"] += 1
                res["events"].append([round(time.time() - t0, 1), "external rewrite -> reapply"])
                hosts.apply(want)
            if int(time.time() - t0) % 5 == 0:
                res["resolve"].append([round(time.time() - t0, 1), resolve()])
        res["held_at_end"] = hosts.current_domains() == want
    except OSError as e:
        res["error"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            hosts.apply(set())
        except OSError as e:
            res["cleanup_error"] = str(e)
        res["clean_after"] = hosts.current_domains() == set()
        res["resolve_after"] = resolve()
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)


def block_selftest(out_path):
    """관리자 권한 검증 2: (1) 남은 hosts 블록 정리 후 보안 프로그램이 되돌리는지 관찰
    (2) 브라우저 정책으로 example.com 을 막고 Edge headless 로 실제 차단 확인 → 원복."""
    import json
    import subprocess
    import tempfile
    import time
    from engine import browserpolicy, hosts
    res = {"is_admin": winutil.is_admin(), "hosts": [], "policy": {}}
    # (1) hosts 정리 + 20초 관찰
    t0 = time.time()
    try:
        res["hosts_block_at_start"] = sorted(hosts.current_domains())
        hosts.apply(set())
        while time.time() - t0 < 20:
            time.sleep(0.5)
            cur = hosts.current_domains()
            if cur:
                res["hosts"].append([round(time.time() - t0, 1), f"block came back ({len(cur)}) -> remove"])
                hosts.apply(set())
        res["hosts_clean_end"] = hosts.current_domains() == set()
    except OSError as e:
        res["hosts_error"] = str(e)

    # (2) 브라우저 정책
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    ud = tempfile.mkdtemp(prefix="dd-edge-")

    def dump(url):
        try:
            r = subprocess.run([edge, "--headless=new", "--disable-gpu", "--no-first-run",
                                f"--user-data-dir={ud}", "--dump-dom", url],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=60, creationflags=0x08000000)
            out = r.stdout or ""
            return {"has_example_title": "Example Domain" in out,
                    "blocked_marker": any(k in out for k in ("ERR_BLOCKED_BY_ADMINISTRATOR", "BLOCKED_BY_ADMIN",
                                                              "blocked", "차단")),
                    "len": len(out)}
        except Exception as e:
            return {"error": str(e)}
    managed = {"example.com"}
    try:
        res["policy"]["before"] = dump("https://example.com")
        browserpolicy.apply({"example.com"}, managed)
        res["policy"]["written"] = [browserpolicy._read_list(v) for v in browserpolicy.VENDORS]
        time.sleep(3)
        res["policy"]["during"] = dump("https://example.com")
    except OSError as e:
        res["policy"]["error"] = str(e)
    finally:
        try:
            browserpolicy.apply(set(), managed)
        except OSError as e:
            res["policy"]["cleanup_error"] = str(e)
        res["policy"]["after_lists"] = [browserpolicy._read_list(v) for v in browserpolicy.VENDORS]
        res["policy"]["after"] = dump("https://example.com")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


def policy_hold(seconds, flag_path, domain="example.com"):
    """검증용: example.com 만 브라우저 정책으로 seconds 초 막았다가 원복. 시작/끝을 flag 파일에 기록."""
    import time
    from engine import browserpolicy
    managed = {domain}
    try:
        browserpolicy.apply({domain}, managed)
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("ON " + repr([browserpolicy._read_list(v) for v in browserpolicy.VENDORS]) + "\n")
        time.sleep(seconds)
    except OSError as e:
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write(f"ERR {e}\n")
    finally:
        browserpolicy.apply(set(), managed)
        with open(flag_path, "a", encoding="utf-8") as f:
            f.write("OFF " + repr([browserpolicy._read_list(v) for v in browserpolicy.VENDORS]) + "\n")


def main():
    if "--policy-hold" in sys.argv:
        i = sys.argv.index("--policy-hold")
        policy_hold(int(sys.argv[i + 1]), sys.argv[i + 2], *(sys.argv[i + 3:i + 4]))
        os._exit(0)
    if "--block-selftest" in sys.argv:
        block_selftest(sys.argv[sys.argv.index("--block-selftest") + 1])
        os._exit(0)
    if "--hosts-selftest" in sys.argv:
        hosts_selftest(sys.argv[sys.argv.index("--hosts-selftest") + 1])
        os._exit(0)
    if "--selftest" in sys.argv:
        selftest(sys.argv[sys.argv.index("--selftest") + 1])
        os._exit(0)
    if not winutil.single_instance():
        winutil.message_box("이미 실행 중이에요. 작업 표시줄 오른쪽 트레이 아이콘을 확인하세요.")
        return
    minimized = "--minimized" in sys.argv
    tray = {"icon": None}

    def notify(title, msg):
        ic = tray["icon"]
        if ic is not None:
            try:
                ic.notify(msg, title)
            except Exception:
                pass

    engine = Engine(notify=notify)
    engine.start()
    api = Api(engine)

    window = webview.create_window(
        "도파민 디톡스", resource("ui", "index.html"), js_api=api,
        width=1000, height=680, min_size=(840, 580), hidden=minimized,
        background_color="#f2f1ec",
    )
    api._window = window
    quitting = {"v": False}

    def on_closing():
        if quitting["v"]:
            return True
        window.hide()
        notify("트레이에서 계속 동작 중", "아이콘을 더블클릭하면 다시 열려요.")
        return False

    window.events.closing += on_closing

    def do_quit():
        quitting["v"] = True
        engine.shutdown()
        window.destroy()

    def on_started():
        tray["icon"] = make_tray(window, engine, do_quit)

    storage = os.path.join(os.environ.get("APPDATA", "."), "DopamineDetox", "webview")
    try:
        webview.start(on_started, private_mode=False, storage_path=storage, gui="edgechromium")
    finally:
        engine.shutdown()
        if tray["icon"] is not None:
            try:
                tray["icon"].stop()
            except Exception:
                pass
        os._exit(0)


if __name__ == "__main__":
    main()
