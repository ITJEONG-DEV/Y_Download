"""
Qt(PySide6) GUI 스모크 테스트 — app_qt.MainWindow 의 실제 위젯 경로를 검증한다.
네트워크(fetch_info/썸네일)는 목킹. QApplication 이 없으면(헤드리스 등) 자동 skip.

실행:  pytest -m gui
"""
import time

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as e:  # PySide6 미설치
        pytest.skip(f"PySide6 없음: {e}")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def main(qapp, isolated_config, monkeypatch):
    import app as app_qt
    from downloader import VideoInfo

    def fake_fetch_info(url, timeout=5):
        vid = url.rsplit("=", 1)[-1]
        return VideoInfo(url=url, title=f"실제-{vid}", thumbnail_url="", duration=100,
                         uploader="u", available_heights=[1080, 720],
                         video_size_by_height={1080: 5_000_000}, best_audio_size=1_000_000)

    monkeypatch.setattr(app_qt, "fetch_info", fake_fetch_info)
    monkeypatch.setattr(app_qt, "_fetch_thumb_bytes", lambda url: None)

    from PySide6.QtGui import QGuiApplication
    if not QGuiApplication.primaryScreen():
        pytest.skip("표시 화면 없음")

    w = app_qt.MainWindow()
    w.setGeometry(200, 200, 880, 660)
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    qapp.processEvents()


def _pump(qapp, pred, timeout=8.0):
    start = time.time()
    while not pred() and time.time() - start < timeout:
        qapp.processEvents()
        time.sleep(0.02)


# --------------------------------------------------------------- 목록 추가
def test_single_add(qapp, main):
    main.add_url("https://www.youtube.com/watch?v=ZZZ")
    _pump(qapp, lambda: len(main.rows) >= 1 and not main._add_pending)
    assert len(main.rows) == 1
    assert main.rows[0].title_label.text().startswith("실제-ZZZ")
    assert main.rows[0].get_params()["kind"] == "video"


def test_playlist_quick_add_and_enrich(qapp, main):
    from downloader import PlaylistEntry
    entries = [PlaylistEntry(url=f"https://www.youtube.com/watch?v=A{i}",
                             title=f"임시-{i}", duration=10 + i) for i in range(3)]
    main._add_playlist_entries(entries)
    assert len(main.rows) == 3
    assert main.rows[0].title_label.text().startswith("임시-0")

    _pump(qapp, lambda: main._enrich_pending == 0)
    assert all(r.title_label.text().startswith("실제-") for r in main.rows)
    assert any("1080" in main.rows[0].quality_menu.itemText(i)
               for i in range(main.rows[0].quality_menu.count()))


def test_remove_and_clear(qapp, main):
    from downloader import PlaylistEntry
    main._add_playlist_entries([PlaylistEntry(url=f"https://y/watch?v={c}", title=c, duration=5)
                                for c in ("a", "b", "c")])
    main._remove_row(main.rows[0])
    assert len(main.rows) == 2
    main.clear_download_list()
    assert len(main.rows) == 0
    assert main.empty_label.isVisible()


# --------------------------------------------------------------- 내역 패널
def test_history_toggle_and_widen(qapp, main, isolated_config):
    isolated_config.add_history({"title": "영상A", "filename": "fileA", "status": "성공",
                                 "kind": "영상", "ext": "mp4", "quality": "1080p (FHD)",
                                 "timestamp": "2026-07-07 10:00", "message": ""})
    import app as app_qt
    w0 = main.geometry().width()
    main.toggle_history()
    qapp.processEvents()
    assert main.history_dock.isVisible()
    assert main.geometry().width() == w0 + app_qt.HISTORY_PANEL_WIDTH  # 창모드 폭 확장
    assert main.history_panel.list.count() == 1

    main.toggle_history()
    qapp.processEvents()
    assert not main.history_dock.isVisible()
    assert main.geometry().width() == w0  # 원복


def test_history_item_collapsed_one_line_and_buttons(qapp, main, isolated_config):
    from PySide6.QtWidgets import QSizePolicy
    isolated_config.add_history({
        "title": "아주긴제목_공백없음_0123456789_abcdefghij_klmnop",
        "filename": "very_long_filename_no_spaces_0123456789_abcdef",
        "status": "실패", "kind": "음원", "ext": "mp3", "quality": "192",
        "timestamp": "2026-07-07 10:05", "message": "긴 오류 메시지"})
    main.toggle_history()
    qapp.processEvents()
    panel = main.history_panel
    row = panel.list.itemWidget(panel.list.item(0))

    # 접힘: 1줄(wordWrap off) + 라벨이 행을 넓히지 않음(버튼 안 넘침)
    assert row.title_lbl.wordWrap() is False
    assert row.title_lbl.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
    assert row.width() <= panel.list.viewport().width() + 2
    h0 = row.sizeHint().height()

    # 펼침: 줄바꿈 + 높이 증가
    panel.toggle(row)
    qapp.processEvents()
    assert row.title_lbl.wordWrap() is True
    assert row.sizeHint().height() >= h0

    # 삭제 → 0건
    panel.delete(row.eid)
    assert panel.list.count() == 0
