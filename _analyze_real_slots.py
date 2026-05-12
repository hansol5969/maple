"""
real_slot_*.png 분석:
  - 각 슬롯의 평균 BGR + 표준편차
  - 5장 통합 색 범위
  - 우리가 쓰던 slot.png와 비교
"""
import os
import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "captcha_assets")


def load_bgr(path):
    return cv2.cvtColor(np.array(Image.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)


def stats(bgr, label):
    flat = bgr.reshape(-1, 3)
    mean = flat.mean(axis=0)
    std = flat.std(axis=0)
    print(f"  {label}: shape={bgr.shape[1]}x{bgr.shape[0]} "
          f"mean=({mean[0]:.0f},{mean[1]:.0f},{mean[2]:.0f}) "
          f"std=({std[0]:.1f},{std[1]:.1f},{std[2]:.1f})")
    return mean, std


def main():
    print("=== 기존 slot.png ===")
    old = load_bgr(os.path.join(ASSETS, "slot.png"))
    h, w = old.shape[:2]
    old_center = old[h//5:h-h//5, w//5:w-w//5]
    stats(old_center, "old slot.png 중심부")

    print("\n=== real_slot_*.png (사용자 지정) ===")
    means = []
    stds = []
    for i in range(1, 6):
        p = os.path.join(ASSETS, f"real_slot_{i:02d}.png")
        if not os.path.exists(p): continue
        img = load_bgr(p)
        # 중심부만 (테두리 노이즈 제외)
        h, w = img.shape[:2]
        center = img[max(1, h//6):h-max(1, h//6), max(1, w//6):w-max(1, w//6)]
        m, s = stats(center, f"real_slot_{i:02d}")
        means.append(m)
        stds.append(s)

    if means:
        ms = np.array(means)
        avg_mean = ms.mean(axis=0)
        avg_std = np.array(stds).mean(axis=0)
        print(f"\n=== 5장 평균 ===")
        print(f"  mean=({avg_mean[0]:.0f},{avg_mean[1]:.0f},{avg_mean[2]:.0f})")
        print(f"  std=({avg_std[0]:.1f},{avg_std[1]:.1f},{avg_std[2]:.1f})")
        print(f"  채널별 mean 분산: "
              f"B={ms[:,0].std():.1f} G={ms[:,1].std():.1f} R={ms[:,2].std():.1f}")
        print(f"\n  → 권장 slot_color: BGR=({avg_mean[0]:.0f},{avg_mean[1]:.0f},{avg_mean[2]:.0f})")
        # tol 추천: 캡차마다 색 변동 + 슬롯 내 std 합산
        rec_tol = int(max(ms[:,c].std() for c in range(3)) + avg_std.max() + 5)
        print(f"  → 권장 tol: {rec_tol}")


if __name__ == "__main__":
    main()
