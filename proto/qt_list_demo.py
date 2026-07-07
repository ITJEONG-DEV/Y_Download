"""
Qt(PySide6) 스크롤 부드러움 데모 — 다운로드 목록 전환 검토용 프로토타입.

현재 CustomTkinter 다운로드 목록과 동일한 형태의 '리치 행'(번호·썸네일·제목·
파일명 입력·확장자/포맷/품질 드롭다운·예상크기·상태·삭제버튼)을 대량으로 띄워
실제 스크롤 감을 확인한다. 백엔드는 쓰지 않고 가짜 데이터로 채운다.

실행:
    pip install PySide6
    python proto/qt_list_demo.py

상단 툴바의 [50행][200행][1000행] 버튼으로 개수를 바꿔가며 스크롤을 체감해 보세요.
(참고: 이 데모는 QListWidget에 실제 위젯을 그대로 얹는 '간단' 방식입니다.
 최종 전환 시 수천 행까지 필요하면 QListView+델리게이트 '완전 가상화'로 갑니다.)
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QToolBar, QVBoxLayout, QWidget,
)

THUMB_W, THUMB_H = 120, 68


def make_thumb(seed: int) -> QPixmap:
    """가짜 썸네일(색 채운 사각형). 실제 이미지 로드 비용을 흉내만 낸다."""
    pm = QPixmap(THUMB_W, THUMB_H)
    r = (seed * 53) % 200 + 40
    g = (seed * 97) % 200 + 40
    b = (seed * 31) % 200 + 40
    pm.fill(QColor(r, g, b))
    return pm


class Row(QWidget):
    """다운로드 목록 한 행과 동일한 구성의 위젯."""

    def __init__(self, i: int):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(8)

        idx = QLabel(str(i + 1))
        idx.setFixedWidth(28)
        idx.setAlignment(Qt.AlignCenter)

        thumb = QLabel()
        thumb.setPixmap(make_thumb(i))
        thumb.setFixedSize(THUMB_W, THUMB_H)

        right = QVBoxLayout()
        right.setSpacing(3)

        title = QLabel(f"[성공] video_{i}  (아주 긴 영상 제목이 들어갈 수 있는 자리입니다 — 샘플 {i})")
        title.setWordWrap(True)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("파일명:"))
        name = QLineEdit(f"video_{i}")
        r2.addWidget(name, 1)
        r2.addWidget(QLabel("확장자:"))
        ext = QComboBox()
        ext.addItems(["mp4", "mkv", "webm"])
        r2.addWidget(ext)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("포맷:"))
        kind = QComboBox()
        kind.addItems(["영상", "음원"])
        r3.addWidget(kind)
        r3.addWidget(QLabel("품질:"))
        quality = QComboBox()
        quality.addItems(["1080p", "720p", "480p", "360p"])
        r3.addWidget(quality)
        r3.addStretch(1)
        r3.addWidget(QLabel("예상: 45.3 MB"))
        r3.addWidget(QLabel("대기"))
        rm = QPushButton("✕")
        rm.setFixedWidth(30)
        r3.addWidget(rm)

        right.addWidget(title)
        right.addLayout(r2)
        right.addLayout(r3)

        h.addWidget(idx)
        h.addWidget(thumb)
        h.addLayout(right, 1)


class Demo(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qt 스크롤 데모 — 다운로드 목록 (PySide6)")
        self.resize(920, 680)

        self.list = QListWidget()
        self.list.setSpacing(4)
        self.setCentralWidget(self.list)

        tb = QToolBar()
        self.addToolBar(tb)
        tb.addWidget(QLabel("  행 개수: "))
        for n in (50, 200, 1000):
            act = QAction(f"{n}행", self)
            act.triggered.connect(lambda _=False, n=n: self.fill(n))
            tb.addAction(act)
        self.status = QLabel("  ")
        tb.addWidget(self.status)

        self.fill(200)

    def fill(self, n: int):
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        for i in range(n):
            w = Row(i)
            item = QListWidgetItem(self.list)
            item.setSizeHint(w.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, w)
        self.list.setUpdatesEnabled(True)
        self.status.setText(f"  {n}행 로드됨 — 스크롤을 움직여 부드러움을 확인하세요")


def main():
    app = QApplication(sys.argv)
    d = Demo()
    d.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
