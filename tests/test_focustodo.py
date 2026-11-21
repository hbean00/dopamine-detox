"""Focus To-Do 판정 테스트 — 2026-11-18 실측한 화면 구조를 그대로 재현."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.focustodo import FocusToDoWatcher, classify, remaining_seconds  # noqa: E402

# ---- 1) 하단 플로팅 타이머 (실측 클래스)
R = "Timer-root-1NNf3 Timer-animation-2BDvS Timer-float-16rJl Timer-withTask-1-yXC"
base = [R, "Timer-bgi-13jbG", "FloatTimer-root-3_uz_", "FloatTimer-timer-2RdpT", "FloatTimer-actions-YG_w6"]
assert classify([], base + ["FloatTimer-start-3nvWr"], 30, {}) == ("idle", "30분")
assert classify([], base + ["FloatTimer-pause-27B29"], 29, {}) == ("focus", "29분")
assert classify([], base + ["FloatTimer-start-3nvWr", "FloatTimer-stop-1zDyB"], 29, {}) == ("paused", "29분")
assert classify([], base + ["FloatTimer-completeRest-2OJcD"], 4, {}) == ("break", "4분")
assert classify([], [], None, {}) == ("idle", None)

# ---- 2) 전체 화면 타이머 (실측: 버튼 클래스는 상태와 무관, 글자 '일시정지' + mm:ss 카운트다운)
FS = ["Timer-root-1NNf3 Timer-animation-2BDvS Timer-fullscreen-1hnGU", "Timer-bgi-13jbG",
      "FullscreenTimer-root-1wlsO", "FullscreenTimer-countdown-3IUFG", "FullscreenTimer-actions-2ivuY",
      "FullscreenTimer-actionWithoutBackground-3Lyki"]
texts_run = ["보고서 작성 - 1장 정리", "5", "16:43", "일시정지", "전체 화면", "타이머 모드"]
assert classify(texts_run, FS, None, {}, now=100)[0] == "focus"          # '일시정지' 글자만으로 즉시 진행 판정
p = {}
assert classify(["16:43", "계속"], FS, None, p, now=100)[0] == "paused"  # 일시정지 화면(버튼 '계속')
assert classify(["16:43", "계속"], FS, None, p, now=110)[0] == "paused"  # 숫자도 그대로
p = {}
classify(["16:43"], FS, None, p, now=100)
assert classify(["16:41"], FS, None, p, now=102) == ("focus", "16:41")  # 버튼 글자를 못 읽어도 숫자가 줄면 진행

# ---- 3) 남은 시간
assert remaining_seconds("16:43") == 1003 and remaining_seconds("1:02:03") == 3723
assert remaining_seconds("29분") == 29 * 60 + 59 and remaining_seconds(None) is None


# ---- 4) 감시기: 최소화(못 읽음) 동안 유지, 해제는 2회 연속 확인
class W(FocusToDoWatcher):
    pass


changes = []
w = W(on_change=lambda o, n, i: changes.append((o, n)))
w.apply_reading(texts_run, FS, None, True, now=1000)
assert w.status == "focus" and abs(w._expected_end - (1000 + 1003)) < 1
w.apply_reading(["Focus To-Do", "최소화"], [], None, False, now=1010)       # 최소화
assert w.status == "focus" and w.hidden and w.timer == "16:33", (w.status, w.timer)
w.apply_reading([], [], None, False, now=1000 + 1003 + 30)                  # 예상 종료 + 30초 지나면 해제
assert w.status == "idle"

w2 = W()
w2.apply_reading(texts_run, FS, None, True, now=50000)
w2.apply_reading(["16:43", "계속"], FS, None, True, now=50010)                  # 한 번 '일시정지 화면' 판독
assert w2.status == "focus"                                                   # 아직 유지 (깜빡임 방지)
w2.apply_reading(["16:43", "계속"], FS, None, True, now=50012)
assert w2.status == "paused"                                                  # 2회 연속이면 해제
w2.apply_reading(texts_run, FS, None, True, now=50014)
assert w2.status == "focus"                                                   # 다시 거는 건 즉시
print("FOCUSTODO TESTS PASSED")
