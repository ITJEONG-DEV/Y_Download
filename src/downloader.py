"""
downloader.py
-------------
yt-dlp를 감싸는 핵심 로직 모듈. GUI(app.py)와 분리되어 있어
단독 테스트 및 CLI 재사용이 가능하다.

주요 기능:
- fetch_info(url): 영상 정보(제목, 썸네일, 길이, 사용 가능한 화질) 조회
- download(...): 선택한 포맷/화질로 실제 다운로드 수행 (진행률 콜백 제공)
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

import yt_dlp


# 파일명에 쓸 수 없는 문자 제거용 (Windows 기준)
_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize_filename(name: str) -> str:
    """파일명에서 사용할 수 없는 문자를 제거하고 공백을 정리한다."""
    cleaned = _ILLEGAL_CHARS.sub("", name).strip()
    return cleaned or "download"


# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------
@dataclass
class VideoInfo:
    """영상 조회 결과."""
    url: str
    title: str
    thumbnail_url: str
    duration: int  # 초 단위
    uploader: str
    # 영상 다운로드 시 선택 가능한 해상도 목록 (예: [1080, 720, 480, 360])
    available_heights: list[int] = field(default_factory=list)

    @property
    def duration_str(self) -> str:
        """길이를 HH:MM:SS 또는 MM:SS 문자열로 변환."""
        if not self.duration:
            return "알 수 없음"
        h, rem = divmod(self.duration, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


# 다운로드 진행률 콜백 타입: (상태 dict) -> None
ProgressCallback = Callable[[dict], None]


# ---------------------------------------------------------------------------
# ffmpeg 위치 탐색 (개발 환경 + PyInstaller 번들 환경 모두 지원)
# ---------------------------------------------------------------------------
def _ffmpeg_location() -> Optional[str]:
    """
    번들된 ffmpeg가 있으면 그 경로를 반환한다.
    PyInstaller로 묶을 때 ffmpeg.exe를 함께 포함시키면
    sys._MEIPASS 아래에 위치한다. 없으면 None을 반환하여
    yt-dlp가 시스템 PATH에서 ffmpeg를 찾도록 둔다.
    """
    # PyInstaller 번들 환경
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = os.path.join(base, "ffmpeg", "ffmpeg.exe")
        if os.path.exists(candidate):
            return os.path.dirname(candidate)
        candidate = os.path.join(base, "ffmpeg.exe")
        if os.path.exists(candidate):
            return base

    # 프로젝트 로컬 bin/ 폴더 (선택적으로 ffmpeg.exe를 여기 둘 수 있음)
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
    local = os.path.normpath(local)
    if os.path.exists(os.path.join(local, "ffmpeg.exe")):
        return local

    return None  # 시스템 PATH 사용


# ---------------------------------------------------------------------------
# 정보 조회
# ---------------------------------------------------------------------------
def fetch_info(url: str) -> VideoInfo:
    """
    URL로부터 영상 메타데이터를 조회한다(다운로드는 하지 않음).
    실패 시 예외를 그대로 던지므로 호출부에서 처리한다.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # 플레이리스트 URL이 들어와도 첫 영상만 처리
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # 사용 가능한 해상도 추출 (중복 제거 후 내림차순)
    heights = set()
    for f in info.get("formats", []):
        h = f.get("height")
        if h and f.get("vcodec") not in (None, "none"):
            heights.add(int(h))
    available = sorted(heights, reverse=True)

    return VideoInfo(
        url=url,
        title=info.get("title", "제목 없음"),
        thumbnail_url=info.get("thumbnail", ""),
        duration=int(info.get("duration") or 0),
        uploader=info.get("uploader", ""),
        available_heights=available,
    )


# ---------------------------------------------------------------------------
# 다운로드
# ---------------------------------------------------------------------------
# 포맷별 선택 가능한 확장자
VIDEO_EXTS = ["mp4", "mkv", "webm"]
AUDIO_EXTS = ["mp3", "m4a", "wav"]


def download(
    url: str,
    output_dir: str,
    *,
    kind: str = "video",            # "video" 또는 "audio"
    ext: Optional[str] = None,      # 출력 확장자 (video: mp4/mkv/webm, audio: mp3/m4a/wav)
    max_height: Optional[int] = None,  # video: 최대 해상도 (예: 1080). None이면 최고 화질
    audio_bitrate: str = "192",     # audio: 비트레이트 (kbps)
    filename: Optional[str] = None,  # 확장자 제외한 파일명. None이면 영상 제목 사용
    progress_callback: Optional[ProgressCallback] = None,
) -> str:
    """
    실제 다운로드 수행. 완료된 파일 경로(추정)를 반환한다.
    kind="video"  -> 영상+음성 병합 (기본 mp4)
    kind="audio"  -> 음원 추출 (기본 mp3)
    """
    os.makedirs(output_dir, exist_ok=True)

    if ext is None:
        ext = "mp3" if kind == "audio" else "mp4"

    # 파일명 템플릿: 커스텀 파일명이 있으면 사용, 없으면 영상 제목
    if filename:
        base = sanitize_filename(filename)
        outtmpl = os.path.join(output_dir, base + ".%(ext)s")
    else:
        outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

    ydl_opts: dict = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    ffmpeg_loc = _ffmpeg_location()
    if ffmpeg_loc:
        ydl_opts["ffmpeg_location"] = ffmpeg_loc

    if progress_callback:
        ydl_opts["progress_hooks"] = [progress_callback]

    if kind == "audio":
        # 최고 음질 오디오를 받아 지정 코덱으로 변환
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": ext,
                "preferredquality": audio_bitrate,
            }
        ]
    else:  # video
        if max_height:
            fmt = (
                f"bestvideo[height<={max_height}]+bestaudio/"
                f"best[height<={max_height}]/best"
            )
        else:
            fmt = "bestvideo+bestaudio/best"
        ydl_opts["format"] = fmt
        ydl_opts["merge_output_format"] = ext

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # 후처리 후 최종 파일명 (확장자를 지정한 것으로 교체)
        produced = ydl.prepare_filename(info)
        final = os.path.splitext(produced)[0] + "." + ext

    return final


# ---------------------------------------------------------------------------
# CLI 단독 테스트용
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_url = input("URL: ").strip()
    vi = fetch_info(test_url)
    print(f"제목: {vi.title}")
    print(f"길이: {vi.duration_str}")
    print(f"업로더: {vi.uploader}")
    print(f"해상도: {vi.available_heights}")
