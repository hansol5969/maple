"""
미니맵 좌표 확인용 도구.

사용법:
  python mm_probe.py        # macro.py / macro_v2.py 용 (minimap_config.json)
  python mm_probe_red.py    # macro_red.py 용 (minimap_config_red.json)

  1) 게임 창 켠 상태로 실행
  2) 캐릭터를 손으로 원하는 위치에 옮기기 (안전지대 입구 등)
  3) 콘솔에 출력되는 mm=(X, Y) 값을 메모
  4) Ctrl+C로 종료

매크로 동작 X — 좌표만 보여주는 도구.
"""
import time
import macro


def main():
    print('=' * 50)
    print('  미니맵 좌표 프로브')
    print('=' * 50)
    print(f'  게임 영역: {macro.GAME_REGION}')
    if macro.MINIMAP_CFG is None:
        print('[!] minimap_config.json 없음 — minimap_setup.py 먼저')
        return
    print('  캐릭터를 옮기면 좌표가 0.3초마다 출력됩니다')
    print('  Ctrl+C 종료\n')

    last = None
    try:
        while True:
            screen = macro.grab()
            pos = macro.find_char_minimap_pos(screen)
            if pos is None:
                msg = 'mm = (검출 실패)'
            else:
                msg = f'mm = ({pos[0]:>4}, {pos[1]:>4})'
            if msg != last:
                print(msg, flush=True)
                last = msg
            time.sleep(0.3)
    except KeyboardInterrupt:
        print('\n종료')


if __name__ == '__main__':
    main()
