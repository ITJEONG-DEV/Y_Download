# bin/ — ffmpeg 바이너리 위치

이 폴더에는 `ffmpeg.exe`가 있어야 합니다. mp3 변환과 영상+음성 병합에 필수입니다.
**바이너리 파일(*.exe)은 용량이 커서 git에 커밋하지 않습니다** (`.gitignore`로 제외).
저장소를 클론한 뒤 아래 방법으로 직접 채워 넣으세요.

## 준비 방법

### 방법 A — winget으로 시스템 설치 (가장 간단)
```powershell
winget install Gyan.FFmpeg
```
시스템 PATH에 설치되며, `src/downloader.py`가 자동으로 찾습니다. 이 경우 bin/은 비워둬도 됩니다.

### 방법 B — 이 폴더에 직접 배치 (배포 exe 번들 시 권장)
1. https://www.ffmpeg.org/download.html → Windows → gyan.dev 또는 BtbN 빌드
2. `ffmpeg-*-essentials_build.zip` 다운로드 (**.tar.xz 소스 아님**, Windows 빌드 .zip)
3. 압축 해제 후 `bin\ffmpeg.exe`를 이 폴더로 복사

> `src/downloader.py._ffmpeg_location()`이 `bin/ffmpeg.exe`를 자동 인식합니다.

## 필요한 파일
| 파일 | 필요성 |
|------|--------|
| `ffmpeg.exe` | ✅ 필수 |
| `ffprobe.exe` | △ 선택 (있으면 일부 처리에 활용, 없어도 동작) |
| `ffplay.exe` | ❌ 불필요 (미디어 플레이어, 넣지 마세요) |
