"""잠수 모드 — 거짓말 탐지기만 감지 + 자동 해제.

사냥/회수/상점/이동 모두 안 함. 게임에서 캐릭은 잠수 상태로 두고,
매크로는 lie 다이얼로그만 polling 후 감지 시 자동 풀이.

word 캡차 솔버(word_captcha_solver.py)를 자동으로 사용. (macro_red 통합)

사용 순서:
  1) 게임에서 캐릭을 안전한 잠수 위치(파티 자리 등)에 두기
  2) python idle_lie.py
  3) F12 = 긴급 정지
"""
import os
import time
import keyboard

import macro_red as m

POLL_INTERVAL_SEC = 0.5        # lie 감지 폴링 주기 (초)
GAME_REGION_REFRESH_SEC = 30.0 # 게임창 위치 갱신 주기 (초)
IDLE_LOG_SEC = 60.0            # 잠수 상태 로그 주기 (초)


def _stop():
    m.STOP = True
    print('[F12] STOP')


def _print_solver_status():
    """word 캡차 솔버 자산 상태 표시 — 테스트 시작 전 빠르게 확인."""
    print('  ── 캡차 솔버 ──')
    if os.path.exists(m.CAPTCHA_WORD_SOLVER_PATH):
        print(f'  word 솔버: {os.path.relpath(m.CAPTCHA_WORD_SOLVER_PATH)}')
        chars_dir = os.path.join(os.path.dirname(m.CAPTCHA_WORD_SOLVER_PATH),
                                 'captcha_assets', 'word', 'chars')
        n_chars = 0
        if os.path.isdir(chars_dir):
            n_chars = sum(1 for f in os.listdir(chars_dir)
                          if f.endswith('.png') and len(f) == 5)
        print(f'  글자 템플릿: {n_chars}/36자  ({os.path.relpath(chars_dir)})')
        if n_chars < 20:
            print('  ⚠ 템플릿 부족 — 매칭 정확도 낮을 수 있음')
    else:
        print(f'  [!] word 솔버 없음 ({m.CAPTCHA_WORD_SOLVER_PATH})')


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
    _print_solver_status()
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
    lie_fail_count = 0
    total_solve_time = 0.0

    while not m.STOP:
        now = time.time()

        # 게임 창 위치 주기 갱신
        if now - last_region_refresh > GAME_REGION_REFRESH_SEC:
            m.refresh_game_region()
            last_region_refresh = now

        screen = m.grab()
        if m.lie_detected(screen):
            attempt_n = lie_solved_count + lie_fail_count + 1
            print(f'\n[!] 거짓말 탐지기 감지 (시도 #{attempt_n}) → 풀이 시작')
            solve_t0 = time.time()
            ok = m.handle_lie_detector()
            solve_dt = time.time() - solve_t0
            total_solve_time += solve_dt
            if ok:
                lie_solved_count += 1
                print(f'[+] 풀이 성공 ({solve_dt:.1f}s) — 누적 성공 {lie_solved_count}회, 실패 {lie_fail_count}회')
            else:
                lie_fail_count += 1
                print(f'[!!] 풀이 실패 ({solve_dt:.1f}s) — STOP')
                break

        # 잠수 상태 주기 로그
        if now - last_log_ts > IDLE_LOG_SEC:
            elapsed_min = (now - start_ts) / 60.0
            print(f'[idle] 잠수 {elapsed_min:.1f}분, lie 성공 {lie_solved_count}회 실패 {lie_fail_count}회')
            last_log_ts = now

        time.sleep(POLL_INTERVAL_SEC)

    elapsed_min = (time.time() - start_ts) / 60.0
    print(f'\n=== 정지됨 ===')
    print(f'  총 경과:        {elapsed_min:.1f}분')
    print(f'  lie 풀이 성공:  {lie_solved_count}회')
    print(f'  lie 풀이 실패:  {lie_fail_count}회')
    if lie_solved_count + lie_fail_count > 0:
        avg = total_solve_time / (lie_solved_count + lie_fail_count)
        print(f'  평균 풀이 시간: {avg:.1f}초/회')


if __name__ == '__main__':
    main()
