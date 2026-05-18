"""노트북 모니터 F12 토글 (Windows).

사용:
  python monitor_off.py        # 단독 실행 (Ctrl+C 종료)

동작:
  F12 첫 번째 → 모니터 OFF (마우스 움직여도 안 켜짐, 매 0.3초 재호출)
  F12 두 번째 → 모니터 ON (정상 동작 복귀)
  Ctrl+C     → 종료

키 후킹은 Windows RegisterHotKey 사용 — 시스템 레벨 핫키.
매크로가 보내는 키 입력에 묻히지 않고 항상 인식됨.

매크로 측 STOP은 Ctrl+F12로 분리됨 — F12 단독은 모니터 토글만, 매크로는 계속 동작.

GPU/캡쳐는 계속 작동 — 매크로와 동시 사용 가능.
"""
import ctypes
import ctypes.wintypes as wt
import threading
import time


WM_SYSCOMMAND   = 0x0112
SC_MONITORPOWER = 0xF170
HWND_BROADCAST  = 0xFFFF
MONITOR_OFF     = 2

WM_HOTKEY       = 0x0312
MOD_NONE        = 0x0000
VK_F12          = 0x7B
HOTKEY_ID       = 1

user32 = ctypes.windll.user32


_state = {'off': False, 'stop': False}


def turn_off_monitor():
    user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_OFF)


def _hotkey_listener_thread():
    """Windows RegisterHotKey + 메시지 loop. F11 누를 때마다 토글."""
    if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_NONE, VK_F12):
        print('[!] F12 핫키 등록 실패 (다른 앱이 F12 점유 중일 수 있음)', flush=True)
        return
    print('[F12] 시스템 핫키 등록 — 매크로 키 입력에 묻히지 않음', flush=True)
    msg = wt.MSG()
    while not _state['stop']:
        # PeekMessage로 non-blocking 체크 (stop flag 반응 위해)
        if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                _state['off'] = not _state['off']
                print(f'[F12] 모니터 {"OFF" if _state["off"] else "ON"}', flush=True)
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.02)
    user32.UnregisterHotKey(None, HOTKEY_ID)


def main():
    listener = threading.Thread(target=_hotkey_listener_thread, daemon=True)
    listener.start()

    print('모니터 토글 대기 — F12 누르면 OFF, 다시 누르면 ON  (Ctrl+C 종료)', flush=True)
    try:
        while not _state['stop']:
            if _state['off']:
                turn_off_monitor()
            time.sleep(0.3)
    except KeyboardInterrupt:
        print('\n종료')
    finally:
        _state['stop'] = True


if __name__ == '__main__':
    main()
