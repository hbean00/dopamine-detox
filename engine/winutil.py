"""Win32 helpers via ctypes: foreground window, process names, keystrokes, admin."""
import ctypes
import ctypes.wintypes as wt
import os

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def is_admin():
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def process_path(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def window_pid(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def foreground():
    """(hwnd, exe_name_lower, title)"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, "", ""
    pid = window_pid(hwnd)
    exe = os.path.basename(process_path(pid)).lower()
    return hwnd, exe, window_title(hwnd)


KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_W = 0x57


def send_ctrl_w():
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_W, 0, 0, 0)
    user32.keybd_event(VK_W, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def message_box(text, title="도파민 디톡스"):
    user32.MessageBoxW(None, text, title, 0x40)


_mutex = None


def single_instance(name="Global\\DopamineDetoxSingleton"):
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, name)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
