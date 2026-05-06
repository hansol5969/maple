"""
미니맵 셋업 툴
- 게임 창 캡처 → 미니맵 영역 드래그로 선택 → 그 안 캐릭터 점 클릭
- minimap_config.json 저장

조작:
  마우스 드래그   = 미니맵 영역 선택 (좌상단→우하단)
  미니맵 안 클릭  = 그 픽셀 색 = 캐릭터 점 색 (그 Y가 1층 기준선)
  r = 다시 캡처
  + / - = 색 허용오차(tolerance) 증감
  s = 저장
  q / ESC = 종료

저장 후 macro.py가 자동 사용함.
"""

import json
import os
import sys
import cv2
import numpy as np
import mss

sys.path.insert(0, '.')
import macro

CONFIG_PATH = 'minimap_config.json'
WINDOW_NAME = 'minimap_setup'

# 디스플레이가 너무 커서 모니터 밖으로 나가지 않도록 축소
DISPLAY_MAX_W = 1600
DISPLAY_MAX_H = 900


state = {
    'screen': None,            # 원본 캡처 (BGR)
    'scale': 1.0,              # 디스플레이 축소율 (mouse 좌표 환산용)
    'minimap_rect': None,      # 원본 좌표계 (x1, y1, x2, y2)
    'char_color_bgr': None,
    'floor1_y_baseline': None, # 미니맵 내부 Y
    'tolerance': 25,
    'mode': 'select_rect',     # 'select_rect' → 'pick_color' → 'done'
    'drag_start': None,        # 원본 좌표
    'drag_now': None,          # 원본 좌표
}


def capture():
    with mss.mss() as sct:
        raw = np.array(sct.grab(macro.GAME_REGION))
    return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)


def compute_scale(img):
    h, w = img.shape[:2]
    return min(DISPLAY_MAX_W / w, DISPLAY_MAX_H / h, 1.0)


def to_img(mx, my):
    """디스플레이(윈도우) 좌표 → 원본 이미지 좌표"""
    s = state['scale']
    return int(mx / s), int(my / s)


def on_mouse(event, mx, my, flags, _):
    x, y = to_img(mx, my)
    if state['mode'] == 'select_rect':
        if event == cv2.EVENT_LBUTTONDOWN:
            state['drag_start'] = (x, y)
            state['drag_now'] = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and state['drag_start']:
            state['drag_now'] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and state['drag_start']:
            x1, y1 = state['drag_start']
            x2, y2 = x, y
            if abs(x2 - x1) < 5 or abs(y2 - y1) < 5:
                print('영역이 너무 작음, 다시 드래그하세요')
            else:
                state['minimap_rect'] = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
                state['mode'] = 'pick_color'
                print(f'[1/2] 미니맵 영역 = {state["minimap_rect"]}')
                print(f'      이제 미니맵 안 캐릭터 점을 클릭하세요')
            state['drag_start'] = None
            state['drag_now'] = None

    elif state['mode'] == 'pick_color':
        if event == cv2.EVENT_LBUTTONDOWN:
            x1, y1, x2, y2 = state['minimap_rect']
            if not (x1 <= x <= x2 and y1 <= y <= y2):
                print(f'미니맵 영역 밖이에요 (클릭 {x},{y}). 미니맵 안에서 클릭하세요.')
                return
            bgr = state['screen'][y, x]
            state['char_color_bgr'] = [int(c) for c in bgr]
            state['floor1_y_baseline'] = y - y1  # 미니맵 내부 Y
            state['mode'] = 'done'
            print(f'[2/2] 캐릭터 색 BGR = {state["char_color_bgr"]} (원본 좌표 {x},{y})')
            print(f'      1층 Y 기준선 = {state["floor1_y_baseline"]} (미니맵 내부)')
            print(f'      s 키 = 저장 / +,- 키 = 색 허용오차 조정')


def render():
    """원본에 그리고 디스플레이 크기로 축소해서 반환"""
    vis = state['screen'].copy()

    # 드래그 중 사각형
    if state['drag_start'] and state['drag_now']:
        cv2.rectangle(vis, state['drag_start'], state['drag_now'], (0, 200, 255), 2)

    # 확정된 미니맵 영역
    if state['minimap_rect']:
        x1, y1, x2, y2 = state['minimap_rect']
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)

    # 색 매칭 미리보기 (mask 시각화)
    if state['minimap_rect'] and state['char_color_bgr']:
        x1, y1, x2, y2 = state['minimap_rect']
        mm = state['screen'][y1:y2, x1:x2]
        color = np.array(state['char_color_bgr'], dtype=int)
        tol = state['tolerance']
        low = np.clip(color - tol, 0, 255).astype(np.uint8)
        high = np.clip(color + tol, 0, 255).astype(np.uint8)
        mask = cv2.inRange(mm, low, high)
        red = np.zeros_like(mm)
        red[mask > 0] = (0, 0, 255)
        vis[y1:y2, x1:x2] = cv2.addWeighted(mm, 0.6, red, 0.4, 0)

        M = cv2.moments(mask)
        if M['m00'] > 0:
            cx = int(M['m10'] / M['m00']) + x1
            cy = int(M['m01'] / M['m00']) + y1
            cv2.drawMarker(vis, (cx, cy), (0, 255, 255), cv2.MARKER_CROSS, 24, 2)

    bar = (
        f'mode={state["mode"]}  rect={state["minimap_rect"]}  '
        f'color={state["char_color_bgr"]}  tol={state["tolerance"]}  '
        f'scale={state["scale"]:.2f}'
    )
    h_, w_ = vis.shape[:2]
    cv2.rectangle(vis, (0, 0), (w_, 28), (0, 0, 0), -1)
    cv2.putText(vis, bar, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    s = state['scale']
    if s < 1.0:
        new_w = int(w_ * s)
        new_h = int(h_ * s)
        vis = cv2.resize(vis, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return vis


def cleanup_windows():
    """destroyAllWindows + waitKey 여러 번 — Windows에서 잔존 창 확실히 제거"""
    for _ in range(4):
        cv2.destroyAllWindows()
        cv2.waitKey(1)


def main():
    # 시작 전 혹시 남아있는 OpenCV 창 정리
    cleanup_windows()

    state['screen'] = capture()
    state['scale'] = compute_scale(state['screen'])

    h, w = state['screen'].shape[:2]
    print(f'캡처 원본: {w}x{h},  디스플레이 축소율: {state["scale"]:.2f}')

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)
    try:
        cv2.moveWindow(WINDOW_NAME, 30, 30)
    except cv2.error:
        pass

    print('드래그=미니맵 영역,  미니맵 안 클릭=캐릭터 점 색,  +/-=tol,  r=재캡처,  s=저장,  q=종료')

    try:
        while True:
            cv2.imshow(WINDOW_NAME, render())
            k = cv2.waitKey(30) & 0xFF

            # X 버튼으로 창을 닫은 경우도 종료
            try:
                if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                    print('창 닫힘 → 종료')
                    break
            except cv2.error:
                break

            if k in (27, ord('q')):
                print('종료')
                break
            if k == ord('r'):
                state['screen'] = capture()
                state['scale'] = compute_scale(state['screen'])
                state['minimap_rect'] = None
                state['char_color_bgr'] = None
                state['floor1_y_baseline'] = None
                state['mode'] = 'select_rect'
                print('재캡처')
            if k in (ord('+'), ord('=')):
                state['tolerance'] = min(state['tolerance'] + 5, 80)
                print(f'tol={state["tolerance"]}')
            if k == ord('-'):
                state['tolerance'] = max(state['tolerance'] - 5, 5)
                print(f'tol={state["tolerance"]}')
            if k == ord('s'):
                if not state['minimap_rect'] or not state['char_color_bgr']:
                    print('미니맵 영역 + 캐릭터 색 둘 다 정해야 저장됩니다')
                    continue
                cfg = {
                    'minimap_rect': list(state['minimap_rect']),
                    'char_color_bgr': state['char_color_bgr'],
                    'tolerance': state['tolerance'],
                    'floor1_y_baseline': state['floor1_y_baseline'],
                }
                with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, indent=2)
                print(f'저장: {CONFIG_PATH}')
                print(json.dumps(cfg, indent=2))
                break
    finally:
        cleanup_windows()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n인터럽트 → 종료')
    finally:
        cleanup_windows()
    # OpenCV GUI 스레드가 살아있어 프로세스가 안 끝나는 경우가 있어 강제 종료
    sys.stdout.flush()
    os._exit(0)
