"""투명도형찾기 캡차 자동 녹화 헬퍼.

매크로 실전에서 캡차 등장 시 mp4 자동 저장. 실전 데이터로 솔버 튜닝.

사용:
  import captcha_recorder
  captcha_recorder.record(grab_fn, game_region, duration_sec=20)
  # grab_fn() 결과(BGR ndarray)를 그대로 영상에 씀. 추가 crop 안 함.
  # game_region은 영상 크기 fallback용으로만 사용 (실제 크기는 첫 프레임 기준).
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
    """캡차 영상 녹화 — grab_fn() 결과(이미 게임 영역) 그대로 저장.

    인자:
      grab_fn: () → BGR np.ndarray (이미 게임 영역으로 잘라진 이미지)
      game_region: {'width', 'height'} — 첫 프레임 실패 시 영상 크기 fallback
      duration_sec: 최대 녹화 시간
      stop_check_fn: () → bool. True면 일찍 종료 (예: 캡차 풀렸음 감지)
      on_log: 로그 함수
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(OUTPUT_DIR, f'captcha_{ts}.mp4')

    # 첫 프레임으로 실제 크기 결정 (grab_fn이 주는 그대로)
    first = grab_fn()
    if first is None:
        H = int(game_region['height'])
        W = int(game_region['width'])
    else:
        H, W = first.shape[:2]

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
    if first is not None:
        out.write(first)
        n_frames += 1
    try:
        while time.time() - t0 < duration_sec:
            if stop_check_fn and stop_check_fn():
                on_log('[captcha-rec] stop_check_fn=True → 일찍 종료')
                break
            frame = grab_fn()
            if frame is None:
                time.sleep(0.05)
                continue
            # grab_fn()이 이미 game_region 영역만 반환하면 그대로 사용.
            # 전체 화면을 반환하면 game_region으로 crop. 어느 쪽도 아니면 resize fallback.
            if frame.shape[:2] != (H, W):
                if (frame.shape[0] >= game_region['top'] + H and
                        frame.shape[1] >= game_region['left'] + W):
                    x = game_region['left']
                    y = game_region['top']
                    frame = frame[y:y+H, x:x+W]
                else:
                    frame = cv2.resize(frame, (W, H))
            out.write(frame)
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


# 캡차 등장 트리거 — templates/invi_ready.png, invi_on.png 매칭
TRIGGER_TEMPLATES = [
    'templates/invi_ready.png',
    'templates/invi_on.png',
]
TRIGGER_MATCH_THRESH = 0.6  # 0.7→0.6 완화 (환경별 매칭 약할 수 있음)
TRIGGER_POLL_SEC = 0.3      # 0.5→0.3 더 자주 (캡차 짧게 떳다 사라지면 놓침)
COOLDOWN_AFTER_RECORD_SEC = 30
DEBUG_LOG_EVERY_N_POLLS = 20  # 매 N polling마다 max score 로그
DEBUG_SAVE_SCREENS_DIR = 'captcha_recordings/debug'


def _load_templates(paths):
    templates = []
    for p in paths:
        if not os.path.exists(p):
            print(f'[trigger] template 없음: {p}', flush=True)
            continue
        im = cv2.imread(p, cv2.IMREAD_COLOR)
        if im is None:
            print(f'[trigger] template 로드 실패: {p}', flush=True)
            continue
        templates.append((p, im))
        print(f'[trigger] loaded: {p} ({im.shape[1]}x{im.shape[0]})', flush=True)
    return templates


def _match_any(screen, templates, thresh, return_best=False):
    """screen에서 templates 매칭. thresh 이상이면 (path, score), 아니면 None.
    return_best=True면 thresh 무관 max score (path, score) 항상 리턴.
    """
    best_path, best_val = None, 0
    for path, tpl in templates:
        if screen.shape[0] < tpl.shape[0] or screen.shape[1] < tpl.shape[1]:
            continue
        try:
            res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val > best_val:
                best_val, best_path = max_val, path
        except Exception:
            continue
    if return_best:
        return (best_path, best_val) if best_path else None
    if best_val >= thresh:
        return best_path, best_val
    return None


def watch_and_record(grab_fn, game_region, *,
                     trigger_paths=None, match_thresh=TRIGGER_MATCH_THRESH,
                     poll_interval=TRIGGER_POLL_SEC,
                     duration_sec=DEFAULT_DURATION_SEC,
                     cooldown_sec=COOLDOWN_AFTER_RECORD_SEC,
                     on_log=print):
    """캡차 트리거 감지 → 자동 녹화 무한 루프.

    invi_ready 또는 invi_on 템플릿 매칭되면 즉시 녹화 시작.
    녹화 끝나면 cooldown_sec 동안 대기 후 다시 watch.
    """
    paths = trigger_paths or TRIGGER_TEMPLATES
    templates = _load_templates(paths)
    if not templates:
        on_log('[watch] 트리거 템플릿 없음 — 종료')
        return
    on_log(f'[watch] 감시 시작 ({len(templates)} 템플릿, thresh={match_thresh}, poll={poll_interval}s)')
    os.makedirs(DEBUG_SAVE_SCREENS_DIR, exist_ok=True)
    poll_n = 0
    max_seen = {p: 0 for p, _ in templates}
    while True:
        screen = grab_fn()
        if screen is None:
            time.sleep(poll_interval)
            continue
        poll_n += 1
        # 항상 max score 추적 — 디버그용
        best = _match_any(screen, templates, match_thresh=0, return_best=True)
        if best:
            p, s = best
            if s > max_seen.get(p, 0):
                max_seen[p] = s
        # 매칭 성공 (thresh 이상)
        m = _match_any(screen, templates, match_thresh)
        # 주기적 디버그 로그
        if poll_n % DEBUG_LOG_EVERY_N_POLLS == 0:
            stats = ', '.join(f'{os.path.basename(p)}:{v:.2f}' for p, v in max_seen.items())
            on_log(f'[debug] poll#{poll_n} max_seen={stats}, current_max={best[1]:.2f if best else 0}')
        if m:
            path, score = m
            on_log(f'[trigger] {path} 매칭 (score={score:.3f}) → 녹화 시작')
            # 트리거 시점 화면도 저장 (분석용)
            try:
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                cv2.imwrite(os.path.join(DEBUG_SAVE_SCREENS_DIR, f'trigger_{ts}.png'), screen)
            except Exception:
                pass
            try:
                winsound = __import__('winsound')
                winsound.Beep(1500, 100)
            except Exception:
                pass
            out_path = record(grab_fn, game_region, duration_sec=duration_sec, on_log=on_log)
            on_log(f'[watch] 녹화 완료, {cooldown_sec}s 쿨다운')
            max_seen = {p: 0 for p, _ in templates}  # 쿨다운 후 통계 리셋
            time.sleep(cooldown_sec)
        else:
            time.sleep(poll_interval)


if __name__ == '__main__':
    # 단독 실행 — 매크로 환경의 grab/GAME_REGION 사용해서 트리거 감시 + 자동 녹화
    import macro_red as m
    print('[recorder] 매크로 환경 watch 시작 — 캡차 등장 시 자동 녹화')
    print(f'[recorder] GAME_REGION: {m.GAME_REGION}')
    print(f'[recorder] 출력 폴더: {os.path.abspath(OUTPUT_DIR)}')
    watch_and_record(m.grab, m.GAME_REGION)
