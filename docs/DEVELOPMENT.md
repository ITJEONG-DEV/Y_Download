# Y_Downloader — 개발 문서

> 이 문서는 작업을 **언제든 중단하고 재개**할 수 있도록 프로젝트의 목표·구조·진행 상황·다음 할 일을 기록한다.
> 새 세션을 시작할 때 이 문서를 먼저 읽으면 현재 상태를 파악할 수 있다.

- 최종 수정: 2026-07-08
- 저장소 경로: `F:\Git\Y_Download`

---

## 1. 프로젝트 개요

유튜브 영상 URL을 붙여넣으면 **영상(mp4 등) 또는 음원(mp3 등)** 으로 다운로드하는 Windows 데스크톱 프로그램.

### 핵심 요구사항
| # | 요구사항 | 상태 |
|---|----------|------|
| 1 | URL 조회 시 영상 정보(제목·썸네일·길이) 표시 | ✅ 구현 |
| 2 | 포맷(영상/음원)·해상도/음질 선택 | ✅ 구현 |
| 3 | 다운로드 위치 선택 | ✅ 구현 (공통/일괄) |
| 4 | **여러 개를 목록에 추가해 일괄 다운로드** | ✅ 구현 |
| 5 | 항목별 **파일명·확장자·포맷·품질 개별 설정** | ✅ 구현 |
| 6 | 저장 위치는 **일괄(공통) 설정** | ✅ 구현 |
| 7 | **마지막 저장 위치 기억** (settings.json) | ✅ 구현 |
| 8 | **선택 포맷/품질 기준 예상 파일 크기 표시** | ✅ 구현 |
| 9 | **다운로드 내역**: 성공/실패 기록, 우측 사이드 패널로 조회, 더블클릭 재추가, 단일·전체 삭제 | ✅ 구현 |
| 10 | **파일명 입력 커서 편의**: Up=맨앞 / Down=맨뒤 | ✅ 구현 |
| 11 | **반응형 목록 행**: 폭에 따라 제목 줄바꿈·파일명 신축(잘림 방지) | ✅ 구현 |
| 12 | 배포용 단독 실행 exe (full/lite 2종) | ✅ 구현 (`build.py`) |
| 13 | **버전 태그 기반 GitHub Release 자동 배포** | ✅ 구현 (GitHub Actions) |
| 14 | **자동 업데이트**: 실행 시 최신 버전 확인 → 모달(변경요약 포함) → 확인 시 자동 교체·재시작 | ✅ 구현 (`updater.py`) |
| 15 | 저장 위치 **[열기]** 버튼(다운로드 폴더를 탐색기로) | ✅ 구현 |
| 16 | **창 위치/크기/모니터 기억** — 화면 밖이면 주모니터 중앙 기본크기로 | ✅ 구현 |
| 17 | **파일명 중복 처리 정책** — 자동번호/덮어쓰기/건너뛰기(설정 선택·기억, 기본 자동번호) | ✅ 구현 |

---

## 2. 기술 스택 (결정 사항)

| 구분 | 선택 | 이유 |
|------|------|------|
| 언어 | **Python 3.14** | 다운로드 표준 엔진 yt-dlp가 Python 라이브러리 |
| 다운로드 엔진 | **yt-dlp** | 정보조회·포맷목록·다운로드 모두 담당, 유지보수 활발 |
| 후처리 | **ffmpeg** | mp3 변환, 영상+음성 병합에 필수 (외부 바이너리) |
| GUI | **PySide6 (Qt)** | 네이티브 위젯·부드러운 스크롤, 모델/뷰. (구 CustomTkinter에서 이식) |
| 이미지 | **Pillow + requests** | 썸네일 다운로드/표시 |
| 배포 | **PyInstaller** | 단독 실행 exe 생성 (ffmpeg 번들 포함 예정) |

### UI 형태 / 배포 방식 (사용자 확정)
- UI: **데스크톱 GUI** (웹앱/CLI 아님)
- 배포: **배포용 exe** (다른 사람에게 배포 가능한 단독 실행파일)

---

## 3. 프로젝트 구조

```
Y_Download/
├── docs/
│   └── DEVELOPMENT.md      # (이 문서) 개발 진행/재개용 기록
├── src/
│   ├── downloader.py       # 핵심 로직: yt-dlp 래핑 (정보조회 + 다운로드 + 크기추정)
│   ├── config.py           # 설정(마지막 저장위치) + 다운로드 내역 JSON 영구저장
│   └── app.py              # PySide6(Qt) GUI (진입점)
├── bin/                    # (선택) ffmpeg.exe를 여기 두면 자동 사용
├── requirements.txt
├── README.md
└── .gitignore
```

### 모듈 책임 분리
- **downloader.py** — GUI와 완전 분리. 단독 CLI 테스트 가능(`python src/downloader.py`).
  - `fetch_info(url) -> VideoInfo` : 제목·썸네일·길이·업로더·사용 가능 해상도 + 크기추정 데이터 조회
  - `download(url, output_dir, *, kind, ext, max_height, audio_bitrate, filename, progress_callback) -> str`
  - `estimate_size(info, *, kind, max_height, audio_bitrate) -> int|None` : 예상 파일 크기(bytes)
  - `format_size(bytes) -> str` : 사람이 읽는 크기 문자열, `sanitize_filename(name)` : 파일명 정리
  - `VideoInfo` 데이터클래스, `VIDEO_EXTS`/`AUDIO_EXTS` 상수
- **config.py** — 설정·내역 JSON 영구저장(`%APPDATA%/Y_Downloader/`).
  - `get_download_dir/set_download_dir` : 마지막 저장 위치 기억(settings.json)
  - `load_history/add_history/delete_history/clear_history` : 내역(history.json), 항목마다 고유 `id`
- **app.py** — UI만 담당. 조회/다운로드 등 무거운 작업은 **스레드**에서 실행하고
  `self.after(0, ...)`로 메인 스레드에서 UI 갱신 (tkinter 스레드 안전성 확보).
  - `DownloadRow(CTkFrame)` : 목록의 한 항목. 중첩 pack 레이아웃(반응형), 자체 위젯 + `VideoInfo` 보유.
    - `get_params()` : 다운로드 파라미터 dict 반환, `_cursor_home/_cursor_end` : 파일명 커서 이동
    - `_update_estimate()` : 포맷/품질 변경 시 예상 크기 갱신
  - `HistoryPanel(CTkFrame)` : 우측 내역 사이드 패널. 더블클릭 재추가 / 🗑 단일삭제 / 전체 지우기.
  - `App(CTk)` : 좌우 분할 창(좌=목록, 우=내역 패널). URL 추가 / 목록 관리 / 저장위치 / 일괄 다운로드.
    - `toggle_history()` + `_resize_for_panel()` : 패널 토글 및 창모드/최대화별 폭 조정.

---

## 4. 동작 흐름

```
[URL 입력] → [목록에 추가] → (백그라운드 조회) → 목록에 DownloadRow 추가
                                                   │
              각 행: 썸네일·제목·길이 표시           │
                     파일명/확장자/포맷/품질 개별 설정 │
                                                   ▼
[저장위치(공통) 지정] → [전체 다운로드] → 행별 순차 다운로드 + 진행률 표시
```

- 포맷을 "음원"으로 바꾸면 확장자 목록이 `mp3/m4a/wav`, 품질이 비트레이트(320~128)로 자동 전환.
- 포맷이 "영상"이면 확장자 `mp4/mkv/webm`, 품질은 조회된 실제 해상도 목록.
- 진행률: 항목별 % + 전체 진행바(완료 항목 수 + 현재 항목 진행분).

### UI/UX 세부
- **예상 크기**: 각 행에 `예상: 45.3 MB` 표시, 포맷/품질 변경 시 실시간 갱신.
- **파일명 커서**: 파일명 입력창 포커스 상태에서 `Up`=커서 맨앞, `Down`=커서 맨뒤.
- **레이아웃 안정화**: OptionMenu는 `dynamic_resizing=False`로 폭 고정, 상태·예상크기 라벨은
  고정 폭 셀(`pack_propagate(False)`)에 배치 → 텍스트/포맷 변경 시 정렬 흔들림 없음.
- **반응형(성능 개선)**: 제목 줄바꿈(wraplength)은 **App이 창 레벨 `<Configure>`를 디바운스(120ms)**
  하여 리사이즈가 멈춘 뒤 모든 행에 한 번만 적용. 행마다 바인딩하던 방식은 리사이즈 시 이벤트
  폭주로 매우 느려서 제거함. 파일명 입력창은 신축.
- **내역 패널**: 우측 사이드 패널(폭 320px). 창모드에선 열/닫을 때 창 폭을 패널만큼 확장/축소
  (가상 데스크톱=모든 모니터 폭 기준 상한 — 주모니터 폭으로 판단하면 보조 모니터에서 창이
  주모니터로 튀므로 `_virtual_screen_bounds` 사용), 최대화 상태에선 목록과 공간 분할.
  **변경됐을 때만 다시 그림**(dirty 플래그).
  토글 시 **왼쪽 콘텐츠(`self.left`)를 현재 크기로 freeze**(`pack_propagate(False)`+`expand=False`)한 뒤
  창을 넓혀, 늘어난 폭이 오른쪽 패널 자리에만 가고 왼쪽 행들은 크기 변화가 없다 → 다운로드 행이
  다시 그려지지 않아 **전체 UI 재그리기 없이 패널만** 나타난다.
  닫을 때는 창 축소가 비동기(WM 왕복)이므로, 곧바로 unfreeze하면 왼쪽이 넓게 늘었다 줄며 깜빡인다.
  그래서 **창이 실제로 목표 폭까지 좁아진 것을 폴링 확인한 뒤 unfreeze**한다(`_schedule_unfreeze`).
  최대화(zoomed) 상태에선 창을 못 넓히므로 freeze를 건너뛴다(목록과 공간 분할).
  (CTk는 위젯 크기가 바뀔 때 그 위젯을 재그리므로, 크기를 안 바꾸는 게 핵심.)
  항목 형식: `[성공/실패] 영상명 (파일명)`. 접힘=1줄+넘치면 …(`_clamp_text`),
  펼침=전체 표시. 추가(＋,파랑)·삭제(🗑,빨강) 버튼은 **접힘·펼침 모두 제목 우측 상단에 place()로
  오버레이**. 제목은 전체 폭 라벨로, **첫 줄만 버튼 자리를 피하고 둘째 줄부터 전체 폭으로 흐르는**
  float 흉내(`_wrap_around`). 펼침 순서: 제목 → 썸네일 → 일시/포맷. 펼침 상태는 `_expanded` set.
  썸네일은 다운로드 시 `thumbs/{id}.jpg`로 저장(`_save_thumb`), 내역 삭제/한도초과 시 파일도 정리.

> 참고: CustomTkinter는 리사이즈마다 위젯 캔버스를 다시 그리는 구조라 근본 한계는 남지만,
> 위 디바운스 + 단일 핸들러 + 내역 dirty 플래그로 체감 지연을 크게 줄임.

### 내역 렌더 성능 — 가상 스크롤(뷰 리사이클링)
`CTkScrollableFrame`에 전 항목을 위젯으로 만들던 방식은 항목 수에 비례해 느려짐(50행 4.6초).
→ **`tk.Canvas` 기반 가상 스크롤**로 재작성(`HistoryPanel` + `_HistoryRow`):
- **뷰 리사이클링**: 보이는 개수(+여유 `BUFFER`)만큼만 행 위젯을 만들어 풀(pool)로 재활용,
  스크롤 시 `bind_entry`로 데이터만 갈아끼움. **200개 내역이어도 위젯은 ~14개** 고정.
- **높이 모델**: 접힘 행은 균일(1회 측정), 펼침 행은 `_measure_row.winfo_reqheight`로 실측·캐시(`_exp_h`).
  누적 오프셋(`_offsets`)으로 스크롤 위치↔항목 매핑(`bisect`).
- **폭 측정 캐시**: 말줄임 계산은 `CTkFont.measure`(개당 ~2.4ms) 대신 일반 tkinter 폰트 + 문자별
  캐시(`_charw`, 개당 ~0.008ms).
- **이동 vs 재그리기 분리**: 펼침/스크롤 시 안 바뀐 행은 `canvas.coords`로 위치만 이동(재그리기 없음),
  내용 바뀐 행만 `bind_entry`. 썸네일은 `_img_cache`로 1회만 로드.
- 성능: 접힘 항목 펼침 ~15ms, 스크롤 ~0.1s, 썸네일 항목 펼침 ~0.1~0.2s(CTkImage 그리기).

---

## 5. 개발 환경 세팅

```powershell
# 1) 가상환경 (권장)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) 의존성 설치
pip install -r requirements.txt

# 3) ffmpeg 준비 (둘 중 하나)
#   a. 시스템 PATH에 ffmpeg 설치  (winget install Gyan.FFmpeg)
#   b. ffmpeg.exe를 프로젝트 bin/ 폴더에 복사  → downloader.py가 자동 인식

# 4) 실행
python src/app.py
```

> ⚠️ **현재 개발 PC에 ffmpeg가 설치되어 있지 않음(PATH에 없음).**
> 영상+음성 병합, mp3 변환에 필수이므로 위 3)을 반드시 먼저 처리할 것.

---

## 6. 배포 (exe 빌드) — ✅ 구현 (`build.py`)

두 가지 산출물을 만든다.

| 산출물 | 명령 | 방식 | ffmpeg | 결과물 |
|--------|------|------|--------|--------|
| **full (기본)** | `python build.py full` | 폴더형(onedir) | **포함** | `dist/Y_Downloader/` (ffmpeg essentials 기준 ~100MB, full build 사용 시 더 큼) |
| **lite (라이트)** | `python build.py lite` | 단일파일(onefile) | 미포함 | `dist/Y_Downloader-lite.exe` (~27MB) |

> exe에는 개발자명 등 메타데이터(버전 리소스)가 포함된다 — `build.py`의 `DEV_NAME` 수정으로 변경.
> (Authenticode 서명 인증서는 아니며, 파일 속성 "자세히" 탭 표기용.)

```powershell
pip install pyinstaller
python build.py           # full + lite 모두
python build.py full      # 폴더형만
python build.py lite      # 라이트만
```

- 공통: `--windowed --collect-submodules/-data yt_dlp`, `--paths src`. (PySide6 Qt 플러그인은
  PyInstaller 내장 훅이 자동 번들)
- full: `bin/ffmpeg.exe`, `bin/ffprobe.exe`를 `ffmpeg/` 하위로 번들 → 런타임에 자동 인식.
- 아이콘: `assets/app.ico`가 있으면 자동 적용(`--icon`).
- 검증됨: 두 빌드 성공, full exe 실행 시 GUI 정상 기동(스모크 테스트 통과).

### ffmpeg 탐색 순서 (`downloader.py._ffmpeg_location`)
1. **번들(full)**: `sys._MEIPASS/ffmpeg/ffmpeg.exe` (폴더형의 `_internal/ffmpeg/`)
2. **실행파일 옆(lite)**: `<exe>/ffmpeg.exe`, `<exe>/ffmpeg/ffmpeg.exe`, `<exe>/bin/ffmpeg.exe`
3. **개발 환경**: 프로젝트 `../bin/ffmpeg.exe`
4. 위 모두 없으면 **시스템 PATH**의 ffmpeg 사용

### 배포 방법
- **full**: `dist/Y_Downloader/` 폴더 전체를 zip으로 압축해 전달 → 받는 사람은 압축 풀고
  `Y_Downloader.exe` 실행. ffmpeg 포함이라 추가 설치 불필요.
- **lite**: `Y_Downloader-lite.exe` 단일 파일. **ffmpeg 미포함**이므로 받는 사람이 아래 중 하나 필요:
  - 시스템에 ffmpeg 설치(`winget install Gyan.FFmpeg`), 또는
  - `ffmpeg.exe`를 **exe와 같은 폴더**(또는 그 아래 `ffmpeg/`·`bin/`)에 배치.
  - → 이 안내를 lite exe와 함께 동봉할 것. (`docs/lite-ffmpeg-안내.md` 참고)

---

## 6-1. 릴리스 / 버전 태그 자동 배포

버전은 `src/version.py`의 `__version__`이 단일 소스이며, 앱 창 제목에 `v{버전}`으로 표시된다.
릴리스는 **Git 태그 push**로 트리거된다 — `.github/workflows/release.yml`(GitHub Actions).

### ✅ 릴리스 체크리스트 (매 릴리스 이 순서대로)

> 순서대로 진행. **7번(main 반영)은 이제 CI가 자동 처리**하지만(v0.3.0에서 누락됐던 이력),
> 자동 fast-forward가 불가능(분기)하면 CI가 경고만 남기므로 그때는 수동으로 반영한다.

1. **dev 그린 확인** — 로컬에서 `pytest` 전체 통과(네트워크·e2e 제외는 기본값). dev push 후
   `test.yml`도 초록인지 확인.
2. **버전 결정** — 태그 규칙 `vMAJOR.MINOR.PATCH`. 새 기능=MINOR, 버그수정=PATCH.
3. **로컬 버전 올려 커밋** — `src/version.py`의 `__version__`을 새 버전으로 바꿔 커밋하고 dev push.
   (CI도 태그에서 버전을 다시 stamp하지만, 로컬 기본값을 맞춰두면 dev 실행/혼선 방지.)
4. **주석 태그 생성** — 태그 메시지가 곧 릴리스 노트의 "변경사항"이 된다(§6-2 참고).
   ```powershell
   git tag -a v1.2.0 -m "- 기능 A 추가`n- 버그 B 수정"
   git push origin v1.2.0
   ```
5. **CI(release.yml) 성공 확인** — 세 잡 모두 초록이어야 한다:
   `test`(게이트) → `build-and-release`(Windows) + `build-macos`(macOS). 상태는 공개 API로 확인
   (`api.github.com/repos/ITJEONG-DEV/Y_Download/actions/runs`).
   - **실패 시**: 원인 수정 → dev에 커밋·push → `git tag -f -a v1.2.0 -m "…"` 로 태그를 새 커밋에
     옮기고 `git push origin v1.2.0 --force`. (릴리스는 test 게이트 통과 전엔 발행 안 되므로 안전.)
6. **릴리스 자산 확인** — Release에 4종이 붙었는지: `Y_Downloader-full-<v>.zip`,
   `Y_Downloader-lite-<v>.zip`, `Y_Downloader-mac-<v>.dmg`, `Y_Downloader-mac-<v>.zip`.
7. **main 반영 — 자동** — `release.yml`의 `update-main` 잡이 두 빌드 성공 후 main을 릴리스
   커밋으로 **fast-forward**하고 push한다(관례: 릴리스 코드 = main, v0.1.8·v0.2.0·v0.3.0).
   - fast-forward 불가(main이 분기됨)면 CI가 `::warning::`만 남기고 실패하지 않으므로, 이때만 수동:
     ```powershell
     git checkout main; git merge --ff-only dev; git push origin main; git checkout dev
     ```
   - GITHUB_TOKEN push라 test.yml을 재트리거하지 않는다(무한루프 방지). main 브랜치 보호가 켜져 있으면
     자동 push가 막힐 수 있으니 그 경우에도 위 수동 절차 사용.

### 워크플로 동작 (`release.yml`)
- **test** (windows-latest): 의존성 설치 → `pytest -m "not network and not e2e"`.
  게이트 — 실패 시 아래 빌드 잡이 실행되지 않아 깨진 릴리스를 막는다.
  (e2e는 실제 유튜브·ffmpeg가 필요해 CI에서 제외. `not network`만 쓰면 pyproject 기본값을 덮어써
  e2e가 돌아 실패하므로 **반드시 `not network and not e2e`**.)
- **build-and-release** (windows-latest, `needs: test`): 태그에서 버전 stamp →
  ffmpeg essentials 받아 `bin/` 배치 → `python build.py all`(full+lite) → zip 패키징 →
  태그 메시지로 릴리스 본문 구성 → `softprops/action-gh-release`로 Release 생성·첨부.
- **build-macos** (macos-latest, `needs: test`): 정적 ffmpeg(arch 감지) 번들 →
  `python build.py full`(.app) → `ditto` zip + `hdiutil` dmg → 같은 태그 릴리스에 자산만 추가.
  (PyInstaller 크로스컴파일 불가 → macOS는 별도 러너 필수. 현재 arm64 단일, **서명·공증 없음**.)

### 버전 올리기 메모
- 평소 개발 중에는 `src/version.py`를 손댈 필요 없음(태그가 릴리스 버전을 결정).
- 태그 규칙: `vMAJOR.MINOR.PATCH` (예: `v1.2.0`).

---

## 6-2. 자동 업데이트 (`updater.py`)

- 실행 1.5초 후 백그라운드 스레드로 GitHub `releases/latest` 조회(패키지 빌드에서만, dev는 건너뜀).
- 최신 태그가 현재 `__version__`보다 높으면 모달 표시:
  "새로운 버전이 릴리즈 되었습니다 / 현재 X → 새 버전 Y / 변경 내용(요약) / [확인] [나중에]".
- **[확인]**: 현재 빌드 종류에 맞는 zip을 받아 도우미 스크립트(Windows=PowerShell / macOS=bash)를
  실행하고 앱 종료. 도우미가 프로세스 종료를 기다렸다가 파일을 교체하고 재시작한다.
  진단 로그: `%TEMP%`(win)·`$TMPDIR`(mac)`/Y_Downloader_update.log`.
  - `lite`(win): 실행 중 exe는 덮어쓰기 불가하므로 **이동(rename) 후 새 파일 복사** (부트로더 잠금 회피)
  - `full`(win): 프로세스 완전 종료 후 폴더 덮어쓰기(사용자 데이터 삭제 없음)
  - `mac`: bash가 `ditto -x -k`로 zip 해제(심볼릭 링크/권한 보존)해 `.app`을 통째 교체 후 `open`
    재실행, 교체본의 `com.apple.quarantine` 제거. (Python `zipfile`은 `.app`을 손상시켜 사용 안 함.)
- 변경 요약: 릴리스 본문의 `<!--CHANGES-->…<!--/CHANGES-->` 구간(= 태그 메시지)에서 추출.
- 빌드 종류 판별(`build_kind`): 비프리즈 → dev, macOS(.app) → mac,
  frozen + `_internal` 폴더 존재 → full, 아니면 → lite.

### 릴리스 노트 변경요약 넣는 법
릴리스는 **주석 태그 메시지**가 "이번 버전 변경사항"이 된다.
```powershell
git tag -a v1.2.0 -m "자동 업데이트 추가
저장 폴더 열기 버튼 추가"
git push origin v1.2.0
```
워크플로가 `docs/release_body_template.md`의 `{{CHANGES}}`에 이 메시지를 넣어 Release 본문을 만든다.

> 주의: 자동 업데이트는 **그 기능이 포함된 버전부터** 동작한다(예: v0.1.2에 처음 탑재 시,
> v0.1.2 사용자가 v0.1.3부터 알림을 받음). 배포 위치가 Program Files 등 쓰기권한 없는 곳이면
> 교체에 관리자 권한이 필요할 수 있음(압축 풀어 쓰는 배포를 권장).

---

## 7. 진행 상황 / TODO

### 완료
- [x] 기술 스택 결정 및 문서화
- [x] `downloader.py` — 정보조회 + 다운로드 로직 (커스텀 파일명·확장자 지원)
- [x] `app.py` — 큐(목록) 기반 GUI, 항목별 개별 설정, 일괄 다운로드
- [x] 스레드 기반 비동기 조회/다운로드 + 진행률
- [x] 마지막 저장 위치 기억 (`config.py` → settings.json)
- [x] 선택 포맷/품질 기준 예상 파일 크기 표시 (`estimate_size`)
- [x] 다운로드 내역(성공/실패) 기록·조회, 더블클릭 시 목록 재추가
- [x] 내역을 우측 사이드 패널로 전환 + 단일(🗑)·전체 삭제, 패널 토글 시 창 폭 조정
- [x] 파일명 입력 커서 편의(Up/Down), OptionMenu 폭 고정, 반응형 행 레이아웃
- [x] 의존성 설치 및 핵심 로직(`fetch_info`/`estimate_size`/`config`) 동작 검증
- [x] PyInstaller 배포 빌드(`build.py`): full(폴더형+ffmpeg) / lite(단일파일) 2종, exe 기동 검증
- [x] 버전 단일 소스(`src/version.py`) + 창 제목 표기
- [x] 버전 태그 push 시 GitHub Actions가 빌드→Release 자동 배포(`.github/workflows/release.yml`)
- [x] 첫 릴리스 `v0.1.0` 발행 검증(full/lite zip 자산 확인)
- [x] 프로그램명 **Y_Downloader**로 변경(창 제목·빌드 산출물·설정 폴더)
- [x] exe 버전 리소스에 개발자명(`DEV_NAME`) 메타데이터 포함
- [x] 내역 패널 열 때 발생하던 `<Configure>`→wraplength 재귀 크래시 수정(after_idle + 상위 컨테이너 바인딩)
- [x] 자동 업데이트(`updater.py`): 실행 시 확인 모달(변경요약) + full/lite 자동 교체·재시작
- [x] 릴리스 노트 템플릿(`docs/release_body_template.md`) + 태그 메시지 기반 변경요약 주입
- [x] 저장 위치 [열기] 버튼(탐색기)
- [x] 창 위치/크기/최대화 상태 기억(settings.json) — 종료 시 저장, 실행 시 복원.
  가상 데스크톱 경계(ctypes)로 화면 밖·모니터 제거 감지 → 주모니터 중앙 기본크기로 폴백.
- [x] **자동 업데이트 실전 검증 완료** (v0.1.4 → v0.1.5: 알림 모달 → [확인] → 교체·재시작).
- [x] Auto update handles non-ASCII paths: replaced `cmd` batch helper with UTF-8 BOM PowerShell helper and `-LiteralPath`.
- [x] 파일명 중복 처리 정책(자동번호/덮어쓰기/건너뛰기) — 설정 드롭다운·기억, `download()`가
  `DownloadResult(path, status)` 반환(status: downloaded/skipped/overwritten).
- [x] **재생목록 URL 전체 추가**: 재생목록 감지(`is_playlist_url`) → 평면 조회(`fetch_playlist`,
  `extract_flat`)로 항목 목록만 빠르게 확보 → 개수 확인 팝업 → 제목만으로 대기열에 즉시 추가하고
  각 항목 상세정보(썸네일·해상도)는 워커 풀(`ENRICH_CONCURRENCY`)로 병렬 개별 조회해 행 갱신
  (`DownloadRow.update_info`). `watch?v=…&list=…`는 '이 영상만' 선택지 제공.
- [x] 팝업(업데이트/재생목록 안내)을 메인 창의 실제 화면 위치 기준 중앙에 배치(`_center_popup`,
  다중 모니터에서 다른 모니터에 뜨던 문제 해결).
- [x] **자동 테스트 파이프라인**(`tests/`, `pytest`): ① 순수 로직 단위 ② GUI 스모크(실제 Tk,
  네트워크 목킹) ③ 실네트워크 통합(수동). dev/main push·PR 시 `test.yml` 자동 실행, 릴리스는
  테스트 통과 후에만 진행(`release.yml` `needs: test`). 상세는 **`docs/TEST.md`** 참고.

### 완료 (추가)
- [x] **UI 프레임워크 CustomTkinter → PySide6(Qt) 전환** (`feature/qt-migration`).
  스크롤 잔상·끊김의 근본 원인이던 Tk 캔버스 렌더링을 벗어남. 백엔드
  (downloader/config/updater)·테스트 ①③ 그대로, `app.py`만 Qt로 재작성.
  내역 패널은 QDockWidget, 스레드→UI는 시그널 브리지(`_post`). GUI 테스트는
  `tests/test_gui.py`(Qt)로 교체. lite exe 빌드·기동 검증 완료. **v0.2.0**.
  > 위 "내역 렌더 성능 — 가상 스크롤" 등 CTk 시절 메모는 역사적 기록(현재는 Qt 네이티브 스크롤).

### 다음 할 일 (우선순위 순)
- [~] (후속) **macOS 배포** — 현재 Windows 전용(exe). Qt 전환으로 UI는 크로스플랫폼.
  진행 상황:
  - [x] **크로스플랫폼 런타임 코드** (Windows에서 단위 테스트 `tests/test_platform.py`로 검증):
    - `config._default_app_dir()` — OS별 설정 폴더(Windows `%APPDATA%` 유지 / macOS
      `~/Library/Application Support` / Linux `$XDG_CONFIG_HOME`·`~/.config`).
    - `downloader._ffmpeg_location`/`_ffmpeg_names` — 실행파일명(`ffmpeg` vs `ffmpeg.exe`),
      macOS `.app`(`Contents/Frameworks`·`Resources[/ffmpeg]`) 탐색, `isfile`로 폴더 오인 방지.
    - `app._open_in_file_manager` — 폴더 열기(Windows `startfile`/macOS `open`/Linux `xdg-open`).
  - [x] `build.py` macOS `.app` 빌드 분기 — `--windowed`(onedir)→`.app`, 아이콘 `.icns`, 버전
    리소스(`--version-file`)는 Windows 전용이라 생략, `--osx-bundle-identifier`. ffmpeg 실행파일명
    OS별 분기. Windows 산출물은 기존과 동일(회귀 없음).
  - [x] GitHub Actions `build-macos` 잡(`macos-latest`) — arch 자동감지 후 정적 ffmpeg/ffprobe
    (`eugeneware/ffmpeg-static b6.1.1`) 내려받아 번들, `.app`을 `ditto`로 zip + `hdiutil`로 `.dmg`
    패키징해 같은 태그 릴리스에 첨부. **현재 러너 아키텍처(arm64) 단일 빌드.**
  - [x] 자동 업데이트 macOS 대응(`updater.py`) — `build_kind()`가 `mac` 반환, `mac` zip 자산 선택,
    bash 도우미가 `ditto`로 압축 해제(심볼릭 링크/권한 보존)해 `.app` 통째 교체 후 `open` 재실행,
    교체본 `com.apple.quarantine` 제거. 단위 테스트 추가.
  - [ ] **코드 서명 + 공증(notarization)** — Gatekeeper 통과용(Apple Developer 인증서 필요, $99/년).
    없으면 사용자가 최초 실행 시 우클릭>열기로 "확인되지 않은 개발자" 경고를 수동 우회해야 함. **(보류)**
  - [ ] (선택) 유니버설(arm64+x86_64) 또는 x86_64 별도 빌드 — 현재 arm64 단일. Intel Mac 대응 필요 시 결정.
  - ⚠️ 위 macOS 빌드/CI/updater는 **Mac이 없어 이 PC에서 실행 검증 불가** — 코드/CI 레벨만 작성.
    실제 `.app` 기동·자동교체는 태그 push 시 CI 로그 및 Mac 실기기에서 확인 필요.
- [x] 다운로드 목록 상단 **포맷/확장자/품질 일괄 변경** 바 (재생목록 대량 추가 대비).
  URL 바 아래에 `일괄 적용` 바(포맷·확장자·품질 + [전체 적용]) 배치. 영상 품질은 **'≤ 목표 해상도'**
  로 각 행의 실제 가용 해상도 중 최적을 선택(정확히 일치하지 않아도 됨), 음원은 비트레이트 직접 적용.
  다운로드 중에는 비활성화. `DownloadRow.apply_bulk` + `MainWindow.on_apply_bulk`, GUI 테스트 추가.
- [~] **실제 다운로드 최종 검증** — dev 모드 UI 종단 다운로드는 **qtbot E2E로 자동화**
  (`tests/test_e2e_qt.py::test_real_download_end_to_end`, `pytest -m e2e`). 남은 것: full/lite
  **exe 산출물**에서의 실제 영상·음원 다운로드 수동 확인.
- [x] 예외 처리 다듬기 — yt-dlp/네트워크 예외를 사용자용 한글 메시지로 변환
  (`downloader.friendly_error`: 삭제/비공개/지역제한/연령제한/멤버십/429/타임아웃/DNS/연결/ffmpeg/403/권한/디스크).
  원인 체인(`__cause__`)까지 살펴 더 구체적인 메시지를 고르고, 알려지지 않은 오류는 ANSI·`ERROR:`
  접두어를 걷어내 한 줄로 노출. `app.py`의 조회/재생목록/다운로드 실패 표시에 적용. 단위 테스트 추가.
- [x] 다운로드 취소 버튼 — 진행 중 `전체 다운로드` 버튼이 `취소`로 바뀜. 클릭 시 진행률 훅에서
  `DownloadCancelled`를 던져 yt-dlp를 중단하고 남은 큐를 멈춤(미처리 항목 '취소됨' 표시, 내역 미기록).
  취소는 yt-dlp가 다른 예외로 감쌀 수 있어 `self._cancel` 플래그로도 판정. GUI 테스트 추가.
- [x] 앱 아이콘 제작·반영 — `assets/make_icon.py`(PIL)로 '둥근 빨강 사각형 + 흰색 다운로드 화살표'
  아이콘 생성: `app.ico`(멀티사이즈, Windows) / `app.icns`(macOS) / `app.png`(마스터). build.py가
  OS별로 자동 적용(`--icon`). **빌드한 lite exe에서 아이콘 임베드 확인**(32px에서도 글리프 선명).
- [x] full 배포 용량 축소 — **구성 분석 후 안전한 축소 적용, v0.3.1 CI에서 실측 확인**
  (full 137.3→128.4MB, lite 62.4→53.8MB, mac dmg 92.2→83.1MB, mac zip 83.5→75.1MB, 각 ~8~9MB↓).
  로컬 full dist(585MB) 구성:
  ffmpeg 415MB(로컬은 full ffmpeg, **CI는 essentials라 더 작음**) / PySide6 93MB(Qt Essentials,
  Addons·QtWebEngine 미포함 — 양호) / **numpy ~27MB(앱 미사용)** / PIL 11MB / 파이썬런타임 등.
  - 적용: `build.py --exclude-module numpy,tkinter,test,unittest,pydoc_data`(numpy ~27MB 제거,
    빌드 exe 기동 검증), `requirements.txt`를 `PySide6-Essentials`로(Addons 설치/번들 차단).
  - **지배적 요인은 ffmpeg** — CI는 이미 essentials 사용. 더 줄이려면 ffprobe 제외(yt-dlp 일부 기능
    저하 위험)나 UPX 압축(AV 오탐·기동 지연 위험)이 필요해 **안정성 우선으로 보류**.
- [x] 내역에 저장 폴더 기록 + **"폴더 열기"** — 내역 항목에 `dir`(저장 폴더)을 저장하고, 각 항목에
  📂 버튼 추가(크로스플랫폼 `_open_in_file_manager` 사용). 폴더 정보 없는 옛 항목은 버튼 비활성,
  폴더가 사라졌으면 안내만. `MainWindow.open_history_dir`, GUI 테스트 추가.

### 크기 추정 정확도 메모
- `estimate_size`는 filesize가 없으면 tbr(평균 비트레이트)×길이로 근사 → 실제와 오차 가능.
- 음원은 mp3 목표 비트레이트×길이 기반이므로 원본이 그보다 낮으면 과대추정될 수 있음.

### 알려진 제약 / 메모
- 현재 조회는 `noplaylist=True`로 플레이리스트 URL이면 첫 영상만 처리.
- Python 3.14는 비교적 최신 → 일부 패키지 휠 미제공 가능성. 문제 시 3.12 사용 검토.
- yt-dlp는 유튜브 변경에 따라 수시 업데이트 필요(`pip install -U yt-dlp`).
- 이모지(🗑/✅/❌)가 일부 환경에서 네모(□)로 보일 수 있음 → 필요 시 텍스트/기호로 대체.

### 리사이즈 재렌더링 지연 대응 옵션 (필요 시)
- 리사이즈 중 썸네일 재스케일 생략(디바운스)로 부담 완화.
- 목록을 더 가벼운 위젯으로 렌더링(작업량 큼).
- 근본 해결이 필요하면 **PySide6(Qt)** 로 GUI 전환 검토(네이티브라 리사이즈가 부드러움, 큰 재작성).

---

## 8. 재개 체크리스트 (새 세션 시작 시)
1. 이 문서 §7 "다음 할 일" 확인
2. `pip install -r requirements.txt` 상태 확인
3. ffmpeg 사용 가능 여부 확인 (`ffmpeg -version` 또는 `bin/ffmpeg.exe`)
4. `python src/app.py`로 현재 동작 확인 후 이어서 작업
