"""
인벤/상점 칸의 픽셀 std/mean 측정 도구.

사용법:
  1) 게임 창 켠 상태로 실행
  2) 인벤 상태(빈/찬)를 바꿔가며 콘솔 값 비교
  3) Ctrl+C 종료

목적:
  - 빈 칸 std vs 찬 칸 std 의 차이 확인
  - INV_FILLED_STD_THRESHOLD를 둘 사이 값으로 조정

세 영역 동시 측정:
  - TRIGGER:    인벤 가득 감지 영역 (3052-3147, 910-1007)
  - INV_FIRST:  장비탭 첫 칸 (판매 종료 판정용)
  - SHOP_FIRST: 상점 UI 첫 칸 (상점 열림 검증용)
"""
import time
import macro


def main():
    print('=' * 70)
    print('  인벤/상점 칸 std/mean 측정')
    print('=' * 70)
    print(f'  GAME_REGION: {macro.GAME_REGION}')
    print(f'  현재 임계값(INV_FILLED_STD_THRESHOLD) = '
          f'{macro.INV_FILLED_STD_THRESHOLD}')
    print()
    print('  인벤 상태 바꿔가며 값 비교 →')
    print('  - 빈 칸일 때 std 와 찬 칸일 때 std 둘 다 메모')
    print('  - 임계값 = 두 값 사이 (예: 빈=4, 찬=42 → 임계값 20~25 적당)')
    print('  Ctrl+C 종료\n')

    h = macro.SLOT_CHECK_SIZE // 2

    try:
        while True:
            screen = macro.grab()
            H, W = screen.shape[:2]

            # 트리거 영역
            tx1, ty1 = macro._game_rel(macro.INV_TRIGGER_ABS[0], macro.INV_TRIGGER_ABS[1])
            tx2, ty2 = macro._game_rel(macro.INV_TRIGGER_ABS[2], macro.INV_TRIGGER_ABS[3])
            tx1 = max(0, tx1); tx2 = min(W, tx2)
            ty1 = max(0, ty1); ty2 = min(H, ty2)
            trig = screen[ty1:ty2, tx1:tx2]
            t_std = float(trig.std()) if trig.size else 0.0
            t_mean = float(trig.mean()) if trig.size else 0.0

            # 인벤 첫 칸
            ix, iy = macro._game_rel(*macro.INV_FIRST_SLOT_ABS)
            inv = screen[max(0, iy - h):min(H, iy + h),
                         max(0, ix - h):min(W, ix + h)]
            i_std = float(inv.std()) if inv.size else 0.0
            i_mean = float(inv.mean()) if inv.size else 0.0

            # 상점 첫 칸
            sx, sy = macro._game_rel(*macro.SHOP_FIRST_SLOT_ABS)
            shop = screen[max(0, sy - h):min(H, sy + h),
                          max(0, sx - h):min(W, sx + h)]
            s_std = float(shop.std()) if shop.size else 0.0
            s_mean = float(shop.mean()) if shop.size else 0.0

            print(f'TRIG  std={t_std:6.2f} mean={t_mean:6.1f}  | '
                  f'INV1  std={i_std:6.2f} mean={i_mean:6.1f}  | '
                  f'SHOP1 std={s_std:6.2f} mean={s_mean:6.1f}',
                  flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print('\n종료')


if __name__ == '__main__':
    main()
