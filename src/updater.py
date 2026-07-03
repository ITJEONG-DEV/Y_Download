"""
updater.py
----------
GitHub Releases 기반 자동 업데이트.

흐름:
  1) check_update(현재버전)  -> 최신 릴리스가 더 높으면 정보 dict 반환
  2) download_and_apply(...)  -> 현재 빌드(full/lite)에 맞는 zip을 받아 교체 준비.
     실행 중인 exe는 스스로 덮어쓸 수 없으므로, 도우미 배치(.bat)가 현재 프로세스
     종료를 기다렸다가 파일을 교체하고 프로그램을 재시작한다.

개발(비프리즈) 실행에서는 자동 적용을 하지 않는다(build_kind()=="dev").
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from typing import Callable, Optional
from urllib.request import Request, urlopen

REPO = "ITJEONG-DEV/Y_Download"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"

# Windows 프로세스 생성 플래그 (도우미 배치를 창 없이 분리 실행)
_DETACHED_NO_WINDOW = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW


# ---------------------------------------------------------------------------
def _parse_version(s: str) -> tuple:
    s = (s or "").lstrip("vV").split("+")[0].split("-")[0]
    parts = []
    for p in s.split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple((parts + [0, 0, 0])[:3])


def build_kind() -> str:
    """현재 실행 형태: 'full'(폴더형), 'lite'(단일파일), 'dev'(소스 실행)."""
    if not getattr(sys, "frozen", False):
        return "dev"
    exe_dir = os.path.dirname(sys.executable)
    if os.path.isdir(os.path.join(exe_dir, "_internal")):
        return "full"
    return "lite"


def get_latest() -> dict:
    req = Request(
        API_LATEST,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Y_Downloader"},
    )
    with urlopen(req, timeout=10) as r:
        data = json.load(r)
    return {
        "tag": data.get("tag_name", ""),
        "body": data.get("body", "") or "",
        "assets": {a["name"]: a["browser_download_url"] for a in data.get("assets", [])},
        "html_url": data.get("html_url", ""),
    }


# 릴리스 본문에서 "이번 버전 변경사항" 요약 섹션만 뽑아낸다(없으면 앞부분 일부).
_SUMMARY_START = "<!--CHANGES-->"
_SUMMARY_END = "<!--/CHANGES-->"


def extract_summary(body: str, max_lines: int = 12) -> str:
    if _SUMMARY_START in body and _SUMMARY_END in body:
        seg = body.split(_SUMMARY_START, 1)[1].split(_SUMMARY_END, 1)[0]
        return seg.strip()
    # 마커가 없으면 앞부분 몇 줄만
    lines = [ln for ln in body.splitlines() if ln.strip()]
    return "\n".join(lines[:max_lines]).strip() or "(변경 내용 정보 없음)"


def check_update(current_version: str) -> Optional[dict]:
    """최신 릴리스가 현재보다 높으면 릴리스 정보 dict, 아니면 None. 네트워크 오류는 예외."""
    latest = get_latest()
    if not latest["tag"]:
        return None
    if _parse_version(latest["tag"]) > _parse_version(current_version):
        return latest
    return None


# ---------------------------------------------------------------------------
def _asset_url(latest: dict, kind: str) -> tuple[Optional[str], Optional[str]]:
    """빌드 종류에 맞는 zip 자산(name, url)을 고른다."""
    for name, url in latest["assets"].items():
        low = name.lower()
        if kind in low and low.endswith(".zip"):
            return name, url
    return None, None


def _download(url: str, dest: str, progress: Optional[Callable[[float], None]] = None) -> None:
    req = Request(url, headers={"User-Agent": "Y_Downloader"})
    with urlopen(req, timeout=30) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done * 100 / total)


def _find(root: str, filename: str) -> Optional[str]:
    for dirpath, _dirs, files in os.walk(root):
        if filename in files:
            return os.path.join(dirpath, filename)
    return None


def _launch_and_exit_helper(bat_text: str, tmp: str) -> None:
    """도우미 배치를 파일로 쓰고 창 없이 분리 실행한다(현재 프로세스 종료 대기)."""
    bat = os.path.join(tmp, "_update.bat")
    with open(bat, "w", encoding="utf-8") as f:
        f.write(bat_text)
    subprocess.Popen(
        ["cmd", "/c", bat],
        creationflags=_DETACHED_NO_WINDOW,
        close_fds=True,
    )


def download_and_apply(
    latest: dict,
    kind: str,
    progress: Optional[Callable[[float], None]] = None,
) -> None:
    """
    최신 자산을 받아 교체 도우미 배치를 실행한다. 이 함수가 리턴한 뒤
    호출자는 앱을 종료해야 배치가 파일 교체를 진행한다.
    """
    if kind == "dev":
        raise RuntimeError("개발 실행에서는 자동 업데이트를 적용할 수 없습니다.")

    name, url = _asset_url(latest, kind)
    if not url:
        raise RuntimeError(f"'{kind}' 빌드용 업데이트 파일을 찾지 못했습니다.")

    tmp = tempfile.mkdtemp(prefix="ydl_update_")
    zpath = os.path.join(tmp, name)
    _download(url, zpath, progress)

    extract = os.path.join(tmp, "extracted")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(extract)

    pid = os.getpid()
    wait_block = (
        f':wait\r\n'
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul\r\n'
        f'if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto wait )\r\n'
    )

    if kind == "lite":
        new_exe = _find(extract, "Y_Downloader-lite.exe")
        if not new_exe:
            raise RuntimeError("압축에서 lite exe를 찾지 못했습니다.")
        cur_exe = sys.executable
        bat = (
            "@echo off\r\n"
            + wait_block
            + f'copy /y "{new_exe}" "{cur_exe}" >nul\r\n'
            + f'start "" "{cur_exe}"\r\n'
            + f'rmdir /s /q "{tmp}"\r\n'
        )
    else:  # full (onedir)
        app_dir = os.path.dirname(sys.executable)
        exe_name = os.path.basename(sys.executable)
        bat = (
            "@echo off\r\n"
            + wait_block
            # 새 폴더 내용을 앱 폴더에 덮어쓰기(추가/변경만, 사용자 데이터 삭제 없음)
            + f'robocopy "{extract}" "{app_dir}" /E /NFL /NDL /NJH /NJS /NP >nul\r\n'
            + f'start "" "{os.path.join(app_dir, exe_name)}"\r\n'
            + f'rmdir /s /q "{tmp}"\r\n'
        )

    _launch_and_exit_helper(bat, tmp)
