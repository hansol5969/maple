"""
real_slot 5장을 template으로 각 full_xx에서 매칭 시도.
가장 깨끗한 real_slot_04가 template으로 어떤 성능을 내는지 확인.

목표: ground truth 위치(template matching 1.000)와 색 mask 결과 비교.
"""
import os
import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "captcha_assets")
DIALOG_W, DIALOG_H = 786, 800
SLIDER_REL = (47, 485)


def load_bgr(path):
    return cv2.cvtColor(np.array(Image.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)


def imwrite(path, img):
    ok, buf = cv2.imencode(os.path.splitext(path)[1], img)
    with open(path, "wb") as f:
        f.write(buf.tobytes())


def main():
    slider = load_bgr(os.path.join(ASSETS, "slider_handle.png"))
    # real_slot 5장 모두 template으로 사용
    templates = []
    for i in range(1, 6):
        p = os.path.join(ASSETS, f"real_slot_{i:02d}.png")
        if os.path.exists(p):
            templates.append((f"real_slot_{i:02d}", load_bgr(p)))
    print(f"templates loaded: {len(templates)}")

    print("\n=== 각 full_xx에서 5개 template 매칭 비교 ===")
    for i in range(1, 6):
        full_path = os.path.join(ASSETS, f"full_{i:02d}.png.png")
        if not os.path.exists(full_path): continue
        full = load_bgr(full_path)
        H, W = full.shape[:2]

        # dialog 영역 추정
        sg = cv2.cvtColor(full, cv2.COLOR_BGR2GRAY)
        slg = cv2.cvtColor(slider, cv2.COLOR_BGR2GRAY)
        sres = cv2.matchTemplate(sg, slg, cv2.TM_CCOEFF_NORMED)
        _, _, _, sloc = cv2.minMaxLoc(sres)
        ax = max(0, min(sloc[0] - SLIDER_REL[0], W - DIALOG_W))
        ay = max(0, min(sloc[1] - SLIDER_REL[1], H - DIALOG_H))
        dialog = full[ay:ay + DIALOG_H, ax:ax + DIALOG_W]

        print(f"\n--- full_{i:02d} (dialog at {ax},{ay}) ---")
        # 진짜 위치 (real_slot_i 매칭)
        truth_tpl = load_bgr(os.path.join(ASSETS, f"real_slot_{i:02d}.png"))
        tres = cv2.matchTemplate(dialog, truth_tpl, cv2.TM_CCOEFF_NORMED)
        _, tscore, _, tloc = cv2.minMaxLoc(tres)
        print(f"  진짜 위치 (self): {tloc} score={tscore:.3f}")

        # 다른 4장 template으로 매칭 + sub-pixel
        results = []
        for name, tpl in templates:
            if name == f"real_slot_{i:02d}":
                continue
            res = cv2.matchTemplate(dialog, tpl, cv2.TM_CCOEFF_NORMED)
            _, sc, _, loc = cv2.minMaxLoc(res)
            # sub-pixel
            H, W = res.shape
            x, y = loc
            if 0 < x < W - 1 and 0 < y < H - 1:
                dx = (res[y, x+1] - res[y, x-1]) * 0.5
                dxx = res[y, x+1] - 2 * res[y, x] + res[y, x-1]
                dy = (res[y+1, x] - res[y-1, x]) * 0.5
                dyy = res[y+1, x] - 2 * res[y, x] + res[y-1, x]
                sub_x = x - (dx / dxx) if abs(dxx) > 1e-6 else float(x)
                sub_y = y - (dy / dyy) if abs(dyy) > 1e-6 else float(y)
                if abs(sub_x - x) > 1.0 or abs(sub_y - y) > 1.0:
                    sub_x, sub_y = float(x), float(y)
            else:
                sub_x, sub_y = float(x), float(y)
            dist_to_truth = abs(sub_x - tloc[0]) + abs(sub_y - tloc[1])
            results.append((name, (sub_x, sub_y), sc, dist_to_truth))
            print(f"  {name}: ({sub_x:.2f},{sub_y:.2f}) score={sc:.3f} "
                  f"(truth와 거리 {dist_to_truth:.2f}px)")

        # 가장 매칭 잘 된 게 진짜 위치인지
        best = max(results, key=lambda r: r[2])
        print(f"  → BEST: {best[0]} 매칭 score {best[2]:.3f} "
              f"({'적중' if best[3] < 30 else f'{best[3]}px 빗나감'})")


if __name__ == "__main__":
    main()
