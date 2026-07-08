"""
config.py
---------
사용자 설정(마지막 저장 위치 등)과 다운로드 내역을 JSON 파일로 영구 저장한다.
저장 위치(OS별):
  - Windows: %APPDATA%/Y_Downloader/
  - macOS:   ~/Library/Application Support/Y_Downloader/
  - Linux:   $XDG_CONFIG_HOME/Y_Downloader/ (없으면 ~/.config/Y_Downloader/)
"""

from __future__ import annotations

import json
import os
import sys
import uuid


def _default_app_dir() -> str:
    """OS 규약에 맞는 앱 데이터 폴더. Windows는 기존과 동일(%APPDATA%)로 호환 유지."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or home
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:  # linux 및 기타 유닉스
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(base, "Y_Downloader")


_APP_DIR = _default_app_dir()
_SETTINGS_PATH = os.path.join(_APP_DIR, "settings.json")
_HISTORY_PATH = os.path.join(_APP_DIR, "history.json")
_THUMBS_DIR = os.path.join(_APP_DIR, "thumbs")

# 내역 최대 보관 개수 (오래된 것부터 버림)
_HISTORY_LIMIT = 200


def _ensure_dir() -> None:
    os.makedirs(_APP_DIR, exist_ok=True)


def thumbs_dir() -> str:
    """내역 썸네일 저장 폴더(없으면 생성)."""
    try:
        os.makedirs(_THUMBS_DIR, exist_ok=True)
    except OSError:
        pass
    return _THUMBS_DIR


def _remove_thumb(entry: dict) -> None:
    path = entry.get("thumb")
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


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


def get_conflict_policy(default: str = "number") -> str:
    return load_settings().get("conflict_policy", default)


def set_conflict_policy(policy: str) -> None:
    data = load_settings()
    data["conflict_policy"] = policy
    save_settings(data)


def get_item_defaults() -> dict:
    defaults = load_settings().get("item_defaults")
    return defaults if isinstance(defaults, dict) else {}


def set_item_defaults(defaults: dict) -> None:
    data = load_settings()
    data["item_defaults"] = defaults
    save_settings(data)


def get_window() -> dict | None:
    """마지막 창 위치/크기/최대화 상태({x,y,w,h,zoomed}) 또는 None."""
    win = load_settings().get("window")
    return win if isinstance(win, dict) else None


def set_window(win: dict) -> None:
    data = load_settings()
    data["window"] = win
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


def _save_history(history: list[dict]) -> None:
    try:
        _ensure_dir()
        with open(_HISTORY_PATH, "w", encoding="utf-8") as fp:
            json.dump(history, fp, ensure_ascii=False, indent=2)
    except OSError:
        pass


def add_history(entry: dict) -> None:
    """
    다운로드 시도 1건을 내역 맨 앞에 추가한다. 고유 id를 자동 부여한다.
    entry 예시 키: url, title, filename, kind, ext, quality, status('성공'/'실패'),
                  message, timestamp(문자열), dir(저장 폴더 — 내역 '폴더 열기'용)
    """
    entry.setdefault("id", uuid.uuid4().hex)
    history = load_history()
    history.insert(0, entry)
    for old in history[_HISTORY_LIMIT:]:  # 한도 초과로 버려지는 항목의 썸네일 정리
        _remove_thumb(old)
    del history[_HISTORY_LIMIT:]
    _save_history(history)


def delete_history(entry_id: str) -> None:
    """id가 일치하는 내역 1건을 삭제한다(썸네일 파일도 제거)."""
    if not entry_id:
        return
    kept = []
    for e in load_history():
        if e.get("id") == entry_id:
            _remove_thumb(e)
        else:
            kept.append(e)
    _save_history(kept)


def clear_history() -> None:
    for e in load_history():
        _remove_thumb(e)
    try:
        _ensure_dir()
        with open(_HISTORY_PATH, "w", encoding="utf-8") as fp:
            json.dump([], fp)
    except OSError:
        pass
