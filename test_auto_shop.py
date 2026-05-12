"""
auto_shop() 단독 테스트 — 사냥 루프 안 돌고 판매 시퀀스만.

사용법:
  1) 인벤이 가득 찬 상태로 캐릭터를 사냥 라인에 둠
  2) python test_auto_shop.py
  3) 5초 후 자동 시작

F12 = 강제 정지.
"""
import time
import keyboard
import macro


def main():
    keyboard.add_hotkey('f12', macro._stop)
    print('=' * 50)
    print('  auto_shop 테스트')
    print('=' * 50)
    print(f'  GAME_REGION: {macro.GAME_REGION}')
    print(f'  CAL: ({macro.COORDS_CAL_GAME_LEFT}, {macro.COORDS_CAL_GAME_TOP})')
    print('  5초 후 시작 — 게임 창에 포커스 두세요')
    time.sleep(5)

    try:
        ok = macro.auto_shop()
        print(f'\n결과: {"성공" if ok else "실패"}')
    finally:
        macro.attack_release()
        macro.release()


if __name__ == '__main__':
    main()
