"""
크로스플랫폼 런타임 코드 단위 테스트 — sys.platform을 목킹해 OS별 분기를 검증한다.
실제 macOS/Linux 없이 Windows에서도 각 분기의 경로/명령을 확인할 수 있다.
"""
import os

import pytest

import config
import downloader as d


# --------------------------------------------------------------- 앱 데이터 폴더
def test_app_dir_windows(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", os.path.join("C:\\", "Users", "u", "AppData", "Roaming"))
    got = config._default_app_dir()
    assert got.endswith(os.path.join("Roaming", "Y_Downloader"))


def test_app_dir_macos(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "darwin")
    monkeypatch.setattr(config.os.path, "expanduser", lambda p: "/Users/u")
    # 구분자는 실행 OS 규약을 따르므로 기대값도 os.path.join으로 구성해 이식성 확보
    expected = os.path.join("/Users/u", "Library", "Application Support", "Y_Downloader")
    assert config._default_app_dir() == expected


def test_app_dir_linux_xdg(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setattr(config.os.path, "expanduser", lambda p: "/home/u")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/u/.config")
    assert config._default_app_dir() == os.path.join("/home/u/.config", "Y_Downloader")


def test_app_dir_linux_default(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setattr(config.os.path, "expanduser", lambda p: "/home/u")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    expected = os.path.join("/home/u", ".config", "Y_Downloader")
    assert config._default_app_dir() == expected


# --------------------------------------------------------------- ffmpeg 이름/위치
def test_ffmpeg_names_windows(monkeypatch):
    monkeypatch.setattr(d.sys, "platform", "win32")
    assert d._ffmpeg_names() == ("ffmpeg.exe", "ffprobe.exe")


@pytest.mark.parametrize("plat", ["darwin", "linux"])
def test_ffmpeg_names_unix(monkeypatch, plat):
    monkeypatch.setattr(d.sys, "platform", plat)
    assert d._ffmpeg_names() == ("ffmpeg", "ffprobe")


def test_ffmpeg_location_points_to_binary_dir():
    """반환값이 있으면 그 폴더에 현재 플랫폼용 ffmpeg 실행파일이 실제로 존재해야 한다."""
    loc = d._ffmpeg_location()
    if loc is not None:
        assert os.path.exists(os.path.join(loc, d._ffmpeg_names()[0]))


def test_ffmpeg_location_macos_app_bundle(monkeypatch, tmp_path):
    """macOS .app 레이아웃(Contents/Resources/ffmpeg)에 둔 ffmpeg를 찾는다."""
    contents = tmp_path / "Y_Downloader.app" / "Contents"
    macos = contents / "MacOS"
    res_ff = contents / "Resources" / "ffmpeg"
    macos.mkdir(parents=True)
    res_ff.mkdir(parents=True)
    (res_ff / "ffmpeg").write_text("x")

    monkeypatch.setattr(d.sys, "platform", "darwin")
    monkeypatch.setattr(d.sys, "frozen", True, raising=False)
    monkeypatch.setattr(d.sys, "executable", str(macos / "Y_Downloader"), raising=False)
    monkeypatch.setattr(d.sys, "_MEIPASS", None, raising=False)
    assert d._ffmpeg_location() == str(res_ff)


# --------------------------------------------------------------- 폴더 열기
def test_open_in_file_manager_windows(monkeypatch):
    import app
    calls = {}
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(app.os, "startfile", lambda p: calls.setdefault("startfile", p), raising=False)
    app._open_in_file_manager("C:\\some\\dir")
    assert calls["startfile"] == "C:\\some\\dir"


@pytest.mark.parametrize("plat, cmd", [("darwin", "open"), ("linux", "xdg-open")])
def test_open_in_file_manager_unix(monkeypatch, plat, cmd):
    import app
    captured = {}
    monkeypatch.setattr(app.sys, "platform", plat)
    monkeypatch.setattr(app.subprocess, "run", lambda args, **kw: captured.setdefault("args", args))
    app._open_in_file_manager("/some/dir")
    assert captured["args"] == [cmd, "/some/dir"]
