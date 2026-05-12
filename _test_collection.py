"""회수 루트 단독 실험용 임시 파일 — macro_red_v1 (회수 루트 보유) 대상.

사용: python _test_collection.py
- v2 (현재 macro_red.py)는 회수 루트 제거됨. 이 스크립트는 v1 보존본을 import해서 테스트.
- 시작까지 3초 카운트다운, F12 = 긴급정지

특정 phase만 실험하고 싶으면 아래 RUN 변수 바꿔:
  'all'      → collection_route() 전체
  'recover'  → _recover_floor1_to_floor2() (1층→2층 복귀)
  'stair'    → _jump_to_floor2_stair() (2층→2층계단)
  'climb'    → _wall_climb(RIGHT, FLOOR1_Y) (2층 우측 → 1층 낙하)
  'safe'     → goto_safe_zone() (안전지대 이동, 상점 가는 단계)
"""
import time
import keyboard

import macro_red_v1 as m

RUN = 'all'   # 'all' | 'recover' | 'stair' | 'climb' | 'safe'


def _stop():
    m.STOP = True
    print('[F12] STOP')


def main():
    keyboard.add_hotkey('f12', _stop)

    print('=' * 60)
    print(f'  회수 루트 실험 — RUN={RUN!r}')
    print('=' * 60)
    if m.MINIMAP_CFG:
        print(f'  미니맵: rect={m.MINIMAP_CFG["minimap_rect"]}')
        print(f'  사냥라인 Y={m.FLOOR2_Y}  1층 Y={m.FLOOR1_Y}  3층 Y={m.FLOOR3_Y}')
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
        if RUN == 'all':
            m.collection_route()
        elif RUN == 'recover':
            m._recover_floor1_to_floor2(max_retries=5)
        elif RUN == 'stair':
            m._jump_to_floor2_stair(max_tries=4)
        elif RUN == 'climb':
            m._wall_climb(m.RIGHT, m.FLOOR1_Y, timeout=8.0)
        elif RUN == 'safe':
            m.goto_safe_zone()
        else:
            print(f'[!] 알 수 없는 RUN: {RUN!r}')
    finally:
        m.release_all()
        print('정지됨')


if __name__ == '__main__':
    main()
