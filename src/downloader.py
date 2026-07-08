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


@dataclass
class PlaylistEntry:
    """재생목록 평면 조회 결과의 항목 1건(상세 정보 없이 URL·제목만)."""
    url: str
    title: str
    duration: int = 0


# 다운로드 진행률 콜백 타입: (상태 dict) -> None
ProgressCallback = Callable[[dict], None]


# ---------------------------------------------------------------------------
# ffmpeg 위치 탐색 (개발 환경 + PyInstaller 번들 환경 모두 지원)
# ---------------------------------------------------------------------------
def _ffmpeg_names() -> tuple[str, str]:
    """(ffmpeg, ffprobe) 실행파일 이름. Windows만 .exe 확장자."""
    if sys.platform == "win32":
        return "ffmpeg.exe", "ffprobe.exe"
    return "ffmpeg", "ffprobe"


def _ffmpeg_location() -> Optional[str]:
    """
    ffmpeg 실행파일이 있는 디렉터리를 찾아 반환한다. 못 찾으면 None을 반환해
    yt-dlp가 시스템 PATH에서 ffmpeg를 찾도록 둔다.

    탐색 우선순위:
      1) PyInstaller 번들(폴더형): sys._MEIPASS/ffmpeg, sys._MEIPASS
      2) 실행 파일 옆(사용자가 직접 배치): <exe>/, <exe>/ffmpeg, <exe>/bin
         - macOS .app 번들이면 Contents/Frameworks, Contents/Resources[/ffmpeg]도 탐색
      3) 개발 환경: 프로젝트 ../bin
    """
    exe_name = _ffmpeg_names()[0]
    candidates: list[str] = []

    # 1) 번들(폴더형)에 포함된 ffmpeg
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates += [os.path.join(base, "ffmpeg"), base]

    # 2) 얼어있는(frozen) 실행파일 옆 — 사용자가 직접 넣는 경우
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates += [
            exe_dir,
            os.path.join(exe_dir, "ffmpeg"),
            os.path.join(exe_dir, "bin"),
        ]
        # macOS .app: 실행파일은 <App>.app/Contents/MacOS/ 에 있고, 번들 리소스는 형제 폴더에 둔다.
        if sys.platform == "darwin":
            contents = os.path.dirname(exe_dir)  # .../Contents
            candidates += [
                os.path.join(contents, "Frameworks"),
                os.path.join(contents, "Resources"),
                os.path.join(contents, "Resources", "ffmpeg"),
            ]

    # 3) 개발 환경: 프로젝트 로컬 bin/
    candidates.append(
        os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
        )
    )

    for d in candidates:
        # isfile: 'ffmpeg'라는 이름의 하위 폴더가 있어도 실행파일로 오인하지 않도록
        if d and os.path.isfile(os.path.join(d, exe_name)):
            return d

    return None  # 시스템 PATH 사용


# ---------------------------------------------------------------------------
# 정보 조회
# ---------------------------------------------------------------------------
def fetch_info(url: str, timeout: int = 5) -> VideoInfo:
    """
    URL로부터 영상 메타데이터를 조회한다(다운로드는 하지 않음).
    실패 시 예외를 그대로 던지므로 호출부에서 처리한다.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": timeout,
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


def is_playlist_url(url: str) -> bool:
    """재생목록 성분(list= 파라미터 또는 /playlist 경로)이 있는 URL인지 판별한다."""
    u = url.lower()
    return "list=" in u or "/playlist" in u


def fetch_playlist(url: str, timeout: int = 15):
    """
    재생목록 URL을 평면(flat) 조회해 (재생목록 제목, [PlaylistEntry, ...])를 반환한다.
    각 항목의 썸네일·해상도 등 상세 정보는 조회하지 않으므로 큰 목록도 빠르게 훑는다.
    재생목록이 아니거나 항목이 없으면 None을 반환한다.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": timeout,
        # 항목을 펼치지 않고 목록만 빠르게 가져온다.
        "extract_flat": "in_playlist",
        "ignoreerrors": True,  # 비공개/삭제 항목이 섞여 있어도 계속 진행
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = info.get("entries") if info else None
    if not entries:
        return None  # 단일 영상 URL이었음

    result: list[PlaylistEntry] = []
    for e in entries:
        if not e:
            continue  # 비공개/삭제 항목
        eurl = e.get("url") or e.get("webpage_url") or e.get("id")
        if not eurl:
            continue
        # 평면 조회에서는 url이 영상 id일 수 있으므로 watch URL로 보정
        if not eurl.startswith("http"):
            eurl = f"https://www.youtube.com/watch?v={eurl}"
        result.append(
            PlaylistEntry(
                url=eurl,
                title=e.get("title") or eurl,
                duration=int(e.get("duration") or 0),
            )
        )

    if not result:
        return None
    return info.get("title") or "재생목록", result


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


# ---------------------------------------------------------------------------
# 예외 메시지 한글화
# ---------------------------------------------------------------------------
# yt-dlp/네트워크 예외의 원문(영문)에서 찾을 패턴 → 사용자용 한글 메시지.
# 위에서부터 순서대로 검사하므로 더 구체적인 패턴을 앞에 둔다. (소문자 기준 부분일치)
_ERROR_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("sign in to confirm your age", "age-restricted", "inappropriate for some users"),
     "연령 제한이 걸린 영상이라 다운로드할 수 없습니다."),
    (("private video",),
     "비공개 영상이라 다운로드할 수 없습니다."),
    (("members-only", "join this channel", "available to this channel's members"),
     "채널 멤버십 전용 영상이라 다운로드할 수 없습니다."),
    (("not available in your country", "not available from your location",
      "blocked it in your country", "geo restricted", "georestricted"),
     "지역 제한으로 이 영상은 현재 위치에서 다운로드할 수 없습니다."),
    (("this live event will begin", "premieres in", "premiere will begin",
      "live event will begin in"),
     "아직 공개되지 않은(예정/프리미어) 영상입니다. 공개 후 다시 시도해 주세요."),
    (("removed for violating", "account associated with this video has been terminated",
      "video has been removed"),
     "삭제된 영상이라 다운로드할 수 없습니다."),
    (("video unavailable", "this video is unavailable", "is not available"),
     "영상을 사용할 수 없습니다. 삭제되었거나 비공개일 수 있습니다."),
    (("too many requests", "http error 429", "rate-limit", "rate limit"),
     "요청이 많아 유튜브가 일시적으로 차단했습니다. 잠시 후 다시 시도해 주세요."),
    # 네트워크 계열은 "unable to download webpage" 같은 일반 오류보다 먼저 판정한다.
    (("timed out", "timeout", "read operation timed out"),
     "네트워크 응답 시간이 초과되었습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요."),
    (("failed to resolve", "getaddrinfo failed", "name or service not known",
      "temporary failure in name resolution", "nodename nor servname",
      "no address associated with hostname"),
     "인터넷에 연결할 수 없습니다. 네트워크 연결을 확인해 주세요."),
    (("connection refused", "connection reset", "connection aborted",
      "network is unreachable", "connection error", "urlopen error"),
     "네트워크 연결에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요."),
    (("ffmpeg not found", "ffprobe not found", "ffmpeg is not installed",
      "you have requested merging", "postprocessing: ffmpeg"),
     "ffmpeg를 찾을 수 없어 변환/병합에 실패했습니다. ffmpeg를 설치하거나 bin 폴더에 넣어 주세요."),
    (("unsupported url", "is not a valid url", "unable to download webpage",
      "no video formats found", "unable to extract"),
     "지원하지 않는 URL이거나 주소 형식이 올바르지 않습니다. 유튜브 링크를 확인해 주세요."),
    (("http error 403", "forbidden"),
     "유튜브가 접근을 거부했습니다(403). 잠시 후 다시 시도하거나 yt-dlp를 최신 버전으로 갱신해 주세요."),
    (("permission denied", "access is denied", "errno 13"),
     "저장 폴더에 쓸 권한이 없습니다. 다른 폴더를 선택해 주세요."),
    (("no space left", "errno 28", "disk full"),
     "저장 공간이 부족합니다. 여유 공간을 확보한 뒤 다시 시도해 주세요."),
]

# ANSI 색상 코드 및 yt-dlp의 "ERROR: " 접두어 제거용
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_PREFIX_RE = re.compile(r"^\s*(ERROR|WARNING)\s*:\s*", re.IGNORECASE)


def friendly_error(exc: object) -> str:
    """
    yt-dlp/네트워크 예외를 사용자용 한글 메시지로 변환한다.
    알려진 패턴에 걸리면 안내 문구를, 아니면 원문을 정리해 그대로 돌려준다.
    (yt-dlp 예외는 흔히 다른 예외를 감싸므로 __cause__ 원문까지 함께 살핀다.)
    """
    parts: list[str] = []
    seen = set()
    cur = exc
    for _ in range(5):  # 원인 체인을 따라가며 텍스트 수집 (무한루프 방지 상한)
        if cur is None or id(cur) in seen:
            break
        seen.add(id(cur))
        parts.append(str(cur))
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)

    raw = " ".join(parts)
    low = raw.lower()
    for needles, message in _ERROR_PATTERNS:
        if any(n in low for n in needles):
            return message

    # 알려지지 않은 오류: 원문에서 ANSI/접두어를 걷어내고 그대로 노출(한 줄).
    cleaned = _ANSI_RE.sub("", str(exc)).strip()
    cleaned = _PREFIX_RE.sub("", cleaned).splitlines()[0] if cleaned else ""
    return cleaned or "알 수 없는 오류가 발생했습니다."


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


class DownloadCancelled(Exception):
    """진행 중 다운로드를 사용자가 취소했음을 알리는 신호.
    progress_callback 안에서 이 예외를 던지면 yt-dlp가 현재 다운로드를 중단한다."""


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
