"""v2 집중 강도 테스트 — 단계별 규칙, 배타성, 정책 내용, 허용 앱, 겹칠 때 가장 엄격한 단계.
실제 창 닫기·웨일 재시작·프로세스 종료는 하지 않는다 (환경 변수 + 가짜 함수)."""
import datetime as dt
import os
import subprocess
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DD_HOSTS_PATH"] = os.path.join(tmp, "hosts")
os.environ["DD_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["DD_POLICY_TEST"] = "1"
os.environ["DD_NO_BROWSER_RESTART"] = "1"
os.environ["DD_NO_APPGUARD"] = "1"
open(os.environ["DD_HOSTS_PATH"], "w").write("127.0.0.1 localhost\n")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from engine import browserpolicy as bp  # noqa: E402
from engine import core, levels  # noqa: E402
from engine.appguard import decide  # noqa: E402

W = bp.VENDORS[0]
S = {"extra_domains": {}, "targets_enabled": {k: True for k in ("instagram", "youtube", "kakaotalk", "webtoon")},
     "allowed_sites": ["lms.example.ac.kr"], "allowed_apps": ["code.exe", "winword.exe"]}

# ---------- 1. 단계별 규칙 (사다리: 위 단계는 아래 단계 차단을 전부 포함)
p1, p2, p3, p4 = (levels.plan(i, S) for i in (1, 2, 3, 4))
assert "www.youtube.com" in p1["block"] and "coupang.com" not in p1["block"]
assert p1["block"] <= p2["block"] and "coupang.com" in p2["block"] and "netflix.com" in p2["block"]
assert p1["kill"] <= p2["kill"] and "discord.exe" in p2["kill"]
assert p1["temp_allow"] and not p2["temp_allow"] and not p3["temp_allow"] and not p4["temp_allow"]
assert p1["ai"] and p2["ai"] and not p3["ai"] and not p4["ai"]
assert p3["block"] == {"*"} and {"claude.ai", "anthropic.com", "lms.example.ac.kr"} <= p3["allow"]
assert "claude.exe" in p3["allowlist_apps"] and "code.exe" in p3["allowlist_apps"]
assert p4["block"] == {"*"} and p4["allow"] == set(levels.LOCAL_SITES)   # 4단계: 외부 웹 없음, localhost만
assert {"localhost", "127.0.0.1", "[::1]"} <= p3["allow"]                 # 3단계: Claude로 만든 로컬 개발 서버
assert "claude.exe" not in p4["allowlist_apps"] and "claude.exe" in p4["kill"]
assert p3["needs_restart"] and p4["needs_restart"] and not p1["needs_restart"] and not p2["needs_restart"]
# 1단계에서 끈 대상은 1단계에서만 빠지고, 2단계부터는 예외 없이 막힘
S_off = dict(S, targets_enabled=dict(S["targets_enabled"], youtube=False))
assert "www.youtube.com" not in levels.plan(1, S_off)["block"]
assert "www.youtube.com" in levels.plan(2, S_off)["block"]

# ---------- 2. 배타성: 1·2단계 차단 대상은 3단계 허용 사이트에 못 넣음
for bad in ("youtube.com", "https://m.youtube.com/watch?v=1", "news.naver.com", "www.instagram.com", "comic.naver.com"):
    clean, err = levels.validate_allowed_sites([bad], {})
    assert err and not clean, bad
clean, err = levels.validate_allowed_sites(["https://lms.example.ac.kr/course", "claude.ai", "mail.example.com"], {})
assert err is None and clean == ["lms.example.ac.kr", "mail.example.com"]   # claude.ai는 항상 허용이라 목록에 안 넣음
_, err = levels.validate_allowed_sites(["myfun.example"], {"webtoon": ["myfun.example"]})  # 사용자가 1단계에 추가한 것도
assert err

# ---------- 3. 허용 앱 판정 (순수 함수)
wins = [(1, 10, "code.exe", "a"), (2, 11, "kakaotalk.exe", "b"), (3, 12, "explorer.exe", "c"), (4, 13, "steam.exe", "d")]
assert [w[2] for w in decide(wins, p4["allowlist_apps"])] == ["kakaotalk.exe", "steam.exe"]

# ---------- 4. 엔진: 단계별 정책·잠깐 열기·상태
e = core.Engine()
killed = []
e._kill_processes = lambda names, now: killed.append(set(names))     # 실제 종료 금지
restarts = []
e._restart_whale_async = lambda why: restarts.append(why)             # 실제 웨일 재시작 금지
s = e.store.settings
s.update(focustodo_enabled=False, tab_guard=False, strict=False, allowed_sites=["lms.example.ac.kr"])
e.tick()
assert e.level is None and bp._read_list(W) == []

e.start_session(30, 2)
st = e.state()
assert st["level"] == 2 and st["level_name"] == "깊은 집중" and len(st["levels"]) == 4
assert not st["targets"]["youtube"]["allowable"]
assert e.allow_temporarily("youtube", 10, "강의 영상")["ok"] is False      # 2단계엔 잠깐 열기 없음
pol = bp._read_list(W)
assert "coupang.com" in pol and "instagram.com" in pol and "*" not in pol
assert any("discord.exe" in k for k in killed) and not restarts

e.start_session(30, 3)
assert e.level == 3
assert bp._read_list(W) == ["*"]
allow = bp._read_list(W, bp.ALLOW)
assert {"claude.ai", "claude.com", "anthropic.com", "lms.example.ac.kr", "localhost", "127.0.0.1", "[::1]"} == set(allow), allow
assert e.appguard.calls and "claude.exe" in e.appguard.calls[-1]
assert restarts == ["Claude만 정책 적용"], restarts
assert "허용 사이트 1곳" in " ".join(e.state()["rules_now"])

e.start_session(30, 4)
assert bp._read_list(W) == ["*"] and set(bp._read_list(W, bp.ALLOW)) == {"localhost", "127.0.0.1", "[::1]"}
assert "claude.exe" not in e.appguard.calls[-1] and any("claude.exe" in k for k in killed)
assert restarts[-1] == "오프라인 정책 적용"

assert e.stop_session()["ok"]
assert bp._read_list(W) == [] and bp._read_list(W, bp.ALLOW) == []
assert restarts[-1] == "3·4단계 차단 해제"                              # 나올 때도 웨일 재시작 (정책 해제 반영)
st = e.state()
assert st["level"] is None and st["rules_now"] == []

# 1단계는 잠깐 열기 가능
e.start_session(30, 1)
assert e.allow_temporarily("youtube", 10, "강의 영상")["ok"]
assert "youtube.com" not in bp._read_list(W)
e.stop_session()

# ---------- 5. 엄격 모드: 집중 중 더 약한 단계로 못 바꿈
s["strict"] = True
e.start_session(30, 3)
r = e.start_session(30, 1)
assert r["ok"] is False and "약한 단계" in r["error"]
assert e.level == 3
s["strict"] = False
e.stop_session()

# ---------- 6. 겹치면 가장 엄격한 단계: 수동 1단계 + 일정 4단계 → 4단계
now = dt.datetime.now()
e.store.add_schedule([now.weekday()], (now - dt.timedelta(minutes=5)).strftime("%H:%M"),
                     (now + dt.timedelta(minutes=30)).strftime("%H:%M"), 4)
assert e.store.schedules()[-1]["level"] == 4
e.start_session(30, 1)
assert e.level == 4 and e.source == "schedule"
e.store.data["schedules"] = []
e.tick()
assert e.level == 1 and e.source == "manual"
e.stop_session()

# ---------- 7. Focus To-Do는 설정한 단계로
s["focustodo_enabled"] = True
s["focustodo_level"] = 2
e.ftd.status = "focus"
e.tick()
assert e.source == "focustodo" and e.level == 2
e.ftd.status = "idle"
e.tick()
assert e.level is None

e.shutdown()
subprocess.run(["reg", "delete", r"HKCU\SOFTWARE\DopamineDetoxTest", "/f"], capture_output=True)
print("LEVEL TESTS PASSED")
