"""
app.py
------
CustomTkinter 기반 데스크톱 GUI. 진입점.

동작 개요:
1) URL 입력 후 [목록에 추가] -> 조회 후 목록(큐)에 항목이 추가됨
2) 각 항목마다 파일명 / 확장자 / 포맷(영상·음원) / 품질을 개별 설정 (예상 크기 표시)
3) 저장 위치는 하단에서 일괄(공통) 설정 — 마지막 위치를 기억함
4) [전체 다운로드] -> 목록의 모든 항목을 순차 다운로드
5) [다운로드 내역] -> 성공/실패 기록 확인, 항목 더블클릭 시 목록에 재추가

무거운 작업(조회/다운로드)은 별도 스레드에서 실행하여 GUI가 멈추지 않게 한다.
"""

from __future__ import annotations

import io
import os
import threading
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk
import requests
from PIL import Image

import config
from downloader import (
    VideoInfo,
    fetch_info,
    download,
    sanitize_filename,
    estimate_size,
    format_size,
    VIDEO_EXTS,
    AUDIO_EXTS,
    CONFLICT_POLICIES,
)

import updater

# 파일명 중복 처리 정책 라벨(표시용) ↔ 내부값
CONFLICT_LABELS = {"number": "자동 번호", "overwrite": "덮어쓰기", "skip": "건너뛰기"}

try:
    from version import __version__
except Exception:
    __version__ = "dev"


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

# 내역 사이드 패널 폭(px) 및 좌우 여백
HISTORY_PANEL_WIDTH = 320
HISTORY_PANEL_GAP = 16

# 창 최소/기본 크기
MIN_WINDOW_WIDTH = 820
MIN_WINDOW_HEIGHT = 580
DEFAULT_WINDOW_WIDTH = 880
DEFAULT_WINDOW_HEIGHT = 660


def _virtual_screen_bounds():
    """모든 모니터를 포함하는 가상 데스크톱 경계 (vx, vy, vw, vh). 실패 시 None."""
    try:
        import ctypes
        u = ctypes.windll.user32
        return (
            u.GetSystemMetrics(76),  # SM_XVIRTUALSCREEN
            u.GetSystemMetrics(77),  # SM_YVIRTUALSCREEN
            u.GetSystemMetrics(78),  # SM_CXVIRTUALSCREEN
            u.GetSystemMetrics(79),  # SM_CYVIRTUALSCREEN
        )
    except Exception:
        return None


def _quality_label(h: int) -> str:
    return HEIGHT_LABELS.get(h, f"{h}p")


class DownloadRow(ctk.CTkFrame):
    """목록의 한 항목. 자체 위젯과 상태(VideoInfo)를 가진다."""

    def __init__(self, master, info: VideoInfo, thumb, on_remove):
        super().__init__(master, fg_color=("gray90", "gray20"))
        self.info = info
        self._thumb = thumb
        self._on_remove = on_remove
        self._last_wl = 0

        # 썸네일 (고정)
        self.thumb_label = ctk.CTkLabel(self, text="", image=thumb, width=120, height=68)
        self.thumb_label.pack(side="left", padx=8, pady=8)

        # 우측 콘텐츠 (가변 폭 — 창/목록 폭에 따라 늘고 줄어듦)
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(0, 6), pady=6)

        # 1줄: 제목 + 삭제 버튼
        titlebar = ctk.CTkFrame(right, fg_color="transparent")
        titlebar.pack(fill="x")
        self.remove_btn = ctk.CTkButton(
            titlebar, text="✕", width=28, fg_color="transparent",
            text_color=("gray30", "gray70"), hover_color=("gray80", "gray30"),
            command=lambda: self._on_remove(self),
        )
        self.remove_btn.pack(side="right")
        self.title_label = ctk.CTkLabel(
            titlebar, text=f"{info.title}   ({info.duration_str})",
            anchor="w", justify="left",
        )
        self.title_label.pack(side="left", fill="x", expand=True)
        # 줄바꿈 폭은 App이 리사이즈(디바운스) 시 일괄로 갱신한다.
        # (행마다 <Configure>를 바인딩하면 리사이즈 때 이벤트 폭주로 크게 느려짐)
        self.title_label.configure(wraplength=500)  # 초기값

        # 2줄: 파일명 + 확장자
        namebar = ctk.CTkFrame(right, fg_color="transparent")
        namebar.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(namebar, text="파일명:").pack(side="left")
        self.name_entry = ctk.CTkEntry(namebar)
        self.name_entry.insert(0, sanitize_filename(info.title))
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(4, 8))
        self.name_entry.bind("<Up>", self._cursor_home)      # 커서 맨 앞으로
        self.name_entry.bind("<Down>", self._cursor_end)     # 커서 맨 뒤로
        ctk.CTkLabel(namebar, text="확장자:").pack(side="left")
        self.ext_menu = ctk.CTkOptionMenu(
            namebar, values=VIDEO_EXTS, width=88, dynamic_resizing=False
        )
        self.ext_menu.pack(side="left", padx=(4, 0))

        # 3줄: 포맷 + 품질 + 예상크기 + 상태
        ctrlbar = ctk.CTkFrame(right, fg_color="transparent")
        ctrlbar.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(ctrlbar, text="포맷:").pack(side="left")
        self.kind_menu = ctk.CTkOptionMenu(
            ctrlbar, values=["영상", "음원"], width=80, dynamic_resizing=False,
            command=self._on_kind_change,
        )
        self.kind_menu.pack(side="left", padx=(4, 10))
        ctk.CTkLabel(ctrlbar, text="품질:").pack(side="left")
        self.quality_menu = ctk.CTkOptionMenu(
            ctrlbar, values=["최고"], width=126, dynamic_resizing=False,
            command=lambda _=None: self._update_estimate(),
        )
        self.quality_menu.pack(side="left", padx=(4, 10))

        # 상태 — 고정 폭 셀(텍스트가 바뀌어도 폭 고정), 우측 정렬
        status_cell = ctk.CTkFrame(ctrlbar, width=88, height=24, fg_color="transparent")
        status_cell.pack(side="right")
        status_cell.pack_propagate(False)
        self.status_label = ctk.CTkLabel(
            status_cell, text="대기", anchor="w", text_color=("gray40", "gray60")
        )
        self.status_label.pack(side="left", fill="x")

        # 예상 크기 — 고정 폭 셀
        size_cell = ctk.CTkFrame(ctrlbar, width=124, height=24, fg_color="transparent")
        size_cell.pack(side="right", padx=(0, 6))
        size_cell.pack_propagate(False)
        self.size_label = ctk.CTkLabel(
            size_cell, text="예상: -", anchor="w", text_color=("gray40", "gray60")
        )
        self.size_label.pack(side="left", fill="x")

        self._apply_video_options()

    # 파일명 입력창 커서 이동 편의 (Up=맨앞, Down=맨뒤)
    def _cursor_home(self, _event=None):
        entry = self.name_entry._entry  # 내부 tkinter.Entry
        entry.icursor(0)
        entry.xview_moveto(0)
        return "break"

    def _cursor_end(self, _event=None):
        entry = self.name_entry._entry
        entry.icursor("end")
        entry.xview_moveto(1)
        return "break"

    def set_title_wraplength(self, wl: int):
        """제목 줄바꿈 폭 설정. App이 리사이즈(디바운스) 시 일괄 호출한다."""
        if self._last_wl == wl:
            return
        self._last_wl = wl
        self.title_label.configure(wraplength=wl)

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
        self._update_estimate()

    def _apply_audio_options(self):
        self.ext_menu.configure(values=AUDIO_EXTS)
        self.ext_menu.set(AUDIO_EXTS[0])
        self.quality_menu.configure(values=AUDIO_BITRATES)
        self.quality_menu.set("192")
        self._update_estimate()

    def _update_estimate(self):
        p = self.get_params()
        size = estimate_size(
            self.info, kind=p["kind"], max_height=p["max_height"],
            audio_bitrate=p["audio_bitrate"],
        )
        self.size_label.configure(text=f"예상: {format_size(size)}")

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

    def quality_text(self) -> str:
        return self.quality_menu.get()

    def set_status(self, text: str, color=None):
        self.status_label.configure(text=text)
        if color:
            self.status_label.configure(text_color=color)

    def set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for w in (self.name_entry, self.ext_menu, self.kind_menu,
                  self.quality_menu, self.remove_btn):
            w.configure(state=state)


class HistoryPanel(ctk.CTkFrame):
    """다운로드 내역(성공/실패) 우측 사이드 패널. 더블클릭 재추가 / 단일·전체 삭제."""

    def __init__(self, master, app: "App", width: int = HISTORY_PANEL_WIDTH):
        super().__init__(master, width=width)
        self.app = app
        self.pack_propagate(False)  # 고정 폭 유지

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(8, 2))
        ctk.CTkLabel(
            header, text="다운로드 내역",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header, text="✕", width=28, fg_color="transparent",
            text_color=("gray30", "gray70"), hover_color=("gray80", "gray30"),
            command=self.app.toggle_history,
        ).pack(side="right")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkLabel(
            toolbar, text="더블클릭 시 목록에 추가",
            text_color=("gray40", "gray60"),
        ).pack(side="left")
        ctk.CTkButton(
            toolbar, text="전체 지우기", width=84, command=self._clear_all
        ).pack(side="right")

        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        self._dirty = True
        self.render()

    def mark_dirty(self):
        self._dirty = True

    def render_if_dirty(self):
        """내역이 바뀐 경우에만 다시 그린다(패널 열 때 불필요한 재렌더 방지)."""
        if self._dirty:
            self.render()

    def render(self):
        self._dirty = False
        for child in self.list_frame.winfo_children():
            child.destroy()

        history = config.load_history()
        if not history:
            ctk.CTkLabel(
                self.list_frame, text="내역이 없습니다.",
                text_color=("gray50", "gray50"),
            ).pack(pady=24)
            return

        for entry in history:
            self._make_row(entry)

    def _make_row(self, entry: dict):
        ok = entry.get("status") == "성공"
        color = ("green", "#4caf50") if ok else ("red", "#e57373")
        row = ctk.CTkFrame(self.list_frame, fg_color=("gray92", "gray18"))
        row.pack(fill="x", padx=2, pady=3)

        # 단일 삭제 (휴지통) 버튼 — 우측
        ctk.CTkButton(
            row, text="🗑", width=28, fg_color="transparent",
            text_color=("gray40", "gray60"), hover_color=("gray80", "gray30"),
            command=lambda i=entry.get("id"): self._delete(i),
        ).pack(side="right", padx=(0, 4), pady=4)

        text_area = ctk.CTkFrame(row, fg_color="transparent")
        text_area.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=4)

        # 1줄: 파일명 (영상명) 성공여부
        status_txt = "성공" if ok else "실패"
        filename = entry.get("filename") or "(제목)"
        title = entry.get("title", "")
        line1 = ctk.CTkLabel(
            text_area, text=f"{filename}  ({title})  · {status_txt}",
            anchor="w", justify="left", text_color=color, wraplength=200,
        )
        line1.pack(fill="x")

        # 2줄: 일시 포맷/확장자 품질
        detail = (
            f"{entry.get('timestamp', '')}  "
            f"{entry.get('kind', '')}/{entry.get('ext', '')} "
            f"{entry.get('quality', '')}"
        )
        msg = entry.get("message")
        if msg:
            detail += f"\n{msg}"
        line2 = ctk.CTkLabel(
            text_area, text=detail, anchor="w", justify="left",
            text_color=("gray40", "gray60"), wraplength=200,
        )
        line2.pack(fill="x")

        # 더블클릭 → 재추가
        url = entry.get("url")
        for w in (text_area, line1, line2):
            w.bind("<Double-Button-1>", lambda e, u=url: self._readd(u))

    def _readd(self, url: str | None):
        if url:
            self.app.add_url(url)

    def _delete(self, entry_id: str | None):
        config.delete_history(entry_id)
        self.render()

    def _clear_all(self):
        config.clear_history()
        self.render()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Y_Downloader-{__version__}")
        self.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        self.rows: list[DownloadRow] = []
        self._downloading = False
        self.history_panel: HistoryPanel | None = None
        self._history_visible = False
        self._normal_geom = None  # 패널 닫힘·비최대화 상태의 기본 창 위치/크기
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.download_dir = config.get_download_dir(default_dir)

        self._build_ui()

        # 지난 세션의 창 위치/크기 복원(없거나 화면 밖이면 주모니터 중앙 기본 크기)
        self._restore_geometry()

        # 리사이즈는 디바운스로 한 번만 반영(이벤트 폭주로 인한 지연 방지)
        self._resize_after = None
        self._last_list_w = 0  # 마지막으로 반영한 목록 폭(변화 없으면 재배치 생략)
        self.bind("<Configure>", self._on_window_configure)
        # 닫을 때 창 상태 저장
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 실행 시 업데이트 확인 (패키지 빌드에서만; 개발 실행은 건너뜀)
        if updater.build_kind() != "dev":
            self.after(1500, self._start_update_check)

    # ------------------------------------------------- 창 위치/크기 기억
    def _restore_geometry(self):
        win = config.get_window()
        if win and self._geometry_valid(win.get("x"), win.get("y"), win.get("w"), win.get("h")):
            self.geometry(f"{win['w']}x{win['h']}+{win['x']}+{win['y']}")
            self._normal_geom = (win["x"], win["y"], win["w"], win["h"])
            if win.get("zoomed"):
                self.after(60, lambda: self.state("zoomed"))
        else:
            self._center_default()

    def _center_default(self):
        """주모니터(1번) 정중앙에 기본 크기로."""
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._normal_geom = (x, y, w, h)

    def _geometry_valid(self, x, y, w, h) -> bool:
        """저장된 창이 현재 모니터 배치 안에서 충분히 보이고 잡을 수 있는지."""
        if None in (x, y, w, h):
            return False
        if w < MIN_WINDOW_WIDTH or h < MIN_WINDOW_HEIGHT:
            return False
        b = _virtual_screen_bounds()
        if not b:
            return True  # 판정 불가하면 그대로 사용
        vx, vy, vw, vh = b
        # 창과 가상 데스크톱의 겹침 면적이 창의 50% 이상
        ix = max(0, min(x + w, vx + vw) - max(x, vx))
        iy = max(0, min(y + h, vy + vh) - max(y, vy))
        if ix * iy < 0.5 * w * h:
            return False
        # 타이틀바(상단)가 화면 안에 있어 드래그 가능한지
        if y < vy or y > vy + vh - 40:
            return False
        return True

    def _save_geometry(self):
        try:
            g = self._normal_geom or (
                self.winfo_x(), self.winfo_y(), self.winfo_width(), self.winfo_height()
            )
            config.set_window({
                "x": g[0], "y": g[1], "w": g[2], "h": g[3],
                "zoomed": self.state() == "zoomed",
            })
        except Exception:
            pass

    def _on_close(self):
        self._save_geometry()
        self.destroy()

    # ------------------------------------------------- 반응형(디바운스)
    def _on_window_configure(self, event):
        # 창 자체의 크기 변경만 처리(자식 위젯 이벤트 무시)
        if event.widget is not self:
            return
        # 패널 닫힘 + 비최대화 상태의 '기본' 위치/크기를 기억(복원 기준)
        if not self._history_visible and self.state() != "zoomed":
            self._normal_geom = (
                self.winfo_x(), self.winfo_y(), self.winfo_width(), self.winfo_height()
            )
        if self._resize_after is not None:
            self.after_cancel(self._resize_after)
        self._resize_after = self.after(120, self._apply_responsive_layout)

    def _apply_responsive_layout(self, force: bool = False):
        self._resize_after = None
        if not self.rows:
            return
        # 목록 폭이 실제로 바뀌었을 때만 반영. 패널 토글은 목록 폭이 안 바뀌므로
        # 여기서 걸러져 '닫은 뒤 한 박자 늦게 깜빡'이는 재그리기를 없앤다.
        w = self.list_frame.winfo_width()
        if not force and w == self._last_list_w:
            return
        self._last_list_w = w
        # 목록 폭 기준으로 제목 줄바꿈 폭 계산(썸네일·버튼·스크롤바·여백 감안)
        wl = max(120, w - 190)
        for row in self.rows:
            row.set_title_wraplength(wl)

    # ------------------------------------------------- 자동 업데이트
    def _start_update_check(self):
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self):
        try:
            latest = updater.check_update(__version__)
        except Exception:
            return  # 네트워크 오류 등은 조용히 무시
        if latest:
            self.after(0, lambda: self._show_update_modal(latest))

    def _show_update_modal(self, latest: dict):
        newver = latest["tag"].lstrip("vV")
        win = ctk.CTkToplevel(self)
        win.title("업데이트")
        win.geometry("440x400")
        win.resizable(False, False)
        win.transient(self)

        ctk.CTkLabel(
            win, text="새로운 버전이 릴리즈 되었습니다.\n업데이트하시겠습니까?",
            font=ctk.CTkFont(size=14, weight="bold"), justify="center",
        ).pack(pady=(20, 6))
        ctk.CTkLabel(win, text=f"현재 {__version__}    →    새 버전 {newver}").pack(pady=2)

        # 변경 내용 요약
        ctk.CTkLabel(win, text="변경 내용", anchor="w").pack(fill="x", padx=20, pady=(10, 0))
        box = ctk.CTkTextbox(win, height=150, wrap="word")
        box.pack(fill="both", expand=True, padx=20, pady=(2, 6))
        box.insert("1.0", updater.extract_summary(latest.get("body", "")))
        box.configure(state="disabled")

        status = ctk.CTkLabel(win, text="", text_color=("gray40", "gray60"))
        status.pack(pady=(0, 0))

        bar = ctk.CTkFrame(win, fg_color="transparent")
        bar.pack(pady=12)
        later_btn = ctk.CTkButton(bar, text="나중에", width=110, fg_color="gray", hover_color="gray30")
        later_btn.pack(side="left", padx=8)
        ok_btn = ctk.CTkButton(bar, text="확인", width=110)
        ok_btn.pack(side="left", padx=8)

        def do_update():
            try:
                updater.download_and_apply(
                    latest, updater.build_kind(),
                    progress=lambda p: self.after(0, lambda: status.configure(text=f"다운로드 중... {p:.0f}%")),
                )
                self.after(0, lambda: status.configure(text="교체 후 재시작합니다..."))
                self.after(900, self._quit_for_update)
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: status.configure(text=f"실패: {msg[:60]}"))
                self.after(0, lambda: ok_btn.configure(state="normal"))
                self.after(0, lambda: later_btn.configure(state="normal"))

        def on_ok():
            ok_btn.configure(state="disabled")
            later_btn.configure(state="disabled")
            status.configure(text="다운로드 준비 중...")
            threading.Thread(target=do_update, daemon=True).start()

        later_btn.configure(command=win.destroy)
        ok_btn.configure(command=on_ok)
        win.after(100, win.grab_set)  # 창이 뜬 뒤 모달 고정

    def _quit_for_update(self):
        # 도우미 배치가 종료를 기다리고 있으므로 앱을 닫으면 교체가 진행된다.
        self._save_geometry()
        self.destroy()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # 좌우 분할: 왼쪽=메인 콘텐츠, 오른쪽=내역 패널(토글)
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

        left = ctk.CTkFrame(self.body, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)

        # 내역 패널 미리 생성(초기엔 숨김)
        self.history_panel = HistoryPanel(self.body, self)

        # --- URL 입력 영역 ---
        url_frame = ctk.CTkFrame(left)
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
        self.add_btn.grid(row=0, column=1, padx=4, pady=8)

        self.history_btn = ctk.CTkButton(
            url_frame, text="다운로드 내역", width=110, command=self.toggle_history
        )
        self.history_btn.grid(row=0, column=2, padx=(4, 8), pady=8)

        # --- 목록 (스크롤 영역) ---
        self.list_frame = ctk.CTkScrollableFrame(left, label_text="다운로드 목록")
        self.list_frame.pack(fill="both", expand=True, padx=16, pady=8)

        self.empty_label = ctk.CTkLabel(
            self.list_frame, text="목록이 비어 있습니다. URL을 추가하세요.",
            text_color=("gray50", "gray50"),
        )
        self.empty_label.pack(pady=40)

        # --- 저장 위치 (일괄) ---
        dir_frame = ctk.CTkFrame(left)
        dir_frame.pack(fill="x", padx=16, pady=8)
        dir_frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(dir_frame, text="저장 위치 (공통):").grid(row=0, column=0, padx=(8, 4), pady=8)
        self.dir_entry = ctk.CTkEntry(dir_frame)
        self.dir_entry.insert(0, self.download_dir)
        self.dir_entry.grid(row=0, column=1, sticky="ew", padx=4, pady=8)
        ctk.CTkButton(dir_frame, text="찾기", width=64, command=self.on_browse).grid(
            row=0, column=2, padx=(4, 2), pady=8
        )
        ctk.CTkButton(dir_frame, text="열기", width=64, command=self.on_open_dir).grid(
            row=0, column=3, padx=(2, 8), pady=8
        )

        # 파일명 중복 시 처리 정책
        ctk.CTkLabel(dir_frame, text="파일명 중복 시:").grid(
            row=1, column=0, padx=(8, 4), pady=(0, 8), sticky="w"
        )
        cur_policy = config.get_conflict_policy("number")
        if cur_policy not in CONFLICT_POLICIES:
            cur_policy = "number"
        self.conflict_menu = ctk.CTkOptionMenu(
            dir_frame, values=[CONFLICT_LABELS[p] for p in CONFLICT_POLICIES],
            width=130, dynamic_resizing=False, command=self._on_conflict_change,
        )
        self.conflict_menu.set(CONFLICT_LABELS[cur_policy])
        self.conflict_menu.grid(row=1, column=1, padx=4, pady=(0, 8), sticky="w")

        # --- 다운로드 버튼 + 진행률 ---
        bottom = ctk.CTkFrame(left, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(4, 12))
        bottom.columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(bottom)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.download_btn = ctk.CTkButton(
            bottom, text="전체 다운로드", width=140, height=36, command=self.on_download_all
        )
        self.download_btn.grid(row=0, column=1)

        self.status_label = ctk.CTkLabel(left, text="대기 중", anchor="w")
        self.status_label.pack(fill="x", padx=16, pady=(0, 8))

    # ------------------------------------------------------ 이벤트 핸들러
    def on_add(self):
        url = self.url_entry.get().strip()
        if not url:
            self._set_status("URL을 입력하세요.")
            return
        self.url_entry.delete(0, "end")
        self.add_url(url)

    def add_url(self, url: str):
        """URL을 조회해 목록에 추가 (on_add 및 내역 재추가에서 공용)."""
        self.add_btn.configure(state="disabled", text="조회 중...")
        self._set_status(f"영상 정보를 조회하는 중... {url}")
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
        self.add_btn.configure(state="normal", text="목록에 추가")
        self._set_status(f"추가됨: {info.title}  (총 {len(self.rows)}개)")
        self.after(30, lambda: self._apply_responsive_layout(force=True))  # 새 행 줄바꿈 폭 반영

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
            self.download_dir = path
            config.set_download_dir(path)  # 선택한 위치 기억

    def on_open_dir(self):
        """저장 위치 폴더를 탐색기로 연다. 없으면 생성 후 연다."""
        path = self.dir_entry.get().strip() or self.download_dir
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)  # Windows 탐색기로 열기
        except Exception as e:
            self._set_status(f"폴더 열기 실패: {e}")

    def _on_conflict_change(self, _label=None):
        config.set_conflict_policy(self._conflict_policy())

    def _conflict_policy(self) -> str:
        label = self.conflict_menu.get()
        for value, lbl in CONFLICT_LABELS.items():
            if lbl == label:
                return value
        return "number"

    def toggle_history(self):
        """우측 내역 패널을 열고 닫는다."""
        if self._history_visible:
            # 닫기: 패널 제거 → 창 축소 (사이에 강제 갱신 없이 한 번의 레이아웃으로)
            self.history_panel.pack_forget()
            self._grow_window(-1)
            self._history_visible = False
        else:
            # 열기: 창을 먼저 넓히고 → 패널 끼움. 좌측 폭이 유지되어 목록 재배치가 없다.
            self.history_panel.render_if_dirty()
            self._grow_window(+1)
            self.history_panel.pack(side="right", fill="y", padx=(0, 8), pady=8)
            self._history_visible = True

    def _grow_window(self, sign: int):
        """
        내역 패널 폭만큼 창 폭을 넓히거나(+1) 줄인다(-1).
        최대화(zoomed) 상태면 창을 바꾸지 않아 목록이 패널과 공간을 나눈다.
        update_idletasks를 호출하지 않아, geometry 변경과 pack이 한 번의 레이아웃으로 합쳐진다.
        경계 판단은 주모니터가 아니라 '가상 데스크톱(모든 모니터)' 기준 — 보조 모니터에서
        창이 주모니터로 튀는 문제 방지.
        """
        if self.state() == "zoomed":
            return
        delta = (HISTORY_PANEL_WIDTH + HISTORY_PANEL_GAP) * sign
        w, h = self.winfo_width(), self.winfo_height()
        x, y = self.winfo_x(), self.winfo_y()
        b = _virtual_screen_bounds()
        if b:
            vx, vy, vw, vh = b
            left_bound, right_bound = vx, vx + vw
        else:
            left_bound, right_bound = 0, self.winfo_screenwidth()
        if sign > 0:
            new_w = min(w + delta, right_bound - left_bound)
            if x + new_w > right_bound:          # 가상 데스크톱 오른쪽 밖으로 나갈 때만 안쪽으로 당김
                x = max(left_bound, right_bound - new_w)
        else:
            new_w = max(MIN_WINDOW_WIDTH, w + delta)
        self.geometry(f"{new_w}x{h}+{x}+{y}")

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
        config.set_download_dir(out_dir)  # 다운로드 시점의 위치도 기억

        self._downloading = True
        self.download_btn.configure(state="disabled", text="다운로드 중...")
        self.add_btn.configure(state="disabled")
        for row in self.rows:
            row.set_controls_enabled(False)
            row.set_status("대기", color=("gray40", "gray60"))

        # 각 항목의 정보를 미리 추출(스레드에서 위젯 접근 방지)
        policy = self._conflict_policy()
        jobs = [
            {
                "row": row,
                "params": {**row.get_params(), "on_conflict": policy},
                "title": row.info.title,
                "quality": row.quality_text(),
            }
            for row in self.rows
        ]
        threading.Thread(
            target=self._download_all_worker, args=(jobs, out_dir), daemon=True
        ).start()

    def _download_all_worker(self, jobs, out_dir):
        total = len(jobs)
        success = 0
        for idx, job in enumerate(jobs, start=1):
            row, params = job["row"], job["params"]
            self.after(0, lambda r=row: r.set_status("다운로드 중...", color=("#1f6aa5", "#5aa0d6")))
            self.after(0, lambda i=idx: self._set_status(f"[{i}/{total}] 다운로드 중..."))
            self.after(0, lambda: self.progress.set((idx - 1) / total))

            status, message = "성공", ""
            try:
                def hook(d, r=row, i=idx):
                    self._item_progress(d, r, i, total)
                result = download(output_dir=out_dir, progress_callback=hook, **params)
                success += 1
                if result.status == "skipped":
                    message = "이미 있어 건너뜀"
                    self.after(0, lambda r=row: r.set_status("건너뜀", color=("gray50", "gray60")))
                elif result.status == "overwritten":
                    message = "덮어씀"
                    self.after(0, lambda r=row: r.set_status("완료(덮어씀) ✓", color=("green", "#4caf50")))
                else:
                    self.after(0, lambda r=row: r.set_status("완료 ✓", color=("green", "#4caf50")))
            except Exception as e:
                status, message = "실패", str(e)
                self.after(0, lambda r=row, m=message: r.set_status("실패", color=("red", "#e57373")))
                self.after(0, lambda m=message: self._set_status(f"실패: {m}"))

            # 내역 기록 (성공/실패 모두)
            self._record_history(job, params, status, message)

        self.after(0, lambda: self._on_all_done(success, total))

    def _record_history(self, job, params, status, message):
        entry = {
            "url": params["url"],
            "title": job["title"],
            "filename": params["filename"] or "(제목)",
            "kind": "음원" if params["kind"] == "audio" else "영상",
            "ext": params["ext"],
            "quality": job["quality"],
            "status": status,
            "message": message[:120],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        config.add_history(entry)

    def _item_progress(self, d: dict, row: DownloadRow, idx: int, total: int):
        if d.get("status") == "downloading":
            tb = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            db = d.get("downloaded_bytes", 0)
            if tb:
                frac = db / tb
                self.after(0, lambda: row.set_status(f"{frac*100:.0f}%", color=("#1f6aa5", "#5aa0d6")))
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
        # 내역이 바뀌었으니 표시. 열려 있으면 즉시, 닫혀 있으면 다음에 열 때 갱신.
        if self.history_panel is not None:
            self.history_panel.mark_dirty()
            if self._history_visible:
                self.history_panel.render()

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
