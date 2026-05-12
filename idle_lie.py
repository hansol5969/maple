"""잠수 모드 — 거짓말 탐지기만 감지 + 자동 해제.

사냥/회수/상점/이동 모두 안 함. 게임에서 캐릭은 잠수 상태로 두고,
매크로는 lie 다이얼로그만 polling 후 감지 시 자동 풀이.

사용 순서:
  1) 게임에서 캐릭을 안전한 잠수 위치(파티 자리 등)에 두기
  2) python idle_lie.py
  3) F12 = 긴급 정지
"""
import time
import keyboard

import macro_red as m

POLL_INTERVAL_SEC = 0.5        # lie 감지 폴링 주기 (초)
GAME_REGION_REFRESH_SEC = 30.0 # 게임창 위치 갱신 주기 (초)
IDLE_LOG_SEC = 60.0            # 잠수 상태 로그 주기 (초)


def _stop():
    m.STOP = True
    print('[F12] STOP')


def main():
    keyboard.add_hotkey('f12', _stop)

    print('=' * 60)
    print('  잠수 모드 — 거짓말 탐지기만 감지 + 자동 해제')
    print('=' * 60)
    if not m.LIE_ENABLED:
        print(f'[!] 거짓말 탐지기 템플릿 없음 ({m.LIE_TEMPLATE}) — 종료')
        return
    print(f'  거짓말 탐지기 템플릿: {m.LIE_TEMPLATE}')
    print(f'  폴링 주기: {POLL_INTERVAL_SEC:.1f}s')
    print(f'  F12 = 긴급 정지')
    print('  ⚠ 게임에서 캐릭은 잠수 상태로 두기 (매크로는 이동/사냥 안 함)')
    print()

    if not m.refresh_game_region():
        print('[!] 게임창 못 찾음 — 종료')
        return

    start_ts = time.time()
    last_log_ts = 0.0
    last_region_refresh = time.time()
    lie_solved_count = 0

    while not m.STOP:
        now = time.time()

        # 게임 창 위치 주기 갱신
        if now - last_region_refresh > GAME_REGION_REFRESH_SEC:
            m.refresh_game_region()
            last_region_refresh = now

        screen = m.grab()
        if m.lie_detected(screen):
            print(f'[!] 거짓말 탐지기 감지 (총 {lie_solved_count + 1}회째) → 풀이 시작')
            ok = m.handle_lie_detector()
            if ok:
                lie_solved_count += 1
                print(f'[+] 거짓말 탐지기 해제 완료 (누적 {lie_solved_count}회)')
            else:
                print('[!!] 거짓말 탐지기 해제 실패 — STOP')
                break

        # 잠수 상태 주기 로그
        if now - last_log_ts > IDLE_LOG_SEC:
            elapsed_min = (now - start_ts) / 60.0
            print(f'[idle] 잠수 중... 경과 {elapsed_min:.1f}분, lie 해제 누적 {lie_solved_count}회')
            last_log_ts = now

        time.sleep(POLL_INTERVAL_SEC)

    print(f'\n정지됨 (총 경과 {(time.time() - start_ts)/60:.1f}분, lie 해제 {lie_solved_count}회)')


if __name__ == '__main__':
    main()
