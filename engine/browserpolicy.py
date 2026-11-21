"""브라우저 정책(URLBlocklist)으로 차단 — hosts 보호 프로그램(은행 보안 프로그램 등)과 무관하게 동작.

Chromium 계열은 레지스트리 SOFTWARE\\Policies\\<vendor>\\URLBlocklist 의 값 "1","2",… 을 읽는다.
정책이 바뀌면 브라우저가 레지스트리 변경을 감지해 바로 다시 읽는다 (관리자 권한 필요).
우리가 넣은 항목만 관리하고, 원래 있던 항목은 그대로 둔다.
"""
import os
import winreg

VENDORS = [
    r"SOFTWARE\Policies\Naver\Naver Whale",
    r"SOFTWARE\Policies\Google\Chrome",
    r"SOFTWARE\Policies\Microsoft\Edge",
]
LIST = "URLBlocklist"
ALLOW = "URLAllowlist"   # v2 3단계: URLBlocklist ["*"] + 허용 사이트
HIVE = winreg.HKEY_LOCAL_MACHINE
if os.environ.get("DD_POLICY_TEST"):  # 단위 테스트: 관리자 권한 없이 HKCU 아래 테스트 키 사용
    HIVE = winreg.HKEY_CURRENT_USER
    VENDORS = [v.replace(r"SOFTWARE\Policies", r"SOFTWARE\DopamineDetoxTest") for v in VENDORS]


def _read_list(path, name=LIST):
    try:
        with winreg.OpenKey(HIVE, path + "\\" + name) as k:
            vals, i = [], 1
            while True:
                try:
                    v, _ = winreg.QueryValueEx(k, str(i))
                except FileNotFoundError:
                    break
                vals.append(v)
                i += 1
            return vals
    except FileNotFoundError:
        return []


def _write_list(path, items, name=LIST):
    full = path + "\\" + name
    if not items:
        try:
            winreg.DeleteKey(HIVE, full)
        except FileNotFoundError:
            pass
        return
    with winreg.CreateKeyEx(HIVE, full, 0, winreg.KEY_ALL_ACCESS) as k:
        # 기존 값 모두 지우고 1..N 으로 다시 씀
        while True:
            try:
                name, _, _ = winreg.EnumValue(k, 0)
                winreg.DeleteValue(k, name)
            except OSError:
                break
        for i, v in enumerate(items, 1):
            winreg.SetValueEx(k, str(i), 0, winreg.REG_SZ, v)


def current(managed, name=LIST):
    """각 브라우저 목록에 들어 있는 우리 항목 (교집합, 브라우저 간 공통)."""
    sets = [set(_read_list(p, name)) & managed for p in VENDORS]
    return set.intersection(*sets) if sets else set()


def refresh():
    """실행 중인 브라우저가 정책을 바로 다시 읽게 그룹 정책 갱신 알림을 보낸다.
    (실측: 알림 없이 키만 새로 만들면 실행 중인 웨일은 정책을 바로 반영하지 않았다)"""
    if HIVE != winreg.HKEY_LOCAL_MACHINE:
        return
    try:
        import ctypes
        userenv = ctypes.windll.userenv
        userenv.RefreshPolicyEx(True, 1)   # machine, RP_FORCE
        userenv.RefreshPolicyEx(False, 1)  # user
    except Exception:
        pass


def apply(want, managed, want_allow=(), managed_allow=()):
    """want: 막을 패턴 집합. managed: 우리가 관리하는 모든 패턴(지울 대상).
    want_allow / managed_allow: URLAllowlist 쪽 (3단계). 실패 시 OSError."""
    changed = False
    for p in VENDORS:
        for name, w, m in ((LIST, want, managed), (ALLOW, want_allow, managed_allow)):
            existing = [v for v in _read_list(p, name) if v not in m]
            new = existing + sorted(w)
            if new != _read_list(p, name):
                _write_list(p, new, name)
                changed = True
        # 브라우저가 시작할 때 감시할 수 있도록 vendor 키는 비어 있어도 남겨 둔다
        try:
            winreg.CreateKeyEx(HIVE, p, 0, winreg.KEY_WRITE).Close()
        except OSError:
            pass
    if changed:
        refresh()
