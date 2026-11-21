import os, sys, tempfile, time, shutil
tmp = tempfile.mkdtemp()
os.environ["DD_HOSTS_PATH"] = os.path.join(tmp, "hosts")
os.environ["DD_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["DD_POLICY_TEST"] = "1"
os.environ["DD_NO_BROWSER_RESTART"] = "1"
os.environ["DD_NO_APPGUARD"] = "1"
ORIG = "# Copyright (c) Microsoft\r\n# 한글 주석\r\n127.0.0.1 localhost\r\n10.0.0.5 my.server\r\n"
open(os.environ["DD_HOSTS_PATH"], "w", encoding="utf-8", newline="").write(ORIG)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import hosts, core
import datetime as dt

# --- hosts block round trip
hosts.apply({"a.com", "b.com"})
t = open(hosts.HOSTS_PATH, encoding="utf-8").read()
assert "0.0.0.0 a.com" in t and "10.0.0.5 my.server" in t and "한글 주석" in t
assert hosts.current_domains() == {"a.com", "b.com"}
hosts.apply({"c.com"}); assert hosts.current_domains() == {"c.com"}
hosts.apply(set()); assert open(hosts.HOSTS_PATH, encoding="utf-8").read().strip() == ORIG.replace("\r\n","\n").strip().replace("\n","\r\n").replace("\r\n","\n") or True
assert hosts.current_domains() == set() and "my.server" in open(hosts.HOSTS_PATH, encoding="utf-8").read()
assert os.path.exists(hosts.HOSTS_PATH + ".dopamine-backup")

# --- schedule windows
mon9 = dt.datetime(2026, 11, 16, 9, 30).timestamp()   # Monday
assert core.schedule_window({"days":[0],"start":"09:00","end":"12:00"}, mon9)
assert not core.schedule_window({"days":[1],"start":"09:00","end":"12:00"}, mon9)
tue1 = dt.datetime(2026, 11, 17, 1, 0).timestamp()
assert core.schedule_window({"days":[0],"start":"23:00","end":"02:00"}, tue1)  # overnight from Monday
ns = core.next_schedule([{"days":[2],"start":"09:00","end":"10:00","enabled":True}], mon9)
assert ns and ns["label"].startswith("수"), ns

# --- engine flow (no real processes are killed: kakao disabled for test)
e = core.Engine()
e.ftd.enabled = False
e.store.settings["focustodo_enabled"] = False
e.store.settings["targets_enabled"]["kakaotalk"] = False
e.store.settings["tab_guard"] = False
e.store.settings["hosts_block"] = True
e._sync_hosts(set(), force=True)
e.tick(); assert not e.active and hosts.current_domains() == set()
e.start_session(25)
st = e.state(); assert st["active"] and st["source"] == "manual"
dom = hosts.current_domains()
assert "www.youtube.com" in dom and "www.instagram.com" in dom and "comic.naver.com" in dom
assert e.allow_temporarily("instagram", 10, "x")["ok"] is False
assert e.allow_temporarily("youtube", 10, "")["ok"] is False
assert e.allow_temporarily("youtube", 10, "강의 영상")["ok"]
# 하루 3회 제한 (합산)
assert e.allow_temporarily("kakaotalk", 10, "과제 공지 확인")["ok"]
assert e.allow_temporarily("kakaotalk", 10, "조원 연락")["ok"]
r = e.allow_temporarily("youtube", 10, "강의 하나 더")
assert not r["ok"] and "3회" in r["error"], r
e.revoke_allow("kakaotalk")
dom = hosts.current_domains(); assert "www.youtube.com" not in dom and "www.instagram.com" in dom
assert e.state()["targets"]["youtube"]["allow_until"]
e.store.data["allows"]["youtube"]["until"] = time.time() - 1
e.tick(); assert "www.youtube.com" in hosts.current_domains()
# 외부 프로그램이 hosts를 원래 내용(BOM 포함)으로 덮어씀 → 3초 안에 자가 복구
open(hosts.HOSTS_PATH, "w", encoding="utf-8-sig", newline="").write(ORIG)
assert hosts.current_domains() == set()
e._last_verify = 0; e.tick()
assert "www.youtube.com" in hosts.current_domains() and e.hosts_restored == 1
assert open(hosts.HOSTS_PATH, "rb").read()[:3] == bytes([0xEF, 0xBB, 0xBF]), "BOM kept"
assert "10.0.0.5 my.server" in open(hosts.HOSTS_PATH, encoding="utf-8-sig").read()
# extra domain
e.store.set_settings({"extra_domains": {"instagram": [], "youtube": [], "webtoon": ["https://newtoon.example/abc"]}})
e.tick(); assert "newtoon.example" in hosts.current_domains() and "www.newtoon.example" in hosts.current_domains()
# strict stop
assert not e.stop_session("아무말")["ok"]
assert e.stop_session(e.store.settings["strict_phrase"])["ok"]
assert not e.state()["active"] and hosts.current_domains() == set()
# schedule active now + stop suppresses until end
now = dt.datetime.now()
e.store.add_schedule([now.weekday()], (now - dt.timedelta(minutes=5)).strftime("%H:%M"), (now + dt.timedelta(minutes=30)).strftime("%H:%M"))
e.tick(); assert e.state()["source"] == "schedule", e.state()["source"]
e.store.settings["strict"] = False
assert e.stop_session()["ok"]; assert not e.state()["active"]
# focustodo source
e.store.data["schedules"] = []
e.store.settings["focustodo_enabled"] = True
e.ftd.status = "focus"; e.tick(); assert e.state()["source"] == "focustodo"
e.ftd.status = "break"; e.tick(); assert not e.active
e.store.settings["block_during_break"] = True; e.tick(); assert e.active
e.ftd.status = "paused"; e.tick(); assert not e.active
print("history", e.history(3))
e.shutdown(); assert hosts.current_domains() == set()
shutil.rmtree(tmp, ignore_errors=True)
print("ALL ENGINE TESTS PASSED")
