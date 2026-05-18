"""회수 루트 전체 단독 실험.

사용 순서:
  1) 게임에서 캐릭을 2층 사냥 라인(Y=159) 어디든 두기
     — collection_route()가 [1] X=231-244 정렬부터 시작
  2) python _test_collect.py
  3) 3초 카운트다운 후 자동 진행:
     [1] X=231-244 정렬
     [2] hold_up_teleport(1.3) → Y=124 최상층 platform 도달 확인 (3회 재시도)
     [3] tap(JUMP) + attack_hold 1.3s
     [4] drop_down → Y=140 안착
     [5] Y=140 attack
     [6] _bounce_with_z_v2(230, 244, 2) — 매끄러운 z hold 왕복
     [6.5] z bounce 후 mm_y ≤ 145면 _collect_special_route() 진입:
           a) LEFT 텔포 hold 1.3s
           b) 공격 hold 1.3s
           c) mm_y=131이면 공격 hold 1.3s
           d) mm_y=131이면 up_tp + 공격 hold 1.3s + drop_down
           e) 3층 mm=(175-191, 110-116) 도달이면 z bounce 2회 왕복
     [7] _drop_until_floor1 → 1층 도달 (max 8회)
     [8a] 1층 좌측 X=170-195 (mm_x < 180일 땐 생략)
     [8b] 1층 우측 X=316-331
     [9] 1층 X=97-110 (up-tp 위치)
     [10] _clear_mobs(97, 128, 2s) + hold_up_teleport(1.3) → 2층 (3회 재시도)
     [11] X=231-244 사냥 zone 복귀
  4) F12 = 긴급정지
"""
import time
import keyboard

import macro_red as m


def _stop():
    m.STOP = True
    print('[F12] STOP')


def main():
    keyboard.add_hotkey('f12', _stop)

    print('=' * 60)
    print('  회수 루트 전체 단독 실험 — collection_route()')
    print('=' * 60)
    if m.MINIMAP_CFG:
        print(f'  미니맵: rect={m.MINIMAP_CFG["minimap_rect"]}')
        print(f'  사냥라인 Y={m.FLOOR2_Y}  사냥 zone X={m.HUNT_X_MIN}-{m.HUNT_X_MAX}')
        print(f'  Y={m.FLOOR2_RIGHT_TOP_Y} z hold platform  Y={m.COLLECT_TOP_PLATFORM_Y} 최상층  '
              f'Y={m.FLOOR3_Y} 안전지대  Y={m.ROUTE_3F_PLATFORM_Y} 3층')
        print(f'  1층 Y={m.FLOOR1_Y}  좌측 회수={m.COLLECT_F1_LEFT_STOP_X}  '
              f'우측={m.COLLECT_F1_PATROL_X[1]}  up-tp={m.COLLECT_F1_UPTP_X}')
    else:
        print('[!] minimap_config_red.json 없음')
        return
    print()
    print(f'  ⚠ 시작 전: 캐릭이 2층 사냥 라인(Y={m.FLOOR2_Y}) 어디든 위치')
    print('  F12 = 긴급정지')
    for sec in (3, 2, 1):
        print(f'  {sec}...', flush=True)
        time.sleep(1)
    print('시작\n')

    if not m.refresh_game_region():
        print('[!] 게임창 못 찾음 — 종료')
        return

    try:
        pos = m.find_char_minimap_pos(m.grab())
        print(f'시작 mm={pos}')
        m.collection_route()
        pos = m.find_char_minimap_pos(m.grab())
        print(f'\n회수 끝 mm={pos}')
    finally:
        m.release_all()
        print('정지됨')


if __name__ == '__main__':
    main()
