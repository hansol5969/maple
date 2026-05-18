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
TELEPORT_TAP_INTERVAL   = 0.5   # 사냥 중 텔포 tap 간격 — 그 사이 공격 ~2회 확실히 나가게
TP_AFTER_ATTACK_GUARD   = 0.0   # 텔포 직후 공격 가드 없음 — 멈칫 시 공격 즉시
PATROL_REVERSE_SECONDS  = 30.0  # 한 방향 직진 — stuck 감지가 양 끝에서 반전 우선, 시간은 안전장치
KEY_REFRESH_INTERVAL    = 8.0   # 같은 키 hold 최대 시간 — 게임 입력 거부 방지 (방향 안 바꿔도 N초마다 떼었다 다시 hold)
PATROL_EDGE_RATIO       = 0.05  # 양 끝 5% zone에서 자동 반대
PATROL_LEARN_THRESHOLD  = 80    # mm 범위가 이 값 이상이어야 위치 기반 방향 활성
PATROL_SETUP_SECONDS    = 50    # 처음 N초는 시간 기반 반전만 (학습 더 길게)
ATTACK_DOWN_SECONDS     = 0.06  # 공격 키 누름 시간

# 안전지대 (red 맵) — 다른 층에 있고 up_teleport 한 번이면 도착.
# 사냥 위치 기준 가변 (왼쪽일 수도 오른쪽일 수도) — 안전지대 위 텔포 가능 X 위치만 알면 됨.
#
# minimap_setup.py red 에서 캐릭을 안전지대 위 텔포 위치에 세우고 클릭하면 char_setup_x 저장됨.
# 그 값을 안전지대 X 기준으로 사용 — 왼쪽으로 여유 SAFE_ZONE_X_LEFT_MARGIN 만큼 추가 허용.
# 직접 값 지정하고 싶으면 minimap_config_red.json 에 safe_zone_x_min/max 추가하면 우선 사용됨.
SAFE_ZONE_X_LEFT_MARGIN  = 12   # 클릭 X 기준 왼쪽 허용 여유 (미니맵 픽셀)
SAFE_ZONE_X_RIGHT_MARGIN = 4    # 클릭 X 기준 오른쪽 허용 여유 (위 텔포 가능 영역 살짝만)
SAFE_ZONE_Y_DELTA        = 10   # 사냥 라인 대비 mm_y가 이만큼 작아지면 "도착" 판정
GOTO_SAFE_TIMEOUT        = 25.0 # 전체 타임아웃(초)
GOTO_SAFE_MAX_TRIES      = 5    # 위+텔포 최대 시도 횟수 (한 번이면 보통 충분)
GOTO_SAFE_TP_TRIGGER_DX  = 8    # 이 이상 멀면 텔포, 미만이면 walk — 거의 항상 텔포 (몹 넉백 회피)
GOTO_SAFE_X_ARRIVAL_TOL  = 5    # X 범위 밖이라도 이만큼 가까우면 도착 인정 (텔포 overshoot 허용)
GOTO_SAFE_VERIFY_WAIT    = 0.5  # up_teleport 후 mm_y 변화 확인 대기


def _safe_zone_x_range():
    """안전지대 위 텔포 가능 mm_x 범위. 우선순위:
       1) minimap_config_red.json 에 safe_zone_x_min/max 직접 지정
       2) char_setup_x 기준 ±MARGIN
       3) None (셋업 안 됨)
    """
    if not MINIMAP_CFG:
        return None
    if 'safe_zone_x_min' in MINIMAP_CFG and 'safe_zone_x_max' in MINIMAP_CFG:
        return int(MINIMAP_CFG['safe_zone_x_min']), int(MINIMAP_CFG['safe_zone_x_max'])
    cx = MINIMAP_CFG.get('char_setup_x')
    if cx is None:
        return None
    return int(cx) - SAFE_ZONE_X_LEFT_MARGIN, int(cx) + SAFE_ZONE_X_RIGHT_MARGIN

# 주기 작업
PICKUP_INTERVAL   = 1e9    # 줍기 비활성 (펫이 처리)
PET_FEED_INTERVAL = 900.0  # 펫 먹이 주기(초) — 15분 (먹이 절약)

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
MINIMAP_CONFIG_PATH = 'minimap_config_red.json'  # macro_red 전용 설정 (red 맵)
MINIMAP_CFG = None
if os.path.exists(MINIMAP_CONFIG_PATH):
    with open(MINIMAP_CONFIG_PATH, encoding='utf-8') as _f:
        MINIMAP_CFG = json.load(_f)


def grab():
    img = np.array(_sct.grab(GAME_REGION))
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


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
_held_tp = False


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


def tp_hold():
    global _held_tp
    if not _held_tp:
        key_down(TELEPORT_KEY)
        _held_tp = True


def tp_release():
    global _held_tp
    if _held_tp:
        key_up(TELEPORT_KEY)
        _held_tp = False


def hold_all(direction: str):
    """이동키 + 공격 hold. 텔포는 hunt 루프에서 TELEPORT_TAP_INTERVAL(0.3s) 간격으로 tap.
    Why: 텔포까지 hold하면 게임 cooldown만큼 빈번히 시전되어 공격이 1번밖에 못 나감.
    텔포를 timed tap으로 바꾸면 그 사이 공격 2번 정도 나가서 사냥 효율 개선."""
    hold(direction)
    attack_hold()


def release_all():
    """모든 hold 키 해제 — 캡차/상점/2층 처리 등 진입 시."""
    release()
    tp_release()
    attack_release()


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


def down_teleport():
    """↓+텔포 — 아래로 한 층 텔포 (drop_down=↓+x 와 다른 동작)."""
    attack_release()
    release()
    key_down('down')
    rsleep(0.10, 0.2)
    key_down(TELEPORT_KEY)
    rsleep(0.05, 0.2)
    key_up(TELEPORT_KEY)
    rsleep(0.03, 0.2)
    key_up('down')


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


def goto_safe_zone() -> bool:
    """
    안전지대(다른 층)로 이동 — up_teleport 한 번이면 도착하는 구조.
    - X를 SAFE_ZONE_X_MIN~MAX로 정렬 (거리 멀면 텔포, 가까우면 walk)
    - 정렬되면 위+텔포
    - mm_y가 사냥 라인보다 SAFE_ZONE_Y_DELTA 이상 작아지면 성공
    - 사냥 위치 기준 안전지대가 좌/우 어느 쪽이든 무관 (현재 mm_x 기준 dx로 자동 결정)
    """
    rng = _safe_zone_x_range()
    if rng is None:
        print('[goto-safe] !! 안전지대 X 범위 미설정 — minimap_setup.py red 다시 실행 필요')
        return False
    target_min, target_max = rng
    target_center = (target_min + target_max) // 2
    base_y = MINIMAP_CFG.get('floor1_y_baseline') if MINIMAP_CFG else None

    print(f'[goto-safe] start (target X: {target_min}-{target_max}, '
          f'success: mm_y < {(base_y - SAFE_ZONE_Y_DELTA) if base_y else "?"})')

    start = time.time()
    tries = 0
    last_attack = 0.0
    last_tp = 0.0

    while not STOP and time.time() - start < GOTO_SAFE_TIMEOUT \
            and tries < GOTO_SAFE_MAX_TRIES:
        screen = grab()
        pos = find_char_minimap_pos(screen)
        now = time.time()
        if pos is None:
            rsleep(0.08, 0.2)
            continue
        mm_x, mm_y = pos

        # 도착 확인 — 사냥 라인보다 위로 올라감
        if base_y is not None and mm_y < base_y - SAFE_ZONE_Y_DELTA:
            print(f'[goto-safe] 도착 mm=({mm_x},{mm_y}) tries={tries}')
            release()
            return True

        # 정렬됨 → 위+텔포 (X 범위 ±arrival_tol 안이면 시도)
        if (target_min - GOTO_SAFE_X_ARRIVAL_TOL) <= mm_x <= (target_max + GOTO_SAFE_X_ARRIVAL_TOL):
            tries += 1
            print(f'[goto-safe] 정렬 OK mm_x={mm_x} → up+tp #{tries}')
            up_teleport()
            last_tp = now
            rsleep(GOTO_SAFE_VERIFY_WAIT, 0.2)
            continue

        # 정렬 이동 — target_center 향해
        dx = target_center - mm_x
        direction = LEFT if dx < 0 else RIGHT
        if abs(dx) >= GOTO_SAFE_TP_TRIGGER_DX:
            if now - last_tp >= jitter(TELEPORT_COOLDOWN, 0.2):
                teleport(direction)
                last_tp = now
                last_attack = now
        else:
            walk_dur = max(0.06, min(0.25, abs(dx) / 200))
            tap(direction, walk_dur)
            if now - last_attack >= 0.5:
                tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
                last_attack = now

        rsleep(0.04, 0.3)

    print(f'[goto-safe] 실패 tries={tries}, elapsed={time.time() - start:.1f}s')
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
# 미니맵 UI 크기에 따라 변동 — 큰 미니맵에선 본인 점 area가 100 가까이 나올 수 있어 max를 넉넉히 둠.
CHAR_BLOB_AREA_MIN = 3
CHAR_BLOB_AREA_MAX = 200

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
    hue_tol = int(MINIMAP_CFG.get('hue_tol', 5))
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

    # 위치 연속성 우선 — 직전 프레임 근처(NEAR_R) 안의 blob을 본인으로 추정.
    # 근처에 없으면 그때만 가장 큰 blob (로스트/리스폰 fallback).
    # Why: 파티원 점이 더 크게 잡혀도, 본인은 이전 위치에서 멀리 못 점프하므로.
    NEAR_R = int(MINIMAP_CFG.get('near_radius', 40))
    if _last_char_mm_pos is not None:
        lx, ly = _last_char_mm_pos
        r2 = NEAR_R * NEAR_R
        near = [c for c in candidates if (c[1] - lx) ** 2 + (c[2] - ly) ** 2 <= r2]
        if near:
            near.sort(key=lambda c: (-c[0], (c[1] - lx) ** 2 + (c[2] - ly) ** 2))
            _, cx, cy = near[0]
        else:
            candidates.sort(key=lambda c: -c[0])
            _, cx, cy = candidates[0]
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
        try:
            # subprocess stdout/stderr 캡쳐 → macro 로그에 통합
            r = subprocess.run(
                [sys.executable, CAPTCHA_SOLVER_PATH, '--auto'],
                cwd=os.path.dirname(CAPTCHA_SOLVER_PATH),
                timeout=CAPTCHA_SOLVER_TIMEOUT,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
            if r.stdout:
                for line in r.stdout.rstrip().splitlines():
                    print(f'  [solver] {line}')
            if r.stderr:
                for line in r.stderr.rstrip().splitlines():
                    print(f'  [solver-err] {line}')
            print(f'[lie] solver exit={r.returncode}')
        except subprocess.TimeoutExpired:
            print('[lie] 솔버 타임아웃')
        except Exception as e:
            print(f'[lie] 솔버 에러: {e}')

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
      1) 안전지대로 이동 (up_teleport 한 번)
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

        if not goto_safe_zone():
            print('[shop] 안전지대 도달 실패 — 중단')
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

# 사냥 라인 양 끝 mm_x 범위 (mm_probe_red로 측정) — 끝 도달 즉시 방향 반전
PATROL_LEFT_BOUND  = 130  # 이 값 이하면 좌측 끝 → right로 반전
PATROL_RIGHT_BOUND = 305  # 이 값 이상이면 우측 끝 → left로 반전 (305 — 1층 낙하 방지)

# 1층 낙하 감지 — 사냥 중 mm_y가 2층 baseline보다 이만큼 더 아래면 낙하 판정
FELL_TO_FLOOR1_DELTA_Y = 15
FELL_HOLD_SECONDS      = 0.4   # 위 조건 이 초 지속하면 확정 (오탐 방지)

# 2층 감지 — 미니맵 Y가 1층 기준선보다 위로(=Y가 작아짐) FLOOR2_DELTA_Y 이상이면 2층으로 봄
FLOOR2_DELTA_Y       = 6     # 미니맵에서 1층/2층 Y 차이 (작은 미니맵이라 픽셀 단위가 작음)
FLOOR2_HOLD_SECONDS  = 0.6   # 이 시간 동안 위에 있으면 2층 확정
DROP_DOWN_COOLDOWN   = 0.6   # 아래 텔포 시도 간격

# === 3층 맵 (red) 회수 루트 설정 =====================================
# 사냥은 2층(floor1_y_baseline=160)에서, 2분마다 회수 루트로 1/2/3층 다 훑어 펫이 줍게 함.
COLLECTION_INTERVAL = 90.0   # 90초
COLLECTION_TIMEOUT  = 90.0   # 회수 루트 전체 타임아웃 — 안 끝나면 강제 종료

# 각 층 mm_y 좌표
FLOOR1_Y       = 191  # 2층 우측 끝에서 낙하한 1층 (가장 아래)
FLOOR2_Y       = 160  # 2층 (사냥라인) — minimap_config_red.floor1_y_baseline 와 동일 의미
FLOOR2_STAIR_Y = 156  # 2층계단 (2층과 3층 사이 작은 platform)
FLOOR3_Y       = 131  # 3층
FLOOR3_TOP_Y   = 115  # 3층에서 위+텔포 후 아래점프 도착 platform
FLOOR2_RIGHT_TOP_Y = 140  # 2층 우측에서 위+텔포 도착 platform
FLOOR_Y_TOL    = 6    # Y 매칭 허용 오차

# 회수 X 좌표 (mm_probe_red 측정값)
ROUTE_F1_UPTP_X      = (95, 109)   # 1층계단 회수 + 위+텔포 시도 X 범위 (→ 2층). 우측 111→109: platform 끝 떨어짐 방지.
ROUTE_F2_STAIR_X     = (152, 162)  # 2층계단 점프 + z hold 왕복 범위
ROUTE_F3_X           = (174, 192)  # 3층 z hold 왕복 범위
ROUTE_F2_RIGHT_X     = (231, 246)  # 2층 우측 위+텔포 + z hold 왕복 범위

# 회수 동작 타이밍
COLLECT_BOUNCE_ROUNDTRIPS    = 2     # z hold 왕복 횟수 (각 zone)
COLLECT_LEFT_TP_EXTRA_ATTACK = 0.3   # 1층 좌측 이동 시 텔포 사이 추가 공격 시간
COLLECT_F1_TO_F2_RETRIES     = 5     # 1층→2층 위+텔포 재시도 횟수
COLLECT_BOUNCE_TIMEOUT       = 12.0  # z bounce 단일 zone 타임아웃


def _wall_climb(direction: str, target_y: int, timeout: float = 8.0) -> bool:
    """위+(direction)+점프(x) hold — y가 target_y 부근에 갈 때까지.
    2층 우측 끝에서 텔포 못 가는 허공일 때 1층으로 낙하 유도.
    Why UP 조기 release: 2층보다 아래로 내려가기 시작하면 UP 키 즉시 떼야 1층 포탈 자동 진입 방지."""
    print(f'[climb] up+{direction}+jump hold → mm_y >= {target_y}')
    release_all()
    rsleep(0.05, 0.2)
    key_down('up')
    key_down(direction)
    key_down(JUMP_KEY)
    up_held = True
    arrived = False
    last_pos = None
    start = time.time()
    try:
        while time.time() - start < timeout and not STOP:
            pos = find_char_minimap_pos(grab())
            last_pos = pos
            # 2층 baseline 아래로 내려가기 시작하면 UP 즉시 떼기 (포탈 자동진입 방지)
            if up_held and pos and pos[1] > FLOOR2_Y + 5:
                key_up('up')
                up_held = False
                print(f'[climb]   ↓ 시작 mm={pos} → UP 키 release')
            if pos and pos[1] >= target_y - FLOOR_Y_TOL:
                arrived = True
                break
            time.sleep(0.1)
    finally:
        key_up(JUMP_KEY)
        key_up(direction)
        if up_held:
            key_up('up')
        rsleep(0.1, 0.2)
    print(f'[climb] {"도착" if arrived else "타임아웃"} mm={last_pos}')
    return arrived


def _route_move_to(x_min: int, x_max: int, target_y: int = None,
                   y_tol: int = FLOOR_Y_TOL, timeout: float = 15.0,
                   attack: bool = True, extra_attack_dwell: float = 0.0,
                   x_arrival_tol: int = None) -> bool:
    """X 범위로 이동 — 텔포 우선, walk 최소화. target_y 지정 시 Y도 일치해야 도착.
    텔포가 X 범위 안에 정확히 안 들어가도 x_arrival_tol(기본 GOTO_SAFE_X_ARRIVAL_TOL=5) 안이면 도착 인정.
    정밀 정렬이 필요한 곳(예: 계단 점프)은 x_arrival_tol=0 으로 호출.
    extra_attack_dwell — 텔포 후 추가 공격 시간 (회수 보장용)."""
    if x_arrival_tol is None:
        x_arrival_tol = GOTO_SAFE_X_ARRIVAL_TOL
    target_center = (x_min + x_max) // 2
    arrival_min = x_min - x_arrival_tol
    arrival_max = x_max + x_arrival_tol
    start = time.time()
    last_tp = 0.0
    last_attack = 0.0
    last_pos = None
    while time.time() - start < timeout and not STOP:
        screen = grab()
        pos = find_char_minimap_pos(screen)
        now = time.time()
        if pos is None:
            time.sleep(0.05)
            continue
        last_pos = pos
        mm_x, mm_y = pos
        if arrival_min <= mm_x <= arrival_max:
            if target_y is None or abs(mm_y - target_y) <= y_tol:
                print(f'[move] 도착 mm=({mm_x},{mm_y}) (arrival_zone {arrival_min}-{arrival_max})')
                release()
                return True
        dx = target_center - mm_x
        direction = LEFT if dx < 0 else RIGHT
        if abs(dx) >= GOTO_SAFE_TP_TRIGGER_DX:
            if now - last_tp >= jitter(TELEPORT_COOLDOWN, 0.2):
                teleport(direction)
                last_tp = now
                last_attack = now
                if extra_attack_dwell > 0:
                    rsleep(extra_attack_dwell, 0.1)
                    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
                    last_attack = time.time()
        else:
            walk_dur = max(0.06, min(0.20, abs(dx) / 200))
            tap(direction, walk_dur)
            # 매 walk 후 공격 — 몹 넉백 방지
            if attack:
                tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
                last_attack = now
        rsleep(0.04, 0.2)
    print(f'[move] 타임아웃 mm={last_pos}')
    release()
    return False


def _bounce_with_z(x_min: int, x_max: int, round_trips: int = 2,
                   timeout: float = COLLECT_BOUNCE_TIMEOUT) -> None:
    """z 키 hold하면서 x_min ↔ x_max N회 왕복. 회수 보장용.
    안전을 위해 1회 왕복(양 끝 2번 도달)마다 공격 1회 (몹 공격 차단).
    시작 위치에 따라 초기 target 자동 선택 — 범위 밖에서 시작해도 정상 왕복 카운트."""
    start_pos = find_char_minimap_pos(grab())
    # 초기 target: 시작 위치에서 먼 쪽으로 (오른쪽에 있으면 x_min, 왼쪽이면 x_max)
    center = (x_min + x_max) / 2
    if start_pos and start_pos[0] >= center:
        target = x_min
    else:
        target = x_max
    print(f'[bounce] z hold X={x_min}-{x_max} {round_trips}회 (시작 mm={start_pos}, 초기 target={target})')
    release_all()
    rsleep(0.05, 0.2)
    key_down('z')
    try:
        ends_hit = 0
        start = time.time()
        last_log = 0.0
        last_mm_x = None
        while ends_hit < round_trips * 2 and time.time() - start < timeout and not STOP:
            pos = find_char_minimap_pos(grab())
            now = time.time()
            if pos is None:
                time.sleep(0.05)
                continue
            mm_x, mm_y = pos
            if now - last_log > 1.0:
                print(f'[bounce]   mm=({mm_x},{mm_y}) → target={target} ends_hit={ends_hit}/{round_trips*2}')
                last_log = now
            if (target == x_max and mm_x >= x_max) or (target == x_min and mm_x <= x_min):
                ends_hit += 1
                target = x_min if target == x_max else x_max
                print(f'[bounce]   ▸ 끝 도달 mm_x={mm_x} → 다음 target={target} (ends_hit={ends_hit})')
                # 매 끝 도달마다 공격 — 몹에 밀려 platform 떨어지는 거 방지
                tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
                continue
            direction = RIGHT if target > mm_x else LEFT
            dx = abs(target - mm_x)
            walk_dur = max(0.05, min(0.18, dx / 100))
            tap(direction, walk_dur)
            # walk 사이에도 공격 — z hold 중에도 몹 정리
            tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
            last_mm_x = mm_x
            time.sleep(0.04)
        elapsed = time.time() - start
        if ends_hit < round_trips * 2:
            print(f'[bounce] !! 미완료 — ends_hit={ends_hit}/{round_trips*2} '
                  f'elapsed={elapsed:.1f}s last_mm_x={last_mm_x}')
        else:
            print(f'[bounce] 완료 ({elapsed:.1f}s)')
    finally:
        key_up('z')
        rsleep(0.05, 0.2)


def _at_floor(target_y: int, tol: int = FLOOR_Y_TOL) -> bool:
    pos = find_char_minimap_pos(grab())
    return bool(pos) and abs(pos[1] - target_y) <= tol


def _clear_mobs(x_min: int, x_max: int, duration: float = 3.0) -> None:
    """X 범위 안에서 duration초 동안 공격 + 위치 유지 — 점프 전 몹 정리.
    범위 밖으로 밀리면 center 향해 walk로 복귀, 그 외엔 attack tap 반복."""
    center = (x_min + x_max) // 2
    print(f'[clear] X={x_min}-{x_max} 몹 정리 ({duration:.1f}s)')
    end = time.time() + duration
    while time.time() < end and not STOP:
        pos = find_char_minimap_pos(grab())
        if pos and not (x_min <= pos[0] <= x_max):
            # 범위 밖 — center 복귀 walk
            dx = center - pos[0]
            direction = LEFT if dx < 0 else RIGHT
            walk_dur = min(0.10, max(0.06, abs(dx) / 80))
            tap(direction, walk_dur)
        tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
        time.sleep(0.04)


def _wait_stable_y(target_y: int, tol: int = 2, timeout: float = 0.6) -> bool:
    """char가 target_y±tol Y에 안정될 때까지 공격하며 대기.
    Why: 몹 넉백으로 mid-air 상태에서 점프 입력하면 게임이 씹어 — 안정 후 점프해야 함."""
    deadline = time.time() + timeout
    while time.time() < deadline and not STOP:
        pos = find_char_minimap_pos(grab())
        if pos and abs(pos[1] - target_y) <= tol:
            return True
        tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
        time.sleep(0.04)
    return False


def _jump_at_iframe(stable_y: int, target_y: int, timeout: float = 2.5,
                    knockback_dx_threshold: int = 3, target_y_tol: int = 3) -> bool:
    """knockback 직후 짧은 i-frame 윈도우 활용해 jump.

    상시 몹 피격 상황에서:
      - knockback 발생 → mm_x 갑자기 변화 → i-frame 시작
      - i-frame 동안 jump tap → 점프 안 씹히고 위로 이동

    knockback 감지 (mm_x 변화 ≥ threshold)되면 즉시 JUMP_KEY tap.
    target_y 이하로 Y 도달하면 성공 반환.
    knockback 안 감지되어도 timeout 직전에 그냥 시도."""
    deadline = time.time() + timeout
    last_pos = find_char_minimap_pos(grab())
    last_jump_ts = 0.0
    fallback_jump_ts = time.time() + 0.5  # 0.5s 안에 knockback 없으면 그냥 시도
    while time.time() < deadline and not STOP:
        pos = find_char_minimap_pos(grab())
        now = time.time()
        if pos:
            # 점프 성공 검증 (target_y_tol px 까지만 허용)
            if pos[1] <= target_y + target_y_tol:
                print(f'[jump-iframe] 도달 mm={pos}')
                return True
            # knockback 감지 → i-frame 시작 → 즉시 jump
            if last_pos and abs(pos[0] - last_pos[0]) >= knockback_dx_threshold \
                    and now - last_jump_ts > 0.3:
                tap(JUMP_KEY, 0.10)
                last_jump_ts = now
                print(f'[jump-iframe] knockback (dx={abs(pos[0] - last_pos[0])}) → jump tap')
            # fallback: knockback 안 감지되면 일정 주기로 그냥 시도
            elif now > fallback_jump_ts and now - last_jump_ts > 0.4:
                tap(JUMP_KEY, 0.10)
                last_jump_ts = now
                fallback_jump_ts = now + 0.5
                print(f'[jump-iframe] fallback jump tap mm={pos}')
            last_pos = pos
        time.sleep(0.04)
    pos = find_char_minimap_pos(grab())
    ok = pos and pos[1] <= target_y + target_y_tol
    print(f'[jump-iframe] {"도달" if ok else "타임아웃"} mm={pos}')
    return bool(ok)


def _wait_attacking(duration: float):
    """duration(초) 동안 ~0.13s 사이클로 공격 tap 반복 — rsleep 대신 사용해 몹 넉백 방지.
    각 사이클: attack tap(~0.06s) + 짧은 sleep(0.07s) = 약 0.13s."""
    end = time.time() + duration
    while time.time() < end and not STOP:
        tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
        remaining = end - time.time()
        if remaining > 0:
            time.sleep(min(0.07, remaining))


def _align_center(x_min: int, x_max: int, target_y: int = None,
                  y_tol: int = 8, timeout: float = 10.0, margin: int = 2) -> bool:
    """X 범위의 중앙(±margin)에 정밀 정렬 — hybrid TP/walk 단일 pass.
    - 멀면(dx≥15) TP, 가까우면 walk + 공격 (knockback 방지)
    - 매 walk 후 공격 → 몹 못 밀게."""
    center = (x_min + x_max) // 2
    arrival_min = center - margin
    arrival_max = center + margin
    print(f'[align-center] X={center}±{margin} (원래 범위 {x_min}-{x_max})')

    deadline = time.time() + timeout
    last_tp = 0.0
    last_pos = None
    while time.time() < deadline and not STOP:
        pos = find_char_minimap_pos(grab())
        now = time.time()
        if not pos:
            time.sleep(0.05)
            continue
        last_pos = pos
        if arrival_min <= pos[0] <= arrival_max:
            if target_y is None or abs(pos[1] - target_y) <= y_tol:
                print(f'[align-center] OK mm={pos}')
                release()
                return True
        dx = center - pos[0]
        direction = LEFT if dx < 0 else RIGHT
        if abs(dx) >= 15 and now - last_tp >= jitter(TELEPORT_COOLDOWN, 0.2):
            teleport(direction)
            last_tp = now
        else:
            # 가까운 거리 walk — walk_dur 늘려서(0.08-0.18) knockback 이김 + 공격
            walk_dur = min(0.18, max(0.08, abs(dx) / 60))
            tap(direction, walk_dur)
            tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    print(f'[align-center] 타임아웃 mm={last_pos}')
    return False


def _jump_to_floor2_stair(max_tries: int = 4) -> bool:
    """2층 X=ROUTE_F2_STAIR_X **중앙**으로 정렬 → 점프 → 2층계단(Y=FLOOR2_STAIR_Y) 도달 검증/재시도.
    매 시도마다 중앙 재정렬 (몹 넉백으로 밀려도 다시 중앙). X+Y 둘 다 검증."""
    s_lo, s_hi = ROUTE_F2_STAIR_X
    for retry in range(max_tries):
        if STOP:
            return False
        # X+Y 둘 다 도착 확인 (Y만 보면 시도 0에서 잘못 통과됨)
        pos = find_char_minimap_pos(grab())
        if pos and s_lo <= pos[0] <= s_hi and abs(pos[1] - FLOOR2_STAIR_Y) <= 3:
            print(f'[stair] 2층계단 도착 mm={pos} (시도 {retry})')
            return True
        # 매번 중앙 재정렬 (knockback 후라도)
        _align_center(s_lo, s_hi, target_y=FLOOR2_Y, y_tol=8, timeout=8.0, margin=2)
        # 점프 전 몹 정리 (3s)
        _clear_mobs(s_lo, s_hi, duration=3.0)
        print(f'[stair] i-frame jump 시도 {retry+1}/{max_tries}')
        # target_y=156(2층계단), tol=1 → Y≤157만 도달 인정 (Y=159 같은 2층 트리비얼 통과 방지)
        _jump_at_iframe(stable_y=FLOOR2_Y, target_y=FLOOR2_STAIR_Y, target_y_tol=1, timeout=2.0)
        _wait_attacking(0.3)
    pos = find_char_minimap_pos(grab())
    ok = pos and s_lo <= pos[0] <= s_hi and abs(pos[1] - FLOOR2_STAIR_Y) <= 3
    print(f'[stair] {"도달" if ok else "!! 실패"} mm={pos}')
    return ok


def _up_until_floor(target_y: int, tol: int = 8, max_tries: int = 4) -> bool:
    """위+텔포로 target_y 도달까지 반복.
    Why: up_tp 후 wait 길게 두면 몹이 platform 밖으로 밀어내 다음 up_tp 실패.
    → 짧은 wait(0.15s) + 즉시 verify, 도달 못하면 즉시 다음 up_tp."""
    for i in range(max_tries):
        if STOP:
            return False
        if _at_floor(target_y, tol=tol):
            print(f'[up→{target_y}] 도달 (시도 {i})')
            return True
        up_teleport()
        time.sleep(0.15)  # 짧은 wait — 안착 확인용 (knockback 없음)
        if _at_floor(target_y, tol=tol):
            print(f'[up→{target_y}] 도달 (시도 {i+1})')
            return True
        # 한 번 더 즉시 (1층→2층 처럼 2번 필요한 경우)
        up_teleport()
        time.sleep(0.15)
    ok = _at_floor(target_y, tol=tol)
    print(f'[up→{target_y}] {"도달" if ok else "실패"} (시도 {max_tries*2})')
    return ok


def _down_until_floor(target_y: int, tol: int = 8, max_tries: int = 4,
                      overshoot_threshold: int = 15) -> bool:
    """아래텔포/drop_down으로 target_y 도달까지 반복. target보다 너무 내려가면 위+텔포 보정."""
    for i in range(max_tries):
        if STOP:
            return False
        pos = find_char_minimap_pos(grab())
        if pos and abs(pos[1] - target_y) <= tol:
            print(f'[down→{target_y}] 도달 (시도 {i})')
            return True
        if pos and pos[1] > target_y + overshoot_threshold:
            print(f'[down→{target_y}] 오버슈트 (mm_y={pos[1]}) → 위+텔포 보정')
            up_teleport()
            _wait_attacking(0.4)
        else:
            down_teleport()
            _wait_attacking(0.3)
    ok = _at_floor(target_y, tol=tol)
    print(f'[down→{target_y}] {"도달" if ok else "실패"} (시도 {max_tries})')
    return ok


def _recover_floor1_to_floor2(max_retries: int = 5) -> bool:
    """1층 → 2층 복귀 (1층계단 회수 포함).
    [순서] X=ROUTE_F1_UPTP_X 정렬 → 점프 → 공격 → z hold X 2회 왕복 → 공격 → 위+텔포 → 도착 확인.
    회수 루트 Phase 2 + 사냥 중 1층 낙하 회복에서 공통 사용."""
    print('[recover] === 1층 → 2층 복귀 (1층계단 회수) ===')
    x_lo, x_hi = ROUTE_F1_UPTP_X

    for retry in range(max_retries):
        if STOP:
            return False
        pos = find_char_minimap_pos(grab())
        if pos and abs(pos[1] - FLOOR2_Y) <= 8:
            print(f'[recover] 2층 도착 (시도 {retry})')
            return True

        # 중간 floor — 어중간한 Y에서 위+텔포는 platform 못 잡고 실패 빈번.
        # 차라리 아래텔포로 1층까지 떨어뜨려서 다음 iter에서 정식 시퀀스 진행.
        if pos and not (pos[1] >= FLOOR1_Y - FLOOR_Y_TOL):
            print(f'[recover] 중간 floor (mm_y={pos[1]}) → 아래텔포로 1층까지')
            tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
            _down_until_floor(FLOOR1_Y, tol=FLOOR_Y_TOL, max_tries=3, overshoot_threshold=999)
            continue

        # 1층 — 1층계단 회수 시퀀스 (중앙 정렬 → 몹 정리 → 점프)
        print(f'[recover] 1층 (mm_y={pos[1] if pos else "?"}) → 중앙 정렬 후 점프')
        _align_center(x_lo, x_hi, target_y=FLOOR1_Y, y_tol=15, timeout=12.0, margin=2)
        # 점프 전 몹 정리 (3s) — knockback 빈도 줄여 점프 신뢰도 ↑
        _clear_mobs(x_lo, x_hi, duration=3.0)
        print('[recover] i-frame jump 시도 → 1층계단 도달 검증')
        _jump_at_iframe(stable_y=FLOOR1_Y, target_y=FLOOR1_Y - 6, timeout=2.5)
        tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
        _bounce_with_z(x_lo, x_hi, round_trips=COLLECT_BOUNCE_ROUNDTRIPS)
        tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
        # 위+텔포 전 다시 중앙 정렬 (knockback로 platform 밑 빠져있을 수 있음)
        _align_center(x_lo, x_hi, target_y=None, y_tol=25, timeout=6.0, margin=3)
        _up_until_floor(FLOOR2_Y, tol=8, max_tries=4)

        if _at_floor(FLOOR2_Y, tol=8):
            print(f'[recover] 2층 도착 (시도 {retry+1})')
            return True
        print(f'[recover] 미도달 — 재시도 {retry+1}/{max_retries}')
    print('[recover] !! 복귀 실패')
    return False


def collection_route():
    """
    회수 루트 (3층 맵, 2층 사냥) — 2분마다 호출.

    [Phase 1] 2층 → 우측 끝 → 1층 낙하 (자연낙하 안 되면 wall climb)
    [Phase 2] 1층 좌측 X=96~112 까지 사냥+회수 → 위+텔포 2번으로 2층
    [Phase 3] 2층 → X=152~162 점프 → 2층계단 → z 왕복 → 위+텔포 → 3층
    [Phase 4] 3층 → X=174~192 → 위+텔포 후 아래점프 → z 왕복
    [Phase 5] 아래 텔포 2번 → 2층
    [Phase 6] 2층 → X=231~246 → 위+텔포 → z 왕복
    [Phase 7] 사냥 재개 (hunt 루프가 자동 drop_down으로 2층 복귀)
    """
    route_start = time.time()

    def stop_check():
        if STOP:
            return True
        if time.time() - route_start > COLLECTION_TIMEOUT:
            print('[collect] !! 전체 타임아웃 — 강제 종료')
            return True
        return False

    print('[collect] === 회수 루트 시작 ===')
    release_all()
    rsleep(0.1, 0.2)

    if MINIMAP_CFG is None:
        print('[collect] minimap config 없음 — 중단')
        return

    # ───── Phase 1: 2층 → 우측 끝 → 1층 낙하 ─────
    print('[collect] [1] 2층 우측 끝(→{}) 으로 사냥+텔포 이동'.format(PATROL_RIGHT_BOUND))
    _route_move_to(PATROL_RIGHT_BOUND - 8, PATROL_RIGHT_BOUND + 5,
                   target_y=FLOOR2_Y, y_tol=10, timeout=15.0, attack=True)
    if stop_check():
        return

    # 자연 낙하 폴백: 0.8초 더 우측 텔포 시도 후 그래도 2층이면 wall climb
    print('[collect] [2] 1층 낙하 시도')
    _natural = False
    _t0 = time.time()
    while time.time() - _t0 < 1.5 and not STOP:
        pos = find_char_minimap_pos(grab())
        if pos and pos[1] >= FLOOR1_Y - FLOOR_Y_TOL:
            _natural = True
            break
        if pos and abs(pos[1] - FLOOR2_Y) <= FLOOR_Y_TOL:
            teleport(RIGHT)  # 한 번 더 밀어보기
        time.sleep(0.15)
    if not _natural:
        print('[collect] 자연 낙하 X → 위+오른쪽+점프 hold 등반')
        _wall_climb(RIGHT, FLOOR1_Y, timeout=6.0)
    # 그래도 1층 미도달이면 아래텔포로 떨어뜨림
    pos = find_char_minimap_pos(grab())
    if not (pos and pos[1] >= FLOOR1_Y - FLOOR_Y_TOL):
        print(f'[collect] climb 후 1층 미도달 (mm_y={pos[1] if pos else "?"}) → 아래텔포 추가')
        _down_until_floor(FLOOR1_Y, tol=FLOOR_Y_TOL, max_tries=3, overshoot_threshold=999)
    if stop_check():
        return

    # ───── Phase 2: 1층 → 좌측 X=96~112 → 위+텔포 2번 → 2층 ─────
    print('[collect] [3-4] 1층 → 2층 복귀 (공통 함수 사용)')
    _recover_floor1_to_floor2(max_retries=COLLECT_F1_TO_F2_RETRIES)
    if stop_check():
        return

    # ───── Phase 3: 2층 → X=152~162 정밀 정렬 → 점프 → 2층계단 → z 왕복 → 위+텔포 → 3층 ─────
    s_lo, s_hi = ROUTE_F2_STAIR_X
    print(f'[collect] [5] 2층계단 X={s_lo}-{s_hi} 점프 시퀀스 (정밀 정렬 + 검증/재시도)')
    _jump_to_floor2_stair(max_tries=4)
    if stop_check():
        return

    print(f'[collect] [6] 2층계단 z-hold 왕복')
    _bounce_with_z(s_lo, s_hi, round_trips=COLLECT_BOUNCE_ROUNDTRIPS)
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    if stop_check():
        return

    print('[collect] [7] 위+텔포 → 3층 (도달 검증)')
    _up_until_floor(FLOOR3_Y, tol=8, max_tries=4)

    # ───── Phase 4: 3층 → X=174~192 중앙 → 위+텔포 후 아래점프 → z 왕복 ─────
    f3_lo, f3_hi = ROUTE_F3_X
    print(f'[collect] [8] 3층 X={f3_lo}-{f3_hi} 중앙 정렬 (knockback 방지)')
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    _align_center(f3_lo, f3_hi, target_y=FLOOR3_Y, y_tol=8, timeout=12.0, margin=2)
    if stop_check():
        return

    print('[collect] [9] 위+텔포 → 아래점프')
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    up_teleport()
    _wait_attacking(0.3)
    drop_down()
    _wait_attacking(0.3)

    print(f'[collect] [10] z-hold 왕복')
    _bounce_with_z(f3_lo, f3_hi, round_trips=COLLECT_BOUNCE_ROUNDTRIPS)
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    if stop_check():
        return

    # ───── Phase 5: 아래 텔포 → 2층 (검증/보정) ─────
    print('[collect] [11] 아래텔포 → 2층 (도달 검증, 1층 떨어지면 위+텔포로 보정)')
    _down_until_floor(FLOOR2_Y, tol=8, max_tries=4)

    # ───── Phase 6: 2층 → X=231~246 중앙 → 위+텔포 → z 왕복 ─────
    r_lo, r_hi = ROUTE_F2_RIGHT_X
    print(f'[collect] [12] 2층 X={r_lo}-{r_hi} 중앙 정렬')
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    _align_center(r_lo, r_hi, target_y=FLOOR2_Y, y_tol=8, timeout=12.0, margin=2)
    if stop_check():
        return
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    # → Y≈140 platform 도달 검증
    _up_until_floor(FLOOR2_RIGHT_TOP_Y, tol=8, max_tries=3)
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)

    print(f'[collect] [13] 2층 우측 platform z-hold 왕복')
    _bounce_with_z(r_lo, r_hi, round_trips=COLLECT_BOUNCE_ROUNDTRIPS)

    print('[collect] === 회수 루트 끝 ({:.1f}s) ==='.format(time.time() - route_start))


def hunt():
    """
    v2: 이동키 + 텔포 + 공격 3개 모두 hold (실제 사용자 플레이 패턴).
    매크로는 모니터링만 — 게임이 cooldown마다 자동으로 텔포/공격 시전.
    캡차/2층/인벤/펫먹이 등 이벤트 시에만 잠깐 release → 처리 → 다시 hold.
    """
    last_petfeed = time.time()  # 첫 시전은 10분 후 (시작 즉시 먹으면 낭비)
    last_collect = time.time()  # 회수 루트 — 첫 시행은 COLLECTION_INTERVAL 후
    stuck_dir    = RIGHT
    frame        = 0

    last_mm_x       = None
    last_mm_move_ts = time.time()

    floor1_y          = MINIMAP_CFG.get('floor1_y_baseline') if MINIMAP_CFG else None
    on_floor2_since   = None
    last_drop_down    = 0.0
    fell_to_f1_since  = None   # 사냥 중 1층 낙하 감지 — N초 지속하면 회복 트리거

    last_log_ts = 0.0
    last_force_reverse = time.time()
    last_key_refresh = time.time()
    last_tp_tap = 0.0  # 텔포 0.3s 간격 tap 시점
    con_check_until = 0.0

    # 사냥 시작: 이동+공격 hold (텔포는 TELEPORT_TAP_INTERVAL마다 tap)
    hold_all(stuck_dir)

    while not STOP:
        screen = grab()
        frame += 1
        now = time.time()

        # 0) 거짓말 탐지기
        if LIE_ENABLED and frame % LIE_CHECK_EVERY == 0 and lie_detected(screen):
            release_all()
            if LIE_HANDLE_MODE == 'stop':
                _stop(); break
            ok = handle_lie_detector()
            if not ok: _stop(); break
            # last_petfeed 리셋 안 함 — 펫 먹이는 정확히 10분 간격 유지
            last_mm_move_ts = time.time()
            on_floor2_since = None
            con_check_until = time.time() + CON_CHECK_WINDOW_SEC
            hold_all(stuck_dir)
            last_key_refresh = time.time()
            continue

        # 0-b) 캡차 통과 안내창
        if (CON_ENABLED and now < con_check_until
                and frame % CON_CHECK_EVERY == 0 and con_detected(screen)):
            release_all()
            handle_con_dialog()
            last_mm_move_ts = time.time()
            on_floor2_since = None
            con_check_until = 0.0
            hold_all(stuck_dir)
            last_key_refresh = time.time()
            continue

        # 0-c) 게임창 위치 갱신
        if frame % GAME_REGION_REFRESH_EVERY == 0 and frame > 0:
            refresh_game_region()

        # 0-d) 인벤 가득 트리거 → auto_shop
        if frame % INV_TRIGGER_CHECK_EVERY == 0 and inv_trigger_full(screen):
            release_all()
            print('[hunt] 인벤 트리거 → auto_shop()')
            auto_shop()
            # last_petfeed 리셋 안 함 — 펫 먹이는 정확히 10분 간격 유지
            last_mm_move_ts = time.time()
            on_floor2_since = None
            hold_all(stuck_dir)
            last_key_refresh = time.time()
            continue

        # 0-e) 주기적 회수 루트 — 펫이 못 주운 다른 층 아이템 회수
        if now - last_collect >= COLLECTION_INTERVAL:
            release_all()
            print(f'[hunt] 회수 루트 트리거 ({(now - last_collect):.0f}s 경과)')
            collection_route()
            last_collect = now
            last_mm_move_ts = time.time()
            on_floor2_since = None
            hold_all(stuck_dir)
            last_key_refresh = time.time()
            continue

        # 미니맵 좌표
        mm_pos = find_char_minimap_pos(screen)
        mm_x, mm_y = (mm_pos if mm_pos else (None, None))
        if mm_x is not None:
            if last_mm_x is None or abs(mm_x - last_mm_x) > STUCK_MINIMAP_DELTA:
                last_mm_x = mm_x
                last_mm_move_ts = now
            if floor1_y is None:
                floor1_y = mm_y

        # 텔포 timed tap — 0.3초 간격으로 시전 (그 사이 공격 ~2회 나가게)
        if now - last_tp_tap >= TELEPORT_TAP_INTERVAL:
            tap(TELEPORT_KEY, 0.04)
            last_tp_tap = now

        # 2층 감지 → 아래 점프 (최우선 — 사냥 중단하고 즉시 내려가기)
        # 주: 변수명은 floor1_y지만 실제로 사냥라인(red 맵에서 2층) 기준선임
        if mm_y is not None and floor1_y is not None and mm_y < floor1_y - FLOOR2_DELTA_Y:
            if on_floor2_since is None:
                on_floor2_since = now
            elif now - on_floor2_since > FLOOR2_HOLD_SECONDS and now - last_drop_down > DROP_DOWN_COOLDOWN:
                print(f'[*] 사냥라인 위로 감지 (mm_y={mm_y}) → 키 릴리스 + 아래 점프')
                release_all()
                rsleep(0.05, 0.2)
                drop_down()
                last_drop_down = now
                on_floor2_since = now
                last_mm_move_ts = now
                hold_all(stuck_dir)
                last_key_refresh = time.time()
                continue
        else:
            on_floor2_since = None

        # 1층 낙하 감지 → 1층→2층 복귀 (의도치 않게 우측 끝에서 떨어진 경우)
        if mm_y is not None and floor1_y is not None and mm_y > floor1_y + FELL_TO_FLOOR1_DELTA_Y:
            if fell_to_f1_since is None:
                fell_to_f1_since = now
            elif now - fell_to_f1_since > FELL_HOLD_SECONDS:
                print(f'[*] 1층 낙하 감지 (mm_y={mm_y}) → 회복 루틴')
                release_all()
                rsleep(0.05, 0.2)
                _recover_floor1_to_floor2(max_retries=8)
                last_mm_move_ts = time.time()
                fell_to_f1_since = None
                on_floor2_since = None
                hold_all(stuck_dir)
                last_key_refresh = time.time()
                continue
        else:
            fell_to_f1_since = None

        # 1초마다 dbg
        if now - last_log_ts > 1.0:
            print(f'[dbg] mm=({mm_x},{mm_y}) dir={stuck_dir}')
            last_log_ts = now

        # 펫 먹이 — 10분에 정확히 2개 (수량 제한). release 충분 후 안정적 2회 tap
        if now - last_petfeed > PET_FEED_INTERVAL:
            print(f'[pet] 먹이 2개 시전 ({PET_FEED_KEY!r})')
            release_all()
            rsleep(0.25, 0.2)         # release 처리 시간 충분히 (안 그러면 tap 무시)
            tap(PET_FEED_KEY, 0.10)
            rsleep(0.40, 0.2)         # 두 tap 사이 충분히 — 게임이 각각 인식
            tap(PET_FEED_KEY, 0.10)
            rsleep(0.20, 0.2)         # 다시 hold 전 안정화
            last_petfeed = now + random.uniform(-15.0, 15.0)
            hold_all(stuck_dir)
            last_key_refresh = time.time()

        # 위치 기반 끝 도달 즉시 반전 (mm_probe로 측정한 PATROL_LEFT/RIGHT_BOUND)
        if mm_x is not None:
            at_left_end  = stuck_dir == LEFT  and mm_x <= PATROL_LEFT_BOUND
            at_right_end = stuck_dir == RIGHT and mm_x >= PATROL_RIGHT_BOUND
            if at_left_end or at_right_end:
                new_dir = RIGHT if at_left_end else LEFT
                print(f'[edge] mm_x={mm_x} {stuck_dir} 끝 → 즉시 {new_dir}')
                release_all()
                jump_teleport(new_dir)
                stuck_dir = new_dir
                last_mm_move_ts = now
                last_force_reverse = now
                last_key_refresh = time.time()
                hold_all(stuck_dir)
                continue

        # stuck 감지 (끝 박힘 — 위치 기반 안 잡힌 케이스 폴백) → 점프+텔포 반전
        mm_stuck = mm_x is not None and now - last_mm_move_ts > STUCK_MINIMAP_SECONDS
        if mm_stuck:
            stuck_dir = LEFT if stuck_dir == RIGHT else RIGHT
            print(f'[stuck-rev] mm_x={mm_x} → jump+{stuck_dir}+tp')
            release_all()
            jump_teleport(stuck_dir)
            last_mm_move_ts = now
            last_force_reverse = now
            last_key_refresh = time.time()
            hold_all(stuck_dir)
            continue

        # 시간 기반 강제 반전 — 모든 키 잠깐 떼고 새 방향으로 다시 hold
        # (게임이 같은 키 오래 누르면 입력 거부 → 키 리프레시 필수)
        if now - last_force_reverse > jitter(PATROL_REVERSE_SECONDS, 0.15):
            stuck_dir = LEFT if stuck_dir == RIGHT else RIGHT
            last_force_reverse = now
            last_key_refresh = now
            print(f'[periodic] 반전 → {stuck_dir} (모든 키 리프레시)')
            release_all()
            rsleep(0.05, 0.2)
            hold_all(stuck_dir)

        # 주기 키 리프레시 — 방향 안 바뀌어도 N초마다 모든 키 떼었다 다시 hold
        # (게임 입력 거부 방지)
        elif now - last_key_refresh > KEY_REFRESH_INTERVAL:
            last_key_refresh = now
            print(f'[refresh] 모든 키 리프레시 (dir={stuck_dir} 유지)')
            release_all()
            rsleep(0.05, 0.2)
            hold_all(stuck_dir)

        rsleep(0.02, 0.3)

    release_all()


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
    _rng = _safe_zone_x_range()
    if _rng:
        print(f'안전지대: X={_rng[0]}-{_rng[1]}, '
              f'성공 mm_y < base-{SAFE_ZONE_Y_DELTA}')
    else:
        print('[!] 경고: 안전지대 X 미설정 — minimap_setup.py red 재실행 필요')
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
