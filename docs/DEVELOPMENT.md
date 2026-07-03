# YouTube Downloader — 개발 문서

> 이 문서는 작업을 **언제든 중단하고 재개**할 수 있도록 프로젝트의 목표·구조·진행 상황·다음 할 일을 기록한다.
> 새 세션을 시작할 때 이 문서를 먼저 읽으면 현재 상태를 파악할 수 있다.

- 최종 수정: 2026-07-03
- 저장소 경로: `D:\2_GIT\Y_Download`

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

---

## 2. 기술 스택 (결정 사항)

| 구분 | 선택 | 이유 |
|------|------|------|
| 언어 | **Python 3.14** | 다운로드 표준 엔진 yt-dlp가 Python 라이브러리 |
| 다운로드 엔진 | **yt-dlp** | 정보조회·포맷목록·다운로드 모두 담당, 유지보수 활발 |
| 후처리 | **ffmpeg** | mp3 변환, 영상+음성 병합에 필수 (외부 바이너리) |
| GUI | **CustomTkinter** | 설치·배포 간단, 모던한 룩앤필, 표준 tkinter 기반 |
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
│   └── app.py              # CustomTkinter GUI (진입점)
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
- **config.py** — 설정·내역 JSON 영구저장(`%APPDATA%/YouTubeDownloader/`).
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
- **반응형**: 제목 라벨은 폭에 맞춰 줄바꿈(`<Configure>`→wraplength), 파일명 입력창은 신축.
- **내역 패널**: 우측 사이드 패널(폭 320px). 창모드에선 열/닫을 때 창 폭을 패널만큼 확장/축소
  (화면 폭 상한), 최대화 상태에선 목록과 공간 분할. 항목 형식은
  `파일명 (영상명) · 성공여부` / `일시 포맷/확장자 품질`.

> 알려진 이슈: 창 크기 조정 시 재렌더링이 다소 느림 — CustomTkinter가 리사이즈마다 모든
> 위젯 캔버스를 다시 그리는 구조적 한계. 심할 경우 §7의 대응 옵션 참고.

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
| **full (기본)** | `python build.py full` | 폴더형(onedir) | **포함** | `dist/YouTubeDownloader/` (~496MB) |
| **lite (라이트)** | `python build.py lite` | 단일파일(onefile) | 미포함 | `dist/YouTubeDownloader-lite.exe` (~39MB) |

```powershell
pip install pyinstaller
python build.py           # full + lite 모두
python build.py full      # 폴더형만
python build.py lite      # 라이트만
```

- 공통: `--windowed --collect-all customtkinter --collect-submodules/-data yt_dlp`, `--paths src`.
- full: `bin/ffmpeg.exe`, `bin/ffprobe.exe`를 `ffmpeg/` 하위로 번들 → 런타임에 자동 인식.
- 아이콘: `assets/app.ico`가 있으면 자동 적용(`--icon`).
- 검증됨: 두 빌드 성공, full exe 실행 시 GUI 정상 기동(스모크 테스트 통과).

### ffmpeg 탐색 순서 (`downloader.py._ffmpeg_location`)
1. **번들(full)**: `sys._MEIPASS/ffmpeg/ffmpeg.exe` (폴더형의 `_internal/ffmpeg/`)
2. **실행파일 옆(lite)**: `<exe>/ffmpeg.exe`, `<exe>/ffmpeg/ffmpeg.exe`, `<exe>/bin/ffmpeg.exe`
3. **개발 환경**: 프로젝트 `../bin/ffmpeg.exe`
4. 위 모두 없으면 **시스템 PATH**의 ffmpeg 사용

### 배포 방법
- **full**: `dist/YouTubeDownloader/` 폴더 전체를 zip으로 압축해 전달 → 받는 사람은 압축 풀고
  `YouTubeDownloader.exe` 실행. ffmpeg 포함이라 추가 설치 불필요.
- **lite**: `YouTubeDownloader-lite.exe` 단일 파일. **ffmpeg 미포함**이므로 받는 사람이 아래 중 하나 필요:
  - 시스템에 ffmpeg 설치(`winget install Gyan.FFmpeg`), 또는
  - `ffmpeg.exe`를 **exe와 같은 폴더**(또는 그 아래 `ffmpeg/`·`bin/`)에 배치.
  - → 이 안내를 lite exe와 함께 동봉할 것. (`docs/lite-ffmpeg-안내.md` 참고)

---

## 6-1. 릴리스 / 버전 태그 자동 배포

버전은 `src/version.py`의 `__version__`이 단일 소스이며, 앱 창 제목에 `v{버전}`으로 표시된다.
릴리스는 **Git 태그 push**로 트리거된다 — `.github/workflows/release.yml`(GitHub Actions).

### 릴리스 방법
```powershell
git tag v1.0.0
git push origin v1.0.0     # -> Actions가 자동 빌드 & Release 발행
```

### 워크플로 동작 (windows-latest)
1. Python 3.12 준비 + 의존성/PyInstaller 설치
2. 태그명(`v1.0.0`)에서 버전 추출해 `src/version.py`에 기록(빌드 산출물에 반영, 커밋 안 함)
3. ffmpeg(essentials) 다운로드 → `bin/`에 배치 (CI에는 ffmpeg가 없으므로)
4. `python build.py all` 로 full + lite 빌드
5. 산출물 zip 패키징
   - `YouTubeDownloader-full-<버전>.zip` (폴더형, ffmpeg 포함)
   - `YouTubeDownloader-lite-<버전>.zip` (단일 exe + `lite-ffmpeg-안내.md`)
6. `softprops/action-gh-release`로 GitHub Release 생성 + zip 첨부(릴리스 노트 자동 생성)

### 버전 올리기
- 평소 개발 중에는 `src/version.py`를 손댈 필요 없음(태그가 릴리스 버전을 결정).
- 원하면 로컬 기본값도 함께 올려 커밋(예: `0.1.0` → `1.0.0`).
- 태그 규칙: `vMAJOR.MINOR.PATCH` (예: `v1.2.0`).

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

### 다음 할 일 (우선순위 순)
- [ ] **실제 다운로드 최종 검증** (full/lite exe에서 영상·음원 다운로드까지 확인)
- [ ] 예외 처리 다듬기 (잘못된 URL, 지역제한, 네트워크 오류 메시지 한글화)
- [ ] 파일명 중복 시 처리(덮어쓰기/자동 번호) 정책 결정
- [ ] 다운로드 취소 버튼
- [ ] 앱 아이콘(`assets/app.ico`) 제작 후 빌드에 반영
- [ ] full 배포 용량 축소 검토 (ffmpeg essentials 빌드로 교체 시 ~85MB)
- [ ] (선택) 플레이리스트 전체 추가 기능
- [ ] (선택) 내역에 저장 경로/파일명 저장해 "폴더 열기" 기능

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
