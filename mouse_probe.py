"""
마우스 좌표 확인용 도구.

사용법:
  1) 게임 창 켜고 인벤토리/상점 UI 띄우기
  2) python mouse_probe.py
  3) 마우스를 원하는 위치(캐시 탭, 휴대용 상점, 상점 첫 칸 등)에 놓고
     콘솔에 출력되는 좌표를 메모
  4) Ctrl+C 종료

5초마다 자동으로 한 줄 — 좌표 변화 없으면 출력 안 함.
"""
import time
import ctypes

# DPI 인식
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def get_pos():
    pt = ctypes.wintypes.POINT() if hasattr(ctypes, 'wintypes') else None
    import ctypes.wintypes as wt
    pt = wt.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def main():
    print('=' * 50)
    print('  마우스 좌표 프로브')
    print('=' * 50)
    print('  마우스 위치 변할 때마다 좌표 출력')
    print('  Ctrl+C 종료\n')

    last = None
    try:
        while True:
            pos = get_pos()
            if pos != last:
                print(f'mouse = ({pos[0]:>5}, {pos[1]:>5})', flush=True)
                last = pos
            time.sleep(0.1)
    except KeyboardInterrupt:
        print('\n종료')


if __name__ == '__main__':
    main()
