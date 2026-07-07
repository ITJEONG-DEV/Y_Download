"""downloader.py 순수 로직 단위 테스트 (네트워크 없음)."""
import os

import pytest

import downloader as d
from downloader import VideoInfo
from conftest import FakeYDL


# --------------------------------------------------------------- sanitize
@pytest.mark.parametrize("raw, expected", [
    ('a/b:c*?"<>|', "abc"),
    ("  hello world  ", "hello world"),
    ("정상 파일명", "정상 파일명"),
    ("", "download"),
    ("///", "download"),
])
def test_sanitize_filename(raw, expected):
    assert d.sanitize_filename(raw) == expected


# --------------------------------------------------------------- 재생목록 URL 판별
@pytest.mark.parametrize("url, expected", [
    ("https://www.youtube.com/watch?v=abc", False),
    ("https://youtu.be/abc", False),
    ("https://www.youtube.com/playlist?list=PL123", True),
    ("https://www.youtube.com/watch?v=abc&list=PL123", True),
    ("https://www.youtube.com/PLAYLIST?LIST=X", True),  # 대소문자 무관
])
def test_is_playlist_url(url, expected):
    assert d.is_playlist_url(url) is expected


# --------------------------------------------------------------- format_size
@pytest.mark.parametrize("num, expected", [
    (None, "알 수 없음"),
    (0, "알 수 없음"),
    (512, "512 B"),
    (1536, "1.5 KB"),
    (5 * 1024 * 1024, "5.0 MB"),
    (3 * 1024 ** 3, "3.0 GB"),
])
def test_format_size(num, expected):
    assert d.format_size(num) == expected


# --------------------------------------------------------------- estimate_size
def _info(**kw):
    base = dict(
        url="u", title="t", thumbnail_url="", duration=100, uploader="",
        available_heights=[1080, 720, 480],
        video_size_by_height={1080: 5_000_000, 720: 3_000_000, 480: 1_000_000},
        best_audio_size=1_000_000,
    )
    base.update(kw)
    return VideoInfo(**base)


def test_estimate_video_selects_by_max_height():
    info = _info()
    assert d.estimate_size(info, kind="video", max_height=720, audio_bitrate="192") == 4_000_000
    assert d.estimate_size(info, kind="video", max_height=None, audio_bitrate="192") == 6_000_000
    # 요청 해상도보다 낮은 후보가 없으면 가장 낮은 해상도로 폴백
    assert d.estimate_size(info, kind="video", max_height=240, audio_bitrate="192") == 2_000_000


def test_estimate_video_none_when_no_sizes():
    info = _info(video_size_by_height={})
    assert d.estimate_size(info, kind="video", max_height=None, audio_bitrate="192") is None


def test_estimate_audio_by_bitrate():
    info = _info()
    assert d.estimate_size(info, kind="audio", max_height=None, audio_bitrate="192") == 2_400_000
    # 길이 정보 없으면 best_audio_size 로 폴백
    info2 = _info(duration=0)
    assert d.estimate_size(info2, kind="audio", max_height=None, audio_bitrate="192") == 1_000_000


# --------------------------------------------------------------- _stream_size
def test_stream_size():
    assert d._stream_size({"filesize": 1234}, 100) == 1234
    assert d._stream_size({"filesize_approx": 999}, 100) == 999
    # filesize 없으면 tbr(kbps)*길이/8
    assert d._stream_size({"tbr": 800}, 100) == int(800 * 1000 / 8 * 100)
    assert d._stream_size({}, 100) is None


# --------------------------------------------------------------- _uniquify
def test_uniquify(tmp_path):
    out = str(tmp_path)
    assert d._uniquify(out, "song", "mp3") == "song"
    (tmp_path / "song.mp3").write_text("x")
    assert d._uniquify(out, "song", "mp3") == "song (1)"
    (tmp_path / "song (1).mp3").write_text("x")
    assert d._uniquify(out, "song", "mp3") == "song (2)"


# --------------------------------------------------------------- 상수 무결성
def test_conflict_policies():
    assert d.CONFLICT_POLICIES == (d.CONFLICT_NUMBER, d.CONFLICT_OVERWRITE, d.CONFLICT_SKIP)
    assert "mp4" in d.VIDEO_EXTS and "mp3" in d.AUDIO_EXTS


# --------------------------------------------------------------- fetch_playlist (yt_dlp 목킹)
def test_fetch_playlist_normalizes_and_filters(monkeypatch):
    FakeYDL.result = {
        "title": "내 재생목록",
        "entries": [
            {"id": "AAA", "title": "첫 곡", "duration": 100},        # id만 → watch URL 보정
            {"url": "https://www.youtube.com/watch?v=BBB", "title": "둘째", "duration": 200},
            None,                                                     # 비공개/삭제 → 건너뜀
            {"title": "url 없음"},                                    # url/id 없음 → 건너뜀
        ],
    }
    monkeypatch.setattr(d.yt_dlp, "YoutubeDL", FakeYDL)
    title, entries = d.fetch_playlist("https://www.youtube.com/playlist?list=X")
    assert title == "내 재생목록"
    assert len(entries) == 2
    assert entries[0].url == "https://www.youtube.com/watch?v=AAA"
    assert entries[0].title == "첫 곡" and entries[0].duration == 100
    assert entries[1].url == "https://www.youtube.com/watch?v=BBB"


def test_fetch_playlist_returns_none_when_no_entries(monkeypatch):
    FakeYDL.result = {"title": "단일 영상"}  # entries 없음
    monkeypatch.setattr(d.yt_dlp, "YoutubeDL", FakeYDL)
    assert d.fetch_playlist("https://www.youtube.com/watch?v=abc") is None
