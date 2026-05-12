"""상점 전체 흐름 단독 실험 (장비 일괄 판매 + 기타템 판매).

사용 순서:
  1) 게임에서 직접 안전지대(상점 가능 지역)로 이동
  2) python _test_shop_etc.py
  3) 3초 카운트다운 후:
     [1] 캐시 탭 클릭
     [2] 휴대용 상점 더블클릭 (UI 열림 확인)
     [3] 장비 일괄 판매 + ENTER
     [4] 기타템 판매 (탭 전환 → 더블클릭+ENTER 반복)
     [5] 상점 닫기
     [6] 장비 탭 복귀
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
    print('  휴대상점 전체 흐름 단독 실험 (장비 일괄 + 기타템)')
    print('=' * 60)
    print(f'  CASH_TAB_ABS: {m.CASH_TAB_ABS}')
    print(f'  PORTABLE_SHOP_ABS: {m.PORTABLE_SHOP_ABS}')
    print(f'  SELL_ALL_BUTTON_ABS: {m.SELL_ALL_BUTTON_ABS}')
    print(f'  ETC_TAB_ABS: {m.ETC_TAB_ABS}')
    print(f'  ETC_SELL_SLOT_ABS: {m.ETC_SELL_SLOT_ABS}')
    print(f'  ETC_CHECK_SLOT_ABS: {m.ETC_CHECK_SLOT_ABS}')
    print(f'  SHOP_CLOSE_ABS: {m.SHOP_CLOSE_ABS}')
    print(f'  EQUIP_TAB_ABS: {m.EQUIP_TAB_ABS}')
    print()
    print('  ⚠ 시작 전: 게임에서 캐릭터를 안전지대(상점 가능 지역)에 두기')
    print('  F12 = 긴급정지')
    for sec in (3, 2, 1):
        print(f'  {sec}...', flush=True)
        time.sleep(1)
    print('시작\n')

    if not m.refresh_game_region():
        print('[!] 게임창 못 찾음 — 종료')
        return

    try:
        # [1] 캐시 탭
        cx, cy = m._abs(*m.CASH_TAB_ABS)
        print(f'[test-shop] [1] 캐시 탭 클릭 ({cx},{cy})')
        m.click_at(cx, cy)
        m.rsleep(0.5, 0.2)
        if m.STOP: return

        # [2] 휴대용 상점 더블클릭 (최대 2회 시도)
        ps_x, ps_y = m._abs(*m.PORTABLE_SHOP_ABS)
        opened = False
        for attempt in range(2):
            print(f'[test-shop] [2] 휴대용 상점 더블클릭 ({ps_x},{ps_y}) — 시도 #{attempt + 1}')
            m.click_at(ps_x, ps_y, double=True)
            m.rsleep(1.2, 0.2)
            if m.STOP: return
            if m.shop_ui_open():
                print('[test-shop] 상점 UI 확인됨')
                opened = True
                break
            print('[test-shop] 상점 UI 미확인 → 재시도')
            m.rsleep(0.5, 0.2)
        if not opened:
            print('[test-shop] !! 상점 안 열림 — 중단')
            return
        if m.STOP: return

        # [3] 장비 일괄 판매 + ENTER
        sa_x, sa_y = m._abs(*m.SELL_ALL_BUTTON_ABS)
        print(f'[test-shop] [3] 일괄 판매 버튼 클릭 ({sa_x},{sa_y})')
        m.click_at(sa_x, sa_y)
        m.rsleep(0.4, 0.2)
        if m.STOP: return
        print('[test-shop] [3] 확인 (ENTER)')
        m.tap('enter', 0.05)
        m.rsleep(1.2, 0.3)
        if m.STOP: return

        # [4] 기타템 판매
        print('[test-shop] [4] _shop_sell_etc() 호출')
        m._shop_sell_etc()
        if m.STOP: return

        # [5] 상점 닫기
        sc_x, sc_y = m._abs(*m.SHOP_CLOSE_ABS)
        print(f'[test-shop] [5] 상점 닫기 ({sc_x},{sc_y})')
        m.click_at(sc_x, sc_y)
        m.rsleep(0.5, 0.2)

        # [6] 장비 탭 복귀
        et_x, et_y = m._abs(*m.EQUIP_TAB_ABS)
        print(f'[test-shop] [6] 장비 탭 ({et_x},{et_y})')
        m.click_at(et_x, et_y)
        m.rsleep(0.4, 0.2)

        print('\n=== 종료 ===')
    finally:
        m.release_all()


if __name__ == '__main__':
    main()
