"""
공용 테스트 픽스처.
- src/ 를 import 경로에 넣어 downloader/config/updater/app 을 직접 import.
- isolated_config: config 의 저장 경로를 임시 폴더로 격리(실제 %APPDATA% 오염 방지).
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """config 모듈의 파일 경로를 임시 폴더로 바꿔 격리한다."""
    import config

    app_dir = tmp_path / "Y_Downloader"
    monkeypatch.setattr(config, "_APP_DIR", str(app_dir))
    monkeypatch.setattr(config, "_SETTINGS_PATH", str(app_dir / "settings.json"))
    monkeypatch.setattr(config, "_HISTORY_PATH", str(app_dir / "history.json"))
    monkeypatch.setattr(config, "_THUMBS_DIR", str(app_dir / "thumbs"))
    return config


class FakeYDL:
    """yt_dlp.YoutubeDL 을 대체하는 컨텍스트 매니저. 정해둔 결과를 반환한다."""

    result = None  # 클래스 속성으로 주입

    def __init__(self, opts=None):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        return type(self).result
