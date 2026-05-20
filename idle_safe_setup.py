"""잠수 안전 한계 측정 — 캐릭이 떨어지면 안 되는 mm_x 범위를 찍어 저장.

사용:
  1) 게임 켠 상태로 python idle_safe_setup.py
  2) 먼저 뜨는 미니맵 셋업 GUI: 드래그=영역, 클릭=캐릭 색, s=저장, q=취소(기존 설정 유지)
  3) 캐릭을 왼쪽 한계(이보다 더 왼쪽 가면 떨어짐) 자리로 옮기고 F1
  4) 오른쪽 한계 자리로 옮기고 F2
  5) F5 저장 → idle_safe_config.json 생성
  6) F12 종료

콘솔에 0.3초마다 현재 mm 좌표 출력. F1/F2 누르면 그 시점 mm_x를 기록.
"""
import json
import os
import subprocess
import sys
import time

import cv2
import keyboard
import mss
import numpy as np

import macro_red as m

CONFIG_PATH = 'idle_safe_config.json'


def _grab():
    """m.GAME_REGION 기준 캡처. mss 검정이면 PIL ImageGrab으로 fallback."""
    try:
        with mss.mss() as sct:
            raw = np.array(sct.grab(m.GAME_REGION))
        img = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        if float(img.mean()) >= 8:
            return img
    except Exception:
        img = None
    try:
        from PIL import ImageGrab
        r = m.GAME_REGION
        bbox = (r['left'], r['top'], r['left'] + r['width'], r['top'] + r['height'])
        pil_img = ImageGrab.grab(bbox=bbox, all_screens=True)
        arr = np.array(pil_img)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:
        return img if img is not None else np.zeros((100, 100, 3), dtype=np.uint8)


def _run_minimap_setup() -> None:
    """미니맵 셋업 GUI 실행 — 매번 환경 변화 대응."""
    here = os.path.dirname(os.path.abspath(__file__))
    setup_path = os.path.join(here, 'minimap_setup_red.py')
    if not os.path.exists(setup_path):
        print(f'[setup] {setup_path} 없음 — 건너뜀')
        return
    print('[setup] 미니맵 셋업 GUI 실행 — 드래그=영역, 클릭=캐릭 색, s=저장, q=취소(기존 설정 유지)')
    try:
        subprocess.run([sys.executable, setup_path], check=False)
    except Exception as e:
        print(f'[setup] 실행 실패: {e}')


def _reload_minimap_cfg() -> bool:
    path = m.MINIMAP_CONFIG_PATH
    if not os.path.exists(path):
        return False
    with open(path, encoding='utf-8') as f:
        m.MINIMAP_CFG = json.load(f)
    rect = m.MINIMAP_CFG.get('minimap_rect')
    color = m.MINIMAP_CFG.get('char_color_bgr')
    print(f'[setup] 미니맵 설정 로드: rect={rect}  color={color}')
    return True

state = {
    'left':  None,
    'right': None,
    'save_request': False,
    'quit': False,
}


def _mark_left():
    pos = m.find_char_minimap_pos(_grab())
    if pos is None:
        print('[!] mm 검출 실패 — 잠시 후 다시 시도')
        return
    state['left'] = int(pos[0])
    print(f'[F1] 좌측 한계 mm_x = {state["left"]}')


def _mark_right():
    pos = m.find_char_minimap_pos(_grab())
    if pos is None:
        print('[!] mm 검출 실패 — 잠시 후 다시 시도')
        return
    state['right'] = int(pos[0])
    print(f'[F2] 우측 한계 mm_x = {state["right"]}')


def _request_save():
    state['save_request'] = True


def _request_quit():
    state['quit'] = True


def _save():
    if state['left'] is None or state['right'] is None:
        print('[!] 좌/우 둘 다 찍어야 저장됨 (F1, F2)')
        return False
    a, b = state['left'], state['right']
    cfg = {
        'safe_mm_x_min': min(a, b),
        'safe_mm_x_max': max(a, b),
        # 환경 변경 감지용 — 측정 당시 미니맵 영역. 다음 실행 시 미니맵이 다르면 재측정 트리거
        'cal_minimap_rect':  list(m.MINIMAP_CFG.get('minimap_rect', [])),
        'cal_game_width':    m.GAME_REGION.get('width'),
        'cal_game_height':   m.GAME_REGION.get('height'),
    }
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
    print(f'[F5] 저장: {CONFIG_PATH} → {cfg}')
    return True


def main():
    keyboard.add_hotkey('f1', _mark_left)
    keyboard.add_hotkey('f2', _mark_right)
    keyboard.add_hotkey('f5', _request_save)
    keyboard.add_hotkey('f12', _request_quit)

    print('=' * 60)
    print('  잠수 안전 한계 측정')
    print('=' * 60)

    # 매 실행마다 미니맵 재캡처 — 해상도/창 위치 매번 달라질 수 있음
    _run_minimap_setup()
    if not _reload_minimap_cfg():
        print(f'[!] {m.MINIMAP_CONFIG_PATH} 없음 — 셋업에서 저장(s) 안 함, 종료')
        return
    if not m.refresh_game_region():
        print('[!] 게임창 못 찾음 — 종료')
        return
    print(f'  게임 영역: {m.GAME_REGION}')
    print('  F1=좌측 한계, F2=우측 한계, F5=저장, F12=종료')
    print('  캐릭 옮기면 mm 좌표가 0.3초마다 출력됩니다.')
    print()

    last_msg = None
    while not state['quit']:
        if state['save_request']:
            state['save_request'] = False
            _save()

        screen = _grab()
        pos = m.find_char_minimap_pos(screen)
        if pos is None:
            msg = 'mm = (검출 실패)'
        else:
            msg = (f'mm = ({pos[0]:>4}, {pos[1]:>4})  '
                   f'L={state["left"]}  R={state["right"]}')
        if msg != last_msg:
            print(msg, flush=True)
            last_msg = msg
        time.sleep(0.3)

    print('\n종료')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n인터럽트 → 종료')
