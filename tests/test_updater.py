"""updater.py 로직 단위 테스트 (네트워크 목킹)."""
import pytest

import updater as u


@pytest.mark.parametrize("s, expected", [
    ("v0.1.8", (0, 1, 8)),
    ("0.1.8", (0, 1, 8)),
    ("0.1.8-beta", (0, 1, 8)),
    ("1.2", (1, 2, 0)),
    ("v10.0.3+build", (10, 0, 3)),
    ("", (0, 0, 0)),
])
def test_parse_version(s, expected):
    assert u._parse_version(s) == expected


def test_version_ordering():
    assert u._parse_version("v0.2.0") > u._parse_version("0.1.9")
    assert u._parse_version("1.0.0") > u._parse_version("0.9.9")
    assert not (u._parse_version("0.1.8") > u._parse_version("0.1.8"))


def test_extract_summary_with_markers():
    body = "머리말\n<!--CHANGES-->\n- 기능 A\n- 기능 B\n<!--/CHANGES-->\n꼬리말"
    assert u.extract_summary(body) == "- 기능 A\n- 기능 B"


def test_extract_summary_without_markers():
    body = "첫 줄\n\n둘째 줄\n셋째 줄"
    assert u.extract_summary(body, max_lines=2) == "첫 줄\n둘째 줄"


def test_extract_summary_empty():
    assert u.extract_summary("") == "(변경 내용 정보 없음)"


def test_asset_url_selects_kind():
    latest = {"assets": {
        "Y_Downloader-full-0.1.8.zip": "http://x/full",
        "Y_Downloader-lite-0.1.8.zip": "http://x/lite",
    }}
    assert u._asset_url(latest, "full") == ("Y_Downloader-full-0.1.8.zip", "http://x/full")
    assert u._asset_url(latest, "lite") == ("Y_Downloader-lite-0.1.8.zip", "http://x/lite")
    assert u._asset_url({"assets": {}}, "full") == (None, None)


def _fake_latest(tag):
    return {"tag": tag, "body": "", "assets": {}, "html_url": ""}


def test_check_update_newer(monkeypatch):
    monkeypatch.setattr(u, "get_latest", lambda: _fake_latest("v0.2.0"))
    assert u.check_update("0.1.8")["tag"] == "v0.2.0"


def test_check_update_same_or_older(monkeypatch):
    monkeypatch.setattr(u, "get_latest", lambda: _fake_latest("v0.1.8"))
    assert u.check_update("0.1.8") is None
    monkeypatch.setattr(u, "get_latest", lambda: _fake_latest("v0.1.0"))
    assert u.check_update("0.1.8") is None


def test_check_update_empty_tag(monkeypatch):
    monkeypatch.setattr(u, "get_latest", lambda: _fake_latest(""))
    assert u.check_update("0.1.8") is None


def test_build_kind_dev_in_source_run():
    # 소스 실행(비 frozen)에서는 항상 'dev'
    assert u.build_kind() == "dev"


def test_lite_script_contains_paths():
    script = u._lite_script(1234, r"C:\old\app.exe", r"C:\new\app.exe", r"C:\log.txt")
    assert "1234" in script
    assert "app.exe" in script
