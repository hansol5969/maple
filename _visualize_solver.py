"""
captcha_solver.py와 동일한 알고리즘으로 full_xx.png를 분석해 시각화.

각 단계:
  1. slider_handle 매칭 → anchor (빨강)
  2. dialog 영역 추정 (786x800) (파랑 사각형)
  3. dialog 안에서 slot 색깔 mask → 가장 큰 component (초록)
  4. confirm 매칭 (마젠타)
  5. 드래그 거리 계산: slot.x - slider.x

결과: visual_full_xx.png 저장
"""
from __future__ import annotations
import os
import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "captcha_assets")

# captcha_solver와 동일 상수
DIALOG_W, DIALOG_H = 786, 800
SLIDER_REL = (47, 485)
SLOT_TOL = 28


def load_bgr(path):
    pil = Image.open(path).convert("RGB")
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def imwrite(path, img):
    ok, buf = cv2.imencode(os.path.splitext(path)[1], img)
    with open(path, "wb") as f:
        f.write(buf.tobytes())


def gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def slot_mean_color(slot_bgr):
    h, w = slot_bgr.shape[:2]
    region = slot_bgr[h // 5:h - h // 5, w // 5:w - w // 5].reshape(-1, 3)
    return region.mean(axis=0)


def match_template(scene_bgr, tmpl_bgr, thr=0.0):
    sg = gray(scene_bgr); tg = gray(tmpl_bgr)
    res = cv2.matchTemplate(sg, tg, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score < thr:
        return None
    h, w = tg.shape
    return loc[0], loc[1], w, h, float(score)


def find_slot_in_dialog(dialog_bgr, slot_color, tol=SLOT_TOL):
    diff = np.abs(dialog_bgr.astype(np.int16) - slot_color.astype(np.int16))
    mask = (diff.max(axis=2) <= tol).astype(np.uint8) * 255
    # close(작게) — 글씨 침투 hole 메꿈
    k_small = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_small, iterations=3)
    # open(크게) — 외부 가는 글씨/선 제거
    k_large = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k_large, iterations=2)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = None
    best_area = 0
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (100 < y < 470 and 40 < x < DIALOG_W - 100):
            continue
        if not (40 < w < 150 and 40 < h < 150):
            continue
        fill_ratio = area / (w * h + 1e-6)
        if fill_ratio < 0.6:
            continue
        if area > best_area:
            best_area = area; best = (x, y, w, h)
    return best


def main():
    slider = load_bgr(os.path.join(ASSETS, "slider_handle.png"))
    confirm = load_bgr(os.path.join(ASSETS, "confirm_button.png"))
    slot_color = slot_mean_color(load_bgr(os.path.join(ASSETS, "slot.png")))
    print(f"slot 대표색 BGR=({slot_color[0]:.0f},{slot_color[1]:.0f},{slot_color[2]:.0f})")
    print(f"DIALOG={DIALOG_W}x{DIALOG_H}, SLIDER_REL={SLIDER_REL}, SLOT_TOL={SLOT_TOL}")

    fulls = sorted(f for f in os.listdir(ASSETS) if f.startswith("full_") and f.endswith(".png"))
    for fname in fulls:
        path = os.path.join(ASSETS, fname)
        scene = load_bgr(path)
        H, W = scene.shape[:2]
        vis = scene.copy()

        print(f"\n=== {fname} ({W}x{H}) ===")

        # 1. slider handle 매칭
        m = match_template(scene, slider)
        if not m:
            print("  [step1] slider 매칭 실패"); continue
        sx, sy, sw, sh, sc = m
        print(f"  [step1] slider score={sc:.3f} at ({sx},{sy})")
        cv2.rectangle(vis, (sx, sy), (sx + sw, sy + sh), (0, 0, 255), 2)
        cv2.putText(vis, f"slider {sc:.2f}", (sx, sy - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        # 2. dialog 영역
        ax = max(0, min(sx - SLIDER_REL[0], W - DIALOG_W))
        ay = max(0, min(sy - SLIDER_REL[1], H - DIALOG_H))
        print(f"  [step2] dialog at ({ax},{ay})")
        cv2.rectangle(vis, (ax, ay), (ax + DIALOG_W, ay + DIALOG_H),
                      (255, 0, 0), 2)

        # 3. slot 검출 — mask 시각화도 같이 저장
        dialog = scene[ay:ay + DIALOG_H, ax:ax + DIALOG_W]
        diff = np.abs(dialog.astype(np.int16) - slot_color.astype(np.int16))
        mask_raw = (diff.max(axis=2) <= SLOT_TOL).astype(np.uint8) * 255
        k_small = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask_morph = cv2.morphologyEx(mask_raw, cv2.MORPH_CLOSE, k_small, iterations=3)
        k_large = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask_morph = cv2.morphologyEx(mask_morph, cv2.MORPH_OPEN, k_large, iterations=2)
        # mask를 dialog에 겹쳐 시각화
        mask_color = cv2.cvtColor(mask_morph, cv2.COLOR_GRAY2BGR)
        mask_color[mask_morph > 0] = (0, 255, 255)  # 노란색 = 회색으로 잡힌 픽셀
        overlay = cv2.addWeighted(dialog, 0.6, mask_color, 0.4, 0)
        imwrite(os.path.join(ASSETS, f"mask_{fname}"), overlay)
        slot = find_slot_in_dialog(dialog, slot_color)
        if slot is None:
            print("  [step3] slot 검출 실패"); imwrite(os.path.join(ASSETS, f"visual_{fname}"), vis); continue
        slx, sly, slw, slh = slot
        slot_cx_screen = ax + slx + slw // 2
        slot_cy_screen = ay + sly + slh // 2
        print(f"  [step3] slot rel=({slx},{sly}) size={slw}x{slh}")
        print(f"          slot center screen=({slot_cx_screen},{slot_cy_screen})")
        cv2.rectangle(vis, (ax + slx, ay + sly),
                      (ax + slx + slw, ay + sly + slh), (0, 255, 0), 2)
        cv2.putText(vis, "slot", (ax + slx, ay + sly - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # 4. confirm 매칭 (dialog 안)
        m_conf = match_template(dialog, confirm, thr=0.7)
        if m_conf:
            cx, cy, cw, ch, ccs = m_conf
            print(f"  [step4] confirm rel=({cx},{cy}) score={ccs:.3f}")
            cv2.rectangle(vis, (ax + cx, ay + cy),
                          (ax + cx + cw, ay + cy + ch), (255, 0, 255), 2)
            cv2.putText(vis, f"confirm {ccs:.2f}", (ax + cx, ay + cy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1)

        # 5. 드래그 거리
        slider_cx = sx + sw // 2
        slider_cy = sy + sh // 2
        target_x = slot_cx_screen
        distance = target_x - slider_cx
        print(f"  [step5] slider_cx={slider_cx} → target_x={target_x}, "
              f"drag={distance}px")
        # 드래그 화살표
        cv2.arrowedLine(vis, (slider_cx, slider_cy),
                        (target_x, slider_cy), (0, 255, 255), 3, tipLength=0.05)
        cv2.putText(vis, f"drag={distance}px",
                    (min(slider_cx, target_x), slider_cy + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3)
        cv2.putText(vis, f"drag={distance}px",
                    (min(slider_cx, target_x), slider_cy + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)

        out = os.path.join(ASSETS, f"visual_{fname}")
        imwrite(out, vis)
        print(f"  → {out}")


if __name__ == "__main__":
    main()
