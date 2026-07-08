# Y_Downloader

유튜브 URL을 붙여넣어 **영상(mp4) 또는 음원(mp3)** 으로 다운로드하는 Windows 데스크톱 프로그램.
여러 개를 목록에 담아 **일괄 다운로드**할 수 있고, 항목마다 **파일명·확장자·포맷·품질**을 개별로 설정할 수 있습니다.

## 기능
- URL 조회 → 제목·썸네일·길이 표시
- 목록(큐)에 여러 영상 추가 후 한 번에 다운로드
- 항목별 파일명 / 확장자 / 포맷(영상·음원) / 품질 개별 설정
- 저장 위치 공통(일괄) 지정
- 실시간 진행률 표시

## 설치 & 실행
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# ffmpeg 필요: winget install Gyan.FFmpeg  (또는 bin/ 폴더에 ffmpeg.exe 배치)
python src/app.py
```

## 배포용 빌드
```powershell
pip install pyinstaller
python build.py          # full(폴더형+ffmpeg) + lite(단일파일) 모두 빌드
```
- **full**: `dist/Y_Downloader/` — ffmpeg 포함, 폴더째 zip으로 배포
- **lite**: `dist/Y_Downloader-lite.exe` — 단일 파일, ffmpeg 미포함
  ([`docs/lite-ffmpeg-안내.md`](docs/lite-ffmpeg-안내.md) 동봉)

macOS도 지원한다(같은 `python build.py full` → `dist/Y_Downloader.app`, ffmpeg 번들 포함).
릴리스는 태그 push 시 GitHub Actions가 Windows(`.zip`)와 macOS(`.dmg`/`.zip`)를 함께 빌드·첨부한다.
> macOS 빌드는 아직 **코드 서명/공증 전**이라 최초 실행 시 우클릭 > **열기**로 한 번 허용해야 한다.

## 기술 스택
Python · yt-dlp · PySide6(Qt) · Pillow · ffmpeg · PyInstaller

자세한 개발 정보와 진행 상황은 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) 참고.
