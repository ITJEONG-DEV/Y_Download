"""
qtbot(pytest-qt) 기반 UI 상호작용/E2E 테스트.
실제 마우스/화면 없이 위젯에 클릭·키입력 이벤트를 주입해 사용자 조작을 재현한다.

- test_click_through_download : 클릭-투-엔드 흐름(타이핑→추가→다운로드). 네트워크·다운로드는
  목킹하므로 기본 스위트에 포함(gui). '실제 클릭'이 동작하는지 검증.
- test_real_download_end_to_end : 실제 유튜브에서 짧은 영상을 UI로 다운로드해 파일 생성까지 확인.
  느리고 외부 의존이라 `e2e` 마커로 기본 제외. 수동 실행:  pytest -m e2e
"""
import os

import pytest

from downloader import VideoInfo, DownloadResult

pytestmark = pytest.mark.gui


@pytest.fixture
def win(qtbot, isolated_config, monkeypatch):
    import app

    def fake_fetch_info(url, timeout=5):
        vid = url.rsplit("=", 1)[-1]
        return VideoInfo(url=url, title=f"제목-{vid}", thumbnail_url="", duration=100,
                         uploader="u", available_heights=[720],
                         video_size_by_height={720: 1_000_000}, best_audio_size=100_000)

    monkeypatch.setattr(app, "fetch_info", fake_fetch_info)
    monkeypatch.setattr(app, "_fetch_thumb_bytes", lambda u: None)

    w = app.MainWindow()
    qtbot.addWidget(w)
    with qtbot.waitExposed(w):
        w.show()
    return w


def test_click_through_download(qtbot, win, isolated_config, monkeypatch, tmp_path):
    """URL 타이핑 → [목록에 추가] 클릭 → [전체 다운로드] 클릭까지 실제 이벤트로."""
    import app
    from PySide6.QtCore import Qt

    win.dir_entry.setText(str(tmp_path))

    # 1) URL 입력창에 타이핑하고 '목록에 추가' 버튼을 클릭
    qtbot.keyClicks(win.url_entry, "https://www.youtube.com/watch?v=ABC")
    qtbot.mouseClick(win.add_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: len(win.rows) == 1, timeout=5000)
    assert win.rows[0].title_label.text().startswith("제목-ABC")

    # 2) 다운로드는 목킹(성공) 후 '전체 다운로드' 버튼 클릭
    def fake_download(output_dir, progress_callback=None, **params):
        name = (params.get("filename") or "out") + "." + params.get("ext", "mp4")
        return DownloadResult(path=os.path.join(output_dir, name), status="downloaded")

    monkeypatch.setattr(app, "download", fake_download)
    qtbot.mouseClick(win.download_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: not win._downloading, timeout=5000)

    # 3) 완료 상태 + 내역 기록 검증
    assert "완료" in win.status_label.text()
    assert win.rows[0].status_label.text().startswith("완료")
    assert len(isolated_config.load_history()) == 1
    assert isolated_config.load_history()[0]["status"] == "성공"


@pytest.mark.e2e
def test_real_download_end_to_end(qtbot, isolated_config, tmp_path):
    """실제 유튜브에서 짧은 영상을 UI 조작으로 음원 다운로드 → 파일 생성 확인 (수동: pytest -m e2e)."""
    import app
    from PySide6.QtCore import Qt

    w = app.MainWindow()
    qtbot.addWidget(w)
    with qtbot.waitExposed(w):
        w.show()

    w.dir_entry.setText(str(tmp_path))
    # 짧고 안정적인 공개 영상 (유튜브 최초 영상 "Me at the zoo", 19초)
    qtbot.keyClicks(w.url_entry, "https://www.youtube.com/watch?v=jNQXAC9IVRw")
    qtbot.mouseClick(w.add_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: len(w.rows) == 1, timeout=30000)

    # 음원(mp3)로 바꿔 빠르게 받기
    w.rows[0].kind_menu.setCurrentText("음원")
    qtbot.mouseClick(w.download_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: not w._downloading, timeout=120000)

    files = list(tmp_path.iterdir())
    assert files, "다운로드 파일이 생성되지 않음"
    assert any(f.suffix.lower() in (".mp3", ".m4a", ".webm", ".mp4") for f in files)
