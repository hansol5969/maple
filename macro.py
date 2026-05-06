"""
MapleStory 사설서버 자동사냥 (이미지 기반)
직업: I/L 마법사 62
- 캐릭터 인식: 미니맵 캐릭터 점 (색상 검출) + 화면 중앙 가정
- 몹 인식: 화면 템플릿 매칭
- 이동: 텔레포트(space) 위주
- 공격: s
- 펫 먹이: 0  (PET_FEED_INTERVAL 마다 자동)
- HP/MP/버프는 펫이 처리
- 거짓말 탐지기: lie_title.png 매칭되면 키 떼고 비프음, 사람이 풀어줘야 재개

준비
1) templates/mob1.png, mob2.png, lie_title.png 준비 (nickname.png는 더 이상 사용 안 함)
2) python minimap_setup.py — 미니맵 영역 + 캐릭터 점 색 잡기 → minimap_config.json 생성
3) 게임 창모드 + 포커스
4) python macro.py  (F12 = 긴급정지)
"""

import time
import os
import json
import random
import winsound
import ctypes
import cv2
import numpy as np
import mss
import pydirectinput
import keyboard
from dataclasses import dataclass
from typing import Optional


# ============================================================
# DirectInput scancode 송신 — pydirectinput/keyboard가 일부 키를 메이플에 못 보내는 케이스 우회
# ============================================================
class _KbInput(ctypes.Structure):
    _fields_ = [
        ('wVk', ctypes.c_ushort),
        ('wScan', ctypes.c_ushort),
        ('dwFlags', ctypes.c_ulong),
        ('time', ctypes.c_ulong),
        ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ('dx', ctypes.c_long), ('dy', ctypes.c_long),
        ('mouseData', ctypes.c_ulong), ('dwFlags', ctypes.c_ulong),
        ('time', ctypes.c_ulong), ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HwInput(ctypes.Structure):
    _fields_ = [('uMsg', ctypes.c_ulong), ('wParamL', ctypes.c_short), ('wParamH', ctypes.c_ushort)]


class _InputUnion(ctypes.Union):
    _fields_ = [('ki', _KbInput), ('mi', _MouseInput), ('hi', _HwInput)]


class _Input(ctypes.Structure):
    _fields_ = [('type', ctypes.c_ulong), ('ii', _InputUnion)]


_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP       = 0x0002
_KEYEVENTF_SCANCODE    = 0x0008
_INPUT_KEYBOARD        = 1

# DirectInput scancode 표 (US 키보드)
SCAN = {
    'a': 0x1E, 'b': 0x30, 'c': 0x2E, 'd': 0x20, 'e': 0x12,
    'f': 0x21, 'g': 0x22, 'h': 0x23, 'i': 0x17, 'j': 0x24,
    'k': 0x25, 'l': 0x26, 'm': 0x32, 'n': 0x31, 'o': 0x18,
    'p': 0x19, 'q': 0x10, 'r': 0x13, 's': 0x1F, 't': 0x14,
    'u': 0x16, 'v': 0x2F, 'w': 0x11, 'x': 0x2D, 'y': 0x15, 'z': 0x2C,
    '0': 0x0B, '1': 0x02, '2': 0x03, '3': 0x04, '4': 0x05,
    '5': 0x06, '6': 0x07, '7': 0x08, '8': 0x09,
    'space': 0x39, 'enter': 0x1C, 'esc': 0x01, 'tab': 0x0F,
    'shift': 0x2A, 'ctrl': 0x1D, 'alt': 0x38,
    'left': 0x4B, 'right': 0x4D, 'up': 0x48, 'down': 0x50,
}
_EXTENDED_KEYS = {'left', 'right', 'up', 'down'}


def _send_scan(key: str, keyup: bool):
    sc = SCAN.get(key)
    if sc is None:
        # 모르는 키는 pydirectinput로 fallback
        if keyup:
            pydirectinput.keyUp(key)
        else:
            pydirectinput.keyDown(key)
        return
    flags = _KEYEVENTF_SCANCODE
    if keyup:
        flags |= _KEYEVENTF_KEYUP
    if key in _EXTENDED_KEYS:
        flags |= _KEYEVENTF_EXTENDEDKEY
    extra = ctypes.c_ulong(0)
    ki = _KbInput(0, sc, flags, 0, ctypes.pointer(extra))
    inp = _Input(_INPUT_KEYBOARD, _InputUnion(ki=ki))
    ctypes.windll.user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


def key_down(key: str):
    _send_scan(key, keyup=False)


def key_up(key: str):
    _send_scan(key, keyup=True)

try:
    import pygetwindow as gw
    HAS_GW = True
except ImportError:
    HAS_GW = False

# ============================================================
# 설정 — 본인 환경에 맞게 수정
# ============================================================

# 키 바인딩 (게임 내 단축키 N창과 일치시킬 것)
ATTACK_KEY    = 's'        # 공격 스킬
TELEPORT_KEY  = 'space'    # 텔레포트 (이동 주력)
JUMP_KEY      = 'x'        # 점프 (아래 점프 = down + 점프)
PICKUP_KEY    = 'z'        # 줍기
PET_FEED_KEY  = '0'        # 펫 먹이

# 군집/사거리 (픽셀 단위)
AOE_RADIUS_X     = 600   # 광역 스킬 가로 반경 (화면 픽셀, 3126 너비의 ~19%)
AOE_MIN_CLUSTER  = 3     # 군집으로 인정할 최소 몹 수
MOB_DETECT_EVERY = 8     # 사이클 N번에 1번 mob 검출
CLUSTER_DIR_COOLDOWN = 5.0  # cluster 기반 stuck_dir 변경 후 N초 동안 재변경 안 함
HUNT_BAND_Y_RATIO_TOP    = 0.70  # mob 검출 영역 — 화면 70~88% Y 범위 (사냥 라인만)
HUNT_BAND_Y_RATIO_BOTTOM = 0.88
ATTACK_COOLDOWN  = 0.08  # 시전 간격(초) — 더 빠르게 (멈칫 최소화)
SINGLE_RANGE_X   = 240   # 단일 사거리
ARRIVAL_DEADZONE = 30    # best_x 도착 허용 오차
Y_TOLERANCE      = 120   # 같은 층으로 인정할 Y 차이 (해상도 큼 → 넉넉히)
CHAR_Y_RATIO     = 0.80  # 화면 높이 대비 캐릭 발 위치 (메이플은 중앙보다 아래)
STUCK_SECONDS    = 5.0   # 이 시간 동안 행동 없으면 방향 반전

# 텔레포트
TELEPORT_COOLDOWN   = 0.35  # 텔레포트 시전 간격(초)
TELEPORT_TRIGGER_DX = 90    # 이 이상 떨어지면 텔레포트, 아니면 짧게 걷거나 그 자리 공격

# 패트롤(몹 검출 무관, 단순 무한공격) 모드
PATROL_HOLD_SECONDS     = 1.0   # 한 자리에서 공격 머무는 시간 후 텔포 — 몹 다 잡을 시간
TP_AFTER_ATTACK_GUARD   = 0.0   # 텔포 직후 공격 가드 없음 — 멈칫 시 공격 즉시
PATROL_REVERSE_SECONDS  = 30.0  # 한 방향 직진 — stuck 감지가 양 끝에서 반전 우선, 시간은 안전장치
PATROL_EDGE_RATIO       = 0.05  # 양 끝 5% zone에서 자동 반대
PATROL_LEARN_THRESHOLD  = 80    # mm 범위가 이 값 이상이어야 위치 기반 방향 활성
PATROL_SETUP_SECONDS    = 50    # 처음 N초는 시간 기반 반전만 (학습 더 길게)
ATTACK_DOWN_SECONDS     = 0.06  # 공격 키 누름 시간

# 주기 작업
PICKUP_INTERVAL   = 1e9    # 줍기 비활성 (펫이 처리)
PET_FEED_INTERVAL = 600.0  # 펫 먹이 주기(초) — 10분

# 매칭 임계값 (0.0 ~ 1.0, 높을수록 엄격)
CHAR_THRESHOLD = 0.80
MOB_THRESHOLD  = 0.60

# 템플릿 경로
CHAR_TEMPLATE = 'templates/nickname.png'
MOB_TEMPLATES = [
    'templates/mob1.png',
    'templates/mob2.png',
]

# 거짓말 탐지기 / 안티봇 팝업
# 팝업 제목 부분만 잘라서 lie_title.png 한 장만 사용 (작아서 빠르고 매번 동일해서 신뢰성 높음)
LIE_TEMPLATE      = 'templates/lie_title.png'
LIE_THRESHOLD     = 0.85   # 팝업은 정확히 매칭되어야 오탐 적음
LIE_CHECK_EVERY   = 8      # N프레임마다 1번만 체크 (CPU 절약)
LIE_HANDLE_MODE   = 'pause'  # 'pause' = 정지+경보+대기, 'stop' = 그대로 종료
LIE_BEEP_INTERVAL = 1.0    # 경보음 주기(초)
LIE_MAX_WAIT_SEC  = 300    # 5분 안에 안 풀리면 강제 종료

# 게임창 제목 키워드 (사설서버 클라이언트 제목 일부)
# IDE/브라우저 등에 'Maple'이 들어가면 잘못 매칭되므로 충분히 구체적인 토큰을 쓸 것
GAME_WINDOW_TITLE = 'MapleStory Worlds'

# 시작 전 대기 (게임 창 포커스 옮길 시간)
START_DELAY = 3.0

# ============================================================
# 코드 (수정 불필요)
# ============================================================

LEFT, RIGHT = 'left', 'right'
STOP = False


@dataclass
class Point:
    x: int
    y: int


def _stop():
    global STOP
    STOP = True


def find_game_region(title_keyword: str):
    if not HAS_GW:
        return None
    try:
        wins = [
            w for w in gw.getAllWindows()
            if title_keyword.lower() in (w.title or '').lower()
            and w.width > 100 and w.height > 100
        ]
        if not wins:
            return None
        w = wins[0]
        return {'left': w.left, 'top': w.top, 'width': w.width, 'height': w.height}
    except Exception:
        return None


_sct = mss.mss()
GAME_REGION = find_game_region(GAME_WINDOW_TITLE) or _sct.monitors[1]

LIE_ENABLED = os.path.exists(LIE_TEMPLATE)

# 미니맵 설정 (minimap_setup.py로 생성)
MINIMAP_CONFIG_PATH = 'minimap_config.json'
MINIMAP_CFG = None
if os.path.exists(MINIMAP_CONFIG_PATH):
    with open(MINIMAP_CONFIG_PATH, encoding='utf-8') as _f:
        MINIMAP_CFG = json.load(_f)


def grab():
    img = np.array(_sct.grab(GAME_REGION))
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def find_one(screen, template_path: str, threshold: float) -> Optional[Point]:
    tpl = cv2.imread(template_path)
    if tpl is None:
        return None
    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    _, val, _, loc = cv2.minMaxLoc(res)
    if val < threshold:
        return None
    h, w = tpl.shape[:2]
    return Point(loc[0] + w // 2, loc[1] + h // 2)


def find_all(screen, template_path: str, threshold: float) -> list:
    tpl = cv2.imread(template_path)
    if tpl is None:
        return []
    h, w = tpl.shape[:2]
    pts = []
    for variant in (tpl, cv2.flip(tpl, 1)):
        res = cv2.matchTemplate(screen, variant, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        pts.extend(Point(int(x + w / 2), int(y + h / 2)) for x, y in zip(xs, ys))
    return _dedupe(pts, min_dist=max(w, h) // 2)


def _dedupe(points, min_dist):
    out = []
    for p in points:
        if all(abs(p.x - q.x) > min_dist or abs(p.y - q.y) > min_dist for q in out):
            out.append(p)
    return out


_held: Optional[str] = None
_held_attack = False


def hold(key):
    global _held
    if _held == key:
        return
    if _held:
        key_up(_held)
    key_down(key)
    _held = key


def release():
    global _held
    if _held:
        key_up(_held)
        _held = None


def attack_hold():
    global _held_attack
    if not _held_attack:
        key_down(ATTACK_KEY)
        _held_attack = True


def attack_release():
    global _held_attack
    if _held_attack:
        key_up(ATTACK_KEY)
        _held_attack = False


def jitter(base: float, pct: float = 0.25) -> float:
    """base에 ±pct 만큼 랜덤 노이즈."""
    return base * (1.0 + random.uniform(-pct, pct))


def rsleep(base: float, pct: float = 0.25):
    time.sleep(max(0.0, jitter(base, pct)))


def tap(key, dur=0.05):
    """ctypes SendInput scancode — DirectX 게임이 가장 잘 인식.
    키업 후 짧은 안정화 — 다음 키 입력과 큐 충돌 회피."""
    key_down(key)
    rsleep(dur, 0.35)
    key_up(key)
    rsleep(0.02, 0.2)


def teleport(direction: str):
    """방향키 + 텔포 키. 끝에 공격 두 번 시전 — 텔포 직후 멈칫 최소화."""
    attack_release()
    release()
    key_down(direction)
    rsleep(0.12, 0.2)
    key_down(TELEPORT_KEY)
    rsleep(0.05, 0.2)
    key_up(TELEPORT_KEY)
    rsleep(0.03, 0.2)
    key_up(direction)
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)


def jump_teleport(direction: str):
    """끝 박힘 탈출용. 점프 + 공중 텔포. 끝에 공격 키 시전 — 멈칫 줄임."""
    attack_release()
    release()
    key_down(direction)
    rsleep(0.06, 0.3)
    key_down(JUMP_KEY)
    rsleep(0.06, 0.3)
    key_up(JUMP_KEY)
    rsleep(0.12, 0.2)
    key_down(TELEPORT_KEY)
    rsleep(0.05, 0.3)
    key_up(TELEPORT_KEY)
    key_up(direction)
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)


def drop_down():
    """아래 점프: ↓ 누른 채 점프키 → 한 층 내려감. 끝에 공격 키 — 멈칫 줄임."""
    attack_release()
    release()
    key_down('down')
    rsleep(0.18, 0.2)
    key_down(JUMP_KEY)
    rsleep(0.10, 0.2)
    key_up(JUMP_KEY)
    rsleep(0.12, 0.2)
    key_up('down')
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)


def move_toward(char_x: int, target_x: int, last_tp_time: float, now: float) -> tuple:
    """
    target_x로 이동. 거리에 따라 텔레포트 / 짧게 걷기 / 도착 판정 결정.
    Returns: ('arrived'|'teleport'|'walk', new_last_tp_time)
    """
    dx = target_x - char_x
    if abs(dx) <= ARRIVAL_DEADZONE:
        return 'arrived', last_tp_time
    direction = LEFT if dx < 0 else RIGHT
    tp_trigger = jitter(TELEPORT_TRIGGER_DX, 0.15)
    tp_cool    = jitter(TELEPORT_COOLDOWN,   0.2)
    if abs(dx) >= tp_trigger and (now - last_tp_time) >= tp_cool:
        teleport(direction)
        return 'teleport', now
    # 가까운데 데드존 밖 → 짧게 걸어서 정렬
    tap(direction, 0.04)
    return 'walk', last_tp_time


def lie_detected(screen) -> bool:
    if not LIE_ENABLED:
        return False
    return find_one(screen, LIE_TEMPLATE, LIE_THRESHOLD) is not None


# 캐릭터 마커 blob 크기 범위 (픽셀 면적). NPC/포탈/퀘스트 마커는 이 밖이면 자동 제외.
CHAR_BLOB_AREA_MIN = 3
CHAR_BLOB_AREA_MAX = 40

# blob 추적: 직전 프레임 위치에 가까운 blob을 우선 선택
_last_char_mm_pos = None  # (x, y)


def find_char_minimap_pos(screen):
    """
    미니맵에서 캐릭터 점의 (X, Y) 반환.
    - 본인 캐릭은 보통 미니맵에서 가장 큰 노란 blob (area 18 vs NPC area 9)
    - 항상 area 가장 큰 거 추종 → 2층 점프 등 큰 위치 변화에도 잘 따라감
    - 동률이면 직전 위치 가까운 거 (안정성)
    """
    global _last_char_mm_pos
    if MINIMAP_CFG is None:
        return None
    x1, y1, x2, y2 = MINIMAP_CFG['minimap_rect']
    mm = screen[y1:y2, x1:x2]
    color = np.array(MINIMAP_CFG['char_color_bgr'], dtype=int)
    tol = MINIMAP_CFG.get('tolerance', 25)
    low = np.clip(color - tol, 0, 255).astype(np.uint8)
    high = np.clip(color + tol, 0, 255).astype(np.uint8)
    mask = cv2.inRange(mm, low, high)

    n_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    candidates = []
    for i in range(1, n_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if CHAR_BLOB_AREA_MIN <= area <= CHAR_BLOB_AREA_MAX:
            cx, cy = centroids[i]
            candidates.append((area, int(cx), int(cy)))

    if not candidates:
        return None

    if _last_char_mm_pos is not None:
        lx, ly = _last_char_mm_pos
        candidates.sort(key=lambda c: (-c[0], (c[1] - lx) ** 2 + (c[2] - ly) ** 2))
    else:
        candidates.sort(key=lambda c: -c[0])

    _, cx, cy = candidates[0]
    _last_char_mm_pos = (cx, cy)
    return (cx, cy)


def char_screen_position() -> Point:
    """카메라 추적이라 X는 거의 화면 중앙. Y는 화면 중앙이 아니라 화면 아래쪽(메이플 카메라 특성)."""
    return Point(GAME_REGION['width'] // 2, int(GAME_REGION['height'] * CHAR_Y_RATIO))


def handle_lie_detector():
    """모든 키 떼고 경보 울리며 사람이 풀 때까지 대기. 풀리면 True, 타임아웃이면 False."""
    release()
    print('[!] 거짓말 탐지기 감지 — 매크로 정지. 직접 풀어주세요.')
    start = time.time()
    last_beep = 0.0
    while not STOP:
        now = time.time()
        if now - start > LIE_MAX_WAIT_SEC:
            print('[!] 타임아웃 — 매크로 종료')
            return False
        if now - last_beep >= LIE_BEEP_INTERVAL:
            try:
                winsound.Beep(1200, 250)
            except Exception:
                pass
            last_beep = now
        screen = grab()
        if not lie_detected(screen):
            print('[+] 팝업 사라짐 — ~5초 후 사냥 재개')
            rsleep(5.0, 0.3)
            return True
        rsleep(0.3, 0.3)
    return False


def nearest_mob(char: Point, mobs: list) -> Optional[Point]:
    same = [m for m in mobs if abs(m.y - char.y) <= Y_TOLERANCE]
    if not same:
        return None
    return min(same, key=lambda m: abs(m.x - char.x))


def best_cluster(char: Point, mobs: list, radius: int):
    """같은 층 몹 중 AoE 한 번에 가장 많이 맞출 수 있는 X와 개수"""
    same = [m for m in mobs if abs(m.y - char.y) <= Y_TOLERANCE]
    if not same:
        return None, 0
    best_x, best_n = None, 0
    for cand in (m.x for m in same):
        n = sum(1 for m in same if abs(m.x - cand) <= radius)
        if n > best_n:
            best_x, best_n = cand, n
    return best_x, best_n


STUCK_MINIMAP_DELTA = 5   # 미니맵 X가 이 픽셀보다 적게 움직이면 정체 — 민감히 잡아 walk fallback 트리거
STUCK_MINIMAP_SECONDS = 2.0  # 빨리 감지 — 끝 박힘 시 시간 낭비 줄임

# 2층 감지 — 미니맵 Y가 1층 기준선보다 위로(=Y가 작아짐) FLOOR2_DELTA_Y 이상이면 2층으로 봄
FLOOR2_DELTA_Y       = 6     # 미니맵에서 1층/2층 Y 차이 (작은 미니맵이라 픽셀 단위가 작음)
FLOOR2_HOLD_SECONDS  = 0.6   # 이 시간 동안 위에 있으면 2층 확정
DROP_DOWN_COOLDOWN   = 1.2   # 아래 텔포 시도 간격


def hunt():
    last_action  = time.time()
    last_pickup  = time.time()
    last_attack  = 0.0
    last_tp      = 0.0
    last_petfeed = time.time()  # 시작 직후 바로 안 먹임
    stuck_dir    = RIGHT
    frame        = 0

    last_mm_x       = None
    last_mm_move_ts = time.time()

    floor1_y          = MINIMAP_CFG.get('floor1_y_baseline') if MINIMAP_CFG else None
    on_floor2_since   = None
    last_drop_down    = 0.0

    last_log_ts = 0.0
    hunt_started = time.time()
    last_force_reverse = time.time()
    stuck_attempts = 0  # 연속 stuck 횟수, fallback 결정용
    mm_observed_min = None
    mm_observed_max = None
    attacks_in_window = 0
    tps_in_window = 0
    last_cluster_change = 0.0

    while not STOP:
        screen = grab()
        frame += 1
        now = time.time()

        # 0) 거짓말 탐지기 체크 (N프레임마다)
        if LIE_ENABLED and frame % LIE_CHECK_EVERY == 0 and lie_detected(screen):
            if LIE_HANDLE_MODE == 'stop':
                _stop()
                break
            ok = handle_lie_detector()
            if not ok:
                _stop()
                break
            last_action     = time.time()
            last_pickup     = time.time()
            last_petfeed    = time.time()
            last_mm_move_ts = time.time()
            on_floor2_since = None
            continue

        # 캐릭터 화면 좌표는 항상 중앙으로 가정 (카메라 추적)
        char = char_screen_position()

        # 미니맵 좌표 (월드)
        mm_pos = find_char_minimap_pos(screen)
        mm_x, mm_y = (mm_pos if mm_pos else (None, None))
        if mm_x is not None:
            if last_mm_x is None or abs(mm_x - last_mm_x) > STUCK_MINIMAP_DELTA:
                last_mm_x = mm_x
                last_mm_move_ts = now
            # floor1 Y 기준선이 없으면 처음 관측값을 베이스라인으로
            if floor1_y is None:
                floor1_y = mm_y
            # 관찰 범위 학습 — 매크로 자동으로 양 끝 좌표 학습
            mm_observed_min = mm_x if mm_observed_min is None else min(mm_observed_min, mm_x)
            mm_observed_max = mm_x if mm_observed_max is None else max(mm_observed_max, mm_x)

        # 2층 감지 → 아래로 텔포
        if mm_y is not None and floor1_y is not None and mm_y < floor1_y - FLOOR2_DELTA_Y:
            if on_floor2_since is None:
                on_floor2_since = now
            elif now - on_floor2_since > FLOOR2_HOLD_SECONDS and now - last_drop_down > DROP_DOWN_COOLDOWN:
                print(f'[*] 2층 감지 (mm_y={mm_y}, base={floor1_y}) → 아래 점프')
                drop_down()
                last_drop_down = now
                on_floor2_since = now  # 한 번에 못 내려올 수도 있어서 갱신
                last_action = now
                last_mm_move_ts = now
                continue
        else:
            on_floor2_since = None

        # 군집 감지 — 좌하단 사냥 라인만 잘라서 매칭(매칭 영역 17%로 단축).
        # 가까운 군집이면 추가 공격 + 텔포 늦춤. 먼 군집이면 그쪽으로 stuck_dir 보정.
        if frame % MOB_DETECT_EVERY == 0:
            h = GAME_REGION['height']
            y_top = int(h * HUNT_BAND_Y_RATIO_TOP)
            y_bot = int(h * HUNT_BAND_Y_RATIO_BOTTOM)
            band = screen[y_top:y_bot, :]
            mobs = []
            for tpl in MOB_TEMPLATES:
                for m in find_all(band, tpl, MOB_THRESHOLD):
                    mobs.append(Point(m.x, m.y + y_top))
            char = char_screen_position()
            if len(mobs) >= AOE_MIN_CLUSTER:
                cluster_x, n = best_cluster(char, mobs, AOE_RADIUS_X)
                if cluster_x is not None and n >= AOE_MIN_CLUSTER:
                    if abs(cluster_x - char.x) < AOE_RADIUS_X:
                        # 캐릭이 군집 사거리 안에 있음 → 즉시 추가 공격 + 다음 텔포 늦춤
                        tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
                        last_attack = now
                        attacks_in_window += 1
                        last_tp = now
                        print(f'[cluster-attack] n={n} 사거리 안(dx={cluster_x - char.x:+d}) → 추가 공격 + tp 늦춤')
                    elif now - last_cluster_change > CLUSTER_DIR_COOLDOWN:
                        # 군집이 멀리 → 그쪽 방향
                        new_dir = LEFT if cluster_x < char.x else RIGHT
                        if new_dir != stuck_dir:
                            print(f'[cluster-dir] n={n} cluster_x={cluster_x} char_x={char.x} → {new_dir}')
                            stuck_dir = new_dir
                            last_force_reverse = now
                            last_cluster_change = now

        # 디버그: 1초마다 상태 한 줄 + 공격/텔포 카운트
        if now - last_log_ts > 1.0:
            print(f'[dbg] mm=({mm_x},{mm_y}) stuck_dir={stuck_dir} '
                  f'attacks_last_sec={attacks_in_window} tp_last_sec={tps_in_window}')
            attacks_in_window = 0
            tps_in_window = 0
            last_log_ts = now

        # 펫 먹이 주기 (두 번, 사이 ~0.5s)
        if now - last_petfeed > PET_FEED_INTERVAL:
            tap(PET_FEED_KEY)
            rsleep(0.5, 0.3)
            tap(PET_FEED_KEY)
            last_petfeed = now + random.uniform(-15.0, 15.0)  # 다음 주기도 ±15s 흔들기

        # 줍기 주기
        if now - last_pickup > PICKUP_INTERVAL:
            tap(PICKUP_KEY)
            rsleep(0.04, 0.5)
            tap(PICKUP_KEY)
            last_pickup = now + random.uniform(-0.4, 0.4)

        # stuck 감지 (미니맵 X 정체) — 끝에 박힘. 사냥 우선이라 walk 단계 없이 즉시 반전.
        mm_stuck = mm_x is not None and now - last_mm_move_ts > STUCK_MINIMAP_SECONDS
        if mm_stuck:
            stuck_dir = LEFT if stuck_dir == RIGHT else RIGHT
            print(f'[stuck-rev] mm_x={mm_x} → 점프+{stuck_dir}+텔포 (즉시 반전)')
            jump_teleport(stuck_dir)
            stuck_attempts = 0
            last_tp = now
            last_force_reverse = now
            last_mm_move_ts = now
            last_action = now
            continue
        elif mm_x is not None and last_mm_x is not None and abs(mm_x - last_mm_x) > STUCK_MINIMAP_DELTA:
            stuck_attempts = 0
        elif mm_x is not None and last_mm_x is not None and abs(mm_x - last_mm_x) > STUCK_MINIMAP_DELTA:
            stuck_attempts = 0

        # 위치 기반 [pos] 트리거 비활성 — 학습된 끝에 도달하자마자 반전이라 캐릭이 더 끝까지 못 감.
        # 시간 기반 반전(PATROL_REVERSE_SECONDS) + stuck 감지(끝에 박힘 시 점프 텔포)에만 의존.

        # 시간 기반 강제 반전 — 위치 기반이 안 잡히는 케이스 보조
        if now - last_force_reverse > jitter(PATROL_REVERSE_SECONDS, 0.15):
            stuck_dir = LEFT if stuck_dir == RIGHT else RIGHT
            last_force_reverse = now
            print(f'[periodic] 반전 → {stuck_dir}')

        # 공격: 짧은 tap을 ATTACK_COOLDOWN마다 반복 시전 (단, 텔포 직후 가드 시간 동안엔 안 함)
        if (now - last_attack >= jitter(ATTACK_COOLDOWN, 0.2)
                and now - last_tp >= TP_AFTER_ATTACK_GUARD):
            tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
            last_attack = now
            last_action = now
            attacks_in_window += 1

        # 텔포 시점
        if now - last_tp > jitter(PATROL_HOLD_SECONDS, 0.2):
            teleport(stuck_dir)
            last_tp = now
            last_action = now
            tps_in_window += 1

        rsleep(0.02, 0.3)

    attack_release()
    release()


def main():
    pydirectinput.PAUSE = 0.02
    keyboard.add_hotkey('f12', _stop)

    print(f'게임 영역: {GAME_REGION}')
    print(f'키: 공격={ATTACK_KEY!r}  텔포={TELEPORT_KEY!r}  점프={JUMP_KEY!r}  줍기={PICKUP_KEY!r}  펫먹이={PET_FEED_KEY!r}')
    print(f'펫 먹이 주기: {PET_FEED_INTERVAL:.0f}초')
    if MINIMAP_CFG:
        print(f'미니맵 설정: rect={MINIMAP_CFG["minimap_rect"]} color={MINIMAP_CFG["char_color_bgr"]} tol={MINIMAP_CFG.get("tolerance",25)}')
        base = MINIMAP_CFG.get('floor1_y_baseline')
        print(f'1층 Y 기준선: {base}  (2층 감지 임계 = base - {FLOOR2_DELTA_Y})')
    else:
        print('[!] 경고: minimap_config.json 없음 — minimap_setup.py 먼저 실행하세요')
    if LIE_ENABLED:
        print(f'거짓말 탐지기 템플릿: {LIE_TEMPLATE}')
    else:
        print(f'[!] 경고: {LIE_TEMPLATE} 없음 — 탐지기 감지 불가능')
    print(f'F12 = 긴급정지')
    print(f'{START_DELAY:.0f}초 후 시작 — 게임 창에 포커스 두세요')
    time.sleep(START_DELAY)

    try:
        hunt()
    finally:
        attack_release()
        release()
        print('정지됨')


if __name__ == '__main__':
    main()
