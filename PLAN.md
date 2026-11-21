# 도파민 디톡스 (Focus Lock) — 구현 계획

> 노트북에서 업무·공부에 몰입하도록, 정해진 시간 동안 딴짓 사이트와 앱을 막는 Windows 데스크톱 앱.
> 결과물은 바탕화면의 `DopamineDetox.exe` 하나.

---

## 1. 이 PC에서 확인한 것

| 항목 | 확인 결과 | 설계에 미치는 영향 |
|---|---|---|
| OS | Windows 11 Home 26200 | WebView2 기본 탑재 → pywebview UI 사용 가능 |
| 브라우저 | Naver Whale (Chromium) | hosts 파일 차단이 그대로 먹힘, 창 제목으로 탭 감지 가능 |
| 카카오톡 | `C:\Program Files\Kakao\KakaoTalk\KakaoTalk.exe` | 프로세스 감시 후 종료 방식으로 차단 |
| Focus To-Do | MS Store판 7.2.2 (`FocusToDo.exe`, WinForms + WebView2) | 공개 API 없음. 내부 저장소는 LevelDB라 읽기 불안정 → **UI Automation으로 화면의 타이머 글자를 읽는 방식** 채택 (실제로 UIA 트리 접근 확인함) |
| Python | 3.12 + pywebview 6.2, pystray, uiautomation, psutil, PyInstaller 6.22 | 전부 설치 완료 |

---

## 2. 기술 구성

```
DopamineDetox.exe  (PyInstaller --onefile, 관리자 권한 요구 manifest)
├─ app.py            진입점: 창 + 트레이 + 백그라운드 엔진 스레드
├─ engine/
│   ├─ hosts.py      hosts 파일에 차단 블록 쓰기/지우기 + DNS 캐시 비우기
│   ├─ apps.py       카카오톡 같은 프로그램 감시·종료
│   ├─ tabguard.py   브라우저 창 제목에 차단 키워드가 보이면 그 탭 닫기 (Ctrl+W)
│   ├─ focustodo.py  Focus To-Do 타이머 감지 (UIA)
│   ├─ scheduler.py  지금 시작 / 반복 일정 / Focus To-Do 연동 → "지금 차단해야 하나?" 판단
│   └─ state.py      설정·기록 JSON 저장 (%APPDATA%\DopamineDetox)
└─ ui/               HTML/CSS/JS (frontend-design 스킬로 디자인)
```

- **UI**: pywebview(WebView2) 위에 HTML/CSS/JS. Python ↔ JS는 `window.pywebview.api`로 통신.
- **권한**: hosts 파일 수정에 관리자 권한이 필요 → exe 실행 시 UAC 창이 1번 뜸.
  (설정에서 "로그인 시 자동 실행"을 켜면 작업 스케줄러에 *가장 높은 권한*으로 등록 → 매번 UAC 안 뜸)
- **창 닫기 = 트레이로 숨기기**. 완전 종료는 트레이 메뉴에서만 (차단 중엔 종료도 마찰 단계를 거침).

---

## 3. 차단 방식

| # | 대상 | 방식 | 공부용 허용 버튼 |
|---|---|---|---|
| 1 | Instagram | hosts 차단 (`instagram.com`, `www.`, `i.`, `l.`, `graph.`, `static.cdninstagram.com` …) + 탭 감시 | 없음 |
| 2 | YouTube | hosts 차단 (`youtube.com`, `www.`, `m.`, `music.`, `youtu.be`, `youtubei.googleapis.com`, `i.ytimg.com` …) + 탭 감시 | **있음** — 사유 입력 + 15/30/60분 선택 → 그 시간만 hosts에서 빼고 탭 감시도 멈춤, 끝나면 자동 재차단 |
| 3 | 카카오톡 | `KakaoTalk.exe` 프로세스를 2초마다 확인해 종료 | **있음** — 같은 방식으로 일정 시간 허용 |
| 4 | 웹툰 | hosts 차단 (`comic.naver.com`, `m.comic.naver.com`, `webtoon.kakao.com`, `page.kakao.com`, `webtoons.com`, `lezhin.com`, `bomtoon.com`, `toomics.com` …) + 탭 감시 | 없음 |
| 5 | AI 업무 관련성 경고 | 맨 앞 창 제목을 Claude CLI(haiku)로 주기 판정 → 무관하면 알림 (8절 참고) | — |

**왜 hosts + 탭 감시 둘 다?**
hosts만 쓰면 이미 열려 있던 유튜브 탭은 기존 연결로 계속 돌아갈 수 있음. 그래서 차단 중에는 브라우저 맨 앞 창 제목에 `YouTube`, `Instagram`, `웹툰` 같은 단어가 보이면 그 탭을 닫음(Ctrl+W). 반대로 탭 감시만 쓰면 제목이 안 바뀌는 경우를 놓치므로 둘을 겹침.

**안전장치**
- hosts에는 `# >>> DopamineDetox` ~ `# <<< DopamineDetox` 사이에만 씀. 그 밖의 줄은 건드리지 않음.
- 앱 시작 시, 차단 중이 아닌데 블록이 남아 있으면 자동 정리 (강제 종료·전원 꺼짐 대비).
- 첫 수정 전에 `hosts.dopamine-backup` 백업.

---

## 4. 차단 시간 정하기

세 가지 방식이 동시에 존재하고, **하나라도 "지금 차단"이면 차단**.

1. **지금 시작** — 30/60/90분 프리셋 또는 직접 입력. 바로 차단 시작.
2. **반복 일정** — 요일 + 시작~끝 시각 (예: 월~금 09:00–12:00). 여러 개 등록.
3. **Focus To-Do 연동** — 포모도로가 돌고 있으면 자동 차단, 휴식·정지되면 자동 해제.
   - 휴식 중에도 계속 막을지 옵션.

**중도 해제 마찰(엄격 모드)**: 차단 중에 "그만하기"를 누르면 문장(예: `나는 지금 집중을 포기합니다`)을 그대로 타이핑해야 해제. 끌 수 있는 옵션.

---

## 5. Focus To-Do 연동 원리

1. `FocusToDo.exe` 창을 찾고, UI Automation으로 그 안의 요소(글자 + 웹 CSS 클래스명)를 읽음.
2. **실측 결과(7.2.2)**: 하단 플로팅 타이머의 버튼 클래스로 상태가 드러남.

   | Focus To-Do 상태 | 보이는 버튼 클래스 | 타이머 숫자 | 앱 판단 |
   |---|---|---|---|
   | 대기 | `FloatTimer-start` | `30` | idle → 차단 안 함 |
   | 포모도로 진행 | `FloatTimer-pause` | `29` (분 단위) | **focus → 자동 차단** |
   | 일시정지 | `FloatTimer-start` + `FloatTimer-stop` | `29` | paused → 차단 안 함 |
   | 휴식 | `FloatTimer-completeRest` | `4` | break → 옵션에 따라 |

3. 숫자는 `mm:ss`가 아니라 **분만** 표시돼서 숫자 변화로는 판단이 느림 → 버튼 클래스를 1순위로 사용, `mm:ss` 변화는 보조.
4. 2026-11-18 실제로 포모도로를 시작 → 차단 시작(hosts에 YouTube 등 추가), 일시정지·정지 → 해제까지 끝에서 끝까지 확인함.

> 테스트 중 포모도로를 두 번 켰다 껐음 ("ASIC LAB3" 작업). 한 번은 정지 후 휴식 화면으로 넘어가서 휴식 끝내기로 되돌림 → Focus To-Do 기록에 짧은 집중 기록이 남았을 수 있음.
> Focus To-Do 창을 트레이로 완전히 숨기면 화면 갱신이 멈출 수 있음 → 설정의 "연동 진단"으로 확인.

### Focus To-Do 연동 보완 (2026-11-18 실사용 피드백)
- 증상: 포모도로 시작 시 차단은 걸렸지만(14:03) 5분 뒤 `idle`로 잘못 읽어 풀림(14:08).
- 원인 1 — **전체 화면 타이머 모드**: 버튼 클래스가 상태와 무관(`FullscreenTimer-actionWithoutBackground`), 대신 버튼 글자 `일시정지` + `mm:ss` 카운트다운이 매초 바뀜.
- 원인 2 — **창 최소화**: 웹 내용이 UIA에 노출되지 않음(창 버튼 몇 개만 보임) → 읽을 게 없어 `idle`.
- 원인 3 — 카운트다운이 매초 다시 그려져 2~3초 걸리는 탐색 도중 요소가 사라지면 회차 전체가 실패, 한 번의 잘못된 판독으로 바로 해제.
- 수정: 전체 화면 모드 판정(버튼 글자·카운트다운), 최소화 중엔 마지막 카운트다운의 예상 종료 시각까지 유지, 요소 단위로 오류를 삼키는 탐색 + 큰 하위 트리 건너뛰기, 해제는 2회 연속 판독, 탐색 스레드 watchdog, 상태 변화를 log.txt에 기록.
- 확인: 실제 전체 화면 포모도로에서 소스 실행·빌드된 exe 모두 즉시 `focus` 판정. 최소화 유지와 깜빡임 방지는 실측 화면 구조로 만든 테스트(`tests/test_focustodo.py`)로 확인.

### hosts가 외부에서 되돌려지는 문제 → 차단 방식 변경 (실측, 2026-11-18)
- 관리자 실행 중 hosts에 블록을 쓰면 몇 초 안에 이전 사본으로 되돌아가고, 블록을 지우면 다시 생김.
  범인은 **AhnLab Safe Transaction**의 hosts 보호(사용자 화면에 hosts 복원 경고가 반복해서 뜸).
- 그래서 **기본 차단을 브라우저 정책 URLBlocklist로 바꿈** (웨일·크롬·엣지 공식 기능, 레지스트리 `HKLM\SOFTWARE\Policies\...`).
  hosts는 설정에서 켤 때만 쓰고, 기본값이면 hosts 파일을 한 번도 쓰지 않음 (`tests/test_policy.py`로 확인).
- 실측 결과
  - 엣지: 정책을 쓰는 즉시 차단, 지우면 즉시 해제.
  - 웨일: 정책이 켜진 동안 새로 띄운 웨일은 차단(`example.com - Whale` 오류 페이지), 끄면 열림.
  - **이미 켜져 있던 웨일은 정책 변경을 바로 반영하지 않음** (정책 갱신 알림을 보내도 instagram.com이 열림, UIA로 탭 이름 확인).
  - 그래서 실행 중인 브라우저는 **탭 감시**가 담당: 실제 웨일로 세션을 돌려 Instagram·YouTube 탭을 열자 **1초 안에 자동으로 닫힘** (`tests/verify_live_session.py`, 로그 `맨 앞 탭 닫음` 2건). 뒤쪽 탭은 사용자가 그 탭으로 전환하는 순간 닫힘.
  - UIA로 뒤쪽 탭의 닫기 버튼을 누르는 방식도 시험했지만 웨일 탭이 닫히지 않아 채택하지 않음.
- 한계: 브라우저 밖 앱(인스타그램 데스크톱 앱 등)은 정책 대상이 아님. 필요하면 Windows 방화벽 규칙이나 NRPT(DNS 정책) 방식을 다음 단계로 검토.

---

## 6. 화면 구성 (frontend-design)

- **홈**: 큰 상태 표시(집중 중 / 대기), 남은 시간, 무엇이 막혀 있는지 4개 칩, "지금 시작" 버튼과 프리셋.
- **허용 요청 시트**: YouTube·카카오톡 카드에서 "공부용으로 잠깐 열기" → 사유 + 시간 → 허용 카운트다운 표시.
- **일정**: 요일·시간 블록 목록, 추가/삭제/켜기·끄기.
- **기록**: 오늘 집중 시간, 차단 횟수(막힌 시도 수), 허용 사용 내역.
- **설정**: 대상별 켜기·끄기, 도메인 추가, 엄격 모드, 휴식 중 차단, 자동 실행, Focus To-Do 연동 진단, AI 경고(곧 추가).

---

## 7. 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 0 | 환경 확인, 작업 폴더, 이 문서 | ✅ |
| 1 | 엔진: hosts / 앱 종료 / 탭 감시 / 스케줄러 / 저장 | ✅ (`tests/test_engine.py` 통과) |
| 2 | Focus To-Do 감지 + 진단 패널 | ✅ 실제 포모도로로 시작·일시정지·정지·휴식 감지 확인 |
| 3 | UI 디자인·구현 | ✅ (서브에이전트, frontend-design) |
| 4 | PyInstaller로 exe → 바탕화면 | ✅ `Desktop\DopamineDetox.exe` |
| 5 | 테스트 (가짜 hosts 단위 테스트, pywebview 실창 연결, frozen exe selftest, Focus To-Do 실연동) | ✅ / 관리자 실행에서 hosts 자가 복구 동작은 다음 실사용 때 log.txt로 확인 |
| 6 | AI 업무 관련성 경고 | ✅ Claude CLI haiku, 5분 간격 |

---

## 8. 구현 논의 — 결정 사항 (2026-11-18 사용자 답변)

| # | 주제 | 결정 | 반영 |
|---|---|---|---|
| 1 | 잠깐 열기 횟수 | **하루 3회 제한** (YouTube·카카오톡 합산, 사유 필수, 기본 15분) | ✅ v1 반영 — 설정에서 1/2/3/5회·제한 없음 선택, 4번째는 거절 (`tests/test_engine.py`) |
| 2 | 엄격 모드 | 켜짐 유지 | ✅ |
| 3 | 유튜브 허용 범위 | **특정 채널·재생목록만 허용** | ⏭ v2 — 브라우저 정책 `URLAllowlist` + 탭 감시가 허용 영상은 건너뛰도록 바꿔야 함 (유튜브는 페이지 이동 없이 영상이 바뀌어 URL 정책만으로는 부족, 설계 필요) |
| 4 | 카카오톡 차단 강도 | **프로세스 종료 유지** | ✅ |
| 5 | AI 업무 관련성 경고 | **Claude CLI(haiku)로 주기 판정** (사용자 제안: 5분마다) | ✅ v1 반영 — 아래 참고 |
| 6 | 차단 방식 | 브라우저 정책(기본) + 탭 감시, hosts는 선택 | ✅ |
| 7 | 추가 차단 대상 | 4종 + 설정에서 도메인 직접 추가 | 프리셋(뉴스·쇼핑·X·틱톡·디스코드)은 필요할 때 추가 |

### AI 업무 관련성 경고 (v1)
- 집중 중 **5분마다**(3/5/10/15분 선택) 맨 앞 창의 **제목과 프로그램 이름만** 이미 로그인된 Claude Code CLI(haiku)에 보내 판정. 화면 내용·URL은 보내지 않음.
- 설정의 "지금 하는 업무"(예: ASIC 설계 LAB3 보고서 작성)를 기준으로 판정 → 무관하면 Windows 알림 + 오늘 기록에 남김.
- 비용 실측: MCP·설정·도구를 끈 최소 호출(`--strict-mcp-config --setting-sources "" --disable-slash-commands --tools ""`)은 **1회 약 900토큰, $0.0002, 9~14초**. 기본 호출은 사용자 MCP·스킬 정의가 들어가 $0.004~0.16이었음.
- 실측 판정: "침착맨 레전드 모음 - YouTube" → 무관, "lab3_report.docx - Word" → 관련.
- 기본은 꺼짐(창 제목이 외부로 나가므로 사용자가 켬). 설정의 "시험하기"로 직전에 보던 창을 바로 판정해 볼 수 있음.
