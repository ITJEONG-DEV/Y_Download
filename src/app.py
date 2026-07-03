"""
app.py
------
CustomTkinter 기반 데스크톱 GUI. 진입점.

동작 개요:
1) URL 입력 후 [목록에 추가] -> 조회 후 목록(큐)에 항목이 추가됨
2) 각 항목마다 파일명 / 확장자 / 포맷(영상·음원) / 품질을 개별 설정
3) 저장 위치는 하단에서 일괄(공통) 설정
4) [전체 다운로드] -> 목록의 모든 항목을 순차 다운로드

무거운 작업(조회/다운로드)은 별도 스레드에서 실행하여 GUI가 멈추지 않게 한다.
"""

from __future__ import annotations

import io
import os
import threading
from tkinter import filedialog

import customtkinter as ctk
import requests
from PIL import Image

from downloader import (
    VideoInfo,
    fetch_info,
    download,
    sanitize_filename,
    VIDEO_EXTS,
    AUDIO_EXTS,
)


ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

HEIGHT_LABELS = {
    2160: "2160p (4K)",
    1440: "1440p (2K)",
    1080: "1080p (FHD)",
    720: "720p (HD)",
    480: "480p",
    360: "360p",
    240: "240p",
    144: "144p",
}
AUDIO_BITRATES = ["320", "256", "192", "128"]


def _quality_label(h: int) -> str:
    return HEIGHT_LABELS.get(h, f"{h}p")


class DownloadRow(ctk.CTkFrame):
    """목록의 한 항목. 자체 위젯과 상태(VideoInfo)를 가진다."""

    def __init__(self, master, info: VideoInfo, thumb, on_remove):
        super().__init__(master, fg_color=("gray90", "gray20"))
        self.info = info
        self._thumb = thumb
        self._on_remove = on_remove

        self.columnconfigure(1, weight=1)

        # 썸네일
        self.thumb_label = ctk.CTkLabel(self, text="", image=thumb, width=120, height=68)
        self.thumb_label.grid(row=0, column=0, rowspan=3, padx=8, pady=8)

        # 제목 + 길이
        title_text = info.title
        if len(title_text) > 60:
            title_text = title_text[:60] + "…"
        self.title_label = ctk.CTkLabel(
            self, text=f"{title_text}   ({info.duration_str})",
            anchor="w", justify="left",
        )
        self.title_label.grid(row=0, column=1, columnspan=4, sticky="w", padx=6, pady=(8, 2))

        # 삭제 버튼
        self.remove_btn = ctk.CTkButton(
            self, text="✕", width=28, fg_color="transparent",
            text_color=("gray30", "gray70"), hover_color=("gray80", "gray30"),
            command=lambda: self._on_remove(self),
        )
        self.remove_btn.grid(row=0, column=5, padx=(0, 6), pady=(8, 2))

        # 파일명 입력 + 확장자
        ctk.CTkLabel(self, text="파일명:").grid(row=1, column=1, sticky="w", padx=6)
        self.name_entry = ctk.CTkEntry(self, width=260)
        self.name_entry.insert(0, sanitize_filename(info.title))
        self.name_entry.grid(row=1, column=2, sticky="w", padx=4)

        ctk.CTkLabel(self, text="확장자:").grid(row=1, column=3, sticky="e", padx=(8, 2))
        self.ext_menu = ctk.CTkOptionMenu(self, values=VIDEO_EXTS, width=90)
        self.ext_menu.grid(row=1, column=4, sticky="w", padx=(0, 6))

        # 포맷 + 품질
        ctk.CTkLabel(self, text="포맷:").grid(row=2, column=1, sticky="w", padx=6, pady=(0, 8))
        self.kind_menu = ctk.CTkOptionMenu(
            self, values=["영상", "음원"], width=90, command=self._on_kind_change,
        )
        self.kind_menu.grid(row=2, column=2, sticky="w", padx=4, pady=(0, 8))

        ctk.CTkLabel(self, text="품질:").grid(row=2, column=3, sticky="e", padx=(8, 2), pady=(0, 8))
        self.quality_menu = ctk.CTkOptionMenu(self, values=["최고"], width=130)
        self.quality_menu.grid(row=2, column=4, sticky="w", padx=(0, 6), pady=(0, 8))

        # 상태 표시(항목별)
        self.status_label = ctk.CTkLabel(self, text="대기", anchor="w", text_color=("gray40", "gray60"))
        self.status_label.grid(row=2, column=5, sticky="w", padx=6, pady=(0, 8))

        self._apply_video_options()

    # 포맷 전환 시 확장자/품질 옵션 갱신
    def _on_kind_change(self, _value=None):
        if self.kind_menu.get() == "음원":
            self._apply_audio_options()
        else:
            self._apply_video_options()

    def _apply_video_options(self):
        self.ext_menu.configure(values=VIDEO_EXTS)
        self.ext_menu.set(VIDEO_EXTS[0])
        if self.info.available_heights:
            labels = [_quality_label(h) for h in self.info.available_heights]
        else:
            labels = ["최고"]
        self.quality_menu.configure(values=labels)
        self.quality_menu.set(labels[0])

    def _apply_audio_options(self):
        self.ext_menu.configure(values=AUDIO_EXTS)
        self.ext_menu.set(AUDIO_EXTS[0])
        self.quality_menu.configure(values=AUDIO_BITRATES)
        self.quality_menu.set("192")

    # 현재 항목의 다운로드 파라미터 추출
    def get_params(self) -> dict:
        is_audio = self.kind_menu.get() == "음원"
        quality = self.quality_menu.get()
        params = {
            "url": self.info.url,
            "kind": "audio" if is_audio else "video",
            "ext": self.ext_menu.get(),
            "filename": self.name_entry.get().strip() or None,
            "max_height": None,
            "audio_bitrate": "192",
        }
        if is_audio:
            params["audio_bitrate"] = quality if quality in AUDIO_BITRATES else "192"
        else:
            digits = "".join(ch for ch in quality.split("p")[0] if ch.isdigit())
            params["max_height"] = int(digits) if digits else None
        return params

    def set_status(self, text: str, color=None):
        self.status_label.configure(text=text)
        if color:
            self.status_label.configure(text_color=color)

    def set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for w in (self.name_entry, self.ext_menu, self.kind_menu,
                  self.quality_menu, self.remove_btn):
            w.configure(state=state)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.geometry("820x640")
        self.minsize(760, 560)

        self.rows: list[DownloadRow] = []
        self._downloading = False
        self.download_dir = os.path.join(os.path.expanduser("~"), "Downloads")

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # --- URL 입력 영역 ---
        url_frame = ctk.CTkFrame(self)
        url_frame.pack(fill="x", padx=16, pady=(16, 8))
        url_frame.columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(
            url_frame, placeholder_text="유튜브 영상 URL을 붙여넣고 [목록에 추가]를 누르세요"
        )
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=8)
        self.url_entry.bind("<Return>", lambda e: self.on_add())

        self.add_btn = ctk.CTkButton(
            url_frame, text="목록에 추가", width=110, command=self.on_add
        )
        self.add_btn.grid(row=0, column=1, padx=(4, 8), pady=8)

        # --- 목록 (스크롤 영역) ---
        self.list_frame = ctk.CTkScrollableFrame(self, label_text="다운로드 목록")
        self.list_frame.pack(fill="both", expand=True, padx=16, pady=8)

        self.empty_label = ctk.CTkLabel(
            self.list_frame, text="목록이 비어 있습니다. URL을 추가하세요.",
            text_color=("gray50", "gray50"),
        )
        self.empty_label.pack(pady=40)

        # --- 저장 위치 (일괄) ---
        dir_frame = ctk.CTkFrame(self)
        dir_frame.pack(fill="x", padx=16, pady=8)
        dir_frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(dir_frame, text="저장 위치 (공통):").grid(row=0, column=0, padx=(8, 4), pady=8)
        self.dir_entry = ctk.CTkEntry(dir_frame)
        self.dir_entry.insert(0, self.download_dir)
        self.dir_entry.grid(row=0, column=1, sticky="ew", padx=4, pady=8)
        ctk.CTkButton(dir_frame, text="찾기", width=80, command=self.on_browse).grid(
            row=0, column=2, padx=(4, 8), pady=8
        )

        # --- 다운로드 버튼 + 진행률 ---
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(4, 12))
        bottom.columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(bottom)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.download_btn = ctk.CTkButton(
            bottom, text="전체 다운로드", width=140, height=36, command=self.on_download_all
        )
        self.download_btn.grid(row=0, column=1)

        self.status_label = ctk.CTkLabel(self, text="대기 중", anchor="w")
        self.status_label.pack(fill="x", padx=16, pady=(0, 8))

    # ------------------------------------------------------ 이벤트 핸들러
    def on_add(self):
        url = self.url_entry.get().strip()
        if not url:
            self._set_status("URL을 입력하세요.")
            return
        self.add_btn.configure(state="disabled", text="조회 중...")
        self._set_status("영상 정보를 조회하는 중...")
        threading.Thread(target=self._add_worker, args=(url,), daemon=True).start()

    def _add_worker(self, url: str):
        try:
            info = fetch_info(url)
            thumb = self._load_thumbnail(info.thumbnail_url)
            self.after(0, lambda: self._on_add_done(info, thumb))
        except Exception as e:
            self.after(0, lambda: self._on_add_error(e))

    def _on_add_done(self, info: VideoInfo, thumb):
        if self.empty_label.winfo_exists():
            self.empty_label.pack_forget()
        row = DownloadRow(self.list_frame, info, thumb, self._remove_row)
        row.pack(fill="x", padx=4, pady=4)
        self.rows.append(row)
        self.url_entry.delete(0, "end")
        self.add_btn.configure(state="normal", text="목록에 추가")
        self._set_status(f"추가됨: {info.title}  (총 {len(self.rows)}개)")

    def _on_add_error(self, err: Exception):
        self.add_btn.configure(state="normal", text="목록에 추가")
        self._set_status(f"조회 실패: {err}")

    def _remove_row(self, row: DownloadRow):
        if self._downloading:
            return
        row.destroy()
        self.rows.remove(row)
        if not self.rows:
            self.empty_label.pack(pady=40)
        self._set_status(f"삭제됨  (총 {len(self.rows)}개)")

    def on_browse(self):
        path = filedialog.askdirectory(initialdir=self.dir_entry.get() or self.download_dir)
        if path:
            self.dir_entry.delete(0, "end")
            self.dir_entry.insert(0, path)

    def on_download_all(self):
        if self._downloading:
            return
        if not self.rows:
            self._set_status("목록이 비어 있습니다.")
            return
        out_dir = self.dir_entry.get().strip()
        if not out_dir:
            self._set_status("저장 위치를 선택하세요.")
            return

        self._downloading = True
        self.download_btn.configure(state="disabled", text="다운로드 중...")
        self.add_btn.configure(state="disabled")
        for row in self.rows:
            row.set_controls_enabled(False)
            row.set_status("대기", color=("gray40", "gray60"))

        # 각 항목의 파라미터를 미리 추출(스레드에서 위젯 접근 방지)
        jobs = [(row, row.get_params()) for row in self.rows]
        threading.Thread(
            target=self._download_all_worker, args=(jobs, out_dir), daemon=True
        ).start()

    def _download_all_worker(self, jobs, out_dir):
        total = len(jobs)
        success = 0
        for idx, (row, params) in enumerate(jobs, start=1):
            self.after(0, lambda r=row: r.set_status("다운로드 중...", color=("#1f6aa5", "#5aa0d6")))
            self.after(0, lambda i=idx: self._set_status(f"[{i}/{total}] 다운로드 중..."))
            self.after(0, lambda: self.progress.set((idx - 1) / total))
            try:
                def hook(d, r=row, i=idx):
                    self._item_progress(d, r, i, total)
                download(out_dir=out_dir, progress_callback=hook, **params)
                success += 1
                self.after(0, lambda r=row: r.set_status("완료 ✓", color=("green", "#4caf50")))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda r=row, m=msg: r.set_status(f"실패: {m[:30]}", color=("red", "#e57373")))
        self.after(0, lambda: self._on_all_done(success, total))

    def _item_progress(self, d: dict, row: DownloadRow, idx: int, total: int):
        if d.get("status") == "downloading":
            tb = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            db = d.get("downloaded_bytes", 0)
            if tb:
                frac = db / tb
                self.after(0, lambda: row.set_status(f"{frac*100:.0f}%", color=("#1f6aa5", "#5aa0d6")))
                # 전체 진행률 = 완료된 항목 + 현재 항목 진행분
                overall = ((idx - 1) + frac) / total
                self.after(0, lambda: self.progress.set(overall))
        elif d.get("status") == "finished":
            self.after(0, lambda: row.set_status("변환 중...", color=("#1f6aa5", "#5aa0d6")))

    def _on_all_done(self, success: int, total: int):
        self._downloading = False
        self.progress.set(1.0)
        self.download_btn.configure(state="normal", text="전체 다운로드")
        self.add_btn.configure(state="normal")
        for row in self.rows:
            row.set_controls_enabled(True)
        self._set_status(f"완료: {success}/{total}개 다운로드됨")

    # -------------------------------------------------------------- 유틸
    def _load_thumbnail(self, url: str):
        if not url:
            return None
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
            return ctk.CTkImage(light_image=img, dark_image=img, size=(120, 68))
        except Exception:
            return None

    def _set_status(self, text: str):
        self.status_label.configure(text=text)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
