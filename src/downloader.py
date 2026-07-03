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
    # 해상도(height) -> 비디오 스트림 예상 크기(bytes). 크기 추정에 사용
    video_size_by_height: dict[int, int] = field(default_factory=dict)
    # bestaudio 예상 크기(bytes). 영상 병합 및 음원 추출 추정에 사용
    best_audio_size: int = 0

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
    ffmpeg.exe가 있는 디렉터리를 찾아 반환한다. 못 찾으면 None을 반환해
    yt-dlp가 시스템 PATH에서 ffmpeg를 찾도록 둔다.

    탐색 우선순위:
      1) PyInstaller 번들(폴더형 exe): sys._MEIPASS/ffmpeg, sys._MEIPASS
      2) 실행 파일 옆(라이트형 exe 사용자가 직접 배치): <exe>/, <exe>/ffmpeg, <exe>/bin
      3) 개발 환경: 프로젝트 ../bin
    """
    candidates: list[str] = []

    # 1) 번들(폴더형)에 포함된 ffmpeg
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates += [os.path.join(base, "ffmpeg"), base]

    # 2) 얼어있는(frozen) exe 옆 — 라이트형에서 사용자가 직접 넣는 경우
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates += [
            exe_dir,
            os.path.join(exe_dir, "ffmpeg"),
            os.path.join(exe_dir, "bin"),
        ]

    # 3) 개발 환경: 프로젝트 로컬 bin/
    candidates.append(
        os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
        )
    )

    for d in candidates:
        if d and os.path.exists(os.path.join(d, "ffmpeg.exe")):
            return d

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

    duration = int(info.get("duration") or 0)

    # 포맷을 훑어 해상도 목록 + 크기 추정 데이터 구성
    heights: set[int] = set()
    video_size_by_height: dict[int, int] = {}
    best_audio_size = 0
    for f in info.get("formats", []):
        has_video = f.get("vcodec") not in (None, "none")
        has_audio = f.get("acodec") not in (None, "none")
        size = _stream_size(f, duration)

        h = f.get("height")
        if h and has_video:
            h = int(h)
            heights.add(h)
            if size:
                # 같은 해상도 중 가장 큰(고화질) 스트림 크기를 대표값으로
                video_size_by_height[h] = max(video_size_by_height.get(h, 0), size)
        elif has_audio and not has_video:
            # 오디오 전용 스트림 중 가장 큰 것을 bestaudio 근사치로
            if size:
                best_audio_size = max(best_audio_size, size)

    return VideoInfo(
        url=url,
        title=info.get("title", "제목 없음"),
        thumbnail_url=info.get("thumbnail", ""),
        duration=duration,
        uploader=info.get("uploader", ""),
        available_heights=sorted(heights, reverse=True),
        video_size_by_height=video_size_by_height,
        best_audio_size=best_audio_size,
    )


def _stream_size(f: dict, duration: int) -> Optional[int]:
    """포맷 하나의 예상 크기(bytes). filesize가 없으면 비트레이트×길이로 추정."""
    s = f.get("filesize") or f.get("filesize_approx")
    if s:
        return int(s)
    tbr = f.get("tbr")  # kbps
    if tbr and duration:
        return int(tbr * 1000 / 8 * duration)
    return None


def estimate_size(
    info: VideoInfo, *, kind: str, max_height: Optional[int], audio_bitrate: str
) -> Optional[int]:
    """선택한 포맷/품질 기준 예상 파일 크기(bytes). 추정 불가 시 None."""
    if kind == "audio":
        # mp3 등: 비트레이트(kbps) × 길이(s) / 8
        try:
            br = int(audio_bitrate)
        except (TypeError, ValueError):
            return info.best_audio_size or None
        if info.duration:
            return int(br * 1000 / 8 * info.duration)
        return info.best_audio_size or None

    # video: 선택 해상도 이하 중 가장 높은 해상도의 비디오 + bestaudio
    if not info.video_size_by_height:
        return None
    if max_height:
        candidates = [h for h in info.available_heights if h <= max_height]
        h = max(candidates) if candidates else min(info.available_heights)
    else:
        h = max(info.available_heights) if info.available_heights else None
    if h is None:
        return None
    vsize = info.video_size_by_height.get(h)
    if not vsize:
        return None
    return vsize + info.best_audio_size


def format_size(num_bytes: Optional[int]) -> str:
    """bytes를 사람이 읽기 쉬운 문자열로 (예: '45.3 MB'). None이면 '알 수 없음'."""
    if not num_bytes:
        return "알 수 없음"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


# ---------------------------------------------------------------------------
# 다운로드
# ---------------------------------------------------------------------------
# 포맷별 선택 가능한 확장자
VIDEO_EXTS = ["mp4", "mkv", "webm"]
AUDIO_EXTS = ["mp3", "m4a", "wav"]

# 파일명 중복 처리 정책
CONFLICT_NUMBER = "number"        # name (1).ext 로 번호 붙이기
CONFLICT_OVERWRITE = "overwrite"  # 기존 파일 덮어쓰기
CONFLICT_SKIP = "skip"            # 이미 있으면 다운로드 건너뜀
CONFLICT_POLICIES = (CONFLICT_NUMBER, CONFLICT_OVERWRITE, CONFLICT_SKIP)


@dataclass
class DownloadResult:
    path: str
    status: str  # "downloaded" | "skipped" | "overwritten"


def _uniquify(output_dir: str, base: str, ext: str) -> str:
    """'base.ext'가 있으면 'base (1).ext', 'base (2).ext' ... 로 비어있는 base 이름을 반환."""
    candidate = base
    n = 1
    while os.path.exists(os.path.join(output_dir, candidate + "." + ext)):
        candidate = f"{base} ({n})"
        n += 1
    return candidate


def download(
    url: str,
    output_dir: str,
    *,
    kind: str = "video",            # "video" 또는 "audio"
    ext: Optional[str] = None,      # 출력 확장자 (video: mp4/mkv/webm, audio: mp3/m4a/wav)
    max_height: Optional[int] = None,  # video: 최대 해상도 (예: 1080). None이면 최고 화질
    audio_bitrate: str = "192",     # audio: 비트레이트 (kbps)
    filename: Optional[str] = None,  # 확장자 제외한 파일명. None이면 영상 제목 사용
    on_conflict: str = CONFLICT_NUMBER,  # 파일명 중복 시 처리 정책
    progress_callback: Optional[ProgressCallback] = None,
) -> DownloadResult:
    """
    실제 다운로드 수행. DownloadResult(path, status)를 반환한다.
    kind="video"  -> 영상+음성 병합 (기본 mp4)
    kind="audio"  -> 음원 추출 (기본 mp3)
    status: "downloaded" | "skipped" | "overwritten"
    """
    os.makedirs(output_dir, exist_ok=True)

    if ext is None:
        ext = "mp3" if kind == "audio" else "mp4"

    ydl_opts: dict = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    status = "downloaded"
    # 파일명 템플릿 + 중복 처리
    if filename:
        base = sanitize_filename(filename)
        target = os.path.join(output_dir, base + "." + ext)
        if os.path.exists(target):
            if on_conflict == CONFLICT_SKIP:
                return DownloadResult(target, "skipped")
            if on_conflict == CONFLICT_OVERWRITE:
                ydl_opts["overwrites"] = True
                status = "overwritten"
            else:  # CONFLICT_NUMBER (기본)
                base = _uniquify(output_dir, base, ext)
        outtmpl = os.path.join(output_dir, base + ".%(ext)s")
    else:
        # 파일명 미지정(제목 사용): 사전 판정이 어려워 덮어쓰기 정책만 반영
        outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")
        if on_conflict == CONFLICT_OVERWRITE:
            ydl_opts["overwrites"] = True

    ydl_opts["outtmpl"] = outtmpl

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

    return DownloadResult(final, status)


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
