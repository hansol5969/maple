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
import subprocess
import sys
import winsound
import ctypes
import cv2
import numpy as np
import mss
import pyautogui
import pydirectinput
import keyboard
from dataclasses import dataclass
from datetime import datetime

# 듀얼·세로·고DPI 모니터에서 게임창 좌표가 가상화되지 않도록 Per-Monitor v2
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


# ---- 캡차 처리 중에만 로그 파일에 출력 (Tee) ----
class _Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, s):
        for st in self.streams:
            try: st.write(s); st.flush()
            except Exception: pass
    def flush(self):
        for st in self.streams:
            try: st.flush()
            except Exception: pass


_LIE_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'captcha_logs')
os.makedirs(_LIE_LOG_DIR, exist_ok=True)


class _LieLogger:
    """with 블록 안에서만 stdout/stderr를 파일에도 동시 출력."""
    def __init__(self):
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.path = os.path.join(_LIE_LOG_DIR, f'captcha_{ts}.log')
        self.f = None
        self.old_out = None
        self.old_err = None

    def __enter__(self):
        self.f = open(self.path, 'w', encoding='utf-8', buffering=1)
        self.f.write(f'===== 캡차 처리 시작: {datetime.now():%Y-%m-%d %H:%M:%S} =====\n')
        self.old_out = sys.stdout
        self.old_err = sys.stderr
        sys.stdout = _Tee(self.old_out, self.f)
        sys.stderr = _Tee(self.old_err, self.f)
        return self

    def __exit__(self, *exc):
        sys.stdout = self.old_out
        sys.stderr = self.old_err
        try:
            self.f.write(f'===== 종료: {datetime.now():%Y-%m-%d %H:%M:%S} =====\n')
            self.f.close()
        except Exception:
            pass
from typing import Optional

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = True  # 마우스 (0,0) 가면 중단


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
MOB_DETECT_ENABLED = False  # 군집 감지 — 비활성화. 효과 미미 + 매 8-12사이클마다 200-900ms 멈칫 유발
MOB_DETECT_EVERY = 12    # (활성화 시) 사이클 N번에 1번 mob 검출
MOB_DETECT_X_RADIUS = 900  # (활성화 시) 캐릭 중심 ±N px만 검사
PERF_WARN_MS     = 150   # 사이클이 이 시간 넘으면 [perf-warn] 출력 (텔포는 ~300ms 정상)
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

# 에스컬레이터 (안전한 곳 이동) — 인벤 가득 시 상점 가기 위해
ESCALATOR_X_MIN          = 410   # 입구 X 범위 시작
ESCALATOR_X_MAX          = 432   # 입구 X 범위 끝
ESCALATOR_Y_DELTA        = 10    # 사냥 라인 대비 mm_y가 이만큼 작아지면 "올라감" 판정
GOTO_ESC_TIMEOUT         = 30.0  # 전체 타임아웃(초)
GOTO_ESC_MAX_TRIES       = 8     # 위+텔포 최대 시도 횟수
GOTO_ESC_TP_TRIGGER_DX   = 80    # 이 이상 멀면 텔포, 미만이면 walk
GOTO_ESC_VERIFY_WAIT     = 0.5   # 위+텔포 후 mm_y 변화 확인 대기

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

# 인벤토리 / 휴대용 상점 좌표
# 좌표는 캘리브레이션 시점의 화면 절대 좌표 — 게임창 옮기면 자동 보정됨
# (refresh_game_region()으로 GAME_REGION 갱신 후 _abs() 헬퍼가 차이만큼 더해줌)
COORDS_CAL_GAME_LEFT = 433     # 좌표 잡았을 때의 게임창 left (mm_probe 출력에서 확인)
COORDS_CAL_GAME_TOP  = 172     # 좌표 잡았을 때의 게임창 top
COORDS_CAL_GAME_W    = 3126    # 좌표 잡았을 때의 게임창 width (스케일 보정 기준)
COORDS_CAL_GAME_H    = 1758    # 좌표 잡았을 때의 게임창 height (16:9)
CASH_TAB_ABS         = (3170, 318)
PORTABLE_SHOP_ABS    = (3090, 957)
SHOP_FIRST_SLOT_ABS  = (2060, 964)   # 상점 UI 등장 검증용 (열림 여부 std 체크)
SELL_ALL_BUTTON_ABS  = (2564, 597)   # 장비 일괄 판매 버튼
SHOP_CLOSE_ABS       = (1845, 603)
EQUIP_TAB_ABS        = (2744, 316)
INV_FIRST_SLOT_ABS   = (2748, 406)
INV_TRIGGER_ABS      = (3052, 910, 3147, 1007)  # x1, y1, x2, y2

INV_FILLED_STD_THRESHOLD = 30    # 빈 std≈8-11, 찬 std≈54-87 (slot_inspect로 측정)
SLOT_CHECK_SIZE          = 30    # 인벤 첫 칸 검사 영역 크기
INV_TRIGGER_CHECK_EVERY  = 30    # N 사이클마다 트리거 체크
SHOP_MAX_SELL_TRIES      = 32    # 판매 반복 최대 시도
GAME_REGION_REFRESH_EVERY = 600  # N 사이클마다 게임창 위치 재탐색 (창 이동 대응)

# 거짓말 탐지기 / 안티봇 팝업
# 팝업 제목 부분만 잘라서 lie_title.png 한 장만 사용 (작아서 빠르고 매번 동일해서 신뢰성 높음)
LIE_TEMPLATE      = 'templates/lie_title.png'
LIE_THRESHOLD     = 0.85   # 팝업은 정확히 매칭되어야 오탐 적음
LIE_CHECK_EVERY   = 60     # 영역 축소 + 60 사이클(~30초)마다 — 멈칫 빈도 더 감소
LIE_HANDLE_MODE   = 'pause'  # 'pause' = 정지+경보+대기, 'stop' = 그대로 종료
LIE_BEEP_INTERVAL = 1.0    # 경보음 주기(초)
LIE_MAX_WAIT_SEC  = 300    # 5분 안에 안 풀리면 강제 종료

# 캡차 통과 확인 다이얼로그 ("거짓말 탐지기 테스트에 무사히 통과...")
# 캡차 풀이 후 잠시 뒤 뜨는 성공 안내창 → ENTER로 닫기
# 매 프레임 매칭하면 무거우니 캡차 풀이 직후 CON_CHECK_WINDOW_SEC 동안만 polling
CON_TEMPLATE          = 'captcha_assets/con.png.png'
CON_THRESHOLD         = 0.80
CON_CHECK_EVERY       = 16
CON_CHECK_WINDOW_SEC  = 30.0  # 캡차 풀이 후 N초간만 polling 활성
CON_MAX_TRIES         = 6     # ENTER 시도 횟수 (창 사라질 때까지)

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

# 픽셀 거리 상수 자동 스케일링 — 캘리브레이션 게임창 대비 현재 게임창 비율로 보정
_SCALE_X = GAME_REGION['width']  / COORDS_CAL_GAME_W
_SCALE_Y = GAME_REGION['height'] / COORDS_CAL_GAME_H
AOE_RADIUS_X        = int(AOE_RADIUS_X        * _SCALE_X)
MOB_DETECT_X_RADIUS = int(MOB_DETECT_X_RADIUS * _SCALE_X)
SINGLE_RANGE_X      = int(SINGLE_RANGE_X      * _SCALE_X)
Y_TOLERANCE         = int(Y_TOLERANCE         * _SCALE_Y)

LIE_ENABLED = os.path.exists(LIE_TEMPLATE)
CON_ENABLED = os.path.exists(CON_TEMPLATE)

# 미니맵 설정 (minimap_setup.py로 생성)
MINIMAP_CONFIG_PATH = 'minimap_config.json'
MINIMAP_CFG = None
if os.path.exists(MINIMAP_CONFIG_PATH):
    with open(MINIMAP_CONFIG_PATH, encoding='utf-8') as _f:
        MINIMAP_CFG = json.load(_f)


def grab():
    # 보조 모니터·음수 좌표·세로 모드에서 mss가 검은 이미지를 잡을 때 PIL로 fallback
    bgr = None
    try:
        raw = np.array(_sct.grab(GAME_REGION))
        bgr = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        if float(bgr.mean()) >= 8:
            return bgr
    except Exception:
        pass
    try:
        from PIL import ImageGrab
        r = GAME_REGION
        bbox = (r['left'], r['top'], r['left'] + r['width'], r['top'] + r['height'])
        pil_img = ImageGrab.grab(bbox=bbox, all_screens=True)
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception:
        return bgr if bgr is not None else np.zeros((100, 100, 3), dtype=np.uint8)


def refresh_game_region() -> bool:
    """게임창 위치 다시 탐색해서 GAME_REGION 갱신. 못 찾으면 False."""
    global GAME_REGION
    new_region = find_game_region(GAME_WINDOW_TITLE)
    if new_region is None:
        return False
    if (new_region['left'] != GAME_REGION.get('left')
            or new_region['top'] != GAME_REGION.get('top')
            or new_region['width'] != GAME_REGION.get('width')
            or new_region['height'] != GAME_REGION.get('height')):
        print(f'[game-region] {GAME_REGION} → {new_region}')
        GAME_REGION = new_region
    return True


def _abs(x: int, y: int) -> tuple:
    """캘리브레이션 시점의 절대 좌표 → 현재 게임창 위치/크기 보정한 절대 좌표.
    게임창이 다른 크기로 떠도 (window/cal) 비율로 스케일 → 같은 UI 요소 클릭."""
    rel_x = x - COORDS_CAL_GAME_LEFT
    rel_y = y - COORDS_CAL_GAME_TOP
    sx = GAME_REGION['width']  / COORDS_CAL_GAME_W
    sy = GAME_REGION['height'] / COORDS_CAL_GAME_H
    return int(rel_x * sx + GAME_REGION['left']), int(rel_y * sy + GAME_REGION['top'])


def _game_rel(x: int, y: int) -> tuple:
    """캘리브레이션 절대 좌표 → 현재 game grab 영역 내 상대 좌표 (스케일 반영)."""
    rel_x = x - COORDS_CAL_GAME_LEFT
    rel_y = y - COORDS_CAL_GAME_TOP
    sx = GAME_REGION['width']  / COORDS_CAL_GAME_W
    sy = GAME_REGION['height'] / COORDS_CAL_GAME_H
    return int(rel_x * sx), int(rel_y * sy)


# SendInput 마우스 이벤트 (pyautogui보다 게임에서 안정적)
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP   = 0x0004


def click_at(x: int, y: int, double: bool = False) -> None:
    """SendInput 마우스 클릭. double=True면 더블클릭 (Windows OS 더블클릭 간격 안)."""
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.06)
    user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.03)
    user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    if double:
        time.sleep(0.08)  # OS 더블클릭 간격 (~500ms) 안에
        user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


class _ShopAborted(Exception):
    """auto_shop 도중 F12 등으로 중단됨."""
    pass


def _shop_check_stop():
    if STOP:
        print('[shop] !! F12 중단 감지')
        attack_release()
        release()
        raise _ShopAborted()


# 템플릿 캐시 — 매 사이클 cv2.imread 재호출 방지 (큰 멈칫 원인)
_SENTINEL = object()
_TPL_CACHE: dict = {}
_TPL_FLIP_CACHE: dict = {}


def _load_tpl(path: str):
    tpl = _TPL_CACHE.get(path, _SENTINEL)
    if tpl is _SENTINEL:
        tpl = cv2.imread(path)
        _TPL_CACHE[path] = tpl
    return tpl


def _load_tpl_flip(path: str):
    f = _TPL_FLIP_CACHE.get(path, _SENTINEL)
    if f is _SENTINEL:
        tpl = _load_tpl(path)
        f = cv2.flip(tpl, 1) if tpl is not None else None
        _TPL_FLIP_CACHE[path] = f
    return f


def find_one(screen, template_path: str, threshold: float) -> Optional[Point]:
    tpl = _load_tpl(template_path)
    if tpl is None:
        return None
    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    _, val, _, loc = cv2.minMaxLoc(res)
    if val < threshold:
        return None
    h, w = tpl.shape[:2]
    return Point(loc[0] + w // 2, loc[1] + h // 2)


def find_all(screen, template_path: str, threshold: float) -> list:
    tpl = _load_tpl(template_path)
    if tpl is None:
        return []
    h, w = tpl.shape[:2]
    pts = []
    for variant in (tpl, _load_tpl_flip(template_path)):
        if variant is None:
            continue
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


def up_teleport():
    """위+텔포 — 에스컬레이터/포탈 진입용."""
    attack_release()
    release()
    key_down('up')
    rsleep(0.10, 0.2)
    key_down(TELEPORT_KEY)
    rsleep(0.05, 0.2)
    key_up(TELEPORT_KEY)
    rsleep(0.03, 0.2)
    key_up('up')


def goto_escalator() -> bool:
    """
    에스컬레이터 위로 이동. 사냥하며 이동 (몹에 박히지 않게 공격 유지).
    - X를 ESCALATOR_X_MIN~MAX로 정렬 (거리 멀면 텔포, 가까우면 walk)
    - 정렬되면 위+텔포
    - mm_y가 사냥 라인보다 ESCALATOR_Y_DELTA 이상 작아지면 성공
    - 타임아웃 또는 최대 시도 초과 시 비프 + False
    """
    target_min, target_max = ESCALATOR_X_MIN, ESCALATOR_X_MAX
    target_center = (target_min + target_max) // 2
    base_y = MINIMAP_CFG.get('floor1_y_baseline') if MINIMAP_CFG else None

    print(f'[goto-esc] start (target X: {target_min}-{target_max}, '
          f'success: mm_y < {(base_y - ESCALATOR_Y_DELTA) if base_y else "?"})')

    start = time.time()
    tries = 0
    last_attack = 0.0
    last_tp = 0.0

    # 이동 우선 정책: 매 사이클 공격 보내지 않음.
    #   - teleport()가 내부에서 자동으로 attack 두 번 시전 → 거리 멀 때 공격 자연 발생
    #   - walk 단계(정밀 정렬)에서만 0.3초마다 한 번 짧게 attack
    while not STOP and time.time() - start < GOTO_ESC_TIMEOUT \
            and tries < GOTO_ESC_MAX_TRIES:
        screen = grab()
        pos = find_char_minimap_pos(screen)
        now = time.time()
        if pos is None:
            rsleep(0.08, 0.2)
            continue
        mm_x, mm_y = pos

        # 도착 확인 — 사냥 라인보다 위로 올라감
        if base_y is not None and mm_y < base_y - ESCALATOR_Y_DELTA:
            print(f'[goto-esc] 도착 mm=({mm_x},{mm_y}) tries={tries}')
            release()
            return True

        # 정렬됨 → 위+텔포
        if target_min <= mm_x <= target_max:
            tries += 1
            print(f'[goto-esc] 정렬 OK mm_x={mm_x} → up+tp #{tries}')
            up_teleport()
            last_tp = now
            rsleep(GOTO_ESC_VERIFY_WAIT, 0.2)
            continue

        # 정렬 이동
        dx = target_center - mm_x
        direction = LEFT if dx < 0 else RIGHT
        if abs(dx) >= GOTO_ESC_TP_TRIGGER_DX:
            # 텔포 — 자체적으로 attack 두 번 포함
            if now - last_tp >= jitter(TELEPORT_COOLDOWN, 0.2):
                teleport(direction)
                last_tp = now
                last_attack = now
        else:
            # walk — 거리에 비례한 시간만큼 방향키 누름 (멀수록 길게)
            #   dx=80: 0.25(cap), dx=40: 0.20, dx=20: 0.10, dx=10: 0.06(최소)
            walk_dur = max(0.06, min(0.25, abs(dx) / 200))
            tap(direction, walk_dur)
            # 공격은 0.5초마다 한 번만 (이동 우선)
            if now - last_attack >= 0.5:
                tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
                last_attack = now

        rsleep(0.04, 0.3)

    print(f'[goto-esc] 실패 tries={tries}, elapsed={time.time() - start:.1f}s')
    try:
        winsound.Beep(2000, 500)
    except Exception:
        pass
    release()
    attack_release()
    return False


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


def _center_region(screen, x_ratio=(0.20, 0.80), y_ratio=(0.10, 0.75)):
    """화면 중앙 영역만 잘라서 반환 — 캡차 다이얼로그 검색 영역 축소용."""
    H, W = screen.shape[:2]
    x1 = int(W * x_ratio[0]); x2 = int(W * x_ratio[1])
    y1 = int(H * y_ratio[0]); y2 = int(H * y_ratio[1])
    return screen[y1:y2, x1:x2]


def lie_detected(screen) -> bool:
    if not LIE_ENABLED:
        return False
    # 화면 전체 → 중앙 60%×65% 영역만 매칭 (시간 약 1/4로 감소)
    return find_one(_center_region(screen), LIE_TEMPLATE, LIE_THRESHOLD) is not None


def con_detected(screen) -> bool:
    if not CON_ENABLED:
        return False
    return find_one(_center_region(screen), CON_TEMPLATE, CON_THRESHOLD) is not None


def handle_con_dialog():
    """캡차 통과 안내창 — ENTER 보내고 사라질 때까지 최대 CON_MAX_TRIES회 시도."""
    release()
    attack_release()
    print('[*] 캡차 통과 안내창 감지 — ENTER 송신')
    for i in range(CON_MAX_TRIES):
        tap('enter', 0.05)
        rsleep(0.6, 0.2)
        if not con_detected(grab()):
            print(f'[+] 안내창 닫힘 ({i + 1}회 시도)')
            rsleep(0.8, 0.2)
            return True
    print('[!] 안내창이 여전히 남아있음 — 그래도 사냥 재개')
    return False


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

    # 파티원(주황 등) 오인식 방지 — 본인 점 색조(Hue)만 통과시키는 게이트.
    # Why: BGR ±tol 만으로는 yellow와 orange가 같이 통과해서, 가까이 있는 파티원이
    # 더 큰 blob일 때 본인으로 잡히는 사례가 있음.
    color_bgr_u8 = np.clip(color, 0, 255).astype(np.uint8).reshape(1, 1, 3)
    target_h = int(cv2.cvtColor(color_bgr_u8, cv2.COLOR_BGR2HSV)[0, 0, 0])
    hue_tol = int(MINIMAP_CFG.get('hue_tol', 8))
    mm_hsv = cv2.cvtColor(mm, cv2.COLOR_BGR2HSV)
    h = mm_hsv[:, :, 0].astype(int)
    h_diff = np.minimum(np.abs(h - target_h), 180 - np.abs(h - target_h))
    hue_mask = (h_diff <= hue_tol).astype(np.uint8) * 255
    mask = cv2.bitwise_and(mask, hue_mask)

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


CAPTCHA_SOLVER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'captcha_solver.py')
CAPTCHA_WORD_SOLVER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        'word_captcha_solver.py')
CAPTCHA_SOLVER_TIMEOUT = 60  # 솔버 프로세스 최대 대기(초)
LIE_MAX_RETRIES        = 3   # 자동 풀이 최대 재시도 횟수
LIE_CON_WAIT_SEC       = 5.0 # 풀이 후 con.png 등장 polling 시간 (성공 판정)


def handle_lie_detector():
    """캡차 처리 — 진입~종료 동안의 모든 출력을 captcha_logs/captcha_<ts>.log 에 저장."""
    with _LieLogger() as logger:
        result = _handle_lie_detector_core()
        print(f'[lie] 로그 저장: {logger.path}')
        return result


def _handle_lie_detector_core():
    """
    captcha_solver 자동 호출 + con.png 등장으로 성공 판정.
    실패 시 (con.png N초 안에 안 뜸) 즉시 재시도, 최대 LIE_MAX_RETRIES번.
    모두 실패하면 매크로 종료.
    """
    release()
    attack_release()
    print('[!] 거짓말 탐지기 감지')

    # 사용자 알림 — PC 앞으로 오라고 (감지 즉시)
    try:
        winsound.Beep(1800, 200)
    except Exception:
        pass

    # 다이얼로그 로딩 대기 — puzzle 이미지 안 떠 있으면 slot 검출 실패
    print('[lie] 다이얼로그 로딩 대기 1.5s')
    rsleep(1.5, 0.3)

    if not os.path.exists(CAPTCHA_SOLVER_PATH):
        print(f'[lie] {CAPTCHA_SOLVER_PATH} 없음 → 수동 모드')
        return _handle_lie_detector_manual()

    for attempt in range(1, LIE_MAX_RETRIES + 1):
        if STOP:
            return False

        # 다이얼로그가 사이에 자동으로 사라졌으면 즉시 종료
        if not lie_detected(grab()):
            print('[lie] 다이얼로그 사라짐 — 사냥 재개')
            return True

        print(f'[lie] 자동 풀이 시도 #{attempt}/{LIE_MAX_RETRIES}')
        # 각 시도 시작 비프 (진행 상황 알림)
        try:
            winsound.Beep(1200, 150)
        except Exception:
            pass
        # word 캡차 솔버 호출 (4글자 코드 매칭 패턴)
        # 슬라이더 캡차는 당분간 안 나오므로 호출하지 않음 (CAPTCHA_SOLVER_PATH는 자산 보존용으로만 유지)
        solver_path = CAPTCHA_WORD_SOLVER_PATH
        try:
            r = subprocess.run(
                [sys.executable, solver_path, '--auto'],
                cwd=os.path.dirname(solver_path),
                timeout=CAPTCHA_SOLVER_TIMEOUT,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
            if r.stdout:
                for line in r.stdout.rstrip().splitlines():
                    print(f'  [word] {line}')
            if r.stderr:
                for line in r.stderr.rstrip().splitlines():
                    print(f'  [word-err] {line}')
            print(f'[lie] word solver exit={r.returncode}')
        except subprocess.TimeoutExpired:
            print('[lie] word 솔버 타임아웃')
        except Exception as e:
            print(f'[lie] word 솔버 에러: {e}')

        # 풀이 직후 즉시 화면 저장 (마을로 쫓겨나기 전 = 캡차 결과 화면)
        try:
            ts = int(time.time())
            fail_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'captcha_assets')
            os.makedirs(fail_dir, exist_ok=True)
            after_path = os.path.join(fail_dir,
                                      f'after_solve_{attempt}_{ts}.png')
            pyautogui.screenshot().save(after_path)
            print(f'[lie] 풀이 직후 화면 저장: {after_path}')
        except Exception as e:
            print(f'[lie] 풀이 직후 화면 저장 실패: {e}')

        # 성공 판정: con.png가 LIE_CON_WAIT_SEC 안에 떠야 함
        print(f'[lie] con.png 등장 폴링 ({LIE_CON_WAIT_SEC:.0f}초)...')
        t0 = time.time()
        con_seen = False
        while time.time() - t0 < LIE_CON_WAIT_SEC:
            if STOP:
                return False
            if con_detected(grab()):
                con_seen = True
                break
            rsleep(0.3, 0.2)

        if con_seen:
            print('[lie] con.png 확인 — 캡차 성공')
            handle_con_dialog()  # ENTER로 닫기
            rsleep(1.0, 0.2)
            return True

        # 풀이 실패 — 현재 화면 저장 (디버그용)
        # mss는 일부 화면에서 검은 화면 캡쳐 → pyautogui로 전체 화면 캡쳐
        try:
            ts = int(time.time())
            fail_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'captcha_assets')
            os.makedirs(fail_dir, exist_ok=True)
            path = os.path.join(fail_dir, f'fail_no_con_{attempt}_{ts}.png')
            pyautogui.screenshot().save(path)
            print(f'[lie] 실패 화면 저장: {path}')
        except Exception as e:
            print(f'[lie] 화면 저장 실패: {e}')

        print(f'[lie] con.png 미확인 → 실패 #{attempt}, '
              f'{"재시도 준비" if attempt < LIE_MAX_RETRIES else "매크로 종료"}')
        rsleep(1.5, 0.2)  # 캡차 화면 안정화 대기

    # 3회 모두 실패 → 매크로 종료 (hunt 루프가 STOP 보고 break)
    print(f'[lie] {LIE_MAX_RETRIES}회 자동 풀이 모두 실패 → 매크로 종료')
    try:
        for _ in range(3):
            winsound.Beep(400, 250)
            time.sleep(0.1)
    except Exception:
        pass
    _stop()
    return False


def _region_std(screen, x1, y1, x2, y2) -> float:
    """grab(screen) 안의 게임 좌표 (x1,y1)-(x2,y2) 영역 표준편차."""
    H, W = screen.shape[:2]
    x1 = max(0, min(x1, W - 1)); x2 = max(0, min(x2, W))
    y1 = max(0, min(y1, H - 1)); y2 = max(0, min(y2, H))
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return float(screen[y1:y2, x1:x2].std())


def inv_trigger_full(screen) -> bool:
    """트리거 영역 픽셀 표준편차로 채워졌는지 판단 (단일색=빈, 그래픽=찬)."""
    x1, y1 = _game_rel(INV_TRIGGER_ABS[0], INV_TRIGGER_ABS[1])
    x2, y2 = _game_rel(INV_TRIGGER_ABS[2], INV_TRIGGER_ABS[3])
    return _region_std(screen, x1, y1, x2, y2) > INV_FILLED_STD_THRESHOLD


def inv_first_slot_filled(screen) -> bool:
    """장비창 첫 칸이 채워져 있는지. 빈 칸 → 단일색 → std 작음."""
    cx, cy = _game_rel(*INV_FIRST_SLOT_ABS)
    h = SLOT_CHECK_SIZE // 2
    return _region_std(screen, cx - h, cy - h, cx + h, cy + h) > INV_FILLED_STD_THRESHOLD


def shop_ui_open() -> bool:
    """
    휴대용 상점 UI가 떠 있는지 검증.
    상점 첫 칸 영역의 std가 임계값 이상이어야 함 (UI 떠 있으면 그래픽 → std 큼).
    """
    screen = grab()
    cx, cy = _game_rel(*SHOP_FIRST_SLOT_ABS)
    h = SLOT_CHECK_SIZE // 2
    return _region_std(screen, cx - h, cy - h, cx + h, cy + h) > INV_FILLED_STD_THRESHOLD


def auto_shop() -> bool:
    """
    자동 판매 시퀀스. 단계마다 F12 STOP 체크 + 비프음.
      1) 에스컬레이터 위로 이동
      2) 캐시 탭 클릭 → 휴대용 상점 더블클릭 (UI 등장 검증)
      3) 상점 첫 칸 더블클릭 + ENTER 반복
      4) 인벤 첫 칸이 비면 종료
      5) 상점 닫기 → 장비 탭
    """
    def beep(freq=1500, dur=80):
        try: winsound.Beep(freq, dur)
        except Exception: pass

    print('[shop] === 자동 판매 시작 ===  (F12 = 중단)')
    try:
        _shop_check_stop()

        if not refresh_game_region():
            print('[shop] 게임창 못 찾음 — 중단')
            return False

        if not goto_escalator():
            print('[shop] 에스컬레이터 도달 실패 — 중단')
            return False
        beep(1200)
        _shop_check_stop()
        rsleep(0.6, 0.2)

        # 캐시 탭
        cx, cy = _abs(*CASH_TAB_ABS)
        print(f'[shop] [1] 캐시 탭 클릭 ({cx},{cy})')
        click_at(cx, cy)
        rsleep(0.5, 0.2)
        _shop_check_stop()

        # 휴대용 상점 더블클릭 (최대 2회 시도)
        ps_x, ps_y = _abs(*PORTABLE_SHOP_ABS)
        opened = False
        for attempt in range(2):
            print(f'[shop] [2] 휴대용 상점 더블클릭 ({ps_x},{ps_y}) — 시도 #{attempt + 1}')
            click_at(ps_x, ps_y, double=True)
            rsleep(1.2, 0.2)
            _shop_check_stop()
            if shop_ui_open():
                print('[shop] 상점 UI 확인됨')
                opened = True
                break
            print('[shop] 상점 UI 미확인 → 재시도')
            rsleep(0.5, 0.2)
        if not opened:
            print('[shop] !! 상점 안 열림 — 중단')
            beep(400, 400)
            return False
        beep(1500)

        # 일괄 판매 버튼 → ENTER (확인 다이얼로그)
        sa_x, sa_y = _abs(*SELL_ALL_BUTTON_ABS)
        print(f'[shop] [3] 일괄 판매 버튼 클릭 ({sa_x},{sa_y})')
        click_at(sa_x, sa_y)
        rsleep(0.4, 0.2)
        _shop_check_stop()

        print('[shop] [4] 확인 (ENTER)')
        tap('enter', 0.05)
        rsleep(1.2, 0.3)  # 일괄 판매 처리 시간
        _shop_check_stop()

        # 검증 — 인벤 첫 칸이 비어야 정상
        screen = grab()
        if inv_first_slot_filled(screen):
            print('[shop] !! 일괄 판매 후에도 인벤 첫 칸 채워져 있음')
            beep(400, 400)
            # 그래도 진행 — 다음 사이클에 다시 트리거 잡힐 거
        else:
            print('[shop] 일괄 판매 성공 — 인벤 비움')
        beep(1800)

        _shop_check_stop()
        sc_x, sc_y = _abs(*SHOP_CLOSE_ABS)
        print(f'[shop] [5] 상점 닫기 ({sc_x},{sc_y})')
        click_at(sc_x, sc_y)
        rsleep(0.5, 0.2)

        _shop_check_stop()
        et_x, et_y = _abs(*EQUIP_TAB_ABS)
        print(f'[shop] [6] 장비 탭 ({et_x},{et_y})')
        click_at(et_x, et_y)
        rsleep(0.4, 0.2)

        print('[shop] === 자동 판매 완료 ===')
        beep(2000, 150)
        return True

    except _ShopAborted:
        return False


def _handle_lie_detector_manual():
    """수동 fallback: 비프음 울리며 사람이 풀 때까지 대기."""
    release()
    print('[!] 직접 풀어주세요.')
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
    con_check_until = 0.0  # 캡차 풀이 후 con polling 활성 만료 시각

    while not STOP:
        cycle_t0 = time.time()
        screen = grab()
        t_grab_ms = (time.time() - cycle_t0) * 1000
        frame += 1
        now = time.time()

        # 0) 거짓말 탐지기 체크 (N프레임마다, 시간 측정)
        t_lie_ms = 0.0
        lie_hit = False
        if LIE_ENABLED and frame % LIE_CHECK_EVERY == 0:
            _t = time.time()
            lie_hit = lie_detected(screen)
            t_lie_ms = (time.time() - _t) * 1000
        if lie_hit:
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
            con_check_until = time.time() + CON_CHECK_WINDOW_SEC
            continue

        # 0-b) 캡차 통과 안내창 체크 — 캡차 직후 30초만 polling (CPU 절약)
        if (CON_ENABLED and now < con_check_until
                and frame % CON_CHECK_EVERY == 0 and con_detected(screen)):
            handle_con_dialog()
            last_action     = time.time()
            last_mm_move_ts = time.time()
            on_floor2_since = None
            con_check_until = 0.0  # 닫혔으니 polling 종료
            continue

        # 0-c) 게임창 위치 주기 갱신 — 사용자가 창 옮긴 경우 자동 추적
        if frame % GAME_REGION_REFRESH_EVERY == 0 and frame > 0:
            refresh_game_region()

        # 0-d) 인벤 가득 트리거 → auto_shop()
        if frame % INV_TRIGGER_CHECK_EVERY == 0 and inv_trigger_full(screen):
            print('[hunt] 인벤 트리거 영역 채워짐 → auto_shop()')
            auto_shop()
            last_action     = time.time()
            last_pickup     = time.time()
            last_petfeed    = time.time()
            last_mm_move_ts = time.time()
            on_floor2_since = None
            continue

        # 캐릭터 화면 좌표는 항상 중앙으로 가정 (카메라 추적)
        char = char_screen_position()

        # 미니맵 좌표 (월드) — 시간 측정
        _t = time.time()
        mm_pos = find_char_minimap_pos(screen)
        t_mm_ms = (time.time() - _t) * 1000
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

        # 군집 감지 — 좌하단 사냥 라인 + 캐릭 중심 가로 사거리만 잘라서 매칭
        # (가로 60% 단축 → matchTemplate 시간 절반 이하 → 멈칫 줄임)
        if MOB_DETECT_ENABLED and frame % MOB_DETECT_EVERY == 0:
            h = GAME_REGION['height']
            w = GAME_REGION['width']
            y_top = int(h * HUNT_BAND_Y_RATIO_TOP)
            y_bot = int(h * HUNT_BAND_Y_RATIO_BOTTOM)
            char_x_screen = w // 2  # 카메라 추적 → 캐릭은 화면 중앙
            x_left  = max(0, char_x_screen - MOB_DETECT_X_RADIUS)
            x_right = min(w, char_x_screen + MOB_DETECT_X_RADIUS)
            band = screen[y_top:y_bot, x_left:x_right]
            mobs = []
            for tpl in MOB_TEMPLATES:
                for m in find_all(band, tpl, MOB_THRESHOLD):
                    mobs.append(Point(m.x + x_left, m.y + y_top))  # 좌표 보정
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
        t_atk_ms = 0.0
        if (now - last_attack >= jitter(ATTACK_COOLDOWN, 0.2)
                and now - last_tp >= TP_AFTER_ATTACK_GUARD):
            _t = time.time()
            tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
            t_atk_ms = (time.time() - _t) * 1000
            last_attack = now
            last_action = now
            attacks_in_window += 1

        # 텔포 시점
        t_tp_ms = 0.0
        if now - last_tp > jitter(PATROL_HOLD_SECONDS, 0.2):
            _t = time.time()
            teleport(stuck_dir)
            t_tp_ms = (time.time() - _t) * 1000
            last_tp = now
            last_action = now
            tps_in_window += 1

        # 사이클 시간 진단 — 임계값 넘으면 단계별 시간 출력
        cycle_ms = (time.time() - cycle_t0) * 1000
        if cycle_ms > PERF_WARN_MS:
            print(f'[perf] cycle={cycle_ms:.0f} grab={t_grab_ms:.0f} '
                  f'mm={t_mm_ms:.0f} lie={t_lie_ms:.0f} atk={t_atk_ms:.0f} '
                  f'tp={t_tp_ms:.0f} (f={frame})')

        rsleep(0.005, 0.3)

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
    if CON_ENABLED:
        print(f'캡차 통과 안내창 템플릿: {CON_TEMPLATE}')
    else:
        print(f'[!] 경고: {CON_TEMPLATE} 없음 — 안내창 감지 불가능')
    print(f'몹 군집 감지: {"ON" if MOB_DETECT_ENABLED else "OFF (효율보다 사이클 속도 우선)"}')
    print(f'에스컬레이터: X={ESCALATOR_X_MIN}-{ESCALATOR_X_MAX}, '
          f'성공 mm_y < base-{ESCALATOR_Y_DELTA}')
    print(f'인벤 자동상점: 트리거 영역 {INV_TRIGGER_ABS} '
          f'std > {INV_FILLED_STD_THRESHOLD} 시 발동')
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
