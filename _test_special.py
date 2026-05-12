"""특별 회수 루트 단독 실험.

사용 순서:
  1) 게임에서 캐릭을 Y=140 z hold platform 위에 두기 (회수 [5] 끝난 직후 상태)
     또는 사냥 zone 정렬 후 hold_up_teleport + drop_down으로 Y=140 도달한 상태
  2) python _test_special.py
  3) 3초 카운트다운 후 _collect_special_route() 단독 실행:
     [1] LEFT 텔포 hold 1.3s
     [2] 공격 hold 1.3s
     [3] mm_y == 131이면 공격 hold 1.3s
     [4] mm_y == 131이면 up_teleport + 공격 hold 1.3s + drop_down
     [5] 3층 mm=(175-191, 110-116) 도달이면 z bounce 2회 왕복
  4) F12 = 긴급정지

RUN 변수로 실험 대상 선택:
  'special'  → _collect_special_route() 단독
  'full_top' → hold_up_teleport + jump + attack_hold + drop_down (회수 [2]-[4])
  'bounce'   → _bounce_with_z_v2(HUNT_X_MIN, HUNT_X_MAX, 2) z hold 매끄러움 확인
  'bounce3f' → 3층 z bounce (175-191, 2회)
"""
import time
import keyboard

import macro_red as m

RUN = 'special'   # 'special' | 'full_top' | 'bounce' | 'bounce3f'


def _stop():
    m.STOP = True
    print('[F12] STOP')


def main():
    keyboard.add_hotkey('f12', _stop)

    print('=' * 60)
    print(f'  특별 회수 단독 실험 — RUN={RUN!r}')
    print('=' * 60)
    if m.MINIMAP_CFG:
        print(f'  미니맵: rect={m.MINIMAP_CFG["minimap_rect"]}')
        print(f'  사냥라인 Y={m.FLOOR2_Y}  Y=140 platform  Y=131 위 platform  Y=113 3층')
    else:
        print('[!] minimap_config_red.json 없음')
        return
    print('  F12 = 긴급정지')
    print('  ⚠ 시작 전: 캐릭이 회수 [5] 직후 상태(Y=140 platform 위)인지 확인')
    for sec in (3, 2, 1):
        print(f'  {sec}...', flush=True)
        time.sleep(1)
    print('시작\n')

    if not m.refresh_game_region():
        print('[!] 게임창 못 찾음 — 종료')
        return

    try:
        if RUN == 'special':
            pos = m.find_char_minimap_pos(m.grab())
            print(f'시작 mm={pos} (Y=140±5 platform 위 권장)')
            m._collect_special_route()
        elif RUN == 'full_top':
            # 회수 [2]-[4] 단독 — hold_up_teleport + jump+attack_hold + drop_down
            print('hold_up_teleport(1.3) → jump + attack_hold 1.3s → drop_down')
            m.hold_up_teleport(1.3)
            m._wait_landed(timeout=1.2, stable_window=0.15)
            pos = m.find_char_minimap_pos(m.grab())
            print(f'[full_top] up_tp 후 mm={pos}')
            m.tap(m.JUMP_KEY, 0.15)
            m.attack_hold()
            time.sleep(1.3)
            m.attack_release()
            m.rsleep(0.2, 0.2)
            pos = m.find_char_minimap_pos(m.grab())
            print(f'[full_top] jump+attack 후 mm={pos}')
            m.drop_down()
            m.rsleep(0.3, 0.2)
            pos = m.find_char_minimap_pos(m.grab())
            print(f'[full_top] drop_down 후 mm={pos}')
        elif RUN == 'bounce':
            print(f'_bounce_with_z_v2({m.HUNT_X_MIN}, {m.HUNT_X_MAX}, round_trips=2) 매끄러운 walk 확인')
            m._bounce_with_z_v2(m.HUNT_X_MIN, m.HUNT_X_MAX, round_trips=2)
        elif RUN == 'bounce3f':
            print('_bounce_with_z_v2(175, 191, round_trips=2) — 3층 z bounce')
            m._bounce_with_z_v2(175, 191, round_trips=2)
        else:
            print(f'[!] 알 수 없는 RUN: {RUN!r} (special|full_top|bounce|bounce3f)')
    finally:
        m.release_all()
        print('\n정지됨')


if __name__ == '__main__':
    main()
