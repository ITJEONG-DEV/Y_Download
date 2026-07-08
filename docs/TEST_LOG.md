# 테스트 진행 기록 (TEST_LOG.md)

커밋/배포 단위로 **무엇을 테스트했고, 어떤 항목이 미흡해 어떻게 개선했는지**를 누적 기록한다.
최신 항목이 위로 온다. 테스트 실행 방법·구조는 [`TEST.md`](TEST.md) 참고.

> **작성 규칙**: 의미 있는 커밋과 모든 릴리스마다 아래 템플릿으로 항목을 추가한다.
> `pytest` 결과 수치(passed/skipped/deselected)를 그대로 남긴다.

```
## <날짜> · <커밋 short 또는 vX.Y.Z> — <제목>
- **테스트한 항목**: …
- **결과**: NN passed, MM skipped, KK deselected(network)
- **미흡 → 개선**: (없으면 "특이사항 없음")
```

---

## 2026-07-08 · dev — 내역 '폴더 열기' 기능
- **테스트한 항목** (GUI):
  - dir 있는 최신 내역 → 📂 클릭 시 `_open_in_file_manager`가 그 폴더로 호출됨(목킹 검증).
  - dir 없는 옛 내역 → 열지 않고 "정보가 없는" 안내.
  - 존재하지 않는 폴더 → "찾을 수 없음" 안내.
- **결과**: 87 passed, 3 deselected. (GUI +1건)
- **미흡 → 개선**: `add_history`가 최신을 index 0에 넣는 순서를 착각해 테스트가 실패 → 추가 순서를
  바로잡아 index 0이 dir 있는 항목이 되게 수정(제품 코드 아닌 테스트 오류).

## 2026-07-08 · dev — CI 그린화(v0.3.0 릴리스 게이트)
- **테스트한 항목**: v0.3.0 태그 push → Release/Tests 워크플로 실패 원인 추적(CI 로그 확인).
- **결과**: 86 passed, 3 deselected(로컬). CI 실패 2건 수정.
- **미흡 → 개선**:
  - `test.yml`/`release.yml`가 `-m "not network"`로 pyproject 기본값을 덮어써 **e2e 실다운로드
    테스트가 CI에서 실행**(ffmpeg 없음·유튜브 봇차단)→ `-m "not network and not e2e"`로 수정.
  - `test_history_toggle_and_widen`가 **좁은 화면(CI≈1024px)에서 창이 목표폭까지 못 늘어**(1028≠1200)
    실패 → 근본은 `_grow_width` 닫기 로직이 '현재폭-패널폭'이라 클램프 시 원복이 틀어지는 **잠재 버그**.
    열기 전 폭을 기억해 정확히 원복하도록 고치고, 테스트는 클램프 허용(넓어짐 범위)으로 견고화.

## 2026-07-08 · dev — macOS 배포: build.py/CI/updater (서명 제외)
- **테스트한 항목**:
  - (단위) `updater`: `_asset_url`의 `mac` zip 선택(dmg 제외), `build_kind`=='mac'(darwin+frozen),
    `_current_app_bundle` 경로 파싱, `_mac_script` 내용(ditto·quarantine·.app 탐색).
  - (검토) `build.py`: Windows 인자 무회귀 확인(--version-file/icon/add-binary 동일), macOS 분기 구성.
  - (검토) `release.yml`: `build-macos` 잡 YAML 파싱 검증(arch감지·정적 ffmpeg·ditto zip·hdiutil dmg).
- **결과**: 86 passed, 3 deselected. (updater +4건)
- **미흡 → 개선**:
  - macOS `.app`은 심볼릭 링크/실행권한을 포함해 **Python zipfile로 풀면 손상** → 자동 업데이트는
    Python 추출을 건너뛰고 bash 도우미의 `ditto -x -k`로 처리하도록 분기.
  - ⚠️ Mac 미보유로 **실제 빌드/기동/자동교체 검증은 불가** — 코드·CI 레벨만 확인, 실기기/CI 필요.

## 2026-07-08 · dev — macOS 배포: 크로스플랫폼 런타임 코드
- **테스트한 항목** (`tests/test_platform.py`, sys.platform 목킹):
  - `config._default_app_dir`: Windows(%APPDATA% 유지)/macOS(Library/Application Support)/
    Linux(XDG·기본) 4분기.
  - `downloader._ffmpeg_names`/`_ffmpeg_location`: 실행파일명 분기, macOS `.app` 번들 경로 탐색,
    현재 플랫폼 반환값 무결성(실제 실행파일 존재).
  - `app._open_in_file_manager`: Windows `startfile`/macOS `open`/Linux `xdg-open` 디스패치.
- **결과**: 82 passed, 3 deselected. (플랫폼 단위 +12건, Windows 회귀 영향 없음)
- **미흡 → 개선**:
  - `_ffmpeg_location`이 `os.path.exists`라 'ffmpeg'라는 **하위 폴더**도 실행파일로 오인 →
    `os.path.isfile`로 좁혀 해결(테스트가 드러냄).
  - 경로 기대값을 리터럴로 적어 Windows 구분자와 불일치 → `os.path.join`으로 구성해 이식성 확보.

## 2026-07-08 · dev — 다운로드 취소 버튼
- **테스트한 항목**:
  - (GUI) 진행 중(훅이 %를 갱신하는 가짜 다운로드) → `on_cancel` → 큐 중단.
  - 취소 후: 상태에 '취소' 표기, 버튼 '전체 다운로드'로 원복, 미처리 항목 '취소됨', 내역 미기록.
- **결과**: 70 passed, 3 deselected. (GUI +1건)
- **미흡 → 개선**: yt-dlp가 훅 예외를 자체 예외로 감쌀 수 있어 `except`에서 `DownloadCancelled`
  타입만으로는 놓칠 수 있음 → `self._cancel` 플래그 병행 판정으로 견고화(내역 기록도 건너뜀).

## 2026-07-08 · dev — 목록 상단 포맷/품질 일괄 적용 바
- **테스트한 항목**:
  - (GUI) 3개 행에 영상+mkv+720p 캡 일괄 적용 → 각 행 kind/ext/max_height 반영.
  - (GUI) 캡(480p)보다 낮은 가용 해상도가 없을 때 최저 해상도(720)로 폴백.
  - (GUI) 음원+m4a+256 일괄 적용 → 확장자/품질 목록이 음원용으로 전환·반영.
  - (GUI) 빈 목록에서 [전체 적용]은 예외 없이 안내만.
- **결과**: 69 passed, 3 deselected. (GUI +2건)
- **미흡 → 개선**: 특이사항 없음. 각 영상의 가용 해상도가 달라 고정 라벨 일괄 지정은 부적합 →
  '≤ 목표 해상도' 매핑(`apply_bulk`/`_select_video_quality_for_cap`)으로 설계.

## 2026-07-08 · dev — 예외 메시지 한글화(`friendly_error`)
- **테스트한 항목**:
  - (단위) `friendly_error`: 삭제/비공개/지역제한/연령제한/멤버십/429/타임아웃/DNS/403 등 알려진
    패턴 → 한글 매핑, 원인 체인(`__cause__`) 추적, 알 수 없는 오류의 ANSI·`ERROR:` 접두어·다중행 정리.
  - (실네트워크, 수동) 내려간 영상으로 실제 `fetch_info` 예외 → "영상을 사용할 수 없습니다…" 확인.
- **결과**: 67 passed, 3 deselected. (downloader 단위 +13건)
- **미흡 → 개선**: 원인 체인 케이스에서 일반 패턴("unable to download webpage")이 타임아웃보다 먼저
  매칭돼 오답 → 네트워크 계열 패턴을 일반 오류보다 **앞으로 재정렬**해 해결.

## 2026-07-08 · dev — qtbot E2E(클릭-투-엔드 + 실제 다운로드) 추가
- **테스트한 항목**:
  - `pytest-qt` 도입, `e2e` 마커 추가(`pyproject.toml`, 기본 실행에서 제외).
  - (gui) `test_click_through_download`: URL 타이핑→[목록에 추가]→[전체 다운로드]를 실제
    마우스/키 이벤트로 조작(다운로드는 목킹). 완료 상태·행 상태·내역 성공 기록까지 검증.
  - (e2e) `test_real_download_end_to_end`: 실제 유튜브에서 UI 조작으로 음원 다운로드→파일 생성 확인.
- **결과**: 54 passed, 3 deselected(network 2 + e2e 1). `pytest -m e2e` 단독 실행 시 1 passed(실다운로드).
- **미흡 → 개선**: 기존 e2e 대상 영상 `BaW_jenozKc`가 유튜브에서 내려가(Video unavailable) 30s
  타임아웃 → 안정적인 유튜브 최초 영상 `jNQXAC9IVRw`("Me at the zoo", 19초)로 교체해 통과(4.8s).

## 2026-07-08 · feature/qt-migration (M4) → v0.2.0 — 전환 마무리·배포
- **테스트한 항목**:
  - 모듈 스왑(CTk `app.py` 제거, Qt를 `app.py`로) 후 **전체 회귀** 실행
  - `build.py`에서 customtkinter 수집 제거, PySide6는 PyInstaller 내장 훅에 위임
  - **lite exe 실제 빌드** 성공 + **기동 확인**(실행 후 생존 → PySide6 platform 플러그인 번들 정상)
  - customtkinter/app_qt 잔여 참조 점검(별칭 `import app as app_qt`만 남김)
- **결과**: 53 passed, 2 deselected(network), 0 skipped. lite 빌드/기동 OK.
- **미흡 → 개선**: 특이사항 없음(전환 후 그린).

## 2026-07-07 · feature/qt-migration (M1~M3) — PySide6 이식
- **테스트한 항목**:
  - (스모크) M1 창 구성·단일/재생목록 추가·파라미터(영상/음원)·삭제
  - (스모크) M2 내역 패널 토글·표시·제목형식·펼침·삭제·전체지우기
  - (스모크) 창모드 내역 폭확장/원복/최대화 안전
  - (스모크) 내역 아이템 접힘 1줄 축약(ElidedLabel)·버튼 영역 유지·펼침 높이 증가
  - M3에서 위 스모크들을 `tests/test_gui_qt.py`(marker gui)로 정식 편입
- **결과**: 56 passed, 2 deselected(network), 0 skipped (Qt GUI 5건 추가). Tk·Qt 테스트 한 프로세스 공존 확인.
- **미흡 → 개선**:
  - 내역 제목이 항상 `wordWrap`이라 접힘에도 여러 줄 + 긴 파일명이 ＋/🗑 버튼을 행 밖으로 밀어냄 →
    가로 sizeHint를 무시하고 접힘 시 …축약하는 **ElidedLabel** 도입으로 두 문제 동시 해결.
  - 스모크를 매번 임시 스크립트로 돌리던 것 → 정식 `test_gui_qt.py`로 회귀 편입.

## 2026-07-07 · c1d50c9 — 자동 테스트 파이프라인 도입
- **테스트한 항목**:
  - ① 단위 — downloader(`sanitize_filename`/`is_playlist_url`/`format_size`/`estimate_size`
    영상·음원·폴백/`_stream_size`/`_uniquify`/중복정책 상수/`fetch_playlist` 정규화·필터),
    config(설정·중복정책·항목기본값·창상태·내역 추가/순서/삭제/전체삭제/보관한도),
    updater(버전파싱·비교/요약추출/자산선택/`check_update` 4케이스/`build_kind`/교체스크립트)
  - ② GUI 스모크 — 재생목록 즉시추가→개별조회 갱신, 단일 추가, 팝업 메인창 중앙 배치
  - ③ 네트워크 — 실제 `fetch_info`/`fetch_playlist` (마커 분리, 기본 실행 제외)
- **결과**: 51 passed, 2 deselected(network), 0 skipped
- **미흡 → 개선**:
  - GUI 테스트를 수동 `update()` 펌프로 돌리자 워커 스레드의 `self.after` 가
    **`RuntimeError: main thread is not in main loop`** 로 실패 → 실제 `mainloop`+`after`
    폴링 헬퍼(`_pump_until`)로 교체해 해결.
  - App(Tk 루트)을 테스트마다 생성/파괴하니 두 번째부터 **`tcl_findLibrary`** 로 1건 skip →
    **모듈 스코프 공유 App 픽스처** + 상태 초기화(`_reset_rows`)로 재설계해 skip 0으로 개선.

## 2026-07-07 · 020cb75 — 재생목록 URL 추가 + 팝업 중앙 배치
- **테스트한 항목** (정식 스위트 도입 이전, 임시 검증 스크립트 기준):
  - `is_playlist_url` 4종 판별, `PlaylistEntry` 구조
  - **실제 공개 재생목록 평면 조회**(100개 항목: 제목·URL·길이 정상 추출)
  - 재생목록 3개 즉시 행 생성 → 백그라운드 개별 조회로 제목 갱신 → 품질 메뉴에 실제 해상도 반영
  - 조회 카운터/워커 정리, `_center_popup` 좌표가 부모 창 영역 내 중앙인지
  - 전체 `py_compile`
- **결과**: 임시 스크립트 6개 항목 전부 통과(+실네트워크 100개 조회 확인)
- **미흡 → 개선**:
  - 검증이 **일회성 임시 스크립트**라 재사용/회귀가 불가 → 다음 커밋(c1d50c9)에서
    `tests/` 정식 스위트로 승격.
  - 팝업이 다중 모니터에서 주모니터에 뜨던 문제 → `_center_popup`(부모 `winfo_rootx/rooty`
    기준 중앙 배치) 추가로 개선.

## 2026-07-06 · 2d6249e → v0.1.8 — dev/main 정합화 및 배포
- **테스트한 항목**:
  - `main→dev` 병합 후 **전체 `py_compile`**
  - 양쪽 기능 마커 상호 존재 확인(가상 스크롤 / 전체 지우기·포맷 기억 / updater 경로 / fetch 타임아웃)
  - 버전 스탬프 0.1.7 → 0.1.8
- **결과**: 컴파일 성공, 기능 마커 모두 확인
- **미흡 → 개선**:
  - **dev/main 분기(diverged)로 v0.1.7 릴리스에 성능 개선(가상 스크롤)이 누락**된 사실을 발견 →
    병합으로 정합화하고 v0.1.8로 재배포.
  - 근본 원인은 "테스트/게이트 없이 태그만 붙여 배포" → 재발 방지책으로 **릴리스 게이트
    (`release.yml` `needs: test`)** 도입(c1d50c9에서 반영).
