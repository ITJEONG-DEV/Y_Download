"""
updater.py
----------
GitHub Releases 기반 자동 업데이트.

흐름:
  1) check_update(현재버전)  -> 최신 릴리스가 더 높으면 정보 dict 반환
  2) download_and_apply(...)  -> 현재 빌드(full/lite)에 맞는 zip을 받아 교체 준비.
     실행 중인 exe는 스스로 덮어쓸 수 없으므로, 도우미 PowerShell 스크립트가 현재 프로세스
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

# Run helper without showing a console window
_CREATE_NO_WINDOW = 0x08000000

# Helper script log path (fixed location for diagnostics)
_LOG_PATH = os.path.join(tempfile.gettempdir(), "Y_Downloader_update.log")


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


_NL = chr(13) + chr(10)


def _ps_literal(s: str) -> str:
    """PowerShell single-quoted string literal."""
    return "'" + s.replace("'", "''") + "'"


def _ps_lines(*lines: str) -> str:
    return _NL.join(lines) + _NL


def _wait_block(pid: int, log: str) -> str:
    """Return PowerShell code that waits for the current process to exit."""
    return _ps_lines(
        f"$Log = {_ps_literal(log)}",
        f"Add-Content -LiteralPath $Log -Encoding UTF8 -Value '[update] waiting for pid {pid}'",
        f"while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{",
        "  Start-Sleep -Milliseconds 700",
        "}",
        "Start-Sleep -Seconds 1",
    )


def _lite_script(pid: int, cur: str, new: str, log: str) -> str:
    # A running exe cannot be overwritten directly; rename it, then copy the new exe.
    return _ps_lines(
        "$ErrorActionPreference = 'Stop'",
        f"$Log = {_ps_literal(log)}",
        "Set-Content -LiteralPath $Log -Encoding UTF8 -Value '[update] lite start'",
        f"$Cur = {_ps_literal(cur)}",
        f"$New = {_ps_literal(new)}",
    ) + _wait_block(pid, log) + _ps_lines(
        "$Old = $Cur + '.old'",
        "try {",
        "  Move-Item -LiteralPath $Cur -Destination $Old -Force",
        "  try {",
        "    Copy-Item -LiteralPath $New -Destination $Cur -Force",
        "  } catch {",
        "    Start-Sleep -Seconds 2",
        "    Copy-Item -LiteralPath $New -Destination $Cur -Force",
        "  }",
        "  Start-Process -FilePath $Cur -WorkingDirectory (Split-Path -LiteralPath $Cur -Parent)",
        "  Remove-Item -LiteralPath $Old -Force -ErrorAction SilentlyContinue",
        "  Add-Content -LiteralPath $Log -Encoding UTF8 -Value '[update] lite done'",
        "} catch {",
        "  Add-Content -LiteralPath $Log -Encoding UTF8 -Value ('[update] lite failed: ' + $_.Exception.Message)",
        "  throw",
        "}",
    )


def _full_script(pid: int, extract: str, app_dir: str, exe_name: str, log: str) -> str:
    # After the process exits, overwrite files in the app directory.
    return _ps_lines(
        "$ErrorActionPreference = 'Stop'",
        f"$Log = {_ps_literal(log)}",
        "Set-Content -LiteralPath $Log -Encoding UTF8 -Value '[update] full start'",
        f"$Extract = {_ps_literal(extract)}",
        f"$AppDir = {_ps_literal(app_dir)}",
        f"$Exe = {_ps_literal(os.path.join(app_dir, exe_name))}",
    ) + _wait_block(pid, log) + _ps_lines(
        "try {",
        "  Get-ChildItem -LiteralPath $Extract -Force | Copy-Item -Destination $AppDir -Recurse -Force",
        "  Start-Process -FilePath $Exe -WorkingDirectory $AppDir",
        "  Add-Content -LiteralPath $Log -Encoding UTF8 -Value '[update] full done'",
        "} catch {",
        "  Add-Content -LiteralPath $Log -Encoding UTF8 -Value ('[update] full failed: ' + $_.Exception.Message)",
        "  throw",
        "}",
    )


def _launch_helper(script_text: str) -> None:
    """Write and launch the helper PowerShell script hidden."""
    helper_dir = tempfile.mkdtemp(prefix="ydl_helper_")
    ps1 = os.path.join(helper_dir, "update.ps1")
    # UTF-8 with BOM lets Windows PowerShell 5.1 read non-ASCII paths reliably.
    with open(ps1, "w", encoding="utf-8-sig") as f:
        f.write(script_text)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden",
            "-File", ps1,
        ],
        creationflags=_CREATE_NO_WINDOW,
        close_fds=True,
    )


def download_and_apply(
    latest: dict,
    kind: str,
    progress: Optional[Callable[[float], None]] = None,
) -> None:
    """
    Download the latest asset and launch a helper PowerShell script.
    The caller must exit the app after this returns so the helper can replace files.
    문제 진단 로그: %TEMP%/Y_Downloader_update.log
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
    log = _LOG_PATH

    if kind == "lite":
        new_exe = _find(extract, "Y_Downloader-lite.exe")
        if not new_exe:
            raise RuntimeError("압축에서 lite exe를 찾지 못했습니다.")
        script = _lite_script(pid, sys.executable, new_exe, log)
    else:  # full (onedir)
        app_dir = os.path.dirname(sys.executable)
        exe_name = os.path.basename(sys.executable)
        script = _full_script(pid, extract, app_dir, exe_name, log)

    _launch_helper(script)
