"""
앱 아이콘 생성기 — '둥근 빨강 사각형 + 흰색 다운로드 화살표 + 받침 바'.
1024px 원본을 만들어 app.ico(멀티사이즈)/app.icns/app.png로 저장한다.

사용:  python assets/make_icon.py        # assets/ 에 생성
(빌드는 assets/app.ico(win)·app.icns(mac)가 있으면 build.py가 자동 적용)
"""
import os

from PIL import Image, ImageDraw

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
S = 1024


def main() -> None:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # 배경: 세로 그라데이션(위 밝은 빨강 → 아래 진한 빨강)을 둥근 사각형으로 오려 붙인다.
    top, bot = (232, 58, 46), (176, 26, 22)   # #E83A2E → #B01A16
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=(
            int(top[0] * (1 - t) + bot[0] * t),
            int(top[1] * (1 - t) + bot[1] * t),
            int(top[2] * (1 - t) + bot[2] * t), 255))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    # 흰색 다운로드 글리프: 기둥 + 화살촉 + 받침 바.
    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    cx = S / 2
    stem_w = S * 0.15
    d.rounded_rectangle([cx - stem_w / 2, S * 0.23, cx + stem_w / 2, S * 0.52],
                        radius=stem_w * 0.4, fill=white)
    ah = S * 0.205
    d.polygon([(cx - ah, S * 0.45), (cx + ah, S * 0.45), (cx, S * 0.71)], fill=white)
    bar_w, bar_h = S * 0.46, S * 0.075
    d.rounded_rectangle([cx - bar_w / 2, S * 0.76, cx + bar_w / 2, S * 0.76 + bar_h],
                        radius=bar_h * 0.5, fill=white)

    img.save(os.path.join(OUT_DIR, "app.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(os.path.join(OUT_DIR, "app.icns"))
    img.save(os.path.join(OUT_DIR, "app.png"))
    print("생성 완료 ->", OUT_DIR, "(app.ico / app.icns / app.png)")


if __name__ == "__main__":
    main()
