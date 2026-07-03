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
| 9 | **다운로드 내역(성공/실패) 기록·조회, 더블클릭 재추가** | ✅ 구현 |
| 10 | 배포용 단독 실행 exe | ⬜ 예정 (PyInstaller) |

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
  - `fetch_info(url) -> VideoInfo` : 제목·썸네일·길이·업로더·사용 가능 해상도 조회
  - `download(url, output_dir, *, kind, ext, max_height, audio_bitrate, filename, progress_callback) -> str`
  - `sanitize_filename(name)` : 파일명 사용 불가 문자 제거
  - `VideoInfo` 데이터클래스, `VIDEO_EXTS`/`AUDIO_EXTS` 상수
- **app.py** — UI만 담당. 조회/다운로드 등 무거운 작업은 **스레드**에서 실행하고
  `self.after(0, ...)`로 메인 스레드에서 UI 갱신 (tkinter 스레드 안전성 확보).
  - `DownloadRow(CTkFrame)` : 목록의 한 항목. 자체 위젯 + `VideoInfo` 보유.
    - `get_params()` : 그 항목의 다운로드 파라미터 dict 반환
  - `App(CTk)` : 전체 창. URL 추가 / 목록 관리 / 저장위치 / 일괄 다운로드.

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

## 6. 배포 (exe 빌드) — 예정 작업

```powershell
pip install pyinstaller

pyinstaller --noconfirm --windowed --name "YouTubeDownloader" ^
  --add-binary "bin/ffmpeg.exe;ffmpeg" ^
  src/app.py
```

- `downloader.py._ffmpeg_location()`이 PyInstaller 번들(`sys._MEIPASS/ffmpeg/ffmpeg.exe`)을
  자동 탐색하도록 이미 구현되어 있음 → 빌드 시 ffmpeg.exe만 위 경로로 포함하면 됨.
- 아이콘 지정: `--icon app.ico` 추가.

---

## 7. 진행 상황 / TODO

### 완료
- [x] 기술 스택 결정 및 문서화
- [x] `downloader.py` — 정보조회 + 다운로드 로직 (커스텀 파일명·확장자 지원)
- [x] `app.py` — 큐(목록) 기반 GUI, 항목별 개별 설정, 일괄 다운로드
- [x] 스레드 기반 비동기 조회/다운로드 + 진행률
- [x] 마지막 저장 위치 기억 (`config.py` → settings.json)
- [x] 선택 포맷/품질 기준 예상 파일 크기 표시 (`estimate_size`)
- [x] 다운로드 내역(성공/실패) 기록·조회 창, 더블클릭 시 목록 재추가
- [x] 의존성 설치 및 핵심 로직(`fetch_info`/`estimate_size`/`config`) 동작 검증

### 다음 할 일 (우선순위 순)
- [ ] **GUI 실행 테스트** (창 표시·버튼 동작은 디스플레이 있는 환경에서 확인 필요)
- [ ] ffmpeg 배치 후 실제 영상/음원 다운로드 최종 검증 (bin/ffmpeg.exe 사용)
- [ ] 예외 처리 다듬기 (잘못된 URL, 지역제한, 네트워크 오류 메시지 한글화)
- [ ] 파일명 중복 시 처리(덮어쓰기/자동 번호) 정책 결정
- [ ] 다운로드 취소 버튼
- [ ] PyInstaller exe 빌드 및 배포 검증
- [ ] (선택) 플레이리스트 전체 추가 기능
- [ ] (선택) 내역에 저장 경로/파일명 저장해 "폴더 열기" 기능

### 크기 추정 정확도 메모
- `estimate_size`는 filesize가 없으면 tbr(평균 비트레이트)×길이로 근사 → 실제와 오차 가능.
- 음원은 mp3 목표 비트레이트×길이 기반이므로 원본이 그보다 낮으면 과대추정될 수 있음.

### 알려진 제약 / 메모
- 현재 조회는 `noplaylist=True`로 플레이리스트 URL이면 첫 영상만 처리.
- Python 3.14는 비교적 최신 → 일부 패키지 휠 미제공 가능성. 문제 시 3.12 사용 검토.
- yt-dlp는 유튜브 변경에 따라 수시 업데이트 필요(`pip install -U yt-dlp`).

---

## 8. 재개 체크리스트 (새 세션 시작 시)
1. 이 문서 §7 "다음 할 일" 확인
2. `pip install -r requirements.txt` 상태 확인
3. ffmpeg 사용 가능 여부 확인 (`ffmpeg -version` 또는 `bin/ffmpeg.exe`)
4. `python src/app.py`로 현재 동작 확인 후 이어서 작업
