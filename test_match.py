"""
템플릿 매칭 테스터
- 5초 후 게임창 전체 캡처
- 모든 템플릿(nickname/mob*/lie_*)에 대해 매칭 점수 출력
- 매칭된 위치를 표시한 이미지를 match_result.png 로 저장

실행: python test_match.py
"""

import sys
import time
import os
import cv2
import numpy as np
import mss

sys.path.insert(0, '.')
import macro

print(f'게임 영역: {macro.GAME_REGION}')
print('5초 후 캡처합니다. 게임 창에 포커스 두세요.')
for i in range(5, 0, -1):
    print(i)
    time.sleep(1)

with mss.mss() as sct:
    raw = np.array(sct.grab(macro.GAME_REGION))
    screen = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

cv2.imwrite('capture_full.png', screen)
print(f'캡처 저장: capture_full.png  (size {screen.shape[1]}x{screen.shape[0]})')
print()

vis = screen.copy()
lie_paths = [macro.LIE_TEMPLATE] if os.path.exists(macro.LIE_TEMPLATE) else []
groups = [
    ('CHAR  ', [macro.CHAR_TEMPLATE], macro.CHAR_THRESHOLD, (0, 255, 0)),
    ('MOB   ', macro.MOB_TEMPLATES,   macro.MOB_THRESHOLD,  (0, 165, 255)),
    ('LIE   ', lie_paths,             macro.LIE_THRESHOLD,  (0, 0, 255)),
]

for label, paths, threshold, color in groups:
    for p in paths:
        tpl = cv2.imread(p)
        if tpl is None:
            print(f'[{label}] {p} — 읽기 실패')
            continue
        h, w = tpl.shape[:2]
        if h > screen.shape[0] or w > screen.shape[1]:
            print(f'[{label}] {p} — 템플릿이 화면보다 큼 ({w}x{h}) 스킵')
            continue

        t0 = time.time()
        res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
        dt = (time.time() - t0) * 1000
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        ys, xs = np.where(res >= threshold)
        n_hits = len(xs)

        status = 'PASS' if max_val >= threshold else 'fail'
        print(f'[{label}] {p:30s} size={w}x{h:<5d} best={max_val:.3f} (>={threshold}) hits={n_hits:<4d} {dt:5.0f}ms  {status}')

        if max_val >= threshold:
            cv2.rectangle(vis, max_loc, (max_loc[0] + w, max_loc[1] + h), color, 2)
            cv2.putText(vis, f'{label.strip()} {max_val:.2f}',
                        (max_loc[0], max_loc[1] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

cv2.imwrite('match_result.png', vis)
print()
print('표시된 이미지: match_result.png')
