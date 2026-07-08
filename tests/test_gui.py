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


# --------------------------------------------------------------- 일괄 적용 바
def test_bulk_apply_video_and_audio(qapp, main):
    from downloader import PlaylistEntry
    main._add_playlist_entries([PlaylistEntry(url=f"https://www.youtube.com/watch?v=B{i}",
                                              title=f"임시-{i}", duration=10) for i in range(3)])
    _pump(qapp, lambda: main._enrich_pending == 0)  # 개별 조회로 해상도[1080,720] 반영

    # 영상 + mkv + 720p 캡 → 모든 행에 반영(각 행 실제 해상도 중 ≤720 최적)
    main.bulk_kind.setCurrentText("영상")
    main.bulk_ext.setCurrentText("mkv")
    main.bulk_quality.setCurrentText("720p (HD)")
    main.on_apply_bulk()
    for r in main.rows:
        p = r.get_params()
        assert p["kind"] == "video" and p["ext"] == "mkv"
        assert p["max_height"] == 720

    # 캡(480p)보다 낮은 가용 해상도가 없으면 가장 낮은 해상도(720)로 폴백
    main.bulk_quality.setCurrentText("480p")
    main.on_apply_bulk()
    assert all(r.get_params()["max_height"] == 720 for r in main.rows)

    # 음원 + m4a + 256 → 확장자/품질 목록이 음원용으로 전환되어 반영
    main.bulk_kind.setCurrentText("음원")
    main.bulk_ext.setCurrentText("m4a")
    main.bulk_quality.setCurrentText("256")
    main.on_apply_bulk()
    for r in main.rows:
        p = r.get_params()
        assert p["kind"] == "audio" and p["ext"] == "m4a" and p["audio_bitrate"] == "256"


def test_bulk_apply_empty_list_is_noop(qapp, main):
    assert main.rows == []
    main.on_apply_bulk()  # 예외 없이 안내만
    assert "없습니다" in main.status_label.text()


# --------------------------------------------------------------- 다운로드 취소
def test_cancel_download(qapp, main, isolated_config, monkeypatch, tmp_path):
    import app as app_qt
    from downloader import DownloadResult, DownloadCancelled
    from downloader import PlaylistEntry

    main._add_playlist_entries([PlaylistEntry(url=f"https://y/watch?v={c}", title=c, duration=5)
                                for c in ("a", "b")])
    _pump(qapp, lambda: main._enrich_pending == 0)
    main.dir_entry.setText(str(tmp_path))

    # 진행률 훅을 반복 호출하며 취소 신호(훅에서 DownloadCancelled)가 오길 기다리는 가짜 다운로드
    def fake_download(output_dir, progress_callback=None, **params):
        for _ in range(2000):
            if progress_callback:
                progress_callback({"status": "downloading",
                                   "total_bytes": 100, "downloaded_bytes": 1})
            time.sleep(0.005)
        return DownloadResult(path=str(tmp_path / "x.mp4"), status="downloaded")

    monkeypatch.setattr(app_qt, "download", fake_download)

    main.on_download_all()
    assert main._downloading and main.download_btn.text() == "취소"
    # 첫 항목이 실제로 진행(%) 상태가 될 때까지 대기
    _pump(qapp, lambda: "%" in main.rows[0].status_label.text())

    main.on_cancel()
    _pump(qapp, lambda: not main._downloading)

    # 큐 중단 + 상태/버튼 원복 + 미처리 항목 '취소됨' + 취소 항목은 내역 미기록
    assert "취소" in main.status_label.text()
    assert main.download_btn.text() == "전체 다운로드"
    assert all(r.status_label.text() == "취소됨" for r in main.rows)
    assert isolated_config.load_history() == []


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
    # 창모드 폭 확장 — 좁은 화면(CI 등)에선 요청 폭이 화면에 맞게 클램프될 수 있으므로
    # '패널폭만큼(그 이하로) 넓어졌는지'로 검증한다.
    assert w0 < main.geometry().width() <= w0 + app_qt.HISTORY_PANEL_WIDTH
    assert main.history_panel.list.count() == 1

    main.toggle_history()
    qapp.processEvents()
    assert not main.history_dock.isVisible()
    assert main.geometry().width() == w0  # 열기 전 폭으로 정확히 원복


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


def test_history_open_folder(qapp, main, isolated_config, monkeypatch, tmp_path):
    import app as app_qt
    save_dir = str(tmp_path)
    # add_history는 최신을 맨 앞(index 0)에 넣는다. dir 없는 옛 항목을 먼저, dir 있는 항목을 나중에
    # 추가해 index 0 = dir 있는 최신 항목이 되게 한다.
    isolated_config.add_history({"title": "옛항목", "filename": "old", "status": "성공",
                                 "kind": "영상", "ext": "mp4", "quality": "720p (HD)",
                                 "timestamp": "2026-07-08 09:00", "message": ""})  # dir 없음
    isolated_config.add_history({"title": "영상B", "filename": "fileB", "status": "성공",
                                 "kind": "영상", "ext": "mp4", "quality": "720p (HD)",
                                 "timestamp": "2026-07-08 10:00", "message": "", "dir": save_dir})
    main.toggle_history()
    qapp.processEvents()
    panel = main.history_panel

    opened = {}
    monkeypatch.setattr(app_qt, "_open_in_file_manager", lambda p: opened.setdefault("path", p))

    # 최신(index 0) = dir 있는 항목 → 폴더 열림
    row0 = panel.list.itemWidget(panel.list.item(0))
    assert row0.save_dir == save_dir
    panel.open_dir(row0.save_dir)
    assert opened["path"] == save_dir

    # dir 없는 옛 항목 → 열지 않고 안내만
    opened.clear()
    row1 = panel.list.itemWidget(panel.list.item(1))
    assert row1.save_dir == ""
    panel.open_dir(row1.save_dir)
    assert "path" not in opened
    assert "정보가 없는" in main.status_label.text()

    # 존재하지 않는 폴더 → 안내
    main.open_history_dir(str(tmp_path / "nope"))
    assert "찾을 수 없" in main.status_label.text()
