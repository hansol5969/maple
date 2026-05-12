"""3층 추가 회수 루트 단독 실험.

사용 순서:
  1) 게임에서 캐릭을 2층 사냥 라인(Y=159) 어디든 두기
     (예: mm=(120, 159)처럼 1층 계단 위 텔포로 막 도달한 위치)
  2) python _test_3f.py
  3) 3초 카운트다운 후 _collect_3f_route() 단독 실행:
     [A] X=182 정렬 + 몹 정리 + hold_up_teleport×2 (Y=102 도달)
     [B] mm=(185, 102) 부근 몹 정리 + 공격 hold 1.4s + drop_down → 3층
     [C] 3층 platform (176-192, 113) z bounce 2회
     [D] drop_down + 공격 hold 1.4s
     [E] X=161 walk 이동 + drop_down×2 (Y=131)
     [F] 2층 계단 (151-163, 144) z bounce 2회
     [G] LEFT 텔포 1회 → 2층 복귀
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
    print('  3층 추가 회수 루트 단독 실험 — _collect_3f_route()')
    print('=' * 60)
    if m.MINIMAP_CFG:
        print(f'  미니맵: rect={m.MINIMAP_CFG["minimap_rect"]}')
        print(f'  3층 진입 X={m.ROUTE_3F_ENTRY_X}  최상 Y={m.ROUTE_3F_TOP_Y}')
        print(f'  3층 platform={m.ROUTE_3F_PLATFORM_X} Y={m.ROUTE_3F_PLATFORM_Y}')
        print(f'  drop 타겟 X={m.ROUTE_3F_DROP_TARGET_X} Y={m.ROUTE_3F_DROP_TARGET_Y}')
        print(f'  2층 계단={m.ROUTE_F2_STAIR_X} Y={m.ROUTE_F2_STAIR_Y}')
    else:
        print('[!] minimap_config_red.json 없음')
        return
    print()
    print('  ⚠ 시작 전: 캐릭이 2층 사냥 라인(Y=159) 어디든 위치')
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
        m._collect_3f_route()
        pos = m.find_char_minimap_pos(m.grab())
        print(f'\n3f 회수 끝 mm={pos}')
    finally:
        m.release_all()
        print('정지됨')


if __name__ == '__main__':
    main()
