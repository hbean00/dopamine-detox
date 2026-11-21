"""AI 업무 관련성 경고 — Claude Code CLI(haiku)로 맨 앞 창이 업무와 관련 있는지 판정.

사용자 결정(2026-11-18): API 키 대신 이미 로그인된 Claude CLI를 쓰고, 집중 중 5분마다 판정.
비용 실측: MCP·설정·도구를 끈 최소 호출은 1회 약 900토큰, $0.0002 (기본 호출은 $0.004~0.16).
보내는 정보: 업무 설명 + 맨 앞 창 제목 + 프로그램 이름. 화면 내용·URL은 보내지 않는다.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from . import winutil

CREATE_NO_WINDOW = 0x08000000
SYSTEM_PROMPT = "You are a focus assistant. Reply with exactly one line of JSON and nothing else."
SKIP_EXES = {"dopaminedetox.exe", "dopaminedetox_test.exe", "explorer.exe", "lockapp.exe", ""}


def find_cli():
    path = shutil.which("claude")
    if path:
        return path
    cand = os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")
    return cand if os.path.exists(cand) else None


def build_prompt(work, title, exe):
    work = (work or "").strip() or "공부 또는 업무 (구체적인 내용은 적지 않음)"
    return (
        f"업무 설명: {work}\n"
        f"현재 맨 앞 창 제목: '{title}' (프로그램: {exe})\n"
        "이 창이 업무 설명과 관련 있으면 related는 true. 업무 도구(문서·코드·메일·검색 등)나 애매한 경우도 true.\n"
        '형식: {"related": true 또는 false, "reason": "15자 이내 한국어"}'
    )


def parse(text):
    m = re.search(r"\{.*?\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(d.get("related"), bool):
        return None
    return {"related": d["related"], "reason": str(d.get("reason", ""))[:60]}


def ask_claude(prompt, cli=None, timeout=90):
    cli = cli or find_cli()
    if not cli:
        raise RuntimeError("Claude CLI(claude)를 찾지 못했어요.")
    args = [cli, "-p", "--model", "haiku", "--output-format", "json",
            "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands",
            "--system-prompt", SYSTEM_PROMPT, "--tools", ""]
    r = subprocess.run(args, input=prompt.encode("utf-8"), capture_output=True, timeout=timeout,
                       cwd=tempfile.gettempdir(), creationflags=CREATE_NO_WINDOW)
    out = r.stdout.decode("utf-8", "replace")
    try:
        result = json.loads(out).get("result", "")
    except ValueError:
        raise RuntimeError((r.stderr.decode("utf-8", "replace") or out or "CLI 응답 없음").strip()[:200])
    verdict = parse(result)
    if verdict is None:
        raise RuntimeError(f"판정을 읽지 못했어요: {result[:80]}")
    return verdict


class AIGuard:
    def __init__(self, engine, log, notify):
        self.e = engine
        self.log = log
        self.notify = notify
        self.last = None          # {"at", "title", "exe", "related", "reason"} 또는 {"at", "error"}
        self._next = 0
        self._stop = threading.Event()
        self._busy = False

    def start(self):
        threading.Thread(target=self._run, name="aiguard", daemon=True).start()

    def stop(self):
        self._stop.set()

    def check_now(self):
        """설정 화면의 '지금 시험' 버튼용 — 결과를 바로 돌려준다."""
        return self._check(force=True)

    def _run(self):
        while not self._stop.is_set():
            s = self.e.store.settings
            now = time.time()
            allowed = self.e.plan.get("ai", True)  # v2: 1·2단계에서만 (3단계는 허용 목록, 4단계는 Claude 불가)
            if s.get("ai_warning") and self.e.active and allowed and now >= self._next and not self._busy:
                self._next = now + max(1, int(s.get("ai_interval_min", 5))) * 60
                res = self._check()
                if res.get("skipped"):
                    self._next = now + 30  # 맨 앞 창이 없으면(자리 비움 등) 30초 뒤 다시
            elif not (s.get("ai_warning") and self.e.active and allowed):
                self._next = 0  # 집중이 시작되면 첫 판정은 바로
            self._stop.wait(5)

    def _check(self, force=False):
        hwnd, exe, title = winutil.foreground()
        if (not title or exe in SKIP_EXES) and self.e.last_fg:
            title, exe = self.e.last_fg  # 이 앱을 보고 있으면 직전에 보던 창으로 판정
        if not title or exe in SKIP_EXES:
            res = {"at": time.time(), "skipped": True, "title": title, "exe": exe}
            if force:
                self.last = res
            return res
        self._busy = True
        try:
            v = ask_claude(build_prompt(self.e.store.settings.get("work_description"), title, exe))
            res = {"at": time.time(), "title": title, "exe": exe, **v}
            self.last = res
            self.log(f"AI 판정: {'관련' if v['related'] else '무관'} — {title} ({v['reason']})")
            if not v["related"]:
                self.e.store.day().setdefault("ai_warnings", []).append(
                    {"at": res["at"], "title": title[:80], "reason": v["reason"]})
                self.e.store.touch()
                self.notify("업무와 관련 없어 보여요", f"{v['reason']} · {title[:40]}")
            return res
        except Exception as ex:
            res = {"at": time.time(), "error": str(ex)[:200]}
            self.last = res
            self.log(f"AI 판정 실패: {ex}")
            return res
        finally:
            self._busy = False
