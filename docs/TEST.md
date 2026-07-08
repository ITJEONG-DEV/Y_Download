# 자동 테스트 가이드 (TEST.md)

Y_Downloader 의 자동 테스트 구조 · 실행 방법 · 규칙을 정리한 문서.
**기능을 추가하거나 수정할 때마다 전체 테스트를 돌려 회귀(regression)를 확인**하는 것이 목표.

---

## 1. 한눈에

| 계층 | 대상 | 마커 | 기본 실행 | 특징 |
|------|------|------|:--------:|------|
| ① 단위 | 순수 로직 (downloader/config/updater) | 없음 | ✅ | 네트워크·GUI 없음, 매우 빠름 |
| ② GUI 스모크 | 실제 Qt(PySide6) 위젯 경로 (app) | `gui` | ✅ | 창을 띄우되 사용자 없이 검증, 네트워크 목킹 |
| ③ 통합 | 실제 yt-dlp/유튜브 | `network` | ❌(수동) | 느리고 외부 상태 의존 |
| ④ E2E | qtbot으로 UI 조작 → 실제 다운로드 | `e2e` | ❌(수동) | 실제 유튜브에서 UI 클릭으로 파일 생성까지 확인 |

> ②의 클릭-투-엔드(목킹) 케이스는 `e2e` 마커 없이 `gui`로 기본 실행된다. `e2e` 마커는
> **실제 네트워크·다운로드**가 필요한 종단 케이스에만 붙어 기본 실행에서 빠진다.

- 테스트 러너: **pytest** (`requirements-dev.txt`)
- 설정: 루트 `pyproject.toml` 의 `[tool.pytest.ini_options]`
- 기본 실행은 `-m 'not network'` 라서 **네트워크 테스트는 자동 제외**된다.

---

## 2. 실행 방법

```bash
# 준비(최초 1회)
pip install -r requirements.txt -r requirements-dev.txt

# 전체 회귀(단위 + GUI, 네트워크 제외) — 기능 추가/수정 후 항상 이걸 실행
pytest

# 단위 테스트만 (가장 빠름, GUI 창도 안 뜸)
pytest -m "not gui and not network"

# GUI 스모크만
pytest -m gui

# 통합(네트워크) 테스트만 — 유튜브 접속 필요, 가끔 수동 확인
pytest -m network

# E2E(실제 다운로드)만 — qtbot이 UI를 조작해 유튜브에서 실제 파일 생성까지 확인
pytest -m e2e

# 특정 파일/테스트
pytest tests/test_downloader.py
pytest tests/test_downloader.py::test_sanitize_filename
```

> Windows에서 `pytest` 명령이 안 잡히면 `python -m pytest` 로 실행.

---

## 3. 폴더 구조

```
pyproject.toml            # pytest 설정(마커, pythonpath=src, 기본 -m 'not network')
requirements-dev.txt      # pytest 등 개발 전용 의존성
tests/
├── conftest.py           # 공용 픽스처: isolated_config, FakeYDL, src 경로 주입
├── test_downloader.py    # ① 파일명 정리/URL 판별/크기추정/유니크이름/재생목록 파싱
├── test_config.py        # ① 설정·내역 JSON 저장(임시 폴더 격리)
├── test_updater.py       # ① 버전 비교·요약 추출·자산 선택(네트워크 목킹)
├── test_platform.py      # ① 크로스플랫폼 분기(설정폴더/ffmpeg 경로/폴더 열기, sys.platform 목킹)
├── test_gui.py           # ② (Qt) 목록 추가/삭제/내역 패널 토글·폭확장·1줄축약
├── test_e2e_qt.py        # ②④ qtbot 클릭-투-엔드(목킹, gui) + 실제 다운로드(e2e)
└── test_network.py       # ③ 실제 fetch_info / fetch_playlist
```

---

## 4. 테스트 작성 규칙

- **네트워크 금지(①②).** 유튜브·GitHub 접속이 필요한 코드는 목킹한다.
  - yt-dlp: `conftest.FakeYDL` 로 `downloader.yt_dlp.YoutubeDL` 을 대체.
  - 업데이트: `updater.get_latest` 를 `monkeypatch` 로 대체.
  - GUI: `app.fetch_info`, `App._load_thumbnail` 을 목킹.
- **파일 오염 금지.** 설정/내역을 다루면 `isolated_config` 픽스처로 임시 폴더에 격리.
  (실제 `%APPDATA%/Y_Downloader` 를 건드리지 않는다.)
- **GUI 테스트는 App 을 모듈당 1개만** 만든다. 한 프로세스에서 Tk 루트를 여러 번
  생성/파괴하면 `tcl_findLibrary` 등으로 불안정해지므로, `test_gui.py` 의 모듈 스코프
  `app` 픽스처를 공유하고 `_reset_rows` 로 상태만 초기화한다.
- **비동기(스레드) 검증은 `_pump_until`** 헬퍼로 실제 `mainloop` 을 돌려 완료를 기다린다.
  (백그라운드 워커가 `self.after` 로 결과를 돌려주므로 mainloop 이 돌아야 반영된다.)
- **UI 조작(클릭/키입력)은 `qtbot`(pytest-qt)** 으로 재현한다. `qtbot.keyClicks`(타이핑)·
  `qtbot.mouseClick`(클릭)·`qtbot.waitUntil`(비동기 완료 대기)를 쓴다. `test_e2e_qt.py` 참고.
- **실제 네트워크·다운로드가 필요한 종단 케이스는 `@pytest.mark.e2e`** 로 표시해 기본 실행에서
  뺀다(`pytest -m e2e` 로만 수동 실행). 안정적인 공개 영상(예: 유튜브 최초 영상)을 사용한다.
- 디스플레이가 없으면 GUI 픽스처가 자동 `skip` 한다(실패 아님).

---

## 5. CI 연동 (GitHub Actions)

| 워크플로 | 트리거 | 동작 |
|----------|--------|------|
| `.github/workflows/test.yml` | dev/main **push·PR** | `pytest -m "not network"` 실행 |
| `.github/workflows/release.yml` | `v*` 태그 push | **`test` 잡 통과 후에만** 빌드/릴리스 (`needs: test`) |

- 두 워크플로 모두 `windows-latest` 에서 실행 → Tk GUI 스모크 테스트도 동작.
- **배포 게이트**: 테스트가 깨지면 릴리스 빌드가 자동 중단되어, 깨진 채 배포되는 것을 막는다.
- 네트워크 테스트는 CI에서 제외(불안정). 필요 시 로컬에서 `pytest -m network` 로 확인.

---

## 6. 새 기능을 추가/수정했다면 (체크리스트)

1. 해당 로직에 **단위 테스트**를 추가(가능하면 순수 함수로 분리해 ①에서 검증).
2. UI 흐름이 바뀌었으면 `test_gui.py` 에 **스모크 테스트** 추가.
3. 로컬에서 **`pytest`** 로 전체 회귀 초록불 확인.
4. 결과(테스트한 항목 / 결과 수치 / 미흡→개선)를 **[`TEST_LOG.md`](TEST_LOG.md)** 에 한 항목 기록.
5. `dev` 에 push → `test.yml` 이 자동 재확인.
6. 배포 시 태그 push → 테스트 통과해야 릴리스 진행.

> 커밋/배포 단위 테스트 진행 이력은 **[`TEST_LOG.md`](TEST_LOG.md)** 에 누적한다.

---

## 7. 현재 커버리지 요약

- **downloader**: `sanitize_filename`, `is_playlist_url`, `format_size`, `estimate_size`
  (영상/음원/폴백), `_stream_size`, `_uniquify`, 중복정책 상수, `fetch_playlist`(정규화·필터),
  `friendly_error`(예외→한글 매핑·원인체인·미지 오류 정리).
- **config**: 설정 라운드트립, 중복정책, 항목 기본값, 창 상태, 내역 추가/순서/삭제/전체삭제/보관한도.
- **updater**: 버전 파싱·비교, 변경요약 추출(마커 유무), 자산 선택, `check_update`(신규/동일/구버전/빈태그),
  `build_kind`, 교체 스크립트 생성.
- **app(GUI)**: 재생목록 즉시추가→개별조회 갱신, 단일 추가, 내역 패널 토글·폭확장·1줄축약,
  일괄 적용 바(영상/음원·확장자·'≤ 목표 해상도' 매핑), 다운로드 취소(큐 중단·미처리 '취소됨'),
  qtbot 클릭-투-엔드.
- **platform**: OS별 설정 폴더(`_default_app_dir`), ffmpeg 실행파일명/위치(`_ffmpeg_names`/
  `_ffmpeg_location`, macOS `.app` 포함), 폴더 열기 디스패치(`_open_in_file_manager`).
- **network(수동)**: 실제 `fetch_info` / `fetch_playlist`.
