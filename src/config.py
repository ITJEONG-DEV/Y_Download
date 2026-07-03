"""
config.py
---------
사용자 설정(마지막 저장 위치 등)과 다운로드 내역을 JSON 파일로 영구 저장한다.
저장 위치: %APPDATA%/YouTubeDownloader/  (없으면 홈 디렉터리)
"""

from __future__ import annotations

import json
import os

_APP_DIR = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), "YouTubeDownloader"
)
_SETTINGS_PATH = os.path.join(_APP_DIR, "settings.json")
_HISTORY_PATH = os.path.join(_APP_DIR, "history.json")

# 내역 최대 보관 개수 (오래된 것부터 버림)
_HISTORY_LIMIT = 200


def _ensure_dir() -> None:
    os.makedirs(_APP_DIR, exist_ok=True)


# --------------------------------------------------------------- 설정
def load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    try:
        _ensure_dir()
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
    except OSError:
        pass  # 설정 저장 실패는 치명적이지 않으므로 무시


def get_download_dir(default: str) -> str:
    return load_settings().get("download_dir", default)


def set_download_dir(path: str) -> None:
    data = load_settings()
    data["download_dir"] = path
    save_settings(data)


# --------------------------------------------------------------- 내역
def load_history() -> list[dict]:
    """최신 항목이 앞(index 0)에 오도록 반환."""
    try:
        with open(_HISTORY_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def add_history(entry: dict) -> None:
    """
    다운로드 시도 1건을 내역 맨 앞에 추가한다.
    entry 예시 키: url, title, filename, kind, ext, quality, status('성공'/'실패'),
                  message, timestamp(문자열)
    """
    history = load_history()
    history.insert(0, entry)
    del history[_HISTORY_LIMIT:]
    try:
        _ensure_dir()
        with open(_HISTORY_PATH, "w", encoding="utf-8") as fp:
            json.dump(history, fp, ensure_ascii=False, indent=2)
    except OSError:
        pass


def clear_history() -> None:
    try:
        _ensure_dir()
        with open(_HISTORY_PATH, "w", encoding="utf-8") as fp:
            json.dump([], fp)
    except OSError:
        pass
