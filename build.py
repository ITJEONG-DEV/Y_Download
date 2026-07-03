"""
build.py
--------
PyInstaller 배포 빌드 스크립트. 두 가지 산출물을 만든다.

  full  : 폴더형(onedir) + ffmpeg 번들 포함  -> dist/YouTubeDownloader/
  lite  : 단일파일(onefile), ffmpeg 미포함    -> dist/YouTubeDownloader-lite.exe

사용법:
  python build.py            # full + lite 모두 빌드
  python build.py full       # 폴더형만
  python build.py lite       # 라이트(단일파일)만

사전 준비:
  pip install pyinstaller
  full 빌드는 bin/ffmpeg.exe, bin/ffprobe.exe 가 있어야 한다.
"""

import os
import sys

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src", "app.py")
ICON = os.path.join(ROOT, "assets", "app.ico")  # 있으면 자동 사용
SEP = os.pathsep  # Windows ';'

APP_NAME = "YouTubeDownloader"
LITE_NAME = "YouTubeDownloader-lite"


def _common_args() -> list[str]:
    args = [
        SRC,
        "--windowed",
        "--noconfirm",
        "--clean",
        "--paths", os.path.join(ROOT, "src"),
        # 데이터/서브모듈 수집 (누락 시 런타임 오류 방지)
        "--collect-all", "customtkinter",
        "--collect-submodules", "yt_dlp",
        "--collect-data", "yt_dlp",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
    ]
    if os.path.exists(ICON):
        args += ["--icon", ICON]
    return args


def build_full() -> None:
    ffmpeg = os.path.join(ROOT, "bin", "ffmpeg.exe")
    ffprobe = os.path.join(ROOT, "bin", "ffprobe.exe")
    if not os.path.exists(ffmpeg):
        raise SystemExit(f"[full] ffmpeg 없음: {ffmpeg}  (bin/ffmpeg.exe 배치 필요)")

    args = _common_args() + [
        "--name", APP_NAME,
        "--onedir",
        "--add-binary", f"{ffmpeg}{SEP}ffmpeg",
    ]
    if os.path.exists(ffprobe):
        args += ["--add-binary", f"{ffprobe}{SEP}ffmpeg"]
    print(">>> [full] 폴더형 + ffmpeg 번들 빌드 시작")
    PyInstaller.__main__.run(args)
    print(">>> [full] 완료 -> dist/%s/" % APP_NAME)


def build_lite() -> None:
    args = _common_args() + [
        "--name", LITE_NAME,
        "--onefile",
    ]
    print(">>> [lite] 단일파일(ffmpeg 미포함) 빌드 시작")
    PyInstaller.__main__.run(args)
    print(">>> [lite] 완료 -> dist/%s.exe" % LITE_NAME)


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target in ("full", "all"):
        build_full()
    if target in ("lite", "all"):
        build_lite()
    if target not in ("full", "lite", "all"):
        raise SystemExit("사용법: python build.py [full|lite|all]")


if __name__ == "__main__":
    main()
