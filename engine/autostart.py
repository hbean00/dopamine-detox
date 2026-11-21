"""로그인 시 자동 실행: 작업 스케줄러에 '가장 높은 권한'으로 등록 (UAC 창 없이 시작)."""
import subprocess
import sys

TASK = "DopamineDetox"
CREATE_NO_WINDOW = 0x08000000


def _cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    return f'"{sys.executable}" "{sys.argv[0]}" --minimized'


def set_autostart(enabled):
    if enabled:
        args = ["schtasks", "/Create", "/TN", TASK, "/TR", _cmd(), "/SC", "ONLOGON",
                "/RL", "HIGHEST", "/F", "/DELAY", "0000:15"]
    else:
        args = ["schtasks", "/Delete", "/TN", TASK, "/F"]
    r = subprocess.run(args, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0 and enabled:
        return {"ok": False, "error": (r.stderr or r.stdout or "작업 스케줄러 등록 실패").strip()}
    return {"ok": True}
