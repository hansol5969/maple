"""
미니맵 안의 모든 채도 높은 점(캐릭/NPC/파티원 다 포함)을 색 무관하게 찾아서
hue/sat/val 출력. 본인 점이 다른 색으로 변했을 때 진짜 색 찾는 용도.

사용법:
  python _diag_all_dots.py

출력 보면:
  - hue 30 부근(노란색) blob이 본인일 가능성 (현재 char_color)
  - hue 0/180 (빨강), 10-20 (주황), 110-130 (파랑) 등은 다른 캐릭일 가능성
"""
import cv2
import numpy as np
import macro_v2 as m


def main():
    if m.MINIMAP_CFG is None:
        print('[!] minimap_config.json 없음')
        return

    screen = m.grab()
    x1, y1, x2, y2 = m.MINIMAP_CFG['minimap_rect']
    mm = screen[y1:y2, x1:x2]
    mm_hsv = cv2.cvtColor(mm, cv2.COLOR_BGR2HSV)

    # 채도 ≥ 120 AND 명도 ≥ 150 인 픽셀만 — 회색/검정 미니맵 배경 제외, 컬러 마커만 잡음
    sat_mask = cv2.inRange(mm_hsv[:, :, 1], 120, 255)
    val_mask = cv2.inRange(mm_hsv[:, :, 2], 150, 255)
    mask = cv2.bitwise_and(sat_mask, val_mask)

    n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    print('=' * 64)
    print(f'미니맵 영역: {(x2 - x1)}x{(y2 - y1)}')
    print(f'1층 baseline = {m.MINIMAP_CFG.get("floor1_y_baseline")}')
    print(f'본인 설정색 BGR={m.MINIMAP_CFG["char_color_bgr"]} (target_h=30, yellow)')
    print(f'채도/명도 통과 컬러 blob: {n_labels - 1}개')
    print('-' * 64)

    rows = []
    for i in range(1, n_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < 2:
            continue
        cx, cy = int(centroids[i][0]), int(centroids[i][1])
        ys, xs = np.where(labels == i)
        avg_h = int(mm_hsv[ys, xs, 0].mean())
        avg_s = int(mm_hsv[ys, xs, 1].mean())
        avg_v = int(mm_hsv[ys, xs, 2].mean())
        # BGR 평균
        avg_b = int(mm[ys, xs, 0].mean())
        avg_g = int(mm[ys, xs, 1].mean())
        avg_r = int(mm[ys, xs, 2].mean())
        rows.append((area, cx, cy, avg_h, avg_s, avg_v, avg_b, avg_g, avg_r))

    rows.sort(key=lambda r: -r[0])

    def hue_name(h):
        if h < 8 or h > 170:    return 'red'
        if h < 22:              return 'orange'
        if h < 35:              return 'yellow'
        if h < 80:              return 'green'
        if h < 100:             return 'cyan'
        if h < 130:             return 'blue'
        if h < 160:             return 'purple/pink'
        return 'red'

    base_y = m.MINIMAP_CFG.get('floor1_y_baseline', 170)
    for r in rows:
        area, cx, cy, h, s, v, b, g, rr = r
        floor = '2층' if cy < base_y - 6 else '1층'
        print(f'  pos=({cx:3},{cy:3}) area={area:3} HSV=({h:3},{s:3},{v:3}) '
              f'BGR=({b:3},{g:3},{rr:3}) {floor} {hue_name(h):11}')

    out = mm.copy()
    for r in rows:
        area, cx, cy, h, *_ = r
        cv2.circle(out, (cx, cy), 7, (0, 0, 255), 1)
        cv2.putText(out, f'h{h}/{area}', (cx + 8, cy + 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
    cv2.imwrite('mm_alldots.png', out)
    print('-' * 64)
    print('이미지 저장: mm_alldots.png (모든 컬러 dot 표시)')


if __name__ == '__main__':
    main()
