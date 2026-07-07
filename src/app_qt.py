"""
app_qt.py
---------
PySide6(Qt) 기반 데스크톱 GUI. CustomTkinter 판(app.py)을 대체하기 위한 이식본.

[마일스톤 1] 핵심 다운로드 흐름:
  - URL 추가(단일 / 재생목록 감지 → 개수 확인 → 전체 추가 + 개별 조회)
  - 다운로드 목록(번호·썸네일·제목·파일명·확장자·포맷·품질·예상크기·상태·삭제)
  - 저장 위치(변경/열기) + 파일명 중복 정책
  - 전체 다운로드 + 진행률 + 상태표시, 내역 기록
[마일스톤 2 예정] 우측 내역 패널, 자동 업데이트 모달, 창 위치 세부 복원.

백엔드(downloader/config/updater)는 UI 무관이라 그대로 재사용한다.
스레드에서 UI를 만지지 않도록, 워커는 self._post(fn)로 메인 스레드에 콜백을 넘긴다
(기존 app.py의 self.after(0, fn) 패턴과 1:1 대응).
"""
from __future__ import annotations

import io
import os
import queue
import threading
import uuid
from datetime import datetime

import requests
from PIL import Image
from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDockWidget, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

import config
import updater
from downloader import (
    VideoInfo, PlaylistEntry,
    fetch_info, fetch_playlist, is_playlist_url, download,
    sanitize_filename, estimate_size, format_size,
    VIDEO_EXTS, AUDIO_EXTS, CONFLICT_POLICIES,
)

try:
    from version import __version__
except Exception:
    __version__ = "0.0.0"

CONFLICT_LABELS = {"number": "자동 번호", "overwrite": "덮어쓰기", "skip": "건너뛰기"}
HEIGHT_LABELS = {
    2160: "2160p (4K)", 1440: "1440p (2K)", 1080: "1080p (FHD)", 720: "720p (HD)",
    480: "480p", 360: "360p", 240: "240p", 144: "144p",
}
AUDIO_BITRATES = ["320", "256", "192", "128"]
INFO_FETCH_TIMEOUT_SEC = 5
ENRICH_CONCURRENCY = 3
THUMB_W, THUMB_H = 120, 68


def _quality_label(h: int) -> str:
    return HEIGHT_LABELS.get(h, f"{h}p")


def _pixmap_from_bytes(data: bytes | None) -> QPixmap | None:
    """(메인 스레드에서) 이미지 바이트를 썸네일 QPixmap으로. 실패 시 None."""
    if not data:
        return None
    pm = QPixmap()
    if not pm.loadFromData(data):
        return None
    return pm.scaled(THUMB_W, THUMB_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _fetch_thumb_bytes(url: str) -> bytes | None:
    """(워커 스레드에서) 썸네일 이미지를 내려받아 바이트로. QPixmap 생성은 메인에서."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.content
    except Exception:
        return None


class _Bridge(QObject):
    """워커 스레드가 넘긴 콜러블을 메인 스레드 이벤트 루프에서 실행."""
    invoke = Signal(object)

    def __init__(self):
        super().__init__()
        self.invoke.connect(lambda fn: fn())


# ---------------------------------------------------------------------------
# 목록의 한 행
# ---------------------------------------------------------------------------
class DownloadRow(QWidget):
    def __init__(self, info: VideoInfo, pixmap: QPixmap | None, on_remove,
                 defaults: dict | None = None, on_defaults_change=None):
        super().__init__()
        self.info = info
        self._on_remove = on_remove
        self._defaults = defaults or {}
        self._on_defaults_change = on_defaults_change
        self._initializing = True

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(8)

        self.index_label = QLabel("")
        self.index_label.setFixedWidth(26)
        self.index_label.setAlignment(Qt.AlignCenter)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(THUMB_W, THUMB_H)
        self.thumb_label.setStyleSheet("background:#2b2b2b; border-radius:4px;")
        self._set_pixmap(pixmap)

        right = QVBoxLayout()
        right.setSpacing(3)

        titlebar = QHBoxLayout()
        self.title_label = QLabel(f"{info.title}   ({info.duration_str})")
        self.title_label.setWordWrap(True)
        titlebar.addWidget(self.title_label, 1)
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedWidth(30)
        self.remove_btn.clicked.connect(lambda: self._on_remove(self))
        titlebar.addWidget(self.remove_btn, 0, Qt.AlignTop)

        namebar = QHBoxLayout()
        namebar.addWidget(QLabel("파일명:"))
        self.name_entry = QLineEdit(sanitize_filename(info.title))
        namebar.addWidget(self.name_entry, 1)
        namebar.addWidget(QLabel("확장자:"))
        self.ext_menu = QComboBox()
        self.ext_menu.setMinimumWidth(84)
        namebar.addWidget(self.ext_menu)

        ctrlbar = QHBoxLayout()
        ctrlbar.addWidget(QLabel("포맷:"))
        self.kind_menu = QComboBox()
        self.kind_menu.addItems(["영상", "음원"])
        self.kind_menu.currentIndexChanged.connect(self._on_kind_change)
        ctrlbar.addWidget(self.kind_menu)
        ctrlbar.addWidget(QLabel("품질:"))
        self.quality_menu = QComboBox()
        self.quality_menu.setMinimumWidth(120)
        self.quality_menu.currentIndexChanged.connect(lambda _=0: self._on_option_change())
        ctrlbar.addWidget(self.quality_menu)
        ctrlbar.addStretch(1)
        self.size_label = QLabel("예상: -")
        self.size_label.setStyleSheet("color:gray;")
        ctrlbar.addWidget(self.size_label)
        self.status_label = QLabel("대기")
        self.status_label.setFixedWidth(96)
        self.status_label.setStyleSheet("color:gray;")
        ctrlbar.addWidget(self.status_label)

        right.addLayout(titlebar)
        right.addLayout(namebar)
        right.addLayout(ctrlbar)

        root.addWidget(self.index_label)
        root.addWidget(self.thumb_label)
        root.addLayout(right, 1)

        self.ext_menu.currentIndexChanged.connect(lambda _=0: self._on_option_change())
        self._apply_defaults()
        self._initializing = False

    # --------------------------------------------------------- 표시 갱신
    def _set_pixmap(self, pixmap: QPixmap | None):
        if pixmap is not None:
            self.thumb_label.setPixmap(pixmap)
        else:
            self.thumb_label.clear()

    def set_index(self, index: int):
        self.index_label.setText(str(index))

    def update_info(self, info: VideoInfo, pixmap: QPixmap | None = None):
        self.info = info
        self.title_label.setText(f"{info.title}   ({info.duration_str})")
        if pixmap is not None:
            self._set_pixmap(pixmap)
        if self.kind_menu.currentText() != "음원" and info.available_heights:
            cur = self.quality_menu.currentText()
            labels = [_quality_label(h) for h in info.available_heights]
            self._set_combo(self.quality_menu, labels, cur if cur in labels else labels[0])
        self._update_estimate()

    # --------------------------------------------------------- 옵션
    @staticmethod
    def _set_combo(combo: QComboBox, values, selected=None):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(values)
        if selected is not None and selected in values:
            combo.setCurrentText(selected)
        combo.blockSignals(False)

    def _on_kind_change(self, _=0):
        if self.kind_menu.currentText() == "음원":
            self._apply_audio_options()
        else:
            self._apply_video_options()
        self._notify_defaults_changed()

    def _on_option_change(self):
        self._update_estimate()
        self._notify_defaults_changed()

    def _notify_defaults_changed(self):
        if self._initializing or self._on_defaults_change is None:
            return
        self._on_defaults_change(self.get_defaults())

    def get_defaults(self) -> dict:
        p = self.get_params()
        return {"kind": p["kind"], "ext": p["ext"], "quality": self.quality_menu.currentText()}

    def _apply_defaults(self):
        kind = self._defaults.get("kind")
        if kind == "audio":
            self.kind_menu.setCurrentText("음원")
            self._apply_audio_options()
        else:
            self.kind_menu.setCurrentText("영상")
            self._apply_video_options()
        ext = self._defaults.get("ext")
        if ext and ext in [self.ext_menu.itemText(i) for i in range(self.ext_menu.count())]:
            self.ext_menu.setCurrentText(ext)
        quality = self._defaults.get("quality")
        if quality and quality in [self.quality_menu.itemText(i) for i in range(self.quality_menu.count())]:
            self.quality_menu.setCurrentText(quality)
        self._update_estimate()

    def _apply_video_options(self):
        self._set_combo(self.ext_menu, VIDEO_EXTS, VIDEO_EXTS[0])
        labels = [_quality_label(h) for h in self.info.available_heights] or ["최고"]
        self._set_combo(self.quality_menu, labels, labels[0])
        self._update_estimate()

    def _apply_audio_options(self):
        self._set_combo(self.ext_menu, AUDIO_EXTS, AUDIO_EXTS[0])
        self._set_combo(self.quality_menu, AUDIO_BITRATES, "192")
        self._update_estimate()

    def _update_estimate(self):
        p = self.get_params()
        size = estimate_size(self.info, kind=p["kind"], max_height=p["max_height"],
                             audio_bitrate=p["audio_bitrate"])
        self.size_label.setText(f"예상: {format_size(size)}")

    # --------------------------------------------------------- 파라미터/상태
    def get_params(self) -> dict:
        is_audio = self.kind_menu.currentText() == "음원"
        quality = self.quality_menu.currentText()
        params = {
            "url": self.info.url,
            "kind": "audio" if is_audio else "video",
            "ext": self.ext_menu.currentText(),
            "filename": self.name_entry.text().strip() or None,
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
        return self.quality_menu.currentText()

    def set_status(self, text: str, color: str | None = None):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};" if color else "color:gray;")

    def set_controls_enabled(self, enabled: bool):
        for w in (self.name_entry, self.ext_menu, self.kind_menu, self.quality_menu, self.remove_btn):
            w.setEnabled(enabled)


# ---------------------------------------------------------------------------
# 내역 패널
# ---------------------------------------------------------------------------
class HistoryRow(QWidget):
    """내역 한 건. 클릭하면 펼쳐져 썸네일/메시지를 보여준다."""

    def __init__(self, panel: "HistoryPanel", entry: dict):
        super().__init__()
        self.panel = panel
        self.entry = entry
        self.eid = entry.get("id")
        self.url = entry.get("url")
        self._expanded = False
        self._item = None

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(3)

        top = QHBoxLayout()
        self.title_lbl = QLabel()
        self.title_lbl.setWordWrap(True)
        top.addWidget(self.title_lbl, 1)
        add_btn = QPushButton("＋")
        add_btn.setFixedSize(26, 24)
        add_btn.setToolTip("다운로드 목록에 다시 추가")
        add_btn.clicked.connect(lambda: panel.readd(self.url))
        del_btn = QPushButton("🗑")
        del_btn.setFixedSize(26, 24)
        del_btn.setStyleSheet("background:#c0392b; color:white;")
        del_btn.setToolTip("이 내역 삭제")
        del_btn.clicked.connect(lambda: panel.delete(self.eid))
        top.addWidget(add_btn, 0, Qt.AlignTop)
        top.addWidget(del_btn, 0, Qt.AlignTop)
        v.addLayout(top)

        self.thumb_lbl = QLabel()
        self.thumb_lbl.setVisible(False)
        v.addWidget(self.thumb_lbl)

        self.detail_lbl = QLabel()
        self.detail_lbl.setWordWrap(True)
        self.detail_lbl.setStyleSheet("color:gray;")
        v.addWidget(self.detail_lbl)

        self._build_text()

    def _build_text(self):
        e = self.entry
        ok = e.get("status") == "성공"
        color = "#4caf50" if ok else "#e57373"
        status_txt = "성공" if ok else "실패"
        filename = e.get("filename") or ""
        title = e.get("title", "(제목 없음)")
        has_fn = bool(filename) and filename != "(제목)"
        primary = f"[{status_txt}] " + (f"{filename} ({title})" if has_fn else title)
        arrow = "▾ " if self._expanded else "▸ "
        self.title_lbl.setText(arrow + primary)
        self.title_lbl.setStyleSheet(f"color:{color};")
        detail = (f"{e.get('timestamp', '')}  "
                  f"{e.get('kind', '')}/{e.get('ext', '')} {e.get('quality', '')}")
        msg = e.get("message")
        if self._expanded and msg:
            detail += f"\n{msg}"
        self.detail_lbl.setText(detail)

    def mousePressEvent(self, ev):
        self.panel.toggle(self)
        super().mousePressEvent(ev)

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self._build_text()
        if expanded:
            pm = self.panel.load_thumb(self.entry.get("thumb"))
            self.thumb_lbl.setPixmap(pm) if pm is not None else self.thumb_lbl.clear()
            self.thumb_lbl.setVisible(pm is not None)
        else:
            self.thumb_lbl.setVisible(False)


class HistoryPanel(QWidget):
    """우측 다운로드 내역 패널."""

    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.main = main
        self._thumb_cache: dict[str, QPixmap] = {}
        self.setMinimumWidth(300)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(QLabel("다운로드 내역"))
        header.addStretch(1)
        clear_btn = QPushButton("전체 지우기")
        clear_btn.clicked.connect(self.clear_all)
        header.addWidget(clear_btn)
        v.addLayout(header)

        self.list = QListWidget()
        self.list.setSpacing(4)
        v.addWidget(self.list, 1)
        self.empty = QLabel("내역이 없습니다.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color:gray; padding:16px;")
        v.addWidget(self.empty)

        self.render()

    def render(self):
        self.list.clear()
        entries = config.load_history()
        self.empty.setVisible(not entries)
        self.list.setVisible(bool(entries))
        for e in entries:
            row = HistoryRow(self, e)
            item = QListWidgetItem(self.list)
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            row._item = item

    def toggle(self, row: HistoryRow):
        row.set_expanded(not row._expanded)
        row.adjustSize()
        if row._item is not None:
            row._item.setSizeHint(row.sizeHint())

    def load_thumb(self, path):
        if not path or not os.path.exists(path):
            return None
        if path in self._thumb_cache:
            return self._thumb_cache[path]
        pm = QPixmap(path)
        if pm.isNull():
            return None
        pm = pm.scaledToWidth(220, Qt.SmoothTransformation)
        self._thumb_cache[path] = pm
        return pm

    def readd(self, url):
        if url:
            self.main.add_url(url)

    def delete(self, eid):
        config.delete_history(eid)
        self.render()

    def clear_all(self):
        config.clear_history()
        self.render()


# ---------------------------------------------------------------------------
# 메인 창
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Y_Downloader  v{__version__}")
        self.resize(880, 660)

        self._bridge = _Bridge()
        self.rows: list[DownloadRow] = []
        self._downloading = False
        self._add_request_id = 0
        self._add_pending = False
        self.download_dir = config.get_download_dir(
            os.path.join(os.path.expanduser("~"), "Downloads"))
        self.item_defaults = config.get_item_defaults()
        # 재생목록 개별 조회
        self._enrich_queue: queue.Queue = queue.Queue()
        self._enrich_lock = threading.Lock()
        self._enrich_workers = 0
        self._enrich_pending = 0
        self._enrich_done = 0

        self._build_ui()
        self._restore_geometry()

    def _post(self, fn):
        """워커 스레드 → 메인 스레드에서 fn() 실행 (app.py의 self.after(0, fn) 대응)."""
        self._bridge.invoke.emit(fn)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 8)
        outer.setSpacing(8)

        # URL 입력
        urlbar = QHBoxLayout()
        urlbar.addWidget(QLabel("URL:"))
        self.url_entry = QLineEdit()
        self.url_entry.setPlaceholderText("유튜브 영상 또는 재생목록 URL을 붙여넣으세요")
        self.url_entry.returnPressed.connect(self.on_add)
        urlbar.addWidget(self.url_entry, 1)
        self.add_btn = QPushButton("목록에 추가")
        self.add_btn.clicked.connect(self.on_add)
        urlbar.addWidget(self.add_btn)
        self.history_btn = QPushButton("내역")
        self.history_btn.setCheckable(True)
        self.history_btn.clicked.connect(self.toggle_history)
        urlbar.addWidget(self.history_btn)
        outer.addLayout(urlbar)

        # 목록
        self.list_widget = QListWidget()
        self.list_widget.setSpacing(4)
        outer.addWidget(self.list_widget, 1)
        self.empty_label = QLabel("목록이 비어 있습니다. URL을 추가하세요.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color:gray; padding:24px;")
        outer.addWidget(self.empty_label)

        # 저장 위치 + 중복 정책
        dirbar = QHBoxLayout()
        dirbar.addWidget(QLabel("저장 위치:"))
        self.dir_entry = QLineEdit(self.download_dir)
        dirbar.addWidget(self.dir_entry, 1)
        browse_btn = QPushButton("변경")
        browse_btn.clicked.connect(self.on_browse)
        dirbar.addWidget(browse_btn)
        open_btn = QPushButton("열기")
        open_btn.clicked.connect(self.on_open_dir)
        dirbar.addWidget(open_btn)
        outer.addLayout(dirbar)

        confbar = QHBoxLayout()
        confbar.addWidget(QLabel("파일명 중복 시:"))
        self.conflict_menu = QComboBox()
        self.conflict_menu.addItems([CONFLICT_LABELS[p] for p in CONFLICT_POLICIES])
        cur = config.get_conflict_policy("number")
        self.conflict_menu.setCurrentText(CONFLICT_LABELS.get(cur, CONFLICT_LABELS["number"]))
        self.conflict_menu.currentIndexChanged.connect(self._on_conflict_change)
        confbar.addWidget(self.conflict_menu)
        confbar.addStretch(1)
        self.clear_list_btn = QPushButton("목록 비우기")
        self.clear_list_btn.clicked.connect(self.clear_download_list)
        confbar.addWidget(self.clear_list_btn)
        outer.addLayout(confbar)

        # 진행률 + 다운로드
        botbar = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        botbar.addWidget(self.progress, 1)
        self.download_btn = QPushButton("전체 다운로드")
        self.download_btn.setFixedWidth(140)
        self.download_btn.clicked.connect(self.on_download_all)
        botbar.addWidget(self.download_btn)
        outer.addLayout(botbar)

        self.status_label = QLabel("대기 중")
        self.status_label.setStyleSheet("color:gray;")
        outer.addWidget(self.status_label)

        # 우측 내역 패널(도크) — 처음엔 숨김
        self.history_panel = HistoryPanel(self)
        self.history_dock = QDockWidget("내역", self)
        self.history_dock.setWidget(self.history_panel)
        self.history_dock.setFeatures(
            QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.history_dock)
        self.history_dock.hide()
        self.history_dock.visibilityChanged.connect(
            lambda vis: self.history_btn.setChecked(vis))

        self._refresh_empty()

        # 패키지 빌드에서만 실행 시 업데이트 확인(개발 소스 실행은 건너뜀)
        if updater.build_kind() != "dev":
            QTimer.singleShot(1500, self._start_update_check)

    def _set_status(self, text: str):
        self.status_label.setText(text)

    def _set_progress(self, frac: float):
        self.progress.setValue(int(max(0.0, min(1.0, frac)) * 1000))

    def _refresh_empty(self):
        has = bool(self.rows)
        self.empty_label.setVisible(not has)
        self.list_widget.setVisible(has)

    def _renumber(self):
        for i, row in enumerate(self.rows, start=1):
            row.set_index(i)

    def _add_row_widget(self, row: DownloadRow):
        item = QListWidgetItem(self.list_widget)
        item.setSizeHint(row.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, row)
        row._item = item  # 삭제 시 역참조
        self.rows.append(row)
        self._refresh_empty()
        self._renumber()

    # ------------------------------------------------------ 추가(단일/재생목록)
    def on_add(self):
        url = self.url_entry.text().strip()
        if not url:
            self._set_status("URL을 입력하세요.")
            return
        self.url_entry.clear()
        self.add_url(url)

    def add_url(self, url: str):
        if is_playlist_url(url):
            self._start_playlist_add(url)
        else:
            self._start_single_add(url)

    def _start_single_add(self, url: str):
        self._add_request_id += 1
        request_id = self._add_request_id
        self._add_pending = True
        self.add_btn.setEnabled(False)
        self.add_btn.setText("조회 중...")
        self._set_status(f"영상 정보를 조회하는 중... {url}")
        threading.Thread(target=self._add_worker, args=(url, request_id), daemon=True).start()

    def _add_worker(self, url: str, request_id: int):
        try:
            info = fetch_info(url, timeout=INFO_FETCH_TIMEOUT_SEC)
            data = _fetch_thumb_bytes(info.thumbnail_url)
            self._post(lambda: self._on_add_done(info, data, request_id))
        except Exception as e:
            self._post(lambda e=e: self._on_add_error(e, request_id))

    def _finish_add_request(self):
        self._add_pending = False
        self.add_btn.setEnabled(True)
        self.add_btn.setText("목록에 추가")

    def _on_add_done(self, info: VideoInfo, thumb_data, request_id: int):
        if request_id != self._add_request_id:
            return
        self._finish_add_request()
        row = DownloadRow(info, _pixmap_from_bytes(thumb_data), self._remove_row,
                          defaults=self.item_defaults, on_defaults_change=self._on_row_defaults_change)
        self._add_row_widget(row)
        self._set_status(f"추가됨: {info.title}  (총 {len(self.rows)}개)")

    def _on_add_error(self, err: Exception, request_id: int):
        if request_id != self._add_request_id:
            return
        self._finish_add_request()
        self._set_status(f"조회 실패: {err}")

    # 재생목록
    def _start_playlist_add(self, url: str):
        self.add_btn.setEnabled(False)
        self.add_btn.setText("재생목록 확인...")
        self._set_status("재생목록을 확인하는 중...")
        threading.Thread(target=self._playlist_worker, args=(url,), daemon=True).start()

    def _playlist_worker(self, url: str):
        try:
            result = fetch_playlist(url)
        except Exception as e:
            self._post(lambda e=e: self._on_playlist_error(e, url))
            return
        self._post(lambda: self._on_playlist_fetched(url, result))

    def _on_playlist_error(self, err: Exception, url: str):
        self._finish_add_request()
        self._set_status(f"재생목록 조회 실패, 단일 영상으로 시도: {err}")
        self._start_single_add(url)

    def _on_playlist_fetched(self, url: str, result):
        self._finish_add_request()
        if not result:
            self._start_single_add(url)
            return
        title, entries = result
        if len(entries) == 1:
            self._start_single_add(entries[0].url)
            return
        has_single = "v=" in url.lower()
        name = title if len(title) <= 34 else title[:33] + "…"
        box = QMessageBox(self)
        box.setWindowTitle("재생목록 추가")
        box.setText(f"재생목록을 감지했습니다.\n\n'{name}'\n영상 {len(entries)}개가 있습니다. 모두 대기열에 추가할까요?")
        add_all = box.addButton(f"모두 추가 ({len(entries)})", QMessageBox.AcceptRole)
        single = box.addButton("이 영상만", QMessageBox.ActionRole) if has_single else None
        box.addButton("취소", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is add_all:
            self._add_playlist_entries(entries)
        elif single is not None and clicked is single:
            self._start_single_add(url)

    def _add_playlist_entries(self, entries):
        new_rows = []
        for e in entries:
            info = VideoInfo(url=e.url, title=e.title, thumbnail_url="", duration=e.duration,
                             uploader="", available_heights=[], video_size_by_height={}, best_audio_size=0)
            row = DownloadRow(info, None, self._remove_row, defaults=self.item_defaults,
                              on_defaults_change=self._on_row_defaults_change)
            self._add_row_widget(row)
            new_rows.append(row)
        self._enqueue_enrichment(new_rows)

    def _enqueue_enrichment(self, rows):
        for row in rows:
            self._enrich_queue.put(row)
        self._enrich_pending += len(rows)
        self._set_status(f"재생목록 {len(rows)}개 추가됨. 상세 정보 조회 중... (0/{self._enrich_pending})")
        with self._enrich_lock:
            while self._enrich_workers < ENRICH_CONCURRENCY and not self._enrich_queue.empty():
                self._enrich_workers += 1
                threading.Thread(target=self._enrich_worker, daemon=True).start()

    def _enrich_worker(self):
        while True:
            try:
                row = self._enrich_queue.get_nowait()
            except queue.Empty:
                break
            info = data = None
            try:
                info = fetch_info(row.info.url, timeout=INFO_FETCH_TIMEOUT_SEC)
                data = _fetch_thumb_bytes(info.thumbnail_url)
            except Exception:
                pass
            self._post(lambda r=row, i=info, d=data: self._apply_enrichment(r, i, d))
        with self._enrich_lock:
            self._enrich_workers -= 1

    def _apply_enrichment(self, row, info, thumb_data):
        if info is not None and row in self.rows:
            row.update_info(info, _pixmap_from_bytes(thumb_data))
            if hasattr(row, "_item"):
                row._item.setSizeHint(row.sizeHint())
        self._enrich_one_done()

    def _enrich_one_done(self):
        self._enrich_done += 1
        total = self._enrich_pending
        if self._enrich_done >= total:
            self._set_status(f"재생목록 상세 정보 조회 완료  (총 {len(self.rows)}개)")
            self._enrich_pending = self._enrich_done = 0
        else:
            self._set_status(f"상세 정보 조회 중... ({self._enrich_done}/{total})")

    # ------------------------------------------------------ 목록 편집
    def _on_row_defaults_change(self, defaults: dict):
        self.item_defaults = defaults
        config.set_item_defaults(defaults)

    def _remove_row(self, row: DownloadRow):
        if self._downloading or row not in self.rows:
            return
        item = getattr(row, "_item", None)
        if item is not None:
            self.list_widget.takeItem(self.list_widget.row(item))
        self.rows.remove(row)
        row.deleteLater()
        self._refresh_empty()
        self._renumber()
        self._set_status(f"삭제됨  (총 {len(self.rows)}개)")

    def clear_download_list(self):
        if self._downloading or not self.rows:
            return
        self.list_widget.clear()
        for row in self.rows:
            row.deleteLater()
        self.rows.clear()
        self._refresh_empty()
        self._set_status("목록을 모두 지웠습니다.")

    # ------------------------------------------------------ 저장 위치/정책
    def on_browse(self):
        path = QFileDialog.getExistingDirectory(self, "저장 위치 선택",
                                                self.dir_entry.text() or self.download_dir)
        if path:
            self.dir_entry.setText(path)
            self.download_dir = path
            config.set_download_dir(path)

    def on_open_dir(self):
        path = self.dir_entry.text().strip() or self.download_dir
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)
        except Exception as e:
            self._set_status(f"폴더 열기 실패: {e}")

    def _on_conflict_change(self, _=0):
        config.set_conflict_policy(self._conflict_policy())

    def _conflict_policy(self) -> str:
        label = self.conflict_menu.currentText()
        for value, lbl in CONFLICT_LABELS.items():
            if lbl == label:
                return value
        return "number"

    # ------------------------------------------------------ 다운로드
    def on_download_all(self):
        if self._downloading:
            return
        if not self.rows:
            self._set_status("목록이 비어 있습니다.")
            return
        out_dir = self.dir_entry.text().strip()
        if not out_dir:
            self._set_status("저장 위치를 선택하세요.")
            return
        config.set_download_dir(out_dir)

        self._downloading = True
        self.download_btn.setEnabled(False)
        self.download_btn.setText("다운로드 중...")
        self.add_btn.setEnabled(False)
        self.clear_list_btn.setEnabled(False)
        for row in self.rows:
            row.set_controls_enabled(False)
            row.set_status("대기", "gray")

        policy = self._conflict_policy()
        jobs = [{
            "row": row,
            "params": {**row.get_params(), "on_conflict": policy},
            "title": row.info.title,
            "quality": row.quality_text(),
            "thumb_url": row.info.thumbnail_url,
        } for row in self.rows]
        threading.Thread(target=self._download_all_worker, args=(jobs, out_dir), daemon=True).start()

    def _download_all_worker(self, jobs, out_dir):
        total = len(jobs)
        success = 0
        for idx, job in enumerate(jobs, start=1):
            row, params = job["row"], job["params"]
            self._post(lambda r=row: r.set_status("다운로드 중...", "#3d8fd6"))
            self._post(lambda i=idx: self._set_status(f"[{i}/{total}] 다운로드 중..."))
            self._post(lambda i=idx: self._set_progress((i - 1) / total))

            status, message, saved_name = "성공", "", None
            try:
                def hook(d, r=row, i=idx):
                    self._item_progress(d, r, i, total)
                result = download(output_dir=out_dir, progress_callback=hook, **params)
                success += 1
                saved_name = os.path.splitext(os.path.basename(result.path))[0]
                if result.status == "skipped":
                    message = "이미 있어 건너뜀"
                    self._post(lambda r=row: r.set_status("건너뜀", "gray"))
                elif result.status == "overwritten":
                    message = "덮어씀"
                    self._post(lambda r=row: r.set_status("완료(덮어씀) ✓", "#4caf50"))
                else:
                    self._post(lambda r=row: r.set_status("완료 ✓", "#4caf50"))
            except Exception as e:
                status, message = "실패", str(e)
                self._post(lambda r=row: r.set_status("실패", "#e57373"))
                self._post(lambda m=message: self._set_status(f"실패: {m}"))
            self._record_history(job, params, status, message, saved_name)
        self._post(lambda: self._on_all_done(success, total))

    def _item_progress(self, d: dict, row: DownloadRow, idx: int, total: int):
        if d.get("status") == "downloading":
            tb = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            db = d.get("downloaded_bytes", 0)
            if tb:
                frac = db / tb
                self._post(lambda: row.set_status(f"{frac*100:.0f}%", "#3d8fd6"))
                self._post(lambda: self._set_progress(((idx - 1) + frac) / total))
        elif d.get("status") == "finished":
            self._post(lambda: row.set_status("변환 중...", "#3d8fd6"))

    def _record_history(self, job, params, status, message, saved_name=None):
        eid = uuid.uuid4().hex
        thumb = self._save_thumb(eid, job.get("thumb_url"))
        entry = {
            "id": eid, "url": params["url"], "title": job["title"],
            "filename": saved_name or params["filename"] or "(제목)",
            "kind": "음원" if params["kind"] == "audio" else "영상",
            "ext": params["ext"], "quality": job["quality"],
            "status": status, "message": message[:120],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"), "thumb": thumb,
        }
        config.add_history(entry)

    def _save_thumb(self, eid: str, url: str | None) -> str | None:
        if not url:
            return None
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            path = os.path.join(config.thumbs_dir(), f"{eid}.jpg")
            Image.open(io.BytesIO(resp.content)).convert("RGB").save(path, "JPEG", quality=85)
            return path
        except Exception:
            return None

    def _on_all_done(self, success: int, total: int):
        self._downloading = False
        self._set_progress(1.0)
        self.download_btn.setEnabled(True)
        self.download_btn.setText("전체 다운로드")
        self.add_btn.setEnabled(True)
        self.clear_list_btn.setEnabled(True)
        for row in self.rows:
            row.set_controls_enabled(True)
        self._set_status(f"완료: {success}/{total}개 다운로드됨")
        # 내역 갱신(패널이 열려 있으면 즉시 반영)
        if self.history_dock.isVisible():
            self.history_panel.render()

    # ------------------------------------------------------ 내역 패널
    def toggle_history(self):
        if self.history_dock.isVisible():
            self.history_dock.hide()
        else:
            self.history_panel.render()
            self.history_dock.show()

    # ------------------------------------------------------ 자동 업데이트
    def _start_update_check(self):
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self):
        try:
            latest = updater.check_update(__version__)
        except Exception:
            return  # 네트워크 오류 등은 조용히 무시
        if latest:
            self._post(lambda: self._show_update_modal(latest))

    def _show_update_modal(self, latest: dict):
        newver = latest["tag"].lstrip("vV")
        dlg = QDialog(self)
        dlg.setWindowTitle("업데이트")
        dlg.setMinimumWidth(420)
        v = QVBoxLayout(dlg)
        head = QLabel("새로운 버전이 릴리즈 되었습니다.\n업데이트하시겠습니까?")
        head.setAlignment(Qt.AlignCenter)
        v.addWidget(head)
        v.addWidget(QLabel(f"현재 {__version__}    →    새 버전 {newver}"), 0, Qt.AlignCenter)
        box = QTextEdit()
        box.setReadOnly(True)
        box.setFixedHeight(150)
        box.setPlainText(updater.extract_summary(latest.get("body", "")))
        v.addWidget(box)
        status = QLabel("")
        status.setStyleSheet("color:gray;")
        v.addWidget(status)

        bar = QHBoxLayout()
        bar.addStretch(1)
        later = QPushButton("나중에")
        later.clicked.connect(dlg.reject)
        ok = QPushButton("확인")
        bar.addWidget(later)
        bar.addWidget(ok)
        v.addLayout(bar)

        def do_update():
            try:
                updater.download_and_apply(
                    latest, updater.build_kind(),
                    progress=lambda p: self._post(lambda: status.setText(f"다운로드 중... {p:.0f}%")),
                )
                self._post(lambda: status.setText("교체 후 재시작합니다..."))
                self._post(lambda: QApplication.instance().quit())  # 종료하면 도우미가 교체
            except Exception as e:
                self._post(lambda e=e: status.setText(f"실패: {str(e)[:60]}"))
                self._post(lambda: (ok.setEnabled(True), later.setEnabled(True)))

        def on_ok():
            ok.setEnabled(False)
            later.setEnabled(False)
            status.setText("다운로드 준비 중...")
            threading.Thread(target=do_update, daemon=True).start()

        ok.clicked.connect(on_ok)
        dlg.exec()

    # ------------------------------------------------------ 창 위치 저장
    def _restore_geometry(self):
        win = config.get_window()
        if win and all(k in win for k in ("x", "y", "w", "h")):
            try:
                self.setGeometry(int(win["x"]), int(win["y"]), int(win["w"]), int(win["h"]))
            except Exception:
                pass

    def closeEvent(self, event):
        g = self.geometry()
        config.set_window({"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height(), "zoomed": False})
        super().closeEvent(event)


def main():
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
