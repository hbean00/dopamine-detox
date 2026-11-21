"""웨일(Chromium) 세션 파일(SNSS)에서 지금 열린 탭 주소를 읽는다.

실측(2026-11-21): 웨일은 --restore-last-session 으로 다시 띄워도 탭을 복원하지 않았다.
그래서 재시작 전에 세션 파일에서 탭별 '현재 페이지' 주소를 뽑아, 다시 열 때 그 주소들로 연다.

SNSS 형식: 'SNSS' + int32 버전, 이후 [uint16 크기][uint8 명령 id][payload]... 반복.
  6  UpdateTabNavigation : pickle(int tab_id, int nav_index, string url, ...)
  7  SetSelectedNavigationIndex : (int tab_id, int index)
  16 TabClosed : (int tab_id, int64 time)
  (창이 닫힌 탭 등은 무시 — 마지막에 살아 있는 탭만)
"""
import glob
import os
import struct

CMD_UPDATE_NAV = 6
CMD_SELECTED_NAV = 7
CMD_TAB_CLOSED = 16
CMD_WINDOW_CLOSED = 17


def _commands(data):
    if data[:4] != b"SNSS":
        return
    i = 8
    n = len(data)
    while i + 2 <= n:
        size = struct.unpack_from("<H", data, i)[0]
        i += 2
        if size == 0 or i + size > n:
            break
        yield data[i], data[i + 1:i + size]
        i += size


def _pickle_nav(payload):
    # pickle: uint32 payload_size, int32 tab_id, int32 index, int32 url_len, url bytes (4바이트 정렬)
    if len(payload) < 16:
        return None
    _sz, tab_id, index, ulen = struct.unpack_from("<Iiii", payload, 0)
    if ulen < 0 or 16 + ulen > len(payload):
        return None
    url = payload[16:16 + ulen].decode("utf-8", "replace")
    return tab_id, index, url


def tab_urls(session_file):
    """세션 파일 하나 → 살아 있는 탭들의 현재 주소 목록 (열린 순서)."""
    data = open(session_file, "rb").read()
    navs = {}       # tab_id -> {index: url}
    selected = {}   # tab_id -> index
    closed = set()
    order = []
    for cid, payload in _commands(data):
        if cid == CMD_UPDATE_NAV:
            r = _pickle_nav(payload)
            if r:
                tab_id, index, url = r
                navs.setdefault(tab_id, {})[index] = url
                if tab_id not in order:
                    order.append(tab_id)
        elif cid == CMD_SELECTED_NAV and len(payload) >= 8:
            tab_id, index = struct.unpack_from("<ii", payload, 0)
            selected[tab_id] = index
        elif cid == CMD_TAB_CLOSED and len(payload) >= 4:
            closed.add(struct.unpack_from("<i", payload, 0)[0])
    out = []
    for t in order:
        if t in closed or t not in navs:
            continue
        idx = selected.get(t, max(navs[t]))
        url = navs[t].get(idx) or navs[t][max(navs[t])]
        if url.startswith(("http://", "https://", "file://")) and url not in out:
            out.append(url)
    return out


def latest_session_file(user_data_dir=None):
    ud = user_data_dir or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Naver", "Naver Whale", "User Data")
    files = []
    for prof in ("Default", "Profile *"):
        files += glob.glob(os.path.join(ud, prof, "Sessions", "Session_*"))
    return max(files, key=os.path.getmtime) if files else None


def current_tab_urls(user_data_dir=None):
    f = latest_session_file(user_data_dir)
    if not f:
        return []
    try:
        return tab_urls(f)
    except (OSError, struct.error):
        return []
