"""
goto_escalator() 단독 테스트.

사용법:
  1) 게임 창 켜고 캐릭터를 사냥 라인에 둠
  2) python test_escalator.py
  3) 3초 후 자동으로 에스컬레이터로 이동 시도

ESC 또는 F12로 강제 정지.
"""
import time
import keyboard
import macro


def main():
    keyboard.add_hotkey('f12', macro._stop)
    print('=' * 50)
    print('  에스컬레이터 도달 테스트 (사냥 X)')
    print('=' * 50)
    print(f'  목표 X: {macro.ESCALATOR_X_MIN}-{macro.ESCALATOR_X_MAX}')
    print(f'  사냥 라인 mm_y: '
          f'{macro.MINIMAP_CFG.get("floor1_y_baseline") if macro.MINIMAP_CFG else "?"}')
    print('  3초 후 시작 — 게임 창에 포커스 두세요')
    print('  F12 = 강제 정지')
    time.sleep(3)

    try:
        ok = macro.goto_escalator()
        print(f'\n결과: {"성공" if ok else "실패"}')
    finally:
        macro.attack_release()
        macro.release()


if __name__ == '__main__':
    main()
