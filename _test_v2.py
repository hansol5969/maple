"""v2 단독 실험용.

사용: python _test_v2.py
RUN 변수로 테스트 대상 선택:
  'collect'  → collection_route_v2() (회수 루트)
  'hunt'     → hunt() 전체 (1분30초 안에 회수까지 보고 싶으면 COLLECT_INTERVAL 줄여)
  'patrol'   → _patrol_with_teleport(156, 321, 2) 단독 (1층 펫 회수)
  'bounce'   → _bounce_with_z_v2(231, 245, 3) 단독 (z 왕복)
"""
import time
import keyboard

import macro_red as m

RUN = 'collect'   # 'collect' | 'hunt' | 'patrol' | 'bounce'


def _stop():
    m.STOP = True
    print('[F12] STOP')


def main():
    keyboard.add_hotkey('f12', _stop)

    print('=' * 60)
    print(f'  v2 실험 — RUN={RUN!r}')
    print('=' * 60)
    if m.MINIMAP_CFG:
        print(f'  미니맵: rect={m.MINIMAP_CFG["minimap_rect"]}')
        print(f'  사냥라인 Y={m.MINIMAP_CFG.get("floor1_y_baseline")}  '
              f'사냥 zone X={m.HUNT_X_MIN}-{m.HUNT_X_MAX}')
    else:
        print('[!] minimap_config_red.json 없음')
        return
    print('  F12 = 긴급정지')
    for sec in (3, 2, 1):
        print(f'  {sec}...', flush=True)
        time.sleep(1)
    print('시작')

    if not m.refresh_game_region():
        print('[!] 게임창 못 찾음 — 종료')
        return

    try:
        if RUN == 'collect':
            m.collection_route()  # v1 복원본
        elif RUN == 'hunt':
            m.hunt()
        elif RUN == 'recover':
            m._recover_floor1_to_floor2(max_retries=m.COLLECT_F1_TO_F2_RETRIES)
        elif RUN == 'stair':
            m._jump_to_floor2_stair(max_tries=4)
        elif RUN == 'climb':
            m._wall_climb(m.RIGHT, m.FLOOR1_Y, timeout=8.0)
        else:
            print(f'[!] 알 수 없는 RUN: {RUN!r} (collect|hunt|recover|stair|climb)')
    finally:
        m.release_all()
        print('정지됨')


if __name__ == '__main__':
    main()
