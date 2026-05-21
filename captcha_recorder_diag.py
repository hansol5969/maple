"""캡차 트리거 매칭 진단 — 현재 화면 vs invi_ready/invi_on 매칭 score 측정.

캡차가 떠 있는 동안 실행하면 매칭 score 보임. score 낮으면 template 다시 캡처 필요.

사용:
  1. 매크로 환경에서 캡차 띄워두고
  2. python captcha_recorder_diag.py
  3. score 출력 + 현재 화면 PNG 저장 → 비교
"""
import os
import sys
import time
import ctypes
import cv2
import numpy as np

if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try: ctypes.windll.user32.SetProcessDPIAware()
        except Exception: pass


def main():
    import macro_red as m

    templates_paths = ['templates/invi_ready.png', 'templates/invi_on.png']
    templates = []
    for p in templates_paths:
        if not os.path.exists(p):
            print(f'[diag] template 없음: {p}')
            continue
        tpl = cv2.imread(p)
        if tpl is None:
            print(f'[diag] template 로드 실패: {p}')
            continue
        templates.append((p, tpl))
        print(f'[diag] loaded: {p} shape={tpl.shape}')

    if not templates:
        print('[diag] templates 없음 → 종료')
        return

    print(f'[diag] GAME_REGION: {m.GAME_REGION}')
    print('[diag] 3초 후 화면 캡처 — 캡차 띄워두기')
    time.sleep(3)
    screen = m.grab()
    print(f'[diag] screen shape: {screen.shape}')

    os.makedirs('captcha_recordings/debug', exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    screen_path = f'captcha_recordings/debug/diag_screen_{ts}.png'
    cv2.imwrite(screen_path, screen)
    print(f'[diag] 화면 저장: {screen_path}')

    print('\n[diag] template 매칭 score:')
    for path, tpl in templates:
        if screen.shape[0] < tpl.shape[0] or screen.shape[1] < tpl.shape[1]:
            print(f'  {path}: screen이 template보다 작음 (skip)')
            continue
        res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        # 매칭 위치 시각화
        vis = screen.copy()
        h, w = tpl.shape[:2]
        cv2.rectangle(vis, max_loc, (max_loc[0]+w, max_loc[1]+h), (0, 255, 0), 3)
        cv2.putText(vis, f'{os.path.basename(path)} {max_val:.3f}',
                    (max_loc[0], max_loc[1]-10), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 255, 0), 2)
        vis_path = f'captcha_recordings/debug/diag_match_{os.path.basename(path)}_{ts}.png'
        cv2.imwrite(vis_path, vis)
        print(f'  {os.path.basename(path)}: max_score={max_val:.3f} at {max_loc}, vis={vis_path}')

    print('\n[diag] 결과 해석:')
    print('  score >= 0.7 — 강한 매칭 (트리거 작동)')
    print('  0.4 ~ 0.7 — 약한 매칭 (threshold 낮춰서 잡힐 수도)')
    print('  < 0.4 — 매칭 안 됨 → template 다시 캡처 필요')


if __name__ == '__main__':
    main()
