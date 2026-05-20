"""거짓말 탐지기 템플릿 재캡처 — templates/lie_title.png 갱신.

매크로가 lie 팝업을 인식 못할 때 사용. 사용자 환경(해상도/UI)에 맞춰 템플릿을 새로 잡음.

== 권장 흐름 (lie가 언제 뜰지 모를 때) ==
  1) idle_buff.py 돌리는 중에 거짓말 탐지기가 떴는데 매크로가 못 잡음
  2) 그 순간 F11 한 번 누름 → lie_snapshot.png 가 자동 저장됨
  3) 거짓말 탐지기는 수동으로 풀고 매크로 계속 진행
  4) 나중에 python lie_template_capture.py 실행 → 스냅샷에서 영역만 드래그로 잘라내기
  5) 다음 idle_buff 실행부터 새 템플릿으로 매칭

== 즉석 캡처 (lie가 지금 떠 있을 때) ==
  1) 게임에 lie 팝업이 떠있는 상태로 python lie_template_capture.py
  2) 스냅샷 없으면 3초 카운트다운 후 실시간 캡처

키: s = 저장 / r = 재캡처(실시간) / q = 종료

팁: 작은 영역일수록 매칭 빠르고 신뢰성 높음. 변하지 않는 텍스트 부분 위주로.
"""
import os
import time

import cv2
import mss
import numpy as np

import macro_red as m

TEMPLATE_PATH = 'templates/lie_title.png'
SNAPSHOT_PATH = 'lie_snapshot.png'   # idle_buff에서 F11로 저장된 화면
WINDOW        = 'lie_template_capture'

state = {
    'screen':    None,
    'scale':     1.0,
    'sel_start': None,
    'sel_end':   None,
    'dragging':  False,
}


def _grab():
    try:
        with mss.mss() as sct:
            raw = np.array(sct.grab(m.GAME_REGION))
        img = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        if float(img.mean()) >= 8:
            return img
    except Exception:
        pass
    from PIL import ImageGrab
    r = m.GAME_REGION
    bbox = (r['left'], r['top'], r['left'] + r['width'], r['top'] + r['height'])
    return cv2.cvtColor(np.array(ImageGrab.grab(bbox=bbox, all_screens=True)), cv2.COLOR_RGB2BGR)


def _load_image(img, source: str):
    h, w = img.shape[:2]
    state['screen'] = img
    state['scale']  = min(1600 / w, 900 / h, 1.0)
    state['sel_start'] = None
    state['sel_end']   = None
    state['dragging']  = False
    print(f'[{source}] {w}x{h}, 평균 밝기 {img.mean():.1f}, 디스플레이 축소 {state["scale"]:.2f}')


def _capture_with_countdown():
    print('3초 후 실시간 캡처 — 게임 창 클릭해 포커스 주세요 (거짓말 탐지기 팝업이 보여야 함)')
    for i in range(3, 0, -1):
        print(f'  {i}...', flush=True)
        time.sleep(1)
    _load_image(_grab(), '실시간 캡처')


def _load_snapshot() -> bool:
    """저장된 lie_snapshot.png 가 있으면 로드. 성공 시 True."""
    if not os.path.exists(SNAPSHOT_PATH):
        return False
    img = cv2.imread(SNAPSHOT_PATH)
    if img is None:
        print(f'[!] {SNAPSHOT_PATH} 읽기 실패 — 실시간 캡처로 대체')
        return False
    _load_image(img, f'스냅샷 {SNAPSHOT_PATH}')
    return True


def _disp_to_img(mx, my):
    s = state['scale']
    return int(mx / s), int(my / s)


def _on_mouse(event, mx, my, flags, _):
    if event == cv2.EVENT_LBUTTONDOWN:
        state['sel_start'] = _disp_to_img(mx, my)
        state['sel_end']   = state['sel_start']
        state['dragging']  = True
    elif event == cv2.EVENT_MOUSEMOVE and state['dragging']:
        state['sel_end'] = _disp_to_img(mx, my)
    elif event == cv2.EVENT_LBUTTONUP:
        state['sel_end']  = _disp_to_img(mx, my)
        state['dragging'] = False
        if state['sel_start'] and state['sel_end']:
            x1, y1 = state['sel_start']
            x2, y2 = state['sel_end']
            x1, x2 = sorted((x1, x2))
            y1, y2 = sorted((y1, y2))
            print(f'  선택: ({x1},{y1}) ~ ({x2},{y2})  크기 {x2-x1}x{y2-y1}px')


def _selection_box():
    if not state['sel_start'] or not state['sel_end']:
        return None
    x1, y1 = state['sel_start']
    x2, y2 = state['sel_end']
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    return x1, y1, x2, y2


def _render():
    vis = state['screen'].copy()
    box = _selection_box()
    if box is not None:
        x1, y1, x2, y2 = box
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 3)
    # 상단 상태 바
    bar = 's=저장  r=재캡처  q=종료    (변하지 않는 작은 영역을 드래그)'
    h_, w_ = vis.shape[:2]
    cv2.rectangle(vis, (0, 0), (w_, 36), (0, 0, 0), -1)
    cv2.putText(vis, bar, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    s = state['scale']
    if s < 1.0:
        vis = cv2.resize(vis, (int(w_ * s), int(h_ * s)), interpolation=cv2.INTER_AREA)
    return vis


def _save():
    box = _selection_box()
    if box is None:
        print('[!] 영역을 먼저 드래그하세요')
        return False
    x1, y1, x2, y2 = box
    if x2 - x1 < 10 or y2 - y1 < 10:
        print(f'[!] 영역이 너무 작음 ({x2-x1}x{y2-y1}) — 다시 드래그')
        return False
    crop = state['screen'][y1:y2, x1:x2]
    os.makedirs(os.path.dirname(TEMPLATE_PATH) or '.', exist_ok=True)
    cv2.imwrite(TEMPLATE_PATH, crop)
    print(f'\n저장: {TEMPLATE_PATH}  ({crop.shape[1]}x{crop.shape[0]}px)')
    print(f'이제 macro_red / idle_buff 다시 실행하면 새 템플릿으로 매칭합니다.')
    return True


def main():
    print('=' * 60)
    print('  거짓말 탐지기 템플릿 재캡처')
    print('=' * 60)
    print(f'  저장 경로: {TEMPLATE_PATH}')
    print('  사전 조건: 게임에 거짓말 탐지기 팝업이 떠 있어야 함')
    print()

    # 스냅샷 우선 — idle_buff에서 F11로 저장된 화면이 있으면 그걸 사용
    used_snapshot = _load_snapshot()
    if not used_snapshot:
        if not m.refresh_game_region():
            print('[!] 게임창 못 찾음 — 종료')
            return
        print(f'게임 영역: {m.GAME_REGION}')
        _capture_with_countdown()
    else:
        print(f'  (실시간 캡처로 전환하려면 r 키. 이 도구 끝나면 {SNAPSHOT_PATH} 삭제 권장)')

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
            if k == ord('r'):
                _capture_with_countdown()
            if k == ord('s'):
                if _save():
                    break
    finally:
        cv2.destroyAllWindows()
        for _ in range(3):
            cv2.waitKey(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n인터럽트 → 종료')
