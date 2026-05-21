"""투명도형찾기 캡차 수동 녹화 — Ctrl+F11 핫키.

매크로 자동 감지(invi_ready 매칭) 실패한 PC에서 사용. 단독 실행해두고
캡차 뜨는 순간 Ctrl+F11 누르면 녹화 시작.

사용:
  python record_captcha_now.py
  python record_captcha_now.py --duration 30
  python record_captcha_now.py --region monitor   # 모니터 전체
  python record_captcha_now.py --title "MapleStory Worlds"

조작:
  Ctrl+F11 = 녹화 시작 (이미 녹화 중이면 무시)
  Ctrl+F12 또는 Ctrl+C = 프로그램 종료
"""

import os
import sys
import time
import argparse
import ctypes
import threading
import ctypes.wintypes as wt
from datetime import datetime

import cv2
import numpy as np
import mss


# Per-Monitor v2 DPI awareness (듀얼/세로/고DPI 환경 대응)
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


GAME_WINDOW_TITLE_DEFAULT = 'MapleStory Worlds'
OUTPUT_DIR = 'captcha_recordings'

_WM_HOTKEY     = 0x0312
_MOD_CONTROL   = 0x0002
_VK_F11        = 0x7A
_VK_F12        = 0x7B
_HKID_REC      = 1
_HKID_QUIT     = 2

_exit_flag = threading.Event()
_rec_lock  = threading.Lock()
_rec_active = False


def find_game_region(title_keyword: str):
    """게임창 좌표 찾기 — pygetwindow 없으면 None."""
    try:
        import pygetwindow as gw
    except ImportError:
        return None
    try:
        wins = [w for w in gw.getAllWindows()
                if title_keyword.lower() in (w.title or '').lower()
                and w.width > 100 and w.height > 100]
        if not wins:
            return None
        w = wins[0]
        return {'left': w.left, 'top': w.top, 'width': w.width, 'height': w.height}
    except Exception:
        return None


def grab(sct, region):
    """region을 BGR로 잡기. mss 검은 이미지 시 PIL fallback."""
    bgr = None
    try:
        raw = np.array(sct.grab(region))
        bgr = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        if float(bgr.mean()) >= 8:
            return bgr
    except Exception:
        pass
    try:
        from PIL import ImageGrab
        bbox = (region['left'], region['top'],
                region['left'] + region['width'],
                region['top'] + region['height'])
        pil_img = ImageGrab.grab(bbox=bbox, all_screens=True)
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception:
        return bgr


def do_record(region, fps, duration):
    """녹화 1회 실행 — 별도 thread에서 호출."""
    global _rec_active
    with _rec_lock:
        if _rec_active:
            print('\n[REC] 이미 녹화 중 — 새 녹화 무시', flush=True)
            return
        _rec_active = True

    try:
        sct = mss.MSS()  # thread-local
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        out_path = os.path.join(OUTPUT_DIR, f'captcha_manual_{ts}.mp4')

        W = int(region['width'])
        H = int(region['height'])
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(out_path, fourcc, fps, (W, H))
        if not out.isOpened():
            print(f'\n[!] VideoWriter 실패: {out_path}', flush=True)
            return

        print(f'\n[REC] 시작 → {out_path} ({W}x{H} @ {fps}fps, {duration:.0f}초)',
              flush=True)
        t0 = time.time()
        frame_interval = 1.0 / fps
        next_t = t0
        n_frames = 0
        last_log_sec = -1
        try:
            while time.time() - t0 < duration and not _exit_flag.is_set():
                frame = grab(sct, region)
                if frame is None:
                    time.sleep(0.05)
                    continue
                if frame.shape[:2] != (H, W):
                    frame = cv2.resize(frame, (W, H))
                out.write(frame)
                n_frames += 1
                sec = int(time.time() - t0)
                if sec != last_log_sec:
                    print(f'  [{sec:02d}s / {int(duration):02d}s] frames={n_frames}',
                          end='\r', flush=True)
                    last_log_sec = sec
                next_t += frame_interval
                sleep_time = next_t - time.time()
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            out.release()
            try:
                sct.close()
            except Exception:
                pass
        elapsed = time.time() - t0
        print(f'\n[REC] 종료 → {out_path}', flush=True)
        print(f'      {n_frames} frames, {elapsed:.1f}s, '
              f'avg {n_frames/max(elapsed, 0.001):.1f} fps', flush=True)
        print('\n  Ctrl+F11 = 새 녹화 시작  |  Ctrl+F12 또는 Ctrl+C = 종료',
              flush=True)
    finally:
        with _rec_lock:
            _rec_active = False


def main():
    p = argparse.ArgumentParser(description='투명도형찾기 캡차 수동 녹화 (Ctrl+F11)')
    p.add_argument('--duration', type=float, default=30,
                   help='녹화 길이 초 (기본 30 — invi 캡차 25초 + 여유)')
    p.add_argument('--fps', type=int, default=30)
    p.add_argument('--region', choices=['game', 'monitor'], default='game',
                   help='game=게임창, monitor=메인 모니터 전체 (기본 game)')
    p.add_argument('--title', default=GAME_WINDOW_TITLE_DEFAULT,
                   help='게임 창 제목 키워드')
    args = p.parse_args()

    sct = mss.MSS()
    if args.region == 'monitor':
        region = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        src = 'monitor'
    else:
        region = find_game_region(args.title)
        if region is None:
            print(f'[!] 게임창 "{args.title}" 못 찾음 → 메인 모니터로 fallback')
            region = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            src = 'monitor (fallback)'
        else:
            src = 'game window'

    print(f'녹화 영역: {region}  ({src})')
    print(f'녹화 길이: {args.duration:.0f}s @ {args.fps}fps')
    print()
    print('  Ctrl+F11 = 녹화 시작 (이미 녹화 중이면 무시)')
    print('  Ctrl+F12 또는 Ctrl+C = 종료')
    print('대기 중...', flush=True)

    user32 = ctypes.windll.user32
    ok_rec = user32.RegisterHotKey(None, _HKID_REC, _MOD_CONTROL, _VK_F11)
    if not ok_rec:
        err = ctypes.windll.kernel32.GetLastError()
        print(f'[!] Ctrl+F11 핫키 등록 실패 (GetLastError={err}) '
              f'— 매크로가 이미 돌고 있나요?')
        sys.exit(1)
    print('[hotkey] Ctrl+F11 등록 OK')
    ok_quit = user32.RegisterHotKey(None, _HKID_QUIT, _MOD_CONTROL, _VK_F12)
    if ok_quit:
        print('[hotkey] Ctrl+F12 등록 OK')
    else:
        print('[!] Ctrl+F12 핫키 등록 실패 (Ctrl+C는 사용 가능)')

    try:
        msg = wt.MSG()
        while not _exit_flag.is_set():
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == _WM_HOTKEY:
                    print(f'[hotkey-msg] wParam={msg.wParam}', flush=True)
                    if msg.wParam == _HKID_REC:
                        threading.Thread(
                            target=do_record,
                            args=(region, args.fps, args.duration),
                            daemon=True,
                        ).start()
                    elif msg.wParam == _HKID_QUIT:
                        print('\n[Ctrl+F12] 종료')
                        _exit_flag.set()
            else:
                time.sleep(0.02)
    except KeyboardInterrupt:
        print('\n[Ctrl+C] 종료')
        _exit_flag.set()
    finally:
        user32.UnregisterHotKey(None, _HKID_REC)
        if ok_quit:
            user32.UnregisterHotKey(None, _HKID_QUIT)


if __name__ == '__main__':
    main()
