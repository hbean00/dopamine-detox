"""hosts 파일에 차단 블록을 쓰고 지운다. 블록 밖의 줄은 절대 건드리지 않는다."""
import os
import shutil
import stat
import subprocess

BEGIN = "# >>> DopamineDetox (자동 생성, 이 블록은 앱이 관리합니다)"
END = "# <<< DopamineDetox"

HOSTS_PATH = os.environ.get(
    "DD_HOSTS_PATH",
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers", "etc", "hosts"),
)

CREATE_NO_WINDOW = 0x08000000


def _read():
    with open(HOSTS_PATH, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "mbcs"):
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1"), "latin-1"


def strip_block(text):
    lines = text.splitlines()
    out, inside = [], False
    for ln in lines:
        s = ln.strip()
        if s.startswith("# >>> DopamineDetox"):
            inside = True
            continue
        if s.startswith(END):
            inside = False
            continue
        if not inside:
            out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    return out


def build(text, domains):
    out = strip_block(text)
    if domains:
        out.append("")
        out.append(BEGIN)
        for d in sorted(domains):
            out.append(f"0.0.0.0 {d}")
            out.append(f":: {d}")
        out.append(END)
    return "\r\n".join(out) + "\r\n"


def current_domains():
    try:
        text, _ = _read()
    except OSError:
        return set()
    res, inside = set(), False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("# >>> DopamineDetox"):
            inside = True
        elif s.startswith(END):
            inside = False
        elif inside and s and not s.startswith("#"):
            parts = s.split()
            if len(parts) >= 2:
                res.add(parts[1])
    return res


def flush_dns():
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=10,
                       creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def apply(domains):
    """domains 집합으로 블록을 맞춘다. 바뀐 게 있으면 True. 실패하면 OSError."""
    text, enc = _read()
    new = build(text, domains)
    if new.replace("\r\n", "\n").strip() == text.replace("\r\n", "\n").strip():
        return False
    backup = HOSTS_PATH + ".dopamine-backup"
    if not os.path.exists(backup):
        try:
            shutil.copy2(HOSTS_PATH, backup)
        except OSError:
            pass
    try:
        mode = os.stat(HOSTS_PATH).st_mode
        if not mode & stat.S_IWRITE:
            os.chmod(HOSTS_PATH, mode | stat.S_IWRITE)
    except OSError:
        pass
    with open(HOSTS_PATH, "w", encoding=enc, newline="") as f:  # 원래 인코딩(BOM 포함) 유지
        f.write(new)
    flush_dns()
    return True
