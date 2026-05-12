"""
미니맵의 모든 노란/주황 계열 blob을 HSV + 위치 + 크기로 출력.
본인 vs 파티원 hue 차이 확인용.

사용법:
  1) 게임 창 켠 상태에서, 본인 + 파티원 미니맵에 둘 다 보이게 두기
  2) python _diag_minimap_blobs.py
  3) 출력 보고 hue_tol 조절 (또는 그대로 보고해줘)
"""
import cv2
import numpy as np
import macro_v2 as m


def main():
    if m.MINIMAP_CFG is None:
        print('[!] minimap_config.json 없음 — minimap_setup.py 먼저')
        return

    screen = m.grab()
    x1, y1, x2, y2 = m.MINIMAP_CFG['minimap_rect']
    mm = screen[y1:y2, x1:x2]
    color = np.array(m.MINIMAP_CFG['char_color_bgr'], dtype=int)
    tol = m.MINIMAP_CFG.get('tolerance', 25)

    low = np.clip(color - tol, 0, 255).astype(np.uint8)
    high = np.clip(color + tol, 0, 255).astype(np.uint8)
    mask_bgr = cv2.inRange(mm, low, high)  # HSV gate 빼고 모든 BGR-통과 blob

    n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_bgr, connectivity=8)
    mm_hsv = cv2.cvtColor(mm, cv2.COLOR_BGR2HSV)

    target_hsv = cv2.cvtColor(
        np.clip(color, 0, 255).astype(np.uint8).reshape(1, 1, 3),
        cv2.COLOR_BGR2HSV,
    )[0, 0]
    print('=' * 64)
    print(f'본인 설정색: BGR={list(color)} → HSV={target_hsv.tolist()} (target_h={target_hsv[0]})')
    print(f'BGR ±{tol} 통과 blob: {n_labels - 1}개')
    print('-' * 64)

    rows = []
    for i in range(1, n_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if not (m.CHAR_BLOB_AREA_MIN <= area <= m.CHAR_BLOB_AREA_MAX):
            tag = '(area 범위 밖, 무시됨)'
        else:
            tag = ''
        cx, cy = int(centroids[i][0]), int(centroids[i][1])
        ys, xs = np.where(labels == i)
        avg_h = int(mm_hsv[ys, xs, 0].mean())
        avg_s = int(mm_hsv[ys, xs, 1].mean())
        avg_v = int(mm_hsv[ys, xs, 2].mean())
        rows.append((area, cx, cy, avg_h, avg_s, avg_v, tag))

    rows.sort(key=lambda r: -r[0])
    for r in rows:
        area, cx, cy, h, s, v, tag = r
        floor = '2층' if cy < 156 else '1층'
        print(f'  pos=({cx:3},{cy:3}) area={area:3} HSV=({h:3},{s:3},{v:3}) {floor} {tag}')

    out = mm.copy()
    for r in rows:
        area, cx, cy, h, *_ = r
        cv2.circle(out, (cx, cy), 6, (0, 0, 255), 1)
        cv2.putText(out, f'h{h}', (cx + 7, cy + 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
    cv2.imwrite('mm_diag.png', out)
    cv2.imwrite('mm_diag_mask.png', mask_bgr)
    print('-' * 64)
    print('이미지 저장: mm_diag.png (blob 표시), mm_diag_mask.png (mask)')


if __name__ == '__main__':
    main()
