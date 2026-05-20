"""잠수 + 버프 + AFK 흔들기 — 사냥 안 함.

- 실행 시 미니맵 셋업 GUI 먼저 띄움 (해상도/창 위치 매번 다를 수 있어 매 실행 재캡처)
- 60초마다 짧게 한쪽으로 갔다가 원래 미니맵 좌표로 복귀 (AFK 방지)
- 90초마다 미니맵에 주황색 점(다른 유저)이 내 근처에 있을 때만 't' 버프 시전
- 거짓말 탐지기 감지 + 자동 풀이 (idle_lie.py와 동일)
- F12 = 긴급 정지

사용 순서:
  1) 게임 켜고 캐릭을 안전한 잠수 자리에 두기 (왕복 방향 쪽으로 약간의 여유)
  2) python idle_buff.py
  3) 뜨는 셋업 창에서: 미니맵 드래그 → 캐릭 점 클릭 → 's' 저장 → 자동으로 본 매크로 시작
     이미 캡처된 설정 그대로 쓰려면 셋업 창에서 'q' 종료 (기존 minimap_config_red.json 사용)
"""
import json
import os
import random
import subprocess
import sys
import time

import cv2
import keyboard
import numpy as np

import macro_red as m

# === 설정 ===
BUFF_KEY            = 't'      # 버프 키 (게임 단축키와 일치)
BUFF_INTERVAL_SEC   = 90.0     # 버프 시전 주기

PET_FEED_KEY          = '0'        # 펫 먹이 (macro_red.PET_FEED_KEY 와 동일)
PET_FEED_COUNT        = 2          # 한 사이클에 먹일 개수
PET_FEED_INTERVAL_SEC = 900.0      # 15분 (macro_red.PET_FEED_INTERVAL 와 동일)
PET_FEED_JITTER_SEC   = 15.0       # 주기에 ±N초 흔들기 (먹이 절약 + 패턴 회피)
PARTY_NEAR_RADIUS   = 65       # 미니맵 픽셀 — 내 점에서 이 반경 안에 주황 있으면 버프
PARTY_HUE_RANGE     = (12, 22) # HSV hue 주황 — 실측 hue=18 중심, 빨강(0)/노랑(30) 양쪽 분리
PARTY_S_MIN         = 120
PARTY_V_MIN         = 120
PARTY_BLOB_AREA_MIN = 4

WANDER_INTERVAL_SEC   = 60.0     # AFK 왕복 주기
WANDER_DIR            = 'auto'   # 'left'/'right'/'auto' — auto면 home과 safe 한계 거리 비교해 여유 큰 쪽
WANDER_HOLD_SEC       = 0.20     # 한 방향 hold 최대 시간 (좁은 안전지대 대비 짧게)
WANDER_RETURN_TIMEOUT = 2.0      # 원래 좌표 복귀 timeout
WANDER_HOME_TOL       = 2        # 원래 mm_x ± N픽셀 안이면 복귀 완료
WANDER_SAFE_MARGIN    = 4        # 한계 안쪽 N픽셀 도달하면 hold 중단 (관성 고려 여유)
WANDER_POLL_SEC       = 0.02     # hold 중 미니맵 폴링 주기 (짧을수록 반응 빠름)

SAFE_CONFIG_PATH = 'idle_safe_config.json'  # idle_safe_setup.py로 생성

POLL_INTERVAL_SEC       = 0.4
GAME_REGION_REFRESH_SEC = 30.0
IDLE_LOG_SEC            = 60.0
INV_CHECK_INTERVAL_SEC  = 30.0   # 잠수 중 인벤 가득 체크 주기 (사냥 안 해 자주 안 참)
LIE_DEBUG               = True   # 진단용: 일정 주기로 lie 매칭 최고 점수 로그
LIE_DEBUG_INTERVAL_SEC  = 15.0


def _stop():
    m.STOP = True
    print('[F12] STOP')


def _save_lie_snapshot():
    """현재 화면을 lie_snapshot.png 로 저장. lie 떴을 때 F11 한 번 누르면
    lie_template_capture.py 로 영역만 잘라내 새 템플릿 만들 수 있음."""
    try:
        screen = m.grab()
        path = 'lie_snapshot.png'
        cv2.imwrite(path, screen)
        print(f'[F11] 스냅샷 저장: {path} ({screen.shape[1]}x{screen.shape[0]}) — '
              f'lie_template_capture.py 로 영역 잘라내세요')
    except Exception as e:
        print(f'[F11] 스냅샷 저장 실패: {e}')


def _run_minimap_setup() -> None:
    """미니맵 셋업 GUI 실행 — 매 실행마다 띄워서 환경 변화(해상도/창 크기) 대응.
    셋업 창에서 's'로 저장 안 하면 기존 JSON 그대로 사용됨."""
    here = os.path.dirname(os.path.abspath(__file__))
    setup_path = os.path.join(here, 'minimap_setup_red.py')
    if not os.path.exists(setup_path):
        print(f'[setup] {setup_path} 없음 — 건너뜀')
        return
    print('[setup] 미니맵 셋업 GUI 실행 — 드래그=영역, 클릭=캐릭 색, s=저장, q=취소(기존 설정 유지)')
    try:
        subprocess.run([sys.executable, setup_path], check=False)
    except Exception as e:
        print(f'[setup] 실행 실패: {e}')


def _reload_minimap_cfg() -> bool:
    """저장된 minimap_config_red.json을 m.MINIMAP_CFG에 다시 로드."""
    path = m.MINIMAP_CONFIG_PATH
    if not os.path.exists(path):
        return False
    with open(path, encoding='utf-8') as f:
        m.MINIMAP_CFG = json.load(f)
    rect = m.MINIMAP_CFG.get('minimap_rect')
    color = m.MINIMAP_CFG.get('char_color_bgr')
    print(f'[setup] 미니맵 설정 로드: rect={rect}  color={color}')
    return True


def _run_subprocess(script_name: str, reason: str) -> None:
    """현재 디렉터리의 setup 스크립트 subprocess 실행."""
    here = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(here, script_name)
    if not os.path.exists(script_path):
        print(f'[setup] {script_path} 없음 — 건너뜀')
        return
    print(f'[setup] {reason} → {script_name} 실행')
    try:
        subprocess.run([sys.executable, script_path], check=False)
    except Exception as e:
        print(f'[setup] {script_name} 실행 실패: {e}')


def _ensure_shop_coords_fresh() -> None:
    """shop_coords.json 캘리브레이션 환경(게임창 크기)이 현재와 다르면 자동 setup."""
    path = m.SHOP_COORDS_PATH
    cur_w = m.GAME_REGION.get('width')
    cur_h = m.GAME_REGION.get('height')
    if not os.path.exists(path):
        print(f'[setup] {path} 없음 → shop_coords_setup 실행')
        _run_subprocess('shop_coords_setup.py', '상점 좌표 미설정')
        return
    try:
        with open(path, encoding='utf-8') as f:
            sc = json.load(f)
    except Exception as e:
        print(f'[setup] {path} 읽기 실패: {e} → shop_coords_setup 실행')
        _run_subprocess('shop_coords_setup.py', f'{path} 손상')
        return
    sw, sh = sc.get('cal_game_width'), sc.get('cal_game_height')
    if sw is None or sh is None:
        print(f'[setup] {path} 구버전(크기 정보 없음) → shop_coords_setup 실행')
        _run_subprocess('shop_coords_setup.py', '구버전 shop_coords 갱신')
        return
    if sw != cur_w or sh != cur_h:
        print(f'[setup] 해상도 변경 감지: shop_coords {sw}x{sh} ≠ 현재 {cur_w}x{cur_h}')
        _run_subprocess('shop_coords_setup.py', '해상도 변경')
        return
    print(f'[setup] shop_coords 환경 일치 ({sw}x{sh}) — 셋업 생략')


def _ensure_safe_config_fresh() -> None:
    """idle_safe_config.json 캘리브레이션 환경(미니맵 영역/게임창 크기)이 다르면 자동 setup."""
    path = SAFE_CONFIG_PATH
    cur_rect = m.MINIMAP_CFG.get('minimap_rect') if m.MINIMAP_CFG else None
    cur_w = m.GAME_REGION.get('width')
    cur_h = m.GAME_REGION.get('height')
    if not os.path.exists(path):
        print(f'[setup] {path} 없음 → idle_safe_setup 실행')
        _run_subprocess('idle_safe_setup.py', '안전 한계 미설정')
        return
    try:
        with open(path, encoding='utf-8') as f:
            sc = json.load(f)
    except Exception as e:
        print(f'[setup] {path} 읽기 실패: {e} → idle_safe_setup 실행')
        _run_subprocess('idle_safe_setup.py', f'{path} 손상')
        return
    saved_rect = sc.get('cal_minimap_rect')
    sw, sh = sc.get('cal_game_width'), sc.get('cal_game_height')
    if not saved_rect or sw is None or sh is None:
        print(f'[setup] {path} 구버전(환경 정보 없음) → idle_safe_setup 실행')
        _run_subprocess('idle_safe_setup.py', '구버전 idle_safe 갱신')
        return
    if list(saved_rect) != list(cur_rect or []):
        print(f'[setup] 미니맵 영역 변경 감지: safe {saved_rect} ≠ 현재 {cur_rect}')
        _run_subprocess('idle_safe_setup.py', '미니맵 영역 변경')
        return
    if sw != cur_w or sh != cur_h:
        print(f'[setup] 해상도 변경 감지: safe {sw}x{sh} ≠ 현재 {cur_w}x{cur_h}')
        _run_subprocess('idle_safe_setup.py', '해상도 변경')
        return
    print(f'[setup] idle_safe 환경 일치 — 셋업 생략')


def _party_nearby(screen, my_mm_pos) -> bool:
    """미니맵에서 주황 blob이 내 점 반경 PARTY_NEAR_RADIUS 안에 있나."""
    if my_mm_pos is None or m.MINIMAP_CFG is None:
        return False
    x1, y1, x2, y2 = m.MINIMAP_CFG['minimap_rect']
    mm = screen[y1:y2, x1:x2]
    hsv = cv2.cvtColor(mm, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0]
    s = hsv[..., 1]
    v = hsv[..., 2]
    lo, hi = PARTY_HUE_RANGE
    mask = ((h >= lo) & (h <= hi) & (s >= PARTY_S_MIN) & (v >= PARTY_V_MIN)).astype(np.uint8) * 255
    n, _l, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    mx, my = my_mm_pos
    r2 = PARTY_NEAR_RADIUS * PARTY_NEAR_RADIUS
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < PARTY_BLOB_AREA_MIN:
            continue
        cx, cy = cents[i]
        if (cx - mx) ** 2 + (cy - my) ** 2 <= r2:
            return True
    return False


def _lie_match_score():
    """현재 화면 중앙 영역에서 lie 템플릿 최고 매칭 점수 (val, loc) 반환.
    임계값 못 넘었는데 실제 lie 팝업이 떠 있다면 템플릿 갱신 또는 임계값 하향 필요."""
    if not m.LIE_ENABLED:
        return None
    try:
        screen = m.grab()
        region = m._center_region(screen)
        tpl = m._load_tpl(m.LIE_TEMPLATE)
        if tpl is None or region.size == 0:
            return None
        if region.shape[0] < tpl.shape[0] or region.shape[1] < tpl.shape[1]:
            return None
        res = cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED)
        _, val, _, loc = cv2.minMaxLoc(res)
        return float(val), loc
    except Exception as e:
        print(f'[lie-dbg] 매칭 에러: {e}')
        return None


def _cast_buff():
    print(f"[buff] '{BUFF_KEY}' 시전")
    m.tap(BUFF_KEY, 0.06)


def _feed_pet():
    """macro_red 본 매크로의 펫 먹이 패턴 그대로 — release_all 후 tap 2회."""
    print(f"[pet] 먹이 {PET_FEED_COUNT}개 시전 ({PET_FEED_KEY!r})")
    try:
        m.release_all()
    except Exception:
        pass
    m.rsleep(0.25, 0.2)
    for i in range(PET_FEED_COUNT):
        if m.STOP:
            return
        m.tap(PET_FEED_KEY, 0.10)
        # 마지막 tap 뒤엔 짧게, 사이엔 길게 (macro_red 패턴: 0.40 / 0.20)
        m.rsleep(0.40 if i < PET_FEED_COUNT - 1 else 0.20, 0.2)


def _get_home_mm_x() -> int:
    """잠수 시작 위치 — 미니맵 X 좌표를 1회 확보."""
    for _ in range(15):
        if m.STOP:
            return None
        screen = m.grab()
        pos = m.find_char_minimap_pos(screen)
        if pos is not None:
            return pos[0]
        time.sleep(0.2)
    return None


def _load_safe_bounds():
    """idle_safe_config.json 읽어 (safe_min, safe_max) 반환. 없으면 (None, None)."""
    if not os.path.exists(SAFE_CONFIG_PATH):
        return (None, None)
    try:
        with open(SAFE_CONFIG_PATH, encoding='utf-8') as f:
            cfg = json.load(f)
        return (int(cfg.get('safe_mm_x_min')), int(cfg.get('safe_mm_x_max')))
    except Exception as e:
        print(f'[!] {SAFE_CONFIG_PATH} 읽기 실패: {e}')
        return (None, None)


def _pick_wander_dir(home_mm_x, safe_min, safe_max) -> str:
    """home과 safe 한계 거리 비교해 더 여유 있는 쪽 반환 (auto 모드용)."""
    if home_mm_x is None or safe_min is None or safe_max is None:
        return 'left'
    left_room  = home_mm_x - safe_min  # 좌측으로 갈 수 있는 거리
    right_room = safe_max - home_mm_x  # 우측으로 갈 수 있는 거리
    return 'left' if left_room >= right_room else 'right'


def _short_wander(home_mm_x, safe_min, safe_max):
    """한 방향으로 잠깐 → 미니맵 좌표 보며 원래 자리 복귀.
    safe_min/max가 주어지면 hold 중에도 한계 닿으면 즉시 중단."""
    direction = _pick_wander_dir(home_mm_x, safe_min, safe_max) if WANDER_DIR == 'auto' else WANDER_DIR
    opposite = 'right' if direction == 'left' else 'left'

    if home_mm_x is None:
        print(f'[wander] 좌표 없음 — 시간 기반 흔들기 ({direction})')
        m.key_down(direction); time.sleep(WANDER_HOLD_SEC); m.key_up(direction)
        time.sleep(0.1)
        m.key_down(opposite); time.sleep(WANDER_HOLD_SEC); m.key_up(opposite)
        return

    # 1단계: direction로 hold — 한계 도달 시 중도 중단
    m.key_down(direction)
    t0 = time.time()
    stop_reason = 'timeout'
    while time.time() - t0 < WANDER_HOLD_SEC and not m.STOP:
        screen = m.grab()
        pos = m.find_char_minimap_pos(screen)
        if pos is not None:
            cx = pos[0]
            if direction == 'left' and safe_min is not None and cx <= safe_min + WANDER_SAFE_MARGIN:
                stop_reason = f'좌측 한계 ({cx}<={safe_min}+{WANDER_SAFE_MARGIN})'
                break
            if direction == 'right' and safe_max is not None and cx >= safe_max - WANDER_SAFE_MARGIN:
                stop_reason = f'우측 한계 ({cx}>={safe_max}-{WANDER_SAFE_MARGIN})'
                break
        time.sleep(WANDER_POLL_SEC)
    m.key_up(direction)
    time.sleep(0.12)

    # 2단계: 반대로 walk → home 좌표 복귀까지
    m.key_down(opposite)
    t0 = time.time()
    cur_x = home_mm_x
    while time.time() - t0 < WANDER_RETURN_TIMEOUT and not m.STOP:
        screen = m.grab()
        pos = m.find_char_minimap_pos(screen)
        if pos is not None:
            cur_x = pos[0]
            if direction == 'left':
                if cur_x >= home_mm_x - WANDER_HOME_TOL:
                    break
            else:
                if cur_x <= home_mm_x + WANDER_HOME_TOL:
                    break
        time.sleep(WANDER_POLL_SEC)
    m.key_up(opposite)
    print(f'[wander] dir={direction} home={home_mm_x} → cur={cur_x} (hold stop: {stop_reason})')


def main():
    keyboard.add_hotkey('f12', _stop)
    keyboard.add_hotkey('f11', _save_lie_snapshot)

    print('=' * 60)
    print('  잠수 + 버프 + AFK 흔들기')
    print('=' * 60)
    print(f"  버프 키 '{BUFF_KEY}', 주기 {BUFF_INTERVAL_SEC:.0f}s (주변에 다른 유저 있을 때만)")
    print(f"  펫 먹이 키 '{PET_FEED_KEY}' x{PET_FEED_COUNT}, 주기 {PET_FEED_INTERVAL_SEC/60:.0f}분")
    print(f'  AFK 왕복 주기 {WANDER_INTERVAL_SEC:.0f}s, 방향 {WANDER_DIR}')
    if m.LIE_ENABLED:
        print('  거짓말 탐지기 자동 풀이 ON')
    else:
        print(f'  [!] lie 템플릿 없음 ({m.LIE_TEMPLATE}) — lie 감지 비활성')
    print('  F11 = lie 화면 스냅샷 (거짓말 탐지기 떴는데 못 잡을 때 누르세요)')
    print('  F12 = 긴급 정지')
    print()

    # 매 실행마다 미니맵 셋업 — 해상도/창 위치 매번 달라질 수 있어 재캡처 필요
    _run_minimap_setup()
    if not _reload_minimap_cfg():
        print('[!] minimap_config_red.json 없음 — 셋업에서 저장(s) 안 함, 종료')
        return

    # 셋업 끝난 뒤 게임창 위치 다시 잡기 (셋업 도중 창 이동했을 수도)
    if not m.refresh_game_region():
        print('[!] 게임창 못 찾음 — 종료')
        return

    # 해상도/미니맵 변경 감지 시 자동 setup — 일치하면 생략
    _ensure_shop_coords_fresh()
    m.reload_shop_coords()              # setup 실행됐든 안 됐든 최신 파일 기준으로 좌표 갱신
    _ensure_safe_config_fresh()
    # idle_safe_setup이 돌면 그 안에서 minimap도 다시 잡힘 → 한 번 더 동기화
    _reload_minimap_cfg()
    m.refresh_game_region()

    home_mm_x = _get_home_mm_x()
    if home_mm_x is None:
        print('[!] 미니맵 위치 못 잡음 — 좌표 기반 복귀 비활성 (시간 기반 fallback)')
    else:
        print(f'[+] 잠수 위치 등록: mm_x={home_mm_x}')

    safe_min, safe_max = _load_safe_bounds()
    if safe_min is None or safe_max is None:
        print(f'[!] {SAFE_CONFIG_PATH} 없음 — 안전 한계 미설정. '
              f'먼저 idle_safe_setup.py 실행 권장 (낭떠러지 보호 없음)')
    else:
        width = safe_max - safe_min
        print(f'[+] 안전 한계 로드: mm_x ∈ [{safe_min}, {safe_max}] (폭 {width}px)')
        if width < 2 * (WANDER_SAFE_MARGIN + WANDER_HOME_TOL):
            print(f'[!] 안전폭 {width}px가 좁아 wander 마진 부족 위험. '
                  f'idle_safe_setup.py로 더 넓게 잡거나 WANDER_HOLD_SEC을 더 줄이세요')
        if home_mm_x is not None and not (safe_min <= home_mm_x <= safe_max):
            print(f'[!!] 주의: 잠수 위치 mm_x={home_mm_x}가 한계 밖! '
                  f'캐릭이 안전 영역 안에 있는지 확인하세요')

    start_ts = time.time()
    last_region_refresh = start_ts
    last_buff_cast = start_ts
    last_wander = start_ts
    last_inv_check = start_ts
    last_pet_feed = start_ts
    last_lie_debug = start_ts
    last_log = 0.0
    lie_count = 0
    buff_count = 0
    wander_count = 0
    shop_count = 0
    pet_count = 0

    while not m.STOP:
        now = time.time()

        if now - last_region_refresh > GAME_REGION_REFRESH_SEC:
            m.refresh_game_region()
            last_region_refresh = now

        screen = m.grab()

        # lie 감지 — 최우선
        if m.LIE_ENABLED and m.lie_detected(screen):
            print(f'[!] 거짓말 탐지기 감지 → 풀이')
            if m.handle_lie_detector():
                lie_count += 1
                print(f'[+] lie 해제 (누적 {lie_count})')
                # 풀이 후엔 다른 동작 잠깐 미룸
                last_buff_cast = time.time()
                last_wander = time.time()
            else:
                print('[!!] lie 해제 실패 — STOP')
                break
            time.sleep(POLL_INTERVAL_SEC)
            continue

        # lie 매칭 점수 진단 — 임계값 못 넘는 경우 추적
        if LIE_DEBUG and m.LIE_ENABLED and now - last_lie_debug >= LIE_DEBUG_INTERVAL_SEC:
            last_lie_debug = now
            r = _lie_match_score()
            if r is not None:
                val, loc = r
                flag = '  *** OVER threshold ***' if val >= m.LIE_THRESHOLD else ''
                print(f'[lie-dbg] score={val:.3f} threshold={m.LIE_THRESHOLD} loc={loc}{flag}')

        # 인벤 가득 → auto_shop (잠수 중에도 거래/줍기로 찰 수 있음)
        if now - last_inv_check >= INV_CHECK_INTERVAL_SEC:
            last_inv_check = now
            if m.inv_trigger_full(screen):
                print('[idle] 인벤 트리거 → auto_shop()')
                ok = m.auto_shop()
                if ok:
                    shop_count += 1
                    print(f'[+] auto_shop 완료 (누적 {shop_count})')
                else:
                    print('[!] auto_shop 실패 — 계속 진행')
                # 상점 다녀온 직후 wander/버프 잠깐 미룸 (자세 안정화)
                last_buff_cast = time.time()
                last_wander = time.time()
                time.sleep(POLL_INTERVAL_SEC)
                continue

        # 펫 먹이 — 15분 주기 (±jitter, macro_red 패턴)
        if now - last_pet_feed >= PET_FEED_INTERVAL_SEC:
            _feed_pet()
            pet_count += PET_FEED_COUNT
            last_pet_feed = now + random.uniform(-PET_FEED_JITTER_SEC, PET_FEED_JITTER_SEC)

        # 버프 — 주기 도래 + 미니맵 주황 점 근처
        if now - last_buff_cast >= BUFF_INTERVAL_SEC:
            my_pos = m.find_char_minimap_pos(screen)
            if _party_nearby(screen, my_pos):
                _cast_buff()
                buff_count += 1
                last_buff_cast = now
            # 근처 없으면 last_buff_cast 갱신 안 함 → 다음 polling 때 다시 검사

        # AFK 왕복
        if now - last_wander >= WANDER_INTERVAL_SEC:
            _short_wander(home_mm_x, safe_min, safe_max)
            wander_count += 1
            last_wander = time.time()

        if now - last_log > IDLE_LOG_SEC:
            elapsed_min = (now - start_ts) / 60.0
            print(f'[idle] {elapsed_min:.1f}분 — lie {lie_count}, buff {buff_count}, '
                  f'wander {wander_count}, shop {shop_count}, pet {pet_count}')
            last_log = now

        time.sleep(POLL_INTERVAL_SEC)

    # 안전: 눌려있을 수 있는 키 풀기
    for k in ('left', 'right', 'up', 'down', WANDER_DIR):
        try:
            m.key_up(k)
        except Exception:
            pass

    print(f'\n정지 ({(time.time()-start_ts)/60:.1f}분 — '
          f'lie {lie_count}, buff {buff_count}, wander {wander_count}, '
          f'shop {shop_count}, pet {pet_count})')


if __name__ == '__main__':
    main()
