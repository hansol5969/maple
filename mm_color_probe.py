"""미니맵 색 픽업 + 매크로 감지 범위 시각화.

본인/파티원/타 유저의 실제 hue 값을 확인하고, idle_buff.py의 감지 범위를
미니맵 위에 직접 그려서 확인할 수 있는 도구.

오버레이:
  - 노랑 십자  = 본인 (find_char_minimap_pos 결과)
  - 초록 원    = PARTY_NEAR_RADIUS — 이 반경 안에 주황 들어오면 버프 시전
  - 초록 다이아 = 주황 blob 중 범위 안 (시전 트리거)
  - 회색 다이아 = 주황 blob 범위 밖
  - 파랑 세로선 = safe_mm_x_min/max (idle_safe_config.json) — 왕복 한계

사용:
  1) 게임 켜고 python mm_color_probe.py
  2) 미니맵 셋업 GUI: 영역 드래그 + 캐릭 클릭 → s 저장 (또는 q로 기존 설정 유지)
  3) 미니맵 창: 좌클릭 = 픽셀 BGR/HSV 출력  /  q = 종료
"""
import json
import os
import subprocess
import sys

import cv2
import mss
import numpy as np

import macro_red as m
import idle_buff  # 매크로의 PARTY_NEAR_RADIUS, PARTY_HUE_RANGE 등 직접 참조


WINDOW = 'mm_color_probe'
ZOOM = 2              # 미니맵 확대 배율 — 너무 크면 모니터 폭 초과
REFRESH_HZ = 5        # 미니맵 업데이트 주기


_click = {'xy': None}  # 미니맵 로컬 좌표


def _run_minimap_setup() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    setup_path = os.path.join(here, 'minimap_setup_red.py')
    if not os.path.exists(setup_path):
        return
    print('[setup] 미니맵 셋업 GUI 실행 — s 저장 / q 취소(기존 설정 유지)')
    try:
        subprocess.run([sys.executable, setup_path], check=False)
    except Exception as e:
        print(f'[setup] 실행 실패: {e}')


def _reload_cfg() -> bool:
    path = m.MINIMAP_CONFIG_PATH
    if not os.path.exists(path):
        return False
    with open(path, encoding='utf-8') as f:
        m.MINIMAP_CFG = json.load(f)
    return True


def _grab_with_fallback():
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


def _on_mouse(event, x, y, flags, _):
    if event != cv2.EVENT_LBUTTONDOWN:
        return
    _click['xy'] = (x // ZOOM, y // ZOOM)


def _detect_party_blobs(mm):
    """mm 영역에서 idle_buff.PARTY_HUE_RANGE에 맞는 blob 위치 리스트 반환.
    각 항목: (mm_x, mm_y, area)."""
    hsv = cv2.cvtColor(mm, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lo, hi = idle_buff.PARTY_HUE_RANGE
    mask = ((h >= lo) & (h <= hi)
            & (s >= idle_buff.PARTY_S_MIN)
            & (v >= idle_buff.PARTY_V_MIN)).astype(np.uint8) * 255
    n, _l, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < idle_buff.PARTY_BLOB_AREA_MIN:
            continue
        cx, cy = cents[i]
        out.append((int(cx), int(cy), area))
    return out


def main():
    print('=' * 60)
    print('  미니맵 색 픽업')
    print('=' * 60)

    _run_minimap_setup()
    if not _reload_cfg():
        print(f'[!] {m.MINIMAP_CONFIG_PATH} 없음 — 종료')
        return
    if not m.refresh_game_region():
        print('[!] 게임창 못 찾음 — 종료')
        return

    rect = m.MINIMAP_CFG['minimap_rect']
    print(f'  미니맵 영역: {rect}')
    print(f'  게임 영역: {m.GAME_REGION}')
    print(f'  좌클릭 = 픽셀 BGR/HSV 출력  /  q = 종료')
    print()

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, _on_mouse)
    try:
        cv2.setWindowProperty(WINDOW, cv2.WND_PROP_TOPMOST, 1)
    except cv2.error:
        pass
    # cv2 창을 미니맵 영역 바깥(미니맵 바로 아래)으로 — 자기 자신 캡처(거울 효과) 방지
    try:
        gx = int(m.GAME_REGION.get('left', 0)) + rect[0]
        gy = int(m.GAME_REGION.get('top', 0)) + rect[3] + 30
        cv2.moveWindow(WINDOW, gx, gy)
    except (cv2.error, AttributeError, TypeError):
        pass

    # 안전 한계 로드 (있으면)
    safe_min, safe_max = None, None
    safe_path = 'idle_safe_config.json'
    if os.path.exists(safe_path):
        try:
            with open(safe_path, encoding='utf-8') as f:
                sc = json.load(f)
            safe_min = int(sc.get('safe_mm_x_min'))
            safe_max = int(sc.get('safe_mm_x_max'))
            print(f'  안전 한계 로드: mm_x ∈ [{safe_min}, {safe_max}]')
        except Exception as e:
            print(f'  [!] {safe_path} 읽기 실패: {e}')

    print(f'  PARTY_NEAR_RADIUS={idle_buff.PARTY_NEAR_RADIUS}  '
          f'PARTY_HUE_RANGE={idle_buff.PARTY_HUE_RANGE}')
    print()

    delay = max(1, int(1000 / REFRESH_HZ))
    try:
        while True:
            screen = _grab_with_fallback()
            x1, y1, x2, y2 = rect
            mm = screen[y1:y2, x1:x2].copy()

            # 클릭 처리 (mm 원본 좌표)
            if _click['xy'] is not None:
                mx, my = _click['xy']
                _click['xy'] = None
                if 0 <= mx < mm.shape[1] and 0 <= my < mm.shape[0]:
                    bgr = mm[my, mx]
                    hsv_pix = cv2.cvtColor(
                        np.uint8([[bgr]]), cv2.COLOR_BGR2HSV)[0, 0]
                    b, g, r = int(bgr[0]), int(bgr[1]), int(bgr[2])
                    H, S, V = int(hsv_pix[0]), int(hsv_pix[1]), int(hsv_pix[2])
                    label = _hue_label(H, S, V)
                    print(f'  mm=({mx:>3},{my:>3})  '
                          f'BGR=({b:>3},{g:>3},{r:>3})  '
                          f'HSV=(H={H:>3}, S={S:>3}, V={V:>3})  → {label}',
                          flush=True)

            # 본인 위치 + 주황 blob 감지 (mm 좌표계)
            # screen 전체 좌표 기반 함수 → screen 넘기되 mm 좌표로 환산
            my_pos_full = m.find_char_minimap_pos(screen)
            my_pos = my_pos_full  # find_char_minimap_pos은 이미 mm 로컬 좌표 반환

            party_blobs = _detect_party_blobs(mm)

            # 오버레이 — 확대 후 그리는 게 깔끔
            zoomed = cv2.resize(mm,
                                (mm.shape[1] * ZOOM, mm.shape[0] * ZOOM),
                                interpolation=cv2.INTER_NEAREST)

            # 안전 한계 세로선
            if safe_min is not None:
                cv2.line(zoomed, (safe_min * ZOOM, 0),
                         (safe_min * ZOOM, zoomed.shape[0]),
                         (255, 80, 0), 1)
            if safe_max is not None:
                cv2.line(zoomed, (safe_max * ZOOM, 0),
                         (safe_max * ZOOM, zoomed.shape[0]),
                         (255, 80, 0), 1)

            # 본인 + PARTY_NEAR_RADIUS 원
            if my_pos is not None:
                mx, my = my_pos
                cv2.circle(zoomed, (mx * ZOOM, my * ZOOM),
                           idle_buff.PARTY_NEAR_RADIUS * ZOOM,
                           (0, 255, 0), 1)
                cv2.drawMarker(zoomed, (mx * ZOOM, my * ZOOM),
                               (0, 255, 255), cv2.MARKER_CROSS, 14, 2)

            # 주황 blob 마커 (범위 안 = 초록, 밖 = 회색)
            r2 = idle_buff.PARTY_NEAR_RADIUS ** 2
            for (cx, cy, area) in party_blobs:
                in_range = (my_pos is not None and
                            (cx - my_pos[0]) ** 2 + (cy - my_pos[1]) ** 2 <= r2)
                col = (0, 255, 0) if in_range else (180, 180, 180)
                cv2.drawMarker(zoomed, (cx * ZOOM, cy * ZOOM),
                               col, cv2.MARKER_DIAMOND, 10, 2)

            # 클릭 표시 (지속)
            cv2.imshow(WINDOW, zoomed)

            try:
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                break

            k = cv2.waitKey(delay) & 0xFF
            if k in (27, ord('q')):
                break
    finally:
        cv2.destroyAllWindows()
        for _ in range(3):
            cv2.waitKey(1)


def _hue_label(h: int, s: int, v: int) -> str:
    """대략 어떤 색인지 한 줄 라벨 — 매크로 hue 범위 튜닝 도와주기 위한 힌트."""
    if s < 60 or v < 60:
        return '회색/배경'
    if h <= 7 or h >= 170:
        return '빨강 (타 유저)'
    if 8 <= h <= 20:
        return '주황 (파티원)'
    if 21 <= h <= 34:
        return '노랑 (본인)'
    if 35 <= h <= 80:
        return '초록'
    if 81 <= h <= 130:
        return '파랑/하늘'
    return f'기타 (h={h})'


if __name__ == '__main__':
    main()
