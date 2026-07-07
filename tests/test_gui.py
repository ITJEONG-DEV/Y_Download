"""
GUI 스모크 테스트 — 실제 Tk 창을 만들되 사용자 상호작용 없이 로직 경로를 검증한다.
네트워크(fetch_info/썸네일)는 목킹한다. 디스플레이가 없으면 자동 skip.

한 프로세스에서 Tk 루트를 여러 번 만들면 불안정하므로(App 은 곧 Tk 루트),
App 을 모듈당 한 번만 생성해 공유하고 각 테스트 시작 시 상태를 초기화한다.

실행:  pytest -m gui        (또는 기본 실행에 포함됨)
"""
import tempfile
import time

import pytest

pytestmark = pytest.mark.gui


def _fake_fetch_info(url, timeout=5):
    from downloader import VideoInfo
    vid = url.rsplit("=", 1)[-1]
    return VideoInfo(
        url=url, title=f"실제제목-{vid}", thumbnail_url="http://x/t.jpg",
        duration=200, uploader="u",
        available_heights=[1080, 720, 480],
        video_size_by_height={1080: 5_000_000}, best_audio_size=1_000_000,
    )


@pytest.fixture(scope="module")
def app():
    """모듈당 1개의 App(=Tk 루트)을 만들어 공유한다. 네트워크·설정은 격리."""
    import app as appmod
    import config

    # 설정 저장을 임시 폴더로 격리(모듈 스코프이므로 monkeypatch 대신 직접)
    tmp = tempfile.TemporaryDirectory()
    import os
    app_dir = os.path.join(tmp.name, "Y_Downloader")
    orig = {k: getattr(config, k) for k in
            ("_APP_DIR", "_SETTINGS_PATH", "_HISTORY_PATH", "_THUMBS_DIR")}
    config._APP_DIR = app_dir
    config._SETTINGS_PATH = os.path.join(app_dir, "settings.json")
    config._HISTORY_PATH = os.path.join(app_dir, "history.json")
    config._THUMBS_DIR = os.path.join(app_dir, "thumbs")

    orig_fetch = appmod.fetch_info
    orig_thumb = appmod.App._load_thumbnail
    appmod.fetch_info = _fake_fetch_info
    appmod.App._load_thumbnail = lambda self, url: None

    import tkinter as tk
    try:
        a = appmod.App()
    except tk.TclError as e:
        # 정리 후 skip
        appmod.fetch_info = orig_fetch
        appmod.App._load_thumbnail = orig_thumb
        for k, v in orig.items():
            setattr(config, k, v)
        tmp.cleanup()
        pytest.skip(f"디스플레이 없음: {e}")
    a.withdraw()

    yield a

    a.destroy()
    appmod.fetch_info = orig_fetch
    appmod.App._load_thumbnail = orig_thumb
    for k, v in orig.items():
        setattr(config, k, v)
    tmp.cleanup()


@pytest.fixture(autouse=True)
def _reset_rows(app):
    """각 테스트 시작 전에 목록/조회 상태를 초기화한다."""
    for row in list(app.rows):
        row.destroy()
    app.rows.clear()
    app._enrich_pending = app._enrich_done = app._enrich_workers = 0
    app._add_pending = False
    app.update_idletasks()
    yield


def _pump_until(app, predicate, timeout=8.0):
    """실제 mainloop 을 돌려 predicate 가 참이 되거나 타임아웃까지 대기."""
    start = time.time()

    def _poll():
        if predicate() or time.time() - start > timeout:
            app.quit()
        else:
            app.after(50, _poll)

    app.after(50, _poll)
    app.mainloop()


def test_playlist_quick_add_and_enrich(app):
    from downloader import PlaylistEntry
    entries = [PlaylistEntry(url=f"https://www.youtube.com/watch?v=A{i}",
                             title=f"임시제목-{i}", duration=100 + i) for i in range(3)]

    # 1) 제목만으로 즉시 3개 추가
    app._add_playlist_entries(entries)
    assert len(app.rows) == 3
    assert app.rows[0].title_label.cget("text").startswith("임시제목-0")

    # 2) 백그라운드 개별 조회 완료까지 대기
    _pump_until(app, lambda: app._enrich_pending == 0)

    assert all(r.title_label.cget("text").startswith("실제제목-") for r in app.rows)
    q = app.rows[0].quality_menu.cget("values")
    assert any("1080" in str(x) for x in q)
    assert app._enrich_pending == 0 and app._enrich_workers == 0


def test_single_add(app):
    app._start_single_add("https://www.youtube.com/watch?v=ZZZ")
    _pump_until(app, lambda: len(app.rows) >= 1 and not app._add_pending)
    assert len(app.rows) == 1
    assert app.rows[0].title_label.cget("text").startswith("실제제목-ZZZ")


def test_popup_centered_over_main_window(app):
    import customtkinter as ctk
    app.deiconify()
    app.geometry("880x660+300+200")
    app.update_idletasks()
    pop = ctk.CTkToplevel(app)
    pop.transient(app)
    app._center_popup(pop, 420, 220)
    app.update_idletasks()
    geo = pop.geometry()  # 'WxH+X+Y'
    gx = int(geo.split("+")[1])
    gy = int(geo.split("+")[2])
    px, py = app.winfo_rootx(), app.winfo_rooty()
    assert px <= gx <= px + 880
    assert py <= gy <= py + 660
    pop.destroy()
    app.withdraw()
