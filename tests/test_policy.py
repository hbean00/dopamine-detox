"""브라우저 정책 계층 테스트 (HKCU 테스트 키 사용, 관리자 권한 불필요)."""
import os
import shutil
import subprocess
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DD_HOSTS_PATH"] = os.path.join(tmp, "hosts")
os.environ["DD_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["DD_POLICY_TEST"] = "1"
open(os.environ["DD_HOSTS_PATH"], "w").write("127.0.0.1 localhost\n")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import browserpolicy as bp  # noqa: E402
from engine import core  # noqa: E402

assert bp.VENDORS[0].startswith("SOFTWARE\\DopamineDetoxTest"), bp.VENDORS
W = bp.VENDORS[0]
try:
    e = core.Engine()
    e.store.settings["focustodo_enabled"] = False
    e.store.settings["targets_enabled"]["kakaotalk"] = False
    e.store.settings["tab_guard"] = False
    e.tick()
    assert bp._read_list(W) == []

    # 사용자가 원래 갖고 있던 항목
    bp._write_list(W, ["user-own.example"])
    e.start_session(25)
    lst = bp._read_list(W)
    assert lst[0] == "user-own.example", lst
    for d in ("instagram.com", "youtube.com", "comic.naver.com", "webtoons.com"):
        assert d in lst, (d, lst)
    for v in bp.VENDORS:
        assert "instagram.com" in bp._read_list(v)
    assert e.policy_error is None, e.policy_error

    # 공부용 유튜브 허용 → 정책에서도 빠짐
    assert e.allow_temporarily("youtube", 10, "강의 영상")["ok"]
    lst = bp._read_list(W)
    assert "youtube.com" not in lst and "instagram.com" in lst

    # 외부에서 정책을 지움 → 5초 주기 검증에서 복구
    bp._write_list(W, ["user-own.example"])
    e._policy_verify = 0
    e.tick()
    assert "instagram.com" in bp._read_list(W)

    # 종료 → 우리 항목만 지우고 사용자 항목은 남김
    e.store.settings["strict"] = False
    assert e.stop_session()["ok"]
    assert bp._read_list(W) == ["user-own.example"], bp._read_list(W)
    e.shutdown()
    assert bp._read_list(W) == ["user-own.example"]

    # 기본값(hosts_block 꺼짐)이면 hosts 파일은 한 번도 쓰지 않는다 → AhnLab 복원 경고 없음
    hp = os.environ["DD_HOSTS_PATH"]
    before = (open(hp, "rb").read(), os.path.getmtime(hp))
    e2 = core.Engine()
    assert e2.store.settings["hosts_block"] is False
    e2.store.settings["focustodo_enabled"] = False
    e2.store.settings["targets_enabled"]["kakaotalk"] = False
    e2.store.settings["tab_guard"] = False
    e2.start()
    e2.start_session(10)
    e2._last_verify = 0
    e2.tick()
    assert "instagram.com" in bp._read_list(W)
    e2.store.settings["strict"] = False
    e2.stop_session()
    e2.shutdown()
    assert (open(hp, "rb").read(), os.path.getmtime(hp)) == before, "hosts must be untouched"
    print("BROWSER POLICY TESTS PASSED")
finally:
    subprocess.run(["reg", "delete", r"HKCU\SOFTWARE\DopamineDetoxTest", "/f"], capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)
