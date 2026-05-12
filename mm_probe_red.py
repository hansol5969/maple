"""macro_red.py 전용 미니맵 좌표 프로브.

사용: python mm_probe_red.py

→ minimap_config_red.json 기반으로 캐릭 mm 좌표 출력.
"""
import time
import macro_red as macro


def main():
    print('=' * 50)
    print('  미니맵 좌표 프로브 (red)')
    print('=' * 50)
    print(f'  게임 영역: {macro.GAME_REGION}')
    if macro.MINIMAP_CFG is None:
        print('[!] minimap_config_red.json 없음 — minimap_setup_red.py 먼저')
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
