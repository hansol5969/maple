"""자동 상점 좌표 캘리브레이션.

순서:
  1) 게임에서 인벤(I 키) 열고 → '캐시' 탭으로 이동 → 휴대용 상점 더블클릭 → 상점 UI 열림
  2) python shop_coords_setup.py
  3) 3초 후 캡처. 캡처된 화면에서 안내에 따라 각 좌표 클릭
  4) s = 저장 (shop_coords.json) / r = 재캡처 / 스페이스 = 스킵 / q = 종료

저장 후 macro_red.py가 import 시 shop_coords.json을 자동 로드해 좌표 override.
"""
import json
import os
import time

import cv2
import mss
import numpy as np

import macro_red as m

CONFIG_PATH = 'shop_coords.json'
WINDOW = 'shop_coords_setup'

# (key, label) 순서 — 좌클릭으로 차례로 측정
STEPS = [
    ('cash_tab',         '캐시 탭 (인벤 안 탭 라벨)'),
    ('portable_shop',    '휴대용 상점 (캐시 탭 안)'),
    ('shop_first_slot',  '상점 첫 칸 (상점 UI 좌상단 슬롯)'),
    ('sell_all_button',  '일괄 판매 버튼'),
    ('shop_close',       '상점 닫기 X 버튼'),
    ('equip_tab',        '장비 탭 (인벤 안 탭 라벨)'),
    ('etc_tab',          '기타 탭 (인벤 안 탭 라벨)'),
    ('etc_sell_slot',    '기타 판매 슬롯 (상점 UI 안 기타용 슬롯 — 한 번 클릭으로 선택)'),
    ('etc_sell_button',  '기타템 판매 버튼 (슬롯 옆 판매 버튼)'),
    ('etc_check_slot',   '기타 인벤 첫 칸 (기타 탭 좌상단 슬롯)'),
    ('inv_first_slot',   '장비 인벤 첫 칸'),
    ('inv_trigger_tl',   'INV 트리거 영역 좌상단 (인벤 우하단 아이콘 영역)'),
    ('inv_trigger_br',   'INV 트리거 영역 우하단'),
]

state = {
    'screen': None,
    'scale': 1.0,
    'idx': 0,
    'coords': {},
}


def _grab():
    """mss → PIL fallback."""
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


def _capture_with_countdown():
    print('3초 후 캡처 — 게임 창 클릭해 포커스 주세요')
    for i in range(3, 0, -1):
        print(f'  {i}...', flush=True)
        time.sleep(1)
    img = _grab()
    h, w = img.shape[:2]
    state['screen'] = img
    state['scale'] = min(1600 / w, 900 / h, 1.0)
    print(f'캡처 완료: {w}x{h}, 평균 밝기 {img.mean():.1f}, 디스플레이 축소 {state["scale"]:.2f}')


def _disp_to_abs(mx, my):
    s = state['scale']
    img_x = int(mx / s)
    img_y = int(my / s)
    return (m.GAME_REGION['left'] + img_x,
            m.GAME_REGION['top'] + img_y)


def _on_mouse(event, mx, my, flags, _):
    if event != cv2.EVENT_LBUTTONDOWN:
        return
    if state['idx'] >= len(STEPS):
        print('  모든 좌표 측정 완료 — s 키로 저장')
        return
    key, label = STEPS[state['idx']]
    abs_xy = _disp_to_abs(mx, my)
    state['coords'][key] = abs_xy
    print(f'  [{state["idx"]+1}/{len(STEPS)}] {label}: {abs_xy}')
    state['idx'] += 1
    if state['idx'] < len(STEPS):
        print(f'  → 다음: {STEPS[state["idx"]][1]}')
    else:
        print('  ✓ 전부 측정됨 — s 키로 저장')


def _render():
    vis = state['screen'].copy()
    for key, (ax, ay) in state['coords'].items():
        gx = ax - m.GAME_REGION['left']
        gy = ay - m.GAME_REGION['top']
        cv2.circle(vis, (gx, gy), 8, (0, 255, 0), 2)
        cv2.putText(vis, key, (gx + 12, gy - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    # 상단 상태 바
    if state['idx'] < len(STEPS):
        bar = f'{state["idx"]+1}/{len(STEPS)}: {STEPS[state["idx"]][1]}'
    else:
        bar = '완료 — s 키로 저장'
    h_, w_ = vis.shape[:2]
    cv2.rectangle(vis, (0, 0), (w_, 30), (0, 0, 0), -1)
    cv2.putText(vis, bar, (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (255, 255, 255), 1)
    s = state['scale']
    if s < 1.0:
        vis = cv2.resize(vis, (int(w_ * s), int(h_ * s)),
                         interpolation=cv2.INTER_AREA)
    return vis


def _save():
    if not state['coords']:
        print('[!] 측정된 좌표 없음')
        return False
    out = {
        'cal_game_left':   m.GAME_REGION['left'],
        'cal_game_top':    m.GAME_REGION['top'],
        'cal_game_width':  m.GAME_REGION['width'],
        'cal_game_height': m.GAME_REGION['height'],
    }
    for k, v in state['coords'].items():
        out[k] = list(v)
    # INV_TRIGGER 좌상단/우하단 → 영역 [x1,y1,x2,y2]
    if 'inv_trigger_tl' in out and 'inv_trigger_br' in out:
        tl = out.pop('inv_trigger_tl')
        br = out.pop('inv_trigger_br')
        out['inv_trigger'] = [min(tl[0], br[0]), min(tl[1], br[1]),
                              max(tl[0], br[0]), max(tl[1], br[1])]
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f'\n저장: {CONFIG_PATH}')
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return True


def main():
    print('=' * 60)
    print('  자동 상점 좌표 캘리브레이션')
    print('=' * 60)
    print('  게임에서 인벤(I) → 캐시 탭 → 휴대용 상점 더블클릭으로 상점 UI 띄운 상태에서 실행')
    print('  좌클릭 = 다음 좌표,  space = 스킵,  r = 재캡처,  s = 저장,  q = 종료')
    print()

    if not m.refresh_game_region():
        print('[!] 게임창 못 찾음 — 종료')
        return
    print(f'게임 영역: {m.GAME_REGION}')

    _capture_with_countdown()

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, _on_mouse)
    try:
        cv2.setWindowProperty(WINDOW, cv2.WND_PROP_TOPMOST, 1)
    except cv2.error:
        pass
    try:
        cv2.moveWindow(WINDOW, 30, 30)
    except cv2.error:
        pass

    print(f'\n  → 1/{len(STEPS)}: {STEPS[0][1]}')

    try:
        while True:
            cv2.imshow(WINDOW, _render())
            k = cv2.waitKey(30) & 0xFF
            try:
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                break
            if k in (27, ord('q')):
                print('종료 (저장 안 함)')
                break
            if k == ord('s'):
                if _save():
                    break
            if k == ord('r'):
                _capture_with_countdown()
                state['coords'].clear()
                state['idx'] = 0
                print(f'재캡처 → 1/{len(STEPS)}: {STEPS[0][1]}')
            if k == ord(' '):
                if state['idx'] < len(STEPS):
                    key, label = STEPS[state['idx']]
                    print(f'  [{state["idx"]+1}/{len(STEPS)}] {label}: 스킵 (기존값 유지)')
                    state['idx'] += 1
                    if state['idx'] < len(STEPS):
                        print(f'  → 다음: {STEPS[state["idx"]][1]}')
    finally:
        cv2.destroyAllWindows()
        for _ in range(3):
            cv2.waitKey(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n인터럽트 → 종료')
