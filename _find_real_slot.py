"""
real_slot_xx.png를 full_xx.png.png에서 template matching으로 찾아
진짜 슬롯 위치를 ground truth로 알아냄. 결과를 시각화.

알고리즘 결과 vs 진짜 위치 비교.
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

    print("=== 진짜 슬롯 위치 (template matching) ===")
    for i in range(1, 6):
        full_path = os.path.join(ASSETS, f"full_{i:02d}.png.png")
        slot_path = os.path.join(ASSETS, f"real_slot_{i:02d}.png")
        if not os.path.exists(full_path) or not os.path.exists(slot_path):
            continue
        full = load_bgr(full_path)
        real = load_bgr(slot_path)

        # full에서 real_slot 매칭
        res = cv2.matchTemplate(full, real, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        rh, rw = real.shape[:2]
        cx, cy = loc[0] + rw // 2, loc[1] + rh // 2
        print(f"full_{i:02d}: 진짜 슬롯 좌상단=({loc[0]},{loc[1]}) "
              f"size={rw}x{rh} 중심=({cx},{cy}) match_score={score:.3f}")

        # dialog 좌상단도 찾기 (slider 매칭)
        sg = cv2.cvtColor(full, cv2.COLOR_BGR2GRAY)
        slg = cv2.cvtColor(slider, cv2.COLOR_BGR2GRAY)
        sres = cv2.matchTemplate(sg, slg, cv2.TM_CCOEFF_NORMED)
        _, sscore, _, sloc = cv2.minMaxLoc(sres)
        ax = max(0, sloc[0] - SLIDER_REL[0])
        ay = max(0, sloc[1] - SLIDER_REL[1])

        # dialog 기준 상대 좌표
        rel_x = loc[0] - ax
        rel_y = loc[1] - ay
        print(f"            dialog=({ax},{ay}) → slot rel=({rel_x},{rel_y})")

        # 시각화
        vis = full.copy()
        # 진짜 슬롯 (빨강 굵게)
        cv2.rectangle(vis, loc, (loc[0] + rw, loc[1] + rh), (0, 0, 255), 3)
        cv2.putText(vis, "REAL SLOT", (loc[0], loc[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        # dialog 영역 (파랑)
        cv2.rectangle(vis, (ax, ay), (ax + DIALOG_W, ay + DIALOG_H),
                      (255, 0, 0), 2)
        out = os.path.join(ASSETS, f"truth_full_{i:02d}.png")
        imwrite(out, vis)
        print(f"            → {out}")


if __name__ == "__main__":
    main()
