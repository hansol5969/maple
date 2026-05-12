"""
slot 검출 v5: slot.png에서 대표 색깔 뽑아 → 캡차에서 그 색에 가까운 픽셀 mask
→ 가장 큰 connected component = slot.
"""
from __future__ import annotations
import os
import cv2
import numpy as np
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captcha_assets")


def load_bgr(path):
    pil = Image.open(path).convert("RGB")
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def imwrite(path, img):
    ok, buf = cv2.imencode(os.path.splitext(path)[1], img)
    with open(path, "wb") as f:
        f.write(buf.tobytes())


def gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def slot_color_stats(slot_bgr):
    """slot.png의 중심 영역에서 대표 BGR 색 평균/표준편차."""
    h, w = slot_bgr.shape[:2]
    # 중심 60% 영역만 (테두리 제외)
    y0, y1 = h // 5, h - h // 5
    x0, x1 = w // 5, w - w // 5
    region = slot_bgr[y0:y1, x0:x1].reshape(-1, 3)
    return region.mean(axis=0), region.std(axis=0)


def find_slot_by_color(scene_bgr, target_bgr, tol=25, min_w=40, min_h=50):
    """target 색에 가까운 픽셀 mask → connected component → piece 크기 후보."""
    diff = np.abs(scene_bgr.astype(np.int16) - target_bgr.astype(np.int16))
    mask = (diff.max(axis=2) <= tol).astype(np.uint8) * 255

    # morph로 노이즈 제거 + 영역 합치기
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=1)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    cands = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w >= min_w and h >= min_h and w < 150 and h < 150:
            cands.append((x, y, w, h, area))
    return cands, mask


def match_one(scene_gray, tmpl_gray):
    res = cv2.matchTemplate(scene_gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    return loc, float(score), (tmpl_gray.shape[1], tmpl_gray.shape[0])


def draw_box(img, xy, wh, color, label):
    x, y = xy; w, h = wh
    cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
    cv2.putText(img, label, (x, max(12, y - 4)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def main():
    slot_tmpl = load_bgr(os.path.join(ROOT, "slot.png"))
    piece_tmpl = load_bgr(os.path.join(ROOT, "piece.png"))
    slider = load_bgr(os.path.join(ROOT, "slider_handle.png"))
    confirm = load_bgr(os.path.join(ROOT, "confirm_button.png"))

    slot_color, slot_std = slot_color_stats(slot_tmpl)
    piece_color, _ = slot_color_stats(piece_tmpl)
    print(f"slot 대표 BGR : ({slot_color[0]:.0f}, {slot_color[1]:.0f}, {slot_color[2]:.0f}) "
          f"std=({slot_std[0]:.1f}, {slot_std[1]:.1f}, {slot_std[2]:.1f})")
    print(f"piece 대표 BGR: ({piece_color[0]:.0f}, {piece_color[1]:.0f}, {piece_color[2]:.0f})")
    print(f"색 차이 (slot vs piece): {np.abs(slot_color - piece_color).max():.1f}")

    fulls = sorted(f for f in os.listdir(ROOT) if f.startswith("full_"))
    for fname in fulls:
        path = os.path.join(ROOT, fname)
        scene = load_bgr(path)
        sg = gray(scene)
        vis = scene.copy()

        cands_slot, mask = find_slot_by_color(scene, slot_color, tol=22)
        cands_piece, _ = find_slot_by_color(scene, piece_color, tol=22)

        print(f"\n{fname}")
        print(f"  slot 후보 {len(cands_slot)}개:")
        for x, y, w, h, a in cands_slot:
            print(f"    ({x},{y}) {w}x{h} area={a}")
        print(f"  piece 후보 {len(cands_piece)}개:")
        for x, y, w, h, a in cands_piece[:3]:
            print(f"    ({x},{y}) {w}x{h} area={a}")

        # piece: 가장 좌측 + 사이즈 적절
        piece_xy = None
        for x, y, w, h, a in sorted(cands_piece, key=lambda r: r[0]):
            if 100 < y < 470 and a > 1500:
                piece_xy = (x, y, w, h)
                break

        # slot: 가장 큰 area
        slot_xy = None
        if cands_slot:
            cands_slot.sort(key=lambda r: -r[4])
            for x, y, w, h, a in cands_slot:
                if 100 < y < 470 and a > 1500:
                    slot_xy = (x, y, w, h)
                    break

        if piece_xy:
            draw_box(vis, piece_xy[:2], piece_xy[2:], (0, 0, 255), "piece")
        if slot_xy:
            draw_box(vis, slot_xy[:2], slot_xy[2:], (0, 255, 0), "slot")

        sl_loc, sl_sc, sl_wh = match_one(sg, gray(slider))
        draw_box(vis, sl_loc, sl_wh, (255, 0, 0), f"slider {sl_sc:.2f}")
        cf_loc, cf_sc, cf_wh = match_one(sg, gray(confirm))
        draw_box(vis, cf_loc, cf_wh, (255, 0, 255), f"confirm {cf_sc:.2f}")

        if piece_xy and slot_xy:
            piece_cx = piece_xy[0] + piece_xy[2] // 2
            slot_cx = slot_xy[0] + slot_xy[2] // 2
            dist = slot_cx - piece_cx
            print(f"  piece_cx={piece_cx}, slot_cx={slot_cx}, drag={dist}px")
            msg = f"drag={dist}px"
        else:
            msg = f"piece={'OK' if piece_xy else 'X'} slot={'OK' if slot_xy else 'X'}"
        cv2.putText(vis, msg, (10, vis.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3)
        cv2.putText(vis, msg, (10, vis.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)

        out = os.path.join(ROOT, "analysis_" + fname.replace(".png.png", ".png"))
        imwrite(out, vis)
        # mask도 저장 (디버그용)
        mask_out = os.path.join(ROOT, "mask_" + fname.replace(".png.png", ".png"))
        imwrite(mask_out, mask)


if __name__ == "__main__":
    main()
