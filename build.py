"""
build.py
--------
PyInstaller 배포 빌드 스크립트.

Windows:
  full  : 폴더형(onedir) + ffmpeg 번들 포함  -> dist/Y_Downloader/
  lite  : 단일파일(onefile), ffmpeg 미포함    -> dist/Y_Downloader-lite.exe
macOS:
  full  : 앱 번들(.app) + ffmpeg 번들 포함     -> dist/Y_Downloader.app
  lite  : 앱 번들(.app), ffmpeg 미포함          -> dist/Y_Downloader-lite.app

사용법:
  python build.py            # full + lite 모두 빌드
  python build.py full       # full만
  python build.py lite       # lite만

사전 준비:
  pip install pyinstaller
  full 빌드는 bin/ffmpeg(.exe), bin/ffprobe(.exe) 가 있어야 한다.
  (PyInstaller는 크로스컴파일 불가 — 각 OS에서 그 OS용 산출물을 빌드해야 함.)
"""

import os
import sys

import PyInstaller.__main__

# CI 등 콘솔 인코딩이 UTF-8이 아닌 환경(cp1252)에서 한글 print가
# UnicodeEncodeError로 죽지 않도록 표준출력을 UTF-8로 재설정한다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src", "app.py")
# 아이콘: Windows는 .ico, macOS는 .icns (있으면 자동 사용)
ICON = os.path.join(ROOT, "assets", "app.icns" if IS_MAC else "app.ico")
SEP = os.pathsep  # --add-binary 구분자: Windows ';' / POSIX ':'

# 버전은 src/version.py 단일 소스에서 가져온다.
sys.path.insert(0, os.path.join(ROOT, "src"))
try:
    from version import __version__
except Exception:
    __version__ = "0.0.0"

APP_TITLE = "Y_Downloader"
APP_NAME = "Y_Downloader"
LITE_NAME = "Y_Downloader-lite"
BUNDLE_ID = "dev.itjeong.ydownloader"  # macOS 번들 식별자

# exe 파일 속성(자세히 탭)에 표시할 개발자명. 서명 인증서는 아니며 단순 표기용.
DEV_NAME = "ITJEONG-DEV"


def _ffmpeg_bin_names() -> tuple[str, str]:
    """(ffmpeg, ffprobe) 실행파일 이름. Windows만 .exe."""
    if IS_WIN:
        return "ffmpeg.exe", "ffprobe.exe"
    return "ffmpeg", "ffprobe"


def _version_tuple() -> tuple:
    nums = []
    for p in __version__.replace("-", ".").split("."):
        digits = "".join(c for c in p if c.isdigit())
        nums.append(int(digits) if digits else 0)
    return tuple((nums + [0, 0, 0, 0])[:4])


def _write_version_file() -> str:
    """PyInstaller용 Windows 버전 리소스 파일 생성(개발자명 등 메타데이터 포함)."""
    v = _version_tuple()
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    path = os.path.join(ROOT, "build", "version_info.txt")
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v}, prodvers={v},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('041204B0', [
        StringStruct('CompanyName', '{DEV_NAME}'),
        StringStruct('FileDescription', '{APP_TITLE}'),
        StringStruct('FileVersion', '{__version__}'),
        StringStruct('InternalName', '{APP_TITLE}'),
        StringStruct('OriginalFilename', '{APP_TITLE}.exe'),
        StringStruct('ProductName', '{APP_TITLE}'),
        StringStruct('ProductVersion', '{__version__}'),
        StringStruct('LegalCopyright', '(c) {DEV_NAME}'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0412, 0x04B0])])
  ]
)
"""
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(content)
    return path


# 앱이 쓰지 않는데 환경에 설치돼 있어 딸려 들어가는 대형 모듈 — 용량만 키우므로 제외한다.
# (numpy는 PIL이 import 타임에 끌어오지 않고 우리 코드도 안 쓴다. tkinter는 Qt 전환 후 불필요.)
_EXCLUDE_MODULES = ["numpy", "tkinter", "test", "unittest", "pydoc_data"]


def _common_args() -> list[str]:
    args = [
        SRC,
        "--windowed",
        "--noconfirm",
        "--clean",
        "--paths", os.path.join(ROOT, "src"),
        # 데이터/서브모듈 수집 (누락 시 런타임 오류 방지)
        # PySide6는 PyInstaller 내장 훅이 Qt 플러그인(platforms 등)을 자동 번들.
        "--collect-submodules", "yt_dlp",
        "--collect-data", "yt_dlp",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
    ]
    for mod in _EXCLUDE_MODULES:
        args += ["--exclude-module", mod]
    # Windows 버전 리소스는 Windows 전용(--version-file). 다른 OS에선 생략.
    if IS_WIN:
        args += ["--version-file", _write_version_file()]
    if IS_MAC:
        args += ["--osx-bundle-identifier", BUNDLE_ID]
    if os.path.exists(ICON):
        args += ["--icon", ICON]
    return args


def _ffmpeg_add_binary_args() -> list[str]:
    """bin/ 의 ffmpeg(+ffprobe)를 'ffmpeg' 하위로 번들하는 --add-binary 인자."""
    ff_name, fp_name = _ffmpeg_bin_names()
    ffmpeg = os.path.join(ROOT, "bin", ff_name)
    ffprobe = os.path.join(ROOT, "bin", fp_name)
    if not os.path.exists(ffmpeg):
        raise SystemExit(f"[full] ffmpeg 없음: {ffmpeg}  (bin/{ff_name} 배치 필요)")
    args = ["--add-binary", f"{ffmpeg}{SEP}ffmpeg"]
    if os.path.exists(ffprobe):
        args += ["--add-binary", f"{ffprobe}{SEP}ffmpeg"]
    return args


def build_full() -> None:
    args = _common_args() + [
        "--name", APP_NAME,
        "--onedir",
    ] + _ffmpeg_add_binary_args()
    print(">>> [full] %s + ffmpeg 번들 빌드 시작" % ("앱 번들(.app)" if IS_MAC else "폴더형"))
    PyInstaller.__main__.run(args)
    out = "dist/%s.app" % APP_NAME if IS_MAC else "dist/%s/" % APP_NAME
    print(">>> [full] 완료 -> %s" % out)


def build_lite() -> None:
    # macOS는 onefile도 --windowed면 .app로 감싸지므로 산출물은 .app.
    args = _common_args() + [
        "--name", LITE_NAME,
        "--onefile",
    ]
    print(">>> [lite] ffmpeg 미포함 빌드 시작")
    PyInstaller.__main__.run(args)
    if IS_MAC:
        out = "dist/%s.app" % LITE_NAME
    elif IS_WIN:
        out = "dist/%s.exe" % LITE_NAME
    else:
        out = "dist/%s" % LITE_NAME
    print(">>> [lite] 완료 -> %s" % out)


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
