"""
미니맵 설정 검증 — 게임 캡처해서 캐릭터 점 검출 확인
실행: python test_minimap.py
- minimap_debug.png : 미니맵 영역 + 검출 위치 표시
"""
import sys, time
import cv2, numpy as np, mss
sys.path.insert(0, '.')
import macro

print(f'미니맵 설정: {macro.MINIMAP_CFG}')
print(f'게임 영역: {macro.GAME_REGION}')
print('3초 후 캡처. 게임 창에 포커스 두세요.')
for i in (3, 2, 1):
    print(i); time.sleep(1)

with mss.mss() as sct:
    raw = np.array(sct.grab(macro.GAME_REGION))
screen = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

pos = macro.find_char_minimap_pos(screen)
print(f'\n검출 결과: {pos}  (None이면 못 찾음)')

if pos:
    mx, my = pos
    base = macro.MINIMAP_CFG.get('floor1_y_baseline')
    print(f'  미니맵 내부 X={mx}  Y={my}')
    print(f'  1층 기준선={base}  현재와 차이={my - base if base else "N/A"}')
    print(f'  → 2층 판정 임계: Y < {base - macro.FLOOR2_DELTA_Y} (현재 Y={my} → {"2층!" if my < base - macro.FLOOR2_DELTA_Y else "1층 / 정상"})')

x1, y1, x2, y2 = macro.MINIMAP_CFG['minimap_rect']
mm = screen[y1:y2, x1:x2].copy()
color = np.array(macro.MINIMAP_CFG['char_color_bgr'], dtype=int)
tol = macro.MINIMAP_CFG.get('tolerance', 25)
low = np.clip(color - tol, 0, 255).astype(np.uint8)
high = np.clip(color + tol, 0, 255).astype(np.uint8)
mask = cv2.inRange(mm, low, high)
n_pixels = int((mask > 0).sum())
print(f'\n총 매칭 픽셀: {n_pixels}')

n_labels, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
print(f'분리된 blob 수: {n_labels - 1}')
print(f'  (CHAR_BLOB_AREA: {macro.CHAR_BLOB_AREA_MIN} ~ {macro.CHAR_BLOB_AREA_MAX})')
print(f'{"#":<3}{"area":<6}{"X":<6}{"Y":<6}{"size":<10}{"판정"}')
for i in range(1, n_labels):
    area = int(stats[i, cv2.CC_STAT_AREA])
    cx, cy = centroids[i]
    w = int(stats[i, cv2.CC_STAT_WIDTH])
    h = int(stats[i, cv2.CC_STAT_HEIGHT])
    selected = (macro.CHAR_BLOB_AREA_MIN <= area <= macro.CHAR_BLOB_AREA_MAX)
    note = '캐릭후보' if selected else '제외'
    print(f'{i:<3}{area:<6}{int(cx):<6}{int(cy):<6}{w}x{h:<6} {note}')

# 시각화
red = np.zeros_like(mm)
red[mask > 0] = (0, 0, 255)
overlay = cv2.addWeighted(mm, 0.6, red, 0.4, 0)

# 모든 blob 박스 표시
for i in range(1, n_labels):
    x = int(stats[i, cv2.CC_STAT_LEFT])
    y = int(stats[i, cv2.CC_STAT_TOP])
    w = int(stats[i, cv2.CC_STAT_WIDTH])
    h = int(stats[i, cv2.CC_STAT_HEIGHT])
    area = int(stats[i, cv2.CC_STAT_AREA])
    selected = (macro.CHAR_BLOB_AREA_MIN <= area <= macro.CHAR_BLOB_AREA_MAX)
    col = (0, 255, 0) if selected else (255, 0, 255)  # green=후보, magenta=제외
    cv2.rectangle(overlay, (x, y), (x + w, y + h), col, 1)
    cv2.putText(overlay, f'{area}', (x, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, col, 1)

# 최종 검출 위치 (노란 십자)
if pos:
    cv2.drawMarker(overlay, pos, (0, 255, 255), cv2.MARKER_CROSS, 16, 2)

# 1층/2층 라인
base = macro.MINIMAP_CFG.get('floor1_y_baseline')
if base is not None:
    cv2.line(overlay, (0, base), (overlay.shape[1], base), (0, 255, 0), 1)
    th = base - macro.FLOOR2_DELTA_Y
    cv2.line(overlay, (0, th), (overlay.shape[1], th), (0, 0, 255), 1)

cv2.imwrite('minimap_debug.png', overlay)
print('\n저장: minimap_debug.png  (초록박스=캐릭후보 blob, 마젠타=제외, 노란십자=최종검출)')
