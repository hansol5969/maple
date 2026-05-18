"""기타템 판매만 단독 실험 — _shop_sell_etc() 새 로직 검증.

새 로직:
  - 기타 탭 클릭
  - 첫 슬롯 1회 클릭 (맨 위 아이템 선택)
  - "팔기" 버튼 + ENTER 반복 (자동으로 다음 아이템 맨 위로)
  - 빈칸 4회 확정 시 종료

사용 순서:
  1) 게임에서 직접 안전지대로 이동
  2) ★ 수동으로 상점 열기 (휴대용 상점 더블클릭 등) — 장비 탭이든 상관 X, 스크립트가 기타 탭 전환
  3) 인벤 기타 탭에 팔 아이템 있어야 검증 가능
  4) python _test_etc_only.py
  5) 3초 카운트다운 후 _shop_sell_etc() 실행
  6) F12 = 긴급정지
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
    print('  기타템 판매 단독 실험 (새 로직: 1회 클릭 + 팔기버튼 ENTER 반복)')
    print('=' * 60)
    print(f'  ETC_TAB_ABS:         {m.ETC_TAB_ABS}')
    print(f'  ETC_SELL_SLOT_ABS:   {m.ETC_SELL_SLOT_ABS}  (첫 슬롯 — 1회 클릭만)')
    print(f'  ETC_SELL_BUTTON_ABS: {m.ETC_SELL_BUTTON_ABS}  (팔기 버튼 — 반복 클릭)')
    print(f'  ETC_CHECK_SLOT_ABS:  {m.ETC_CHECK_SLOT_ABS}  (빈칸 체크 영역)')
    print(f'  ETC_MAX_SELL_TRIES:  {m.ETC_MAX_SELL_TRIES}')
    print()
    print('  ⚠ 사전 준비: 게임에서 휴대상점이 ★열린 상태★ 여야 함')
    print('  F12 = 긴급정지')
    for sec in (3, 2, 1):
        print(f'  {sec}...', flush=True)
        time.sleep(1)
    print('시작\n')

    if not m.refresh_game_region():
        print('[!] 게임창 못 찾음 — 종료')
        return

    try:
        m._shop_sell_etc()
        print('\n=== 종료 ===')
    except m._ShopAborted:
        print('[!] _ShopAborted 발생 (캡차 또는 F12)')
    finally:
        m.release_all()


if __name__ == '__main__':
    main()
