"""투명도형찾기 캡차 자동 녹화 헬퍼.

매크로 실전에서 캡차 등장 시 mp4 자동 저장. 실전 데이터로 솔버 튜닝.

사용:
  import captcha_recorder
  captcha_recorder.record(grab_fn, game_region, duration_sec=20)
"""

import os
import sys
import time
import threading
import ctypes
from datetime import datetime

import cv2
import numpy as np


# Per-Monitor v2 DPI awareness (듀얼/세로/고DPI 환경 대응)
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


OUTPUT_DIR = 'captcha_recordings'
DEFAULT_DURATION_SEC = 25  # 캡차 길이 (카운트다운 5 + 추적 10~15 + 여유)
DEFAULT_FPS = 30


def record(grab_fn, game_region, *, duration_sec=DEFAULT_DURATION_SEC,
           fps=DEFAULT_FPS, stop_check_fn=None, on_log=print):
    """캡차 영상 녹화. 게임 영역만 캡처 → mp4 저장.

    인자:
      grab_fn: () → BGR np.ndarray (전체 화면 또는 게임 영역)
      game_region: {'left', 'top', 'width', 'height'}
      duration_sec: 최대 녹화 시간
      stop_check_fn: () → bool. True면 일찍 종료 (예: 캡차 풀렸음 감지)
      on_log: 로그 함수
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(OUTPUT_DIR, f'captcha_{ts}.mp4')

    W = int(game_region['width'])
    H = int(game_region['height'])
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(out_path, fourcc, fps, (W, H))
    if not out.isOpened():
        on_log(f'[captcha-rec] VideoWriter 실패: {out_path}')
        return None

    on_log(f'[captcha-rec] 녹화 시작 → {out_path} ({W}x{H} @ {fps}fps)')
    t0 = time.time()
    frame_interval = 1.0 / fps
    next_t = t0
    n_frames = 0
    try:
        while time.time() - t0 < duration_sec:
            if stop_check_fn and stop_check_fn():
                on_log('[captcha-rec] stop_check_fn=True → 일찍 종료')
                break
            screen = grab_fn()
            if screen is None:
                time.sleep(0.05)
                continue
            # game_region 안에서만 crop
            x = game_region['left']
            y = game_region['top']
            crop = screen[y:y+H, x:x+W]
            if crop.shape[:2] != (H, W):
                crop = cv2.resize(crop, (W, H))
            out.write(crop)
            n_frames += 1
            next_t += frame_interval
            sleep_time = next_t - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)
    finally:
        out.release()
    on_log(f'[captcha-rec] 녹화 종료: {n_frames} frames, '
           f'{time.time()-t0:.1f}s → {out_path}')
    return out_path


def record_background(grab_fn, game_region, **kwargs):
    """별도 thread로 녹화 (매크로 메인 흐름 차단 X).

    리턴: thread object. 사용자가 join 가능.
    """
    t = threading.Thread(target=record, args=(grab_fn, game_region),
                         kwargs=kwargs, daemon=True)
    t.start()
    return t


if __name__ == '__main__':
    # 단독 실행 — macro_red.GAME_REGION/grab 사용해서 즉시 녹화
    import macro_red as m
    print('[test] 3초 후 녹화 시작 — 캡차 띄워두기')
    time.sleep(3)
    out_path = record(m.grab, m.GAME_REGION, duration_sec=20)
    print(f'[test] 저장: {out_path}')
