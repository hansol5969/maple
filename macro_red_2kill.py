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
TELEPORT_TAP_INTERVAL   = 0.10  # 사냥 중 텔포 tap 간격 — 물리 hold auto-repeat(~33ms)에 근접하게 빠르게
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
SAFE_ZONE_TARGET_Y       = 131  # 안전지대 도착 판정 mm_y (이 값 이하면 도착)
# 안전지대 전체 X 범위 (사용자 mm_probe 측정): X=284-324, Y=131
# 그 중 포탈 영역(X=291-309)은 안전지대에서 제외 — 위 텔포 시전 X
# 위 텔포 시전 가능: 우측 영역 X=310-324 (폭 15px, 좌측 284-290은 폭 7로 너무 좁아 미사용)
SAFE_ZONE_X_FULL         = (284, 324)  # 참고용 — 안전지대 전체
PORTAL_DANGER_X          = (291, 309)  # 포탈 영역 — 위 텔포 시전 금지
SAFE_ZONE_TP_X           = (310, 324)  # 실제 위 텔포 시전 영역 (안전지대 우측, 포탈 회피)
GOTO_SAFE_TIMEOUT        = 40.0 # 전체 타임아웃(초) — 단발 텔포 반복 누적
GOTO_SAFE_MAX_TRIES      = 25   # up+tp 최대 시도 (mm_y=131 도달까지 반복)
GOTO_SAFE_TP_TRIGGER_DX  = 8    # 이 이상 멀면 텔포, 미만이면 walk — 거의 항상 텔포 (몹 넉백 회피)
GOTO_SAFE_X_ARRIVAL_TOL  = 5    # X 범위 밖이라도 이만큼 가까우면 도착 인정 (텔포 overshoot 허용)
GOTO_SAFE_VERIFY_WAIT    = 0.7  # up_teleport 후 안착 대기 — mid-air 검출 실패 방지


def _safe_zone_x_range():
    """안전지대 위 텔포 시전 가능 mm_x 범위.
    SAFE_ZONE_TP_X (310-324, 안전지대 우측) — 포탈 영역(291-309) 제외."""
    return SAFE_ZONE_TP_X


def _safe_zone_x_range_legacy():
    """[deprecated] 이전 동작 보존 — 우선순위: config 파일 → char_setup_x ± margin."""
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
CASH_TAB_ABS         = (3170, 318)
PORTABLE_SHOP_ABS    = (3090, 957)
SHOP_FIRST_SLOT_ABS  = (2060, 964)   # 상점 UI 등장 검증용 (열림 여부 std 체크)
SELL_ALL_BUTTON_ABS  = (2564, 597)   # 장비 일괄 판매 버튼
SHOP_CLOSE_ABS       = (1845, 603)
EQUIP_TAB_ABS        = (2744, 316)
ETC_TAB_ABS          = (2488, 865)   # 기타 탭
ETC_SELL_SLOT_ABS    = (2500, 982)   # 기타템 판매 — 상점 UI 안 이 좌표 더블클릭하면 1개 판매
ETC_CHECK_SLOT_ABS   = (2058, 987)   # 기타템 인벤 첫 칸 — std 체크용 (빈칸=다 팔렸음)
INV_FIRST_SLOT_ABS   = (2748, 406)
INV_TRIGGER_ABS      = (3052, 910, 3147, 1007)  # x1, y1, x2, y2

# 기타 탭 판매: N회 자동상점마다 1번 추가 실행 (기타템은 일괄 판매 X → 개별 더블클릭+ENTER)
SHOP_SALE_COUNT_FOR_ETC = 3
ETC_MAX_SELL_TRIES      = 32

INV_FILLED_STD_THRESHOLD = 30    # 빈 std≈8-11, 찬 std≈54-87 (slot_inspect로 측정)
SLOT_CHECK_SIZE          = 30    # 인벤 첫 칸 검사 영역 크기
INV_TRIGGER_CHECK_EVERY  = 30    # N 사이클마다 트리거 체크
SHOP_MAX_SELL_TRIES      = 32    # 판매 반복 최대 시도
GAME_REGION_REFRESH_EVERY = 600  # N 사이클마다 게임창 위치 재탐색 (창 이동 대응)

# 거짓말 탐지기 / 안티봇 팝업
# 팝업 제목 부분만 잘라서 lie_title.png 한 장만 사용 (작아서 빠르고 매번 동일해서 신뢰성 높음)
LIE_TEMPLATE      = 'templates/lie_title.png'
LIE_THRESHOLD     = 0.85   # 팝업은 정확히 매칭되어야 오탐 적음
LIE_CHECK_EVERY   = 1      # 매 사이클 체크 — 거짓말 탐지기는 무조건 최우선 (회수/상점보다 앞)
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
    """캘리브레이션 시점의 절대 좌표 → 현재 게임창 위치 보정한 절대 좌표."""
    dx = GAME_REGION['left'] - COORDS_CAL_GAME_LEFT
    dy = GAME_REGION['top'] - COORDS_CAL_GAME_TOP
    return x + dx, y + dy


def _game_rel(x: int, y: int) -> tuple:
    """캘리브레이션 절대 좌표 → 현재 game grab 영역 내 상대 좌표."""
    return x - COORDS_CAL_GAME_LEFT, y - COORDS_CAL_GAME_TOP


# SendInput 마우스 이벤트 (pyautogui보다 게임에서 안정적)
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP   = 0x0004


def click_at(x: int, y: int, double: bool = False) -> None:
    """SendInput 마우스 클릭. double=True면 더블클릭 (Windows OS 더블클릭 간격 안).
    각 timing은 게임 안정 인식 위주 — 너무 짧으면 더블클릭 인식 실패함."""
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.08)                            # 커서 안정 (60→80ms)
    user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)                            # 클릭 holding (30→40ms)
    user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    if double:
        time.sleep(0.12)                        # 더블클릭 간격 (80→120ms — 짧으면 단일클릭 2번으로 인식)
        user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)                        # 두 번째 클릭 holding
        user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


class _ShopAborted(Exception):
    """auto_shop 도중 F12 등으로 중단됨."""
    pass


def _shop_check_stop():
    """auto_shop click 단계 사이 체크 — STOP + 거짓말 탐지기 둘 다.
    lie 감지 시 풀이 후 _ShopAborted raise → caller가 상점 닫기/장비 탭 복귀 보장."""
    global STOP
    if STOP:
        print('[shop] !! F12 중단 감지')
        attack_release()
        release()
        raise _ShopAborted()
    if LIE_ENABLED and lie_detected(grab()):
        print('[shop] !! 거짓말 탐지기 감지 — 풀이 후 상점 마무리')
        attack_release()
        release()
        ok = handle_lie_detector()
        if not ok:
            STOP = True
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
    """이동키 + 텔포 + 공격 모두 hold (macro_v2 단순 패턴)."""
    hold(direction)
    tp_hold()
    attack_hold()


def patrol_hold(direction: str):
    """패트롤 hold — 방향+attack+teleport 동시 hold (macro_v2 hold_all와 동일).
    Why: 0.1s 대기 빼서 매번 re-hold 시 누적 delay 제거 → macro_v2 수준 속도."""
    hold(direction)
    tp_hold()
    attack_hold()


# === 텔포 background pulse — 물리 hold의 auto-repeat 흉내 ===
_TP_PULSE_THREAD = None
_TP_PULSE_STOP   = None
TP_PULSE_INTERVAL = 0.035  # 30Hz (Windows default typematic ~30Hz)
TP_PULSE_PRESS    = 0.008  # 짧은 press


def _tp_pulse_loop(stop_event):
    while not stop_event.is_set():
        key_down(TELEPORT_KEY)
        time.sleep(TP_PULSE_PRESS)
        key_up(TELEPORT_KEY)
        time.sleep(max(0.0, TP_PULSE_INTERVAL - TP_PULSE_PRESS))


def start_tp_pulse():
    """텔포 키 background 반복 시작 — patrol_hold와 함께 호출."""
    global _TP_PULSE_THREAD, _TP_PULSE_STOP
    if _TP_PULSE_THREAD is not None and _TP_PULSE_THREAD.is_alive():
        return
    import threading
    _TP_PULSE_STOP = threading.Event()
    _TP_PULSE_THREAD = threading.Thread(target=_tp_pulse_loop, args=(_TP_PULSE_STOP,), daemon=True)
    _TP_PULSE_THREAD.start()


def stop_tp_pulse():
    """텔포 background pulse 중단 — release_all()/hunt_release() 시 호출."""
    global _TP_PULSE_THREAD, _TP_PULSE_STOP
    if _TP_PULSE_STOP is not None:
        _TP_PULSE_STOP.set()
    _TP_PULSE_THREAD = None
    _TP_PULSE_STOP   = None
    # 마지막 KEYUP 보장
    try:
        key_up(TELEPORT_KEY)
    except Exception:
        pass


def hunt_release():
    """hold 해제 — 모든 키 즉시 해제 (macro_v2 release_all과 동일)."""
    stop_tp_pulse()
    release()
    attack_release()
    tp_release()


# (face-lock 관련 helpers 제거 — 자연스러운 패트롤로 복원)


def release_all():
    """모든 hold 키 해제 — 캡차/상점/2층 처리 등 진입 시. 텔포 background pulse도 중단."""
    stop_tp_pulse()
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
    """↓+텔포 — drop_down 안 통하는 platform에서 fallback. 한 층 텔포로 내려감."""
    attack_release()
    release()
    key_down('down')
    rsleep(0.10, 0.2)
    key_down(TELEPORT_KEY)
    rsleep(0.05, 0.2)
    key_up(TELEPORT_KEY)
    rsleep(0.03, 0.2)
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


def up_teleport_safe():
    """포탈 진입 위험 영역(안전지대 등)에서 사용 — 단발 위+텔포.
    위 키 총 hold ≈ 100ms (0.1초) — 자리 잃음(포탈 진입 ≥300ms) 안전 마진.
    한 번에 위 텔포 안 되면 호출자가 여러 번 시도."""
    attack_release()
    release()
    key_down('up')
    time.sleep(0.070)            # up 인식 (70ms)
    key_down(TELEPORT_KEY)
    time.sleep(0.030)            # 텔포 발사 시점에 up 눌려있게 (30ms — up 총 100ms)
    key_up('up')                 # 텔포 키 떼기 전 위 키 먼저 떼기
    time.sleep(0.020)
    key_up(TELEPORT_KEY)


def hold_up_teleport(duration: float = 1.5):
    """up + space 동시 hold N초 — 연속 up_teleport로 빠르게 위층 도달.
    중간에 mob 맞아 떨어져도 다시 텔포 시전돼서 platform에 안착."""
    attack_release()
    release()
    print(f'[hold-up-tp] up+space hold {duration}s')
    key_down('up')
    key_down(TELEPORT_KEY)
    time.sleep(duration)
    key_up(TELEPORT_KEY)
    key_up('up')
    rsleep(0.1, 0.2)


def find_char_pos_with_jump() -> Optional[tuple]:
    """일반 검출 시도 후 None이면 점프로 본인 위치 확인.
    점프 키(x)는 포탈 트리거와 무관, 안전지대 platform에서도 떨어지지 않음 — 위 키 안 누름.
    다른 유저랑 겹쳐 일반 검출 실패할 때 본인 Y가 일시 변동되어 검출 가능.
    Returns (mm_x, mm_y) or None."""
    pos = find_char_minimap_pos(grab())
    if pos:
        return pos
    print('[jump-verify] mm None → 점프로 본인 위치 확인')
    tap(JUMP_KEY, 0.05)
    # 점프 모션 중(~0.3-0.5s) 짧게 여러 번 캡쳐
    deadline = time.time() + 0.5
    while time.time() < deadline:
        pos = find_char_minimap_pos(grab())
        if pos:
            print(f'[jump-verify] 점프 후 검출 OK mm={pos}')
            return pos
        time.sleep(0.04)
    print('[jump-verify] 점프 후도 검출 실패')
    return None


def _walk_in_safe_zone(target_x: int = 287, timeout: float = 5.0) -> None:
    """안전지대 platform 안에서 walk만으로 target X로 이동.
    텔포 절대 사용 안 함 (platform 좁아 떨어짐 위험), 위 키 절대 안 누름.
    None pos (다른 유저 겹침) 시 점프로 본인 위치 확인 후 walk."""
    print(f'[walk-safe] target_x={target_x} timeout={timeout}s')
    deadline = time.time() + timeout
    last_x = None
    none_streak = 0
    while time.time() < deadline and not STOP:
        pos = find_char_pos_with_jump()  # 점프 fallback 포함
        if not pos:
            none_streak += 1
            if none_streak > 3:
                print(f'[walk-safe] 점프 후도 None {none_streak}회 — 종료 (안전)')
                return
            time.sleep(0.08)
            continue
        none_streak = 0
        cur_x, cur_y = pos
        last_x = cur_x
        # 안전지대 platform 떨어짐 (mm_y 크게 변동) → 종료 (보호)
        if cur_y > SAFE_ZONE_TARGET_Y + 15:
            print(f'[walk-safe] platform 떨어짐 mm={pos} — 종료')
            return
        dx = target_x - cur_x
        if abs(dx) <= 3:
            print(f'[walk-safe] 도착 mm={pos}')
            return
        direction = LEFT if dx < 0 else RIGHT
        walk_dur = max(0.08, min(0.25, abs(dx) / 50))
        tap(direction, walk_dur)
        rsleep(0.04, 0.2)
    print(f'[walk-safe] timeout — 마지막 mm={pos if pos else None}')


def goto_safe_zone() -> bool:
    """
    안전지대(포탈 있는 층)로 이동 — 단발 up+tp 반복, mm_y <= SAFE_ZONE_TARGET_Y(131)까지.
    - up 키는 절대 hold 안 함 — 포탈 진입 방지 위해 up_teleport_safe() 단발만 사용.
    - X를 SAFE_ZONE_X_MIN~MAX로 정렬 → 도착할 때까지 단발 텔포 반복.
    - 도착 후 우측(310-324)이거나 캐릭 겹침이면 _walk_in_safe_zone으로 좌측(287) 이동.
    """
    rng = _safe_zone_x_range()
    if rng is None:
        print('[goto-safe] !! 안전지대 X 범위 미설정 — minimap_setup.py red 다시 실행 필요')
        return False
    target_min, target_max = rng
    target_center = (target_min + target_max) // 2

    print(f'[goto-safe] start (target X: {target_min}-{target_max}, '
          f'success: mm_y <= {SAFE_ZONE_TARGET_Y})')

    start = time.time()
    tries = 0
    last_attack = 0.0
    last_tp = 0.0
    safe_lie_counter = 0
    none_streak = 0          # 미니맵 검출 None 연속 카운터
    last_known_x = None      # 마지막으로 검출된 mm_x (다른 유저 겹침으로 None일 때 추정용)
    last_known_y = None      # 마지막으로 검출된 mm_y

    while not STOP and time.time() - start < GOTO_SAFE_TIMEOUT \
            and tries < GOTO_SAFE_MAX_TRIES:
        # 매 4 cycle마다 거짓말 탐지기 체크 (최우선)
        safe_lie_counter += 1
        if safe_lie_counter % 4 == 0 and lie_priority_check():
            return False
        screen = grab()
        pos = find_char_minimap_pos(screen)
        now = time.time()
        if pos is None:
            # 점프로 본인 위치 확인 시도 (다른 유저 겹쳐 안 보일 때 — 위 키 안 누름, 포탈 안전)
            pos = find_char_pos_with_jump()
        if pos is None:
            none_streak += 1
            # !! 미니맵 검출 None일 때 절대 위 키 시전 금지 — 포탈 진입 위험
            # last_known_y 기반 도착 추정만 허용 (위 키 안 누르고 그냥 return)
            if none_streak >= 8 and last_known_y is not None \
                    and last_known_y <= SAFE_ZONE_TARGET_Y + 20:
                print(f'[goto-safe] mm 검출 {none_streak}회 실패, last_y={last_known_y}'
                      f' (<={SAFE_ZONE_TARGET_Y + 20}) → 안전지대 도착 추정')
                release()
                return True
            rsleep(0.08, 0.2)
            continue
        none_streak = 0
        mm_x, mm_y = pos
        last_known_x = mm_x
        last_known_y = mm_y

        # 도착 확인 — mm_y가 안전지대 Y(131) 이하
        if mm_y <= SAFE_ZONE_TARGET_Y:
            print(f'[goto-safe] 도착 mm=({mm_x},{mm_y}) tries={tries}')
            # 도착 X가 좌측 안전 영역(284-290) 외이면 좌측 안전지대(287)로 walk 이동
            # mm_x=326처럼 안전지대 범위 약간 넘어도 trigger되도록 mm_x > 290 조건으로 확대
            if mm_x > 290:
                print(f'[goto-safe] 도착 X={mm_x} (좌측 안전 외) → 좌측 안전지대(287) walk 이동')
                _walk_in_safe_zone(target_x=287, timeout=8.0)
            release()
            return True

        # 정렬됨 → 단발 위+텔포 (X 범위 ±arrival_tol 안이면 시도)
        if (target_min - GOTO_SAFE_X_ARRIVAL_TOL) <= mm_x <= (target_max + GOTO_SAFE_X_ARRIVAL_TOL):
            # 포탈 영역(291-309) 안이면 위 키 시전 절대 금지 — 우측(310-324)으로 이동 후 재시도
            if PORTAL_DANGER_X[0] <= mm_x <= PORTAL_DANGER_X[1]:
                print(f'[goto-safe] !! 포탈 영역 mm_x={mm_x} ({PORTAL_DANGER_X[0]}-{PORTAL_DANGER_X[1]}) '
                      f'→ 위 키 금지, 우측({target_center}) walk')
                walk_dur = max(0.10, min(0.30, abs(target_center - mm_x) / 50))
                tap(RIGHT, walk_dur)
                rsleep(0.04, 0.3)
                continue
            # 시도/시간 기반 도달 가정 fallback — 다른 유저와 미니맵 겹침으로 검출 부정확한 환경 대응
            # tries 6번 + 6초 이상 시도했으면 도착 가정 (실제 미도달이면 shop_ui_open 검증에서 fail)
            if tries >= 6 and time.time() - start > 6.0:
                print(f'[goto-safe] tries={tries} elapsed={time.time()-start:.1f}s — '
                      f'도착 가정 (검출 부정확 가능 — 다른 유저 겹침)')
                release()
                return True
            tries += 1
            print(f'[goto-safe] 정렬 OK mm=({mm_x},{mm_y}) → up_tp_safe #{tries}')
            up_teleport_safe()
            last_tp = now
            rsleep(GOTO_SAFE_VERIFY_WAIT, 0.2)
            # 효과 검증 — 시도 후 mm_y 변화 출력
            pos_after = find_char_minimap_pos(grab())
            if pos_after:
                dy = pos_after[1] - mm_y
                marker = '✓ 올라감' if dy < -3 else ('= 변화 없음' if abs(dy) <= 3 else '↓ 내려감')
                print(f'[goto-safe]   ↳ #{tries} 후 mm={pos_after} dy={dy:+d} {marker}')
            continue

        # 정렬 이동 — target_center 향해
        # 사냥라인(평지)이면 dx>=30일 때 텔포 가능 (빠르게 접근)
        # 안전지대 platform(mm_y < 145)이면 좁아서 텔포 시 떨어짐 → walk만 (over-shoot 방지)
        dx = target_center - mm_x
        direction = LEFT if dx < 0 else RIGHT
        on_safe_platform = mm_y < (SAFE_ZONE_TARGET_Y + 14)  # 131+14=145
        if not on_safe_platform and abs(dx) >= 30:
            if now - last_tp >= jitter(TELEPORT_COOLDOWN, 0.2):
                teleport(direction)
                last_tp = now
                last_attack = now
        else:
            # walk — dx 비례, 너무 느리지 않게 (dx/50, 0.08~0.50s)
            walk_dur = max(0.08, min(0.50, abs(dx) / 50))
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


def lie_priority_check() -> bool:
    """무거운 함수(회수/상점/안전지대) 도중 호출 — 거짓말 탐지기 감지 시 즉시 처리.
    감지되면 release_all + handle_lie_detector 실행, True 리턴.
    caller는 True 받으면 자기 함수도 즉시 중단해야 함."""
    global STOP
    if STOP or not LIE_ENABLED:
        return False
    if not lie_detected(grab()):
        return False
    print('[lie-priority] 무거운 함수 도중 거짓말 탐지기 감지 → 즉시 처리')
    release_all()
    if LIE_HANDLE_MODE == 'stop':
        STOP = True
        return True
    ok = handle_lie_detector()
    if not ok:
        STOP = True
    return True


def handle_lie_detector():
    """캡차 처리 — 로그 파일 저장 안 함 (사용자 비활성화)."""
    return _handle_lie_detector_core()


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


def etc_check_slot_filled(screen) -> bool:
    """기타탭 인벤 첫 칸이 채워져 있는지 — ETC_CHECK_SLOT_ABS 영역 std 체크."""
    cx, cy = _game_rel(*ETC_CHECK_SLOT_ABS)
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


_shop_sale_count = 0  # 자동상점 누적 실행 횟수 — N회마다 기타템 판매


def _shop_sell_etc():
    """기타 탭 전환 후 개별 판매.
    - 상점 UI 안 ETC_SELL_SLOT_ABS(2500,982) 더블클릭 + ENTER → 1개 판매
    - 빈칸 체크: ETC_CHECK_SLOT_ABS(2050,990) 의 std
    - 첫 칸 비면 break, 그 외 ETC_MAX_SELL_TRIES 까지 반복."""
    print('[shop-etc] === 기타템 판매 시작 ===')
    try:
        _shop_check_stop()
        # 기타 탭 클릭
        et_x, et_y = _abs(*ETC_TAB_ABS)
        print(f'[shop-etc] 기타 탭 클릭 ({et_x},{et_y})')
        click_at(et_x, et_y)
        rsleep(0.5, 0.2)
        _shop_check_stop()

        # 판매: 상점 안 첫 슬롯 더블클릭 + ENTER 반복
        sell_x, sell_y = _abs(*ETC_SELL_SLOT_ABS)
        sold = 0
        empty_streak = 0  # 빈칸 연속 카운터 — 판매 중 그래픽 변화로 false positive 방지
        for i in range(ETC_MAX_SELL_TRIES):
            if STOP:
                break
            if not etc_check_slot_filled(grab()):
                empty_streak += 1
                if empty_streak >= 2:
                    print(f'[shop-etc] 인벤 빈칸 2회 확정 → 기타템 판매 완료 ({sold}개)')
                    break
                # 1회는 false positive 의심 — 잠깐 대기 후 재확인
                rsleep(0.12, 0.2)
                continue
            empty_streak = 0
            click_at(sell_x, sell_y, double=True)
            rsleep(0.08, 0.2)         # 판매 확인 다이얼로그 등장 대기 — 너무 빠르면 ENTER 씹힘
            _shop_check_stop()
            tap('enter', 0.03)
            rsleep(0.05, 0.2)         # ENTER 처리 + 인벤 슬롯 갱신 대기 (next iter 빈칸 오탐 방지)
            sold += 1
        else:
            print(f'[shop-etc] !! 최대 시도({ETC_MAX_SELL_TRIES}) 도달 — 인벤 안 비어있음')

        # 장비 탭 복귀는 auto_shop이 상점 닫은 후 처리 — 여기선 안 함
        print('[shop-etc] === 기타템 판매 끝 ===')
    except _ShopAborted:
        print('[shop-etc] !! F12 중단')


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

        # 자동상점 카운터 — N회마다 기타템도 판매
        global _shop_sale_count
        _shop_sale_count += 1
        if _shop_sale_count % SHOP_SALE_COUNT_FOR_ETC == 0:
            print(f'[shop] {_shop_sale_count}회째 — 기타템 판매 루트 추가')
            _shop_sell_etc()
            beep(1700)

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
        # 거짓말 탐지기 풀이 등으로 중간 중단 — 상점이 열려있을 가능성에 대비해
        # 상점 닫기 + 장비 탭 복귀 click을 안전망으로 보냄 (이미 닫혀있어도 무해)
        print('[shop] 중단 안전망 — 상점 닫기 + 장비 탭 복귀 시도')
        try:
            sc_x, sc_y = _abs(*SHOP_CLOSE_ABS)
            click_at(sc_x, sc_y)
            rsleep(0.4, 0.2)
            et_x, et_y = _abs(*EQUIP_TAB_ABS)
            click_at(et_x, et_y)
            rsleep(0.4, 0.2)
        except Exception as e:
            print(f'[shop] 안전망 click 실패 (무시): {e}')
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


STUCK_MINIMAP_DELTA = 5   # 미니맵 X가 이 픽셀보다 적게 움직이면 정체
STUCK_MINIMAP_SECONDS = 2.0  # 빨리 감지 — 끝 박힘 시 시간 낭비 줄임

# 사냥 라인 양 끝 mm_x 범위 (mm_probe_red로 측정) — 끝 도달 즉시 방향 반전
PATROL_LEFT_BOUND  = 113  # 좌측 끝 — 사냥 범위 확장
PATROL_RIGHT_BOUND = 295  # 우측 끝 — 안전지대(X=301-317) 잠수 유저 겹침 회피용으로 줄임

# 1층 낙하 감지 — 사냥 중 mm_y가 2층 baseline보다 이만큼 더 아래면 낙하 판정
FELL_TO_FLOOR1_DELTA_Y = 15
FELL_HOLD_SECONDS      = 0.4   # 위 조건 이 초 지속하면 확정 (오탐 방지)

# 2층 위(2층계단/3층) 감지 — 사냥라인 위로 올라간 경우 drop_down으로 복귀
FLOOR2_DELTA_Y       = 6     # mm_y가 사냥라인보다 이만큼 작아지면 위 platform 판정
FLOOR2_HOLD_SECONDS  = 0.6   # 위 조건 이 초 지속하면 확정
DROP_DOWN_COOLDOWN   = 1.2   # drop_down 시도 사이 최소 간격

# z hold platform 범위 230-244
HUNT_X_MIN = 230
HUNT_X_MAX = 244

# === 3층 맵 (red) 회수 루트 설정 =====================================
# 사냥은 2층(floor1_y_baseline=160)에서, 2분마다 회수 루트로 1/2/3층 다 훑어 펫이 줍게 함.
COLLECTION_INTERVAL = 70.0   # 70초 (2kill 버전 — 사냥 빠름)
COLLECTION_TIMEOUT  = 90.0   # 회수 루트 전체 타임아웃 — 안 끝나면 강제 종료

# 각 층 mm_y 좌표
FLOOR1_Y       = 191  # 2층 우측 끝에서 낙하한 1층 (가장 아래)
FLOOR2_Y       = 160  # 2층 (사냥라인) — minimap_config_red.floor1_y_baseline 와 동일 의미
FLOOR2_STAIR_Y = 156  # 2층계단 (2층과 3층 사이 작은 platform)
FLOOR3_Y       = 131  # 3층
FLOOR3_TOP_Y   = 115  # 3층에서 위+텔포 후 아래점프 도착 platform
FLOOR2_RIGHT_TOP_Y = 140  # 2층 우측에서 위+텔포 도착 platform (jump+drop 후 안착, z bounce 위치)
COLLECT_TOP_PLATFORM_Y = 124  # 회수 [2-4] hold_up_teleport 최종 도달 platform (Y=140 위 한 단계)
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
    clear_lie_counter = 0
    while time.time() < end and not STOP:
        clear_lie_counter += 1
        if clear_lie_counter % 5 == 0 and lie_priority_check():
            return
        pos = find_char_minimap_pos(grab())
        if pos and not (x_min <= pos[0] <= x_max):
            # 범위 밖 — center 복귀 walk
            dx = center - pos[0]
            direction = LEFT if dx < 0 else RIGHT
            walk_dur = min(0.10, max(0.06, abs(dx) / 80))
            tap(direction, walk_dur)
        tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
        time.sleep(0.04)


def _wait_landed(timeout: float = 1.0, stable_window: float = 0.15) -> bool:
    """char Y가 stable_window 초 동안 변화 ≤1px이면 landed로 판정.
    텔포/점프 후 mid-air 상태에서 다음 동작 시전하면 씹히므로, 안착 확인용."""
    deadline = time.time() + timeout
    last_y = None
    stable_since = None
    while time.time() < deadline and not STOP:
        pos = find_char_minimap_pos(grab())
        now = time.time()
        if pos:
            if last_y is None or abs(pos[1] - last_y) > 1:
                last_y = pos[1]
                stable_since = now
            elif stable_since is not None and now - stable_since >= stable_window:
                print(f'[landed] mm_y={pos[1]} (stable {stable_window}s)')
                return True
        time.sleep(0.04)
    print(f'[landed] timeout — last_y={last_y}')
    return False


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


# === v2 회수 helpers ===

HUNT_X_MIN = 230  # collection 정렬용 / z hold platform 좌측
HUNT_X_MAX = 244  # z hold platform 우측 마진
COLLECT_F1_PATROL_X = (156, 331)  # 1층 텔포공격 왕복 범위 (우측 +10)
COLLECT_F1_UPTP_X   = (97, 110)   # 1층 위+텔포 시도 X
COLLECT_F1_CLEAR_X  = (97, 128)   # 1층 up_tp 직전 몹 정리 X 범위
COLLECT_F1_LEFT_STOP_X = 180      # 1층 도착 후 먼저 찍는 X (좌측 회수)

# 3층 추가 회수 루트 (mm_probe 측정값)
ROUTE_3F_ENTRY_X        = 182          # 3층 진입 위 텔포 시작 X (Y=159 사냥라인)
ROUTE_3F_TOP_Y          = 102          # hold_up_teleport×2 후 도착 mm_y
ROUTE_3F_PLATFORM_X     = (176, 189)   # 3층 z bounce 범위 (우측 192→189, 가장자리 안전 마진)
ROUTE_3F_PLATFORM_Y     = 113
ROUTE_3F_DROP_TARGET_X  = 161          # 3층→2층 계단 가는 X
ROUTE_3F_DROP_TARGET_Y  = 131
ROUTE_F2_STAIR_X        = (151, 163)   # 2층 소규모 계단 z bounce
ROUTE_F2_STAIR_Y        = 144


def _route_to_x(x_min: int, x_max: int, target_y: int = None,
                y_tol: int = 10, timeout: float = 10.0,
                attack: bool = True, walk_threshold: int = 0) -> bool:
    """X 범위로 이동 — 텔포 우선, dx < walk_threshold일 때만 walk.
    walk_threshold=0(기본) 이면 walk 안 하고 텔포만 — walk 허용할 caller만 명시적으로 지정.
    walk 허용 범위: 1층 Y좌표 계단 근처(97-110), 2층 Y좌표 플랫폼 근처(231-245)."""
    target_center = (x_min + x_max) // 2
    deadline = time.time() + timeout
    last_tp = 0.0
    last_pos = None
    route_lie_counter = 0
    last_dx_sign = 0           # 마지막 dx 부호 (-1/0/+1)
    overshoot_count = 0        # 텔포 over-shoot 누적 — tolerance 넓힐 트리거
    arrival_tol = 0            # over-shoot 발생 시 도착 tolerance 추가 (텔포만 사용 시 무한 왕복 방지)
    while time.time() < deadline and not STOP:
        # 매 6 cycle마다 거짓말 탐지기 체크 (최우선)
        route_lie_counter += 1
        if route_lie_counter % 6 == 0 and lie_priority_check():
            return False
        pos = find_char_minimap_pos(grab())
        now = time.time()
        if not pos:
            time.sleep(0.05)
            continue
        last_pos = pos
        # 도착 — over-shoot 발생 후엔 arrival_tol만큼 범위 확장 (무한 왕복 방지)
        if (x_min - arrival_tol) <= pos[0] <= (x_max + arrival_tol):
            if target_y is None or abs(pos[1] - target_y) <= y_tol:
                print(f'[move] 도착 mm={pos} (tol={arrival_tol})')
                release()
                return True
        # Y가 target_y에서 크게 벗어남 → 다른 층에 떨어진 거. X 정렬 시도 무의미 → 일찍 종료
        if target_y is not None and abs(pos[1] - target_y) > y_tol * 3:
            print(f'[move] !! 다른 층 mm={pos} target_y={target_y} (|dy|>{y_tol*3}) → 일찍 종료')
            release()
            return False
        dx = target_center - pos[0]
        direction = LEFT if dx < 0 else RIGHT
        dx_sign = -1 if dx < 0 else (1 if dx > 0 else 0)
        # over-shoot 감지: 부호 반전 = 텔포가 target을 지나쳐 반대편으로
        # 텔포만 사용 — walk 금지. over-shoot마다 도착 tolerance 1씩 증가, 최대 8.
        # 8회 이상도 도착 못 하면 무한 왕복으로 판단해 일찍 종료.
        if last_dx_sign != 0 and dx_sign != 0 and last_dx_sign != dx_sign:
            overshoot_count += 1
            arrival_tol = min(overshoot_count * 2, 12)  # 2px씩 누적, 최대 12 (빠른 수렴)
            print(f'[move] over-shoot #{overshoot_count} mm={pos} → 도착 tol=±{arrival_tol} (텔포 유지)')
            if overshoot_count >= 6:
                print(f'[move] !! over-shoot {overshoot_count}회 — 무한 왕복으로 판단, 종료')
                release()
                return False
        last_dx_sign = dx_sign

        # 텔포 우선 (over-shoot 발생해도 walk 강제 안 함)
        if abs(dx) >= walk_threshold and now - last_tp >= jitter(TELEPORT_COOLDOWN, 0.2):
            teleport(direction)
            last_tp = now
        elif walk_threshold > 0:
            walk_dur = max(0.10, min(0.30, abs(dx) / 35))
            tap(direction, walk_dur)
            if attack:
                tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
        else:
            # walk_threshold=0 — walk 안 함, 텔포만. 텔포 못 시전하면 잠시 대기
            rsleep(0.05, 0.2)
        rsleep(0.04, 0.2)
    print(f'[move] 타임아웃 mm={last_pos}')
    release()
    return False


def _patrol_with_teleport(x_min: int, x_max: int, round_trips: int = 2,
                          timeout: float = 20.0) -> None:
    """텔포 우선으로 x_min↔x_max 왕복. 펫 회수용."""
    print(f'[patrol-tp] X={x_min}-{x_max} {round_trips}회왕복')
    release_all()
    rsleep(0.05, 0.2)
    start_pos = find_char_minimap_pos(grab())
    center = (x_min + x_max) // 2
    target = x_min if (start_pos and start_pos[0] >= center) else x_max
    ends_hit = 0
    last_tp = 0.0
    start = time.time()
    while ends_hit < round_trips * 2 and time.time() - start < timeout and not STOP:
        pos = find_char_minimap_pos(grab())
        now = time.time()
        if not pos:
            time.sleep(0.05)
            continue
        mm_x = pos[0]
        if (target == x_max and mm_x >= x_max) or (target == x_min and mm_x <= x_min):
            ends_hit += 1
            target = x_min if target == x_max else x_max
            print(f'[patrol-tp]   ▸ 끝 mm_x={mm_x} ends_hit={ends_hit}')
            continue
        direction = RIGHT if target > mm_x else LEFT
        dx = abs(target - mm_x)
        if dx >= 8 and now - last_tp >= jitter(TELEPORT_COOLDOWN, 0.2):
            teleport(direction)
            last_tp = now
        else:
            walk_dur = max(0.06, min(0.18, dx / 80))
            tap(direction, walk_dur)
            tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
        rsleep(0.04, 0.2)


def _bounce_with_z_v2(x_min: int, x_max: int, round_trips: int = 2,
                      timeout: float = 20.0, platform_y: int = None) -> None:
    """z hold + 왕복. 매 pass 중앙 통과 시 attack 1회 (왕복 1회당 2번 = 양방향 각각).
    platform_y가 명시되면 그 기준 +10px 이상 떨어지면 'platform 떨어짐' 감지 → up_teleport 복구.
    platform_y 미명시 시 기본값 = 2층 platform(Y=140) 기준.
    복구 실패 시 그대로 왕복 끝까지 진행 — caller가 drop_down으로 처리."""
    center = (x_min + x_max) // 2
    if platform_y is not None:
        fall_y_threshold = platform_y + 10
    else:
        fall_y_threshold = (FLOOR2_RIGHT_TOP_Y + FLOOR2_Y) // 2
    print(f'[bounce-v2] z hold X={x_min}-{x_max} {round_trips}회왕복 (매 pass 중앙 {center} attack)')
    release_all()
    rsleep(0.05, 0.2)
    key_down('z')
    try:
        start_pos = find_char_minimap_pos(grab())
        target = x_min if (start_pos and start_pos[0] >= center) else x_max
        last_x = start_pos[0] if start_pos else center
        pass_attacked = False
        ends_hit = 0
        start = time.time()
        bounce_lie_counter = 0
        last_uptp_attempt = 0.0
        while ends_hit < round_trips * 2 and time.time() - start < timeout and not STOP:
            bounce_lie_counter += 1
            if bounce_lie_counter % 4 == 0 and lie_priority_check():
                return
            pos = find_char_minimap_pos(grab())
            now = time.time()
            if not pos:
                time.sleep(0.05)
                continue
            mm_x, mm_y = pos
            # 2층 떨어짐 + zone 안 → up_teleport 시도 (1초 cooldown). 시도 1회 = 왕복 1회 카운트.
            if mm_y >= fall_y_threshold and x_min <= mm_x <= x_max and \
                    now - last_uptp_attempt > 1.0:
                ends_hit += 2
                print(f'[bounce-v2]   ⚠ 2층 떨어짐 mm={pos} → up_teleport 복구 (왕복 1회 카운트, ends_hit={ends_hit})')
                up_teleport()
                rsleep(0.3, 0.2)
                tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
                last_uptp_attempt = now
                last_x = mm_x
                continue
            # 중앙 통과 감지 — pass당 한 번만 attack
            if not pass_attacked:
                if (last_x < center and mm_x >= center) or (last_x > center and mm_x <= center):
                    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
                    pass_attacked = True
                    print(f'[bounce-v2]   ▷ 중앙 통과 mm_x={mm_x} [+attack]')
            last_x = mm_x
            if (target == x_max and mm_x >= x_max) or (target == x_min and mm_x <= x_min):
                ends_hit += 1
                target = x_min if target == x_max else x_max
                pass_attacked = False
                print(f'[bounce-v2]   ▸ 끝 mm_x={mm_x} ends_hit={ends_hit}')
                continue
            # 짧은 tap — hold면 가장자리 over-shoot로 platform 떨어짐.
            # walk 길게 + sleep 짧게로 매끄러움 유지하되 가장자리 안전.
            direction = RIGHT if target > mm_x else LEFT
            dx = abs(target - mm_x)
            walk_dur = max(0.06, min(0.16, dx / 80))
            tap(direction, walk_dur)
            time.sleep(0.02)
    finally:
        release()      # 방향키 떼기 (안전)
        key_up('z')
        rsleep(0.05, 0.2)


def _collect_special_route() -> None:
    """특별 회수 — z bounce 후 Y=140 platform 위에 그대로 있을 때 호출.
    LEFT 텔포 hold → 공격 hold → mm_y=131이면 더 공격 → 위텔포+아래점프 → 3층 z bounce.
    종료 후 1층까지 떨어짐은 caller가 _drop_until_floor1로 처리."""
    print('[collect-special] === 시작 ===')
    # 1) LEFT 텔포 hold 최대 1.3s — Y=131 도달 또는 platform 떨어짐 감지 시 조기 종료
    print('[collect-special] [1] LEFT 텔포 hold 최대 1.3s (Y=131 도달/떨어짐 시 조기 종료)')
    release_all()
    rsleep(0.05, 0.2)
    hold(LEFT)
    tp_hold()
    deadline = time.time() + 1.3
    while time.time() < deadline and not STOP:
        pos = find_char_minimap_pos(grab())
        if pos:
            if abs(pos[1] - 131) <= 3:
                print(f'[collect-special] [1] Y=131 도달 mm={pos} → 텔포 hold 종료')
                break
            if pos[1] >= FLOOR2_Y - 3:   # Y가 사냥 라인 가까이 = platform 떨어짐
                print(f'[collect-special] [1] platform 떨어짐 mm={pos} → 텔포 hold 종료')
                break
        time.sleep(0.05)
    release()
    tp_release()
    if STOP:
        return

    # 2) 공격 hold 1.3s
    print('[collect-special] [2] 공격 hold 1.3s')
    attack_hold()
    time.sleep(1.3)
    attack_release()
    rsleep(0.1, 0.2)   # 공격 떼기 인식 시간 — 다음 동작 씹힘 방지
    if STOP:
        return

    # 3) mm_y == 131이면 위 platform 도달 → 공격 hold 1.3s 더
    pos = find_char_minimap_pos(grab())
    if not pos or abs(pos[1] - 131) > 3:
        print(f'[collect-special] mm_y != 131 ({pos[1] if pos else "None"}) → 특별 회수 종료')
        return

    print(f'[collect-special] [3] mm={pos} (Y≈131) → 공격 hold 1.3s 더')
    attack_hold()
    time.sleep(1.3)
    attack_release()
    rsleep(0.1, 0.2)
    if STOP:
        return

    # 4) mm_y 다시 131 확인 → 위 텔포 + 공격 hold 1.3s → 공격 끊고 → 아래 점프
    pos = find_char_minimap_pos(grab())
    if not pos or abs(pos[1] - 131) > 3:
        print(f'[collect-special] mm_y != 131 ({pos[1] if pos else "None"}) → 특별 회수 종료')
        return

    print(f'[collect-special] [4] mm={pos} (Y≈131) → up_teleport + 공격 hold 1.3s + 공격 끊고 drop_down')
    up_teleport()
    rsleep(0.4, 0.2)
    # 위 텔포 후 위 platform에서 공격 hold 1.3s
    attack_hold()
    time.sleep(1.3)
    attack_release()
    rsleep(0.15, 0.2)   # 공격 떼기 인식 시간 — drop_down 씹힘 방지
    if STOP:
        return
    # up_tp 후 mm_y 기록 → drop_down 후 변화 없으면 down_teleport fallback
    pos_before = find_char_minimap_pos(grab())
    drop_down()
    rsleep(0.4, 0.2)
    pos_after = find_char_minimap_pos(grab())
    # drop_down 씹힘 검출: Y 변화 ≤ 5px이면 fallback
    if pos_before and pos_after and abs(pos_after[1] - pos_before[1]) <= 5:
        print(f'[collect-special] [4] drop_down 씹힘 (Y {pos_before[1]}→{pos_after[1]}) → down_teleport fallback')
        down_teleport()
        rsleep(0.4, 0.2)
    if STOP:
        return

    # 5) 3층 도달 검증 (X=175-191, Y=113-114)
    pos = find_char_minimap_pos(grab())
    if pos and 175 <= pos[0] <= 191 and 110 <= pos[1] <= 116:
        print(f'[collect-special] [5] 3층 도달 mm={pos} → z bounce 2회 왕복 (빠르게)')
        _bounce_with_z_v2(175, 191, round_trips=2)
    else:
        print(f'[collect-special] [5] 3층 미도달 mm={pos}')

    print('[collect-special] === 끝 ===')


def _drop_until_floor1(max_tries: int = 8, y_tol: int = 8) -> bool:
    """drop_down 반복해서 1층(FLOOR1_Y)까지 내려감.
    drop_down 씹힘 (Y 변화 ≤ 5) 감지 시 down_teleport fallback.
    max_tries 안에 못 내려가면 False."""
    for i in range(max_tries):
        if STOP:
            return False
        pos = find_char_minimap_pos(grab())
        if pos and abs(pos[1] - FLOOR1_Y) <= y_tol:
            print(f'[drop→F1] mm={pos} → 1층 도달 (시도 {i})')
            return True
        prev_y = pos[1] if pos else None
        print(f'[drop→F1] 시도 {i + 1}/{max_tries} mm={pos} → drop_down')
        drop_down()
        rsleep(DROP_DOWN_COOLDOWN, 0.2)
        # 씹힘 검출 → down_teleport fallback
        pos2 = find_char_minimap_pos(grab())
        if prev_y is not None and pos2 and abs(pos2[1] - prev_y) <= 5:
            print(f'[drop→F1]   ⚠ drop_down 씹힘 (Y {prev_y}→{pos2[1]}) → down_teleport')
            down_teleport()
            rsleep(DROP_DOWN_COOLDOWN, 0.2)
    pos = find_char_minimap_pos(grab())
    print(f'[drop→F1] !! {max_tries}회 시도 후도 1층 미도달 mm={pos}')
    return False


def _collect_3f_route() -> None:
    """[10] 2층 도달 후 추가 회수 — 3층까지 올라가 회수 후 2층 복귀.
    [A] X=182 정렬 + 몹 정리 + hold_up_teleport×2 (Y=102 도달)
    [B] mm=(185, 102) 부근 몹 정리 + 공격 hold 1.4s + drop_down → 3층 platform
    [C] 3층 platform (176-192, 113) z bounce 2회
    [D] drop_down + 공격 hold 1.4s
    [E] X=161 walk 이동 + drop_down×2 (Y=131 → 2층 계단)
    [F] 2층 계단 (151-163, 144) z bounce 2회
    [G] LEFT 텔포 1회 → 2층 복귀"""
    print('[3f-route] === 시작 ===')

    # [A] X=182 정렬 + 몹 정리 + hold_up_teleport×2
    print(f'[3f-route] [A] X={ROUTE_3F_ENTRY_X} 정렬 (공격 끔)')
    ok = _route_to_x(ROUTE_3F_ENTRY_X - 5, ROUTE_3F_ENTRY_X + 5,
                     target_y=FLOOR2_Y, y_tol=10, timeout=10.0,
                     walk_threshold=15, attack=False)
    if STOP or not ok:
        print('[3f-route] [A] 정렬 실패 → 종료')
        return
    _clear_mobs(ROUTE_3F_ENTRY_X - 5, ROUTE_3F_ENTRY_X + 5, duration=1.4)
    if STOP:
        return
    print(f'[3f-route] [A] hold_up_teleport(1.3) — Y={ROUTE_3F_TOP_Y} 도달까지 3회 (미도달 시 X 재정렬)')
    top_reached = False
    for tp_try in range(3):
        if STOP:
            return
        hold_up_teleport(1.3)
        rsleep(0.4, 0.2)
        pos = find_char_minimap_pos(grab())
        if pos and pos[1] <= ROUTE_3F_TOP_Y + 5:
            print(f'[3f-route] [A] Y≈{ROUTE_3F_TOP_Y} 도달 mm={pos}')
            top_reached = True
            break
        print(f'[3f-route] [A] 미도달 #{tp_try + 1}/3 mm={pos} → X={ROUTE_3F_ENTRY_X} 재정렬 (Y 무시)')
        # 몹 피격으로 X 틀어졌을 수 있음 → X만 재정렬 (Y는 현재 위치 그대로)
        _route_to_x(ROUTE_3F_ENTRY_X - 5, ROUTE_3F_ENTRY_X + 5,
                    target_y=None, timeout=8.0,
                    walk_threshold=15, attack=False)
    if not top_reached:
        print('[3f-route] [A] !! Y=102 미도달 → 종료')
        return

    # [B] 공격 1회 + drop_down → 3층 (공격 너무 많으면 drop_down 씹힘 → _clear_mobs 제거)
    print('[3f-route] [B] 공격 1회 + drop_down → 3층(Y=113)')
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    attack_release()        # 공격 키 buffer 비우기 (drop_down 씹힘 방지)
    rsleep(0.20, 0.2)
    for d_try in range(2):
        drop_down()
        rsleep(0.3, 0.2)
        pos = find_char_minimap_pos(grab())
        if pos and abs(pos[1] - ROUTE_3F_PLATFORM_Y) <= 5:
            print(f'[3f-route] [B] 3층 도달 mm={pos}')
            break
        print(f'[3f-route] [B] drop_down #{d_try+1} 미도달 mm={pos}')
        if STOP:
            return

    # [C] 3층 platform z bounce 2회 — X 맞고 사냥라인보다 위(Y<154)면 platform 위로 간주
    # 떨어짐 감지 기준 3층 platform_y=113 → 떨어지면 up_teleport 복구
    pos = find_char_minimap_pos(grab())
    if pos and ROUTE_3F_PLATFORM_X[0] <= pos[0] <= ROUTE_3F_PLATFORM_X[1] and \
            pos[1] < FLOOR2_Y - 5:
        print(f'[3f-route] [C] 3층 X 범위 도달 mm={pos} (Y<{FLOOR2_Y-5}) → z bounce 2회')
        _bounce_with_z_v2(ROUTE_3F_PLATFORM_X[0], ROUTE_3F_PLATFORM_X[1],
                          round_trips=2, platform_y=ROUTE_3F_PLATFORM_Y)
    else:
        print(f'[3f-route] [C] 3층 미도달 mm={pos} → z bounce 생략')
    if STOP:
        return

    # [D] drop_down → Y=131 통과 platform 도달까지 최대 2회 + 공격 hold 1.4s
    print('[3f-route] [D] drop_down → Y=131 + 공격 hold 1.4s')
    for d_try in range(2):
        drop_down()
        rsleep(0.3, 0.2)
        pos = find_char_minimap_pos(grab())
        if pos and abs(pos[1] - ROUTE_3F_DROP_TARGET_Y) <= 5:
            print(f'[3f-route] [D] Y={ROUTE_3F_DROP_TARGET_Y} 도달 mm={pos}')
            break
        print(f'[3f-route] [D] drop_down #{d_try+1} 미도달 mm={pos}')
        if STOP:
            return
    attack_hold()
    time.sleep(1.4)
    attack_release()
    rsleep(0.15, 0.2)
    if STOP:
        return

    # [E] X=161 walk 이동 — Y=114(3층)/131/144 어느 platform에서든 시작 가능
    # 사냥라인(Y=159)/1층(Y=191)까지 떨어졌으면 진짜 떨어짐 → 종료
    print(f'[3f-route] [E] X={ROUTE_3F_DROP_TARGET_X} walk 이동')
    target_x = ROUTE_3F_DROP_TARGET_X
    walk_deadline = time.time() + 8.0
    arrived_x = False
    while time.time() < walk_deadline and not STOP:
        pos = find_char_minimap_pos(grab())
        if not pos:
            time.sleep(0.05)
            continue
        cur_x, cur_y = pos
        # 사냥라인 이하로 떨어졌으면 진짜 platform 떨어진 거 → 종료
        if cur_y >= FLOOR2_Y - 5:
            print(f'[3f-route] [E] 사냥라인까지 떨어짐 mm={pos} → 종료')
            return
        dx = target_x - cur_x
        if abs(dx) <= 3:
            print(f'[3f-route] [E] X 도착 mm={pos}')
            arrived_x = True
            break
        direction = LEFT if dx < 0 else RIGHT
        walk_dur = max(0.06, min(0.15, abs(dx) / 60))
        tap(direction, walk_dur)
        rsleep(0.03, 0.2)
    if STOP or not arrived_x:
        if not arrived_x:
            print('[3f-route] [E] walk 타임아웃')
        return

    # 2층 계단(Y=144) 도달까지 drop_down 최대 2회 — 도달 후엔 멈춤 (지나치지 않게)
    print('[3f-route] [E] drop_down → 2층 계단(Y=144) 도달까지 최대 2회')
    for d_try in range(2):
        drop_down()
        rsleep(0.3, 0.2)
        pos = find_char_minimap_pos(grab())
        if pos and abs(pos[1] - ROUTE_F2_STAIR_Y) <= 5:
            print(f'[3f-route] [E] 2층 계단 도달 mm={pos}')
            break
        print(f'[3f-route] [E] drop_down #{d_try + 1} 미도달 mm={pos}')
        if STOP:
            return

    # [F] 2층 계단 z bounce 1회 — X 맞고 사냥라인보다 위면 platform 위로 간주
    # 떨어짐 감지 기준 2층 계단 platform_y=144 → 떨어지면 up_teleport 복구
    # z bounce 후 사냥라인까지 떨어졌으면 [G] LEFT 텔포 생략, 그냥 사냥 재개
    pos = find_char_minimap_pos(grab())
    if pos and ROUTE_F2_STAIR_X[0] <= pos[0] <= ROUTE_F2_STAIR_X[1] and \
            pos[1] < FLOOR2_Y - 5:
        print(f'[3f-route] [F] 2층 계단 X 범위 도달 mm={pos} (Y<{FLOOR2_Y-5}) → z bounce 1회')
        _bounce_with_z_v2(ROUTE_F2_STAIR_X[0], ROUTE_F2_STAIR_X[1],
                          round_trips=1, platform_y=ROUTE_F2_STAIR_Y)
        # 떨어짐 확인 — 사냥라인 이하면 [G] 생략하고 바로 사냥 재개
        pos = find_char_minimap_pos(grab())
        if pos and pos[1] >= FLOOR2_Y - 5:
            print(f'[3f-route] [F] z bounce 후 떨어짐 mm={pos} → [G] 생략, 사냥 재개')
            return
    else:
        print(f'[3f-route] [F] 2층 계단 미도달 mm={pos} → z bounce 생략')
    if STOP:
        return

    # [G] LEFT 텔포 1회 → 2층 복귀
    print('[3f-route] [G] LEFT 텔포 1회 → 2층 복귀')
    teleport(LEFT)
    rsleep(0.4, 0.2)

    print('[3f-route] === 끝 ===')


def _collect_phase_f1_to_hunt(skip_patrol: bool = False):
    """[8-11] 1층에서 사냥 zone(231-245)으로 복귀.
    skip_patrol=False (회수): LEFT 180 → RIGHT 321 → UP 97-110 → up_tp → 231-245
    skip_patrol=True  (낙하 복귀): 좌/우 왕복 생략, 바로 UP 97-110 → up_tp → 231-245"""
    if STOP:
        return
    _, f1_hi = COLLECT_F1_PATROL_X  # (_, 331)
    f1up_lo, f1up_hi = COLLECT_F1_UPTP_X  # (97, 110)
    clear_lo, clear_hi = COLLECT_F1_CLEAR_X  # (97, 128)

    if not skip_patrol:
        # 시작 위치 확인 — 좌측 기준점(180)보다 왼쪽에 떨어졌으면 [8a] 생략하고 바로 [8b]
        cur_pos = find_char_minimap_pos(grab())
        skip_8a = bool(cur_pos and cur_pos[0] < COLLECT_F1_LEFT_STOP_X)
        if skip_8a:
            print(f'[recover/collect] 시작 mm={cur_pos} → 좌측 기준({COLLECT_F1_LEFT_STOP_X}) 왼쪽 → [8a] 생략, 바로 [8b]')
        else:
            # [8a] 좌측 X=180 먼저 찍기 — 펫 좌측 회수
            print(f'[recover/collect] [8a] 1층 좌측 X={COLLECT_F1_LEFT_STOP_X} 이동 (텔포 only)')
            _route_to_x(COLLECT_F1_LEFT_STOP_X - 10, COLLECT_F1_LEFT_STOP_X + 5,
                        target_y=FLOOR1_Y, y_tol=15, timeout=12.0, walk_threshold=0)
            if STOP:
                return

        # [8b] 우측 끝 (321) 찍기 — 펫 우측 회수
        print(f'[recover/collect] [8b] 1층 우측 끝 X={f1_hi} 이동 (텔포 only)')
        _route_to_x(f1_hi - 15, f1_hi, target_y=FLOOR1_Y, y_tol=15, timeout=15.0,
                    walk_threshold=0)
        if STOP:
            return
    else:
        print('[recover/collect] 1층 좌/우 왕복 [8a/8b] 생략 — 바로 up-tp 위치로')

    # [9] 좌측 up-tp 위치 (97-110) 이동 — 폭 13px이라 텔포 over-shoot 잦음. walk_threshold 크게 (계단 근처 walk)
    print(f'[recover/collect] [9] X={f1up_lo}-{f1up_hi} 이동 (up-tp 위치)')
    _route_to_x(f1up_lo, f1up_hi, target_y=FLOOR1_Y, y_tol=15, timeout=15.0,
                walk_threshold=15)
    if STOP:
        return

    # [10] 몹 정리 (97-128 넓게) → up+space hold (실패 시 재정렬 + 재시도)
    # 2층 도달하면 사냥 zone 정렬 안 하고 바로 hunt 복귀 — patrol이 알아서 사냥
    _clear_mobs(clear_lo, clear_hi, duration=2.0)
    for tp_try in range(3):
        if STOP:
            return
        print(f'[recover/collect] [10] up+space 1.3s hold #{tp_try + 1}/3')
        hold_up_teleport(1.3)
        tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
        rsleep(0.4, 0.2)
        pos = find_char_minimap_pos(grab())
        if pos and pos[1] <= FLOOR2_Y + 10:
            print(f'[recover/collect] [10] 2층 도달 mm={pos} → 3층 추가 회수 진입')
            _collect_3f_route()
            print('[recover/collect] [10] 3층 추가 회수 끝 → 사냥 복귀')
            return
        print(f'[recover/collect] [10] 2층 미도달 mm={pos} → 재정렬 후 재시도')
        # up-tp 위치(97-110)로 재정렬 — walk_threshold 크게 (텔포 over-shoot 방지)
        _route_to_x(f1up_lo, f1up_hi, target_y=FLOOR1_Y, y_tol=15, timeout=8.0,
                    walk_threshold=15)
    # 3회 모두 실패 시 종료 (hunt 루프가 1층 낙하 감지로 재시도)
    print('[recover/collect] [10] !! 3회 시도 후도 2층 미도달 — 종료')


_collect_start_ts = 0.0   # collection_route 시작 시각 — 끝 시 elapsed 출력용


def collection_route():
    """v2 회수 루트 — 80초마다.
    [1] 231-245 정렬 → [2-4] up_tp×2(hold) + jump + drop (→ Y=140)
    [5] Y=140 attack → [6] z bounce 1회왕복 → [7] drop×2 → 1층
    [8-11] _collect_phase_f1_to_hunt: 156-321 텔포공격 → 97-110 → up_tp → 231-245 복귀"""
    global _collect_start_ts
    _collect_start_ts = time.time()
    print('[collect-v2] === 시작 ===')
    release_all()
    rsleep(0.1, 0.2)
    if MINIMAP_CFG is None:
        print('[collect-v2] minimap config 없음 — 중단')
        return

    # [1] X=231-245 정렬 — 공격 끄고 정렬만. 사냥 라인(Y=160) 정렬 실패 시 = 캐릭이 2층 아님 → 1층 회수로 우회
    # (위 platform에 있는 상태로 hold_up_teleport 시전하면 더 위로 가서 이상한 곳 도달)
    print('[collect-v2] [1] X=231-245 정렬 (공격 끔)')
    ok = _route_to_x(HUNT_X_MIN, HUNT_X_MAX, target_y=FLOOR2_Y, y_tol=10, timeout=10.0,
                    walk_threshold=30, attack=False)
    if STOP:
        return
    if not ok:
        pos = find_char_minimap_pos(grab())
        print(f'[collect-v2] [1] 2층 정렬 실패 mm={pos} → 1층까지 떨어진 후 1층 회수만 진행')
        _drop_until_floor1(max_tries=8)
        if STOP:
            return
        _collect_phase_f1_to_hunt()
        print(f'[collect-v2] === 끝 (2층 정렬 실패, 소요 {time.time() - _collect_start_ts:.1f}s) ===')
        return

    # [2-4] 몹 정리(_clear_mobs에서 처리) → 재정렬(공격 끔) → up_tp(hold) → platform 도달 확인 후 jump + drop
    _clear_mobs(HUNT_X_MIN, HUNT_X_MAX, duration=2.0)
    pos = find_char_minimap_pos(grab())
    if pos and not (HUNT_X_MIN <= pos[0] <= HUNT_X_MAX):
        print(f'[collect-v2] clear 후 zone 벗어남 mm={pos} → 재정렬 (공격 끔)')
        _route_to_x(HUNT_X_MIN, HUNT_X_MAX, target_y=FLOOR2_Y, y_tol=10, timeout=6.0,
                    walk_threshold=30, attack=False)

    # up_tp hold → 최상층 Y=124 도달까지 최대 3회 재시도
    # 원거리 공격 맞고 떨어지면 jump+drop이 그대로 실행돼 1층까지 떨어지는 문제 방지
    platform_reached = False
    for up_try in range(3):
        if STOP:
            return
        print(f'[collect-v2] [2-4] up_tp hold 1.3s #{up_try + 1}/3')
        hold_up_teleport(1.3)
        _wait_landed(timeout=1.2, stable_window=0.15)
        pos = find_char_minimap_pos(grab())
        # 최상층 platform 도달 = mm_y <= COLLECT_TOP_PLATFORM_Y(124) + 3 → Y=123~127
        if pos and pos[1] <= COLLECT_TOP_PLATFORM_Y + 3:
            print(f'[collect-v2] [2-4] 최상층 platform 도달 mm={pos}')
            platform_reached = True
            break
        print(f'[collect-v2] [2-4] 최상층 미도달 mm={pos} (Y>{COLLECT_TOP_PLATFORM_Y + 3}) → 재정렬 후 재시도 (공격 끔)')
        # 사냥 zone(231-244)으로 재정렬 — 공격 끄고 정렬만
        _route_to_x(HUNT_X_MIN, HUNT_X_MAX, target_y=FLOOR2_Y, y_tol=10, timeout=8.0,
                    walk_threshold=30, attack=False)

    if not platform_reached:
        print('[collect-v2] [2-4] !! 최상층 미도달 — [5-6] 생략, 바로 1층 회수로')
        _drop_until_floor1(max_tries=8)
        if STOP:
            return
        _collect_phase_f1_to_hunt()
        print(f'[collect-v2] === 끝 (최상층 미도달, 소요 {time.time() - _collect_start_ts:.1f}s) ===')
        return

    # [3] 최상층 도달 → 점프만 (공격 hold X, 단순)
    print('[collect-v2] [3] jump')
    tap(JUMP_KEY, 0.15); rsleep(0.4, 0.2)
    # 점프 후 최상층 platform 이탈 체크 (knockback으로 한 층 아래 떨어졌으면 mm_y 커짐)
    pos = find_char_minimap_pos(grab())
    if not pos or pos[1] > COLLECT_TOP_PLATFORM_Y + 10:
        print(f'[collect-v2] jump+attack 후 최상층 이탈 mm={pos} → drop 생략, 1층 회수로')
        _drop_until_floor1(max_tries=8)
        if STOP:
            return
        _collect_phase_f1_to_hunt()
        print(f'[collect-v2] === 끝 (jump 후 이탈, 소요 {time.time() - _collect_start_ts:.1f}s) ===')
        return
    # [3.5] 아래 점프 직전 — 최상층(Y=124) platform 위에서 attack ×2 (몹 정리)
    print('[collect-v2] [3.5] 최상층 attack ×2 (아래 점프 직전)')
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)

    # [4] 아래점프 → Y=140 안착 (씹힘 검출 시 down_teleport fallback)
    drop_down(); rsleep(0.3, 0.2)
    pos = find_char_minimap_pos(grab())
    if pos and pos[1] <= COLLECT_TOP_PLATFORM_Y + 5:
        print(f'[collect-v2] [4] drop_down 씹힘 mm={pos} → down_teleport fallback')
        down_teleport()
        rsleep(0.3, 0.2)
    if STOP:
        return

    # [5] Y=140 attack
    pos = find_char_minimap_pos(grab())
    print(f'[collect-v2] [5] mm={pos} → attack')
    tap(ATTACK_KEY, ATTACK_DOWN_SECONDS)

    # [6] z bounce 2회왕복 (매 pass 중앙 attack, 빠르고 매끄럽게)
    print('[collect-v2] [6] z bounce 2회왕복')
    _bounce_with_z_v2(HUNT_X_MIN, HUNT_X_MAX, round_trips=2)
    if STOP:
        return

    # [7] drop_down → 1층 (도달할 때까지 반복)
    print('[collect-v2] [7] drop_down → 1층 (도달까지 반복)')
    _drop_until_floor1(max_tries=8)

    # [8-11] 1층 → 사냥 zone 복귀
    _collect_phase_f1_to_hunt()

    print(f'[collect-v2] === 끝 (소요 {time.time() - _collect_start_ts:.1f}s) ===')


def hunt():
    """
    v2 패턴 (좌우 교대 패트롤): macro_v2.hunt() 와 동일 구조.
    - 130~305 X 사이 좌우 교대, LEFT 끝에서만 release+hold(RIGHT)로 반전 (jump_teleport X)
    - 3개 키(direction/attack/teleport) 모두 hold
    - 1분 30초마다 collection_route()
    - 1층 낙하 시 _recover_floor1_to_floor2 복귀
    """
    last_petfeed = time.time()
    last_collect = time.time()
    stuck_dir    = LEFT  # 안전지대 우측 = 낭떠러지 → 시작은 LEFT로 이동
    frame        = 0

    # 시작 위치 체크 — 안전지대 등 2층 위에 있으면 drop_down으로 먼저 내려옴
    _floor_y_init = MINIMAP_CFG.get('floor1_y_baseline') if MINIMAP_CFG else None
    if _floor_y_init is not None:
        for _ in range(5):
            _p = find_char_minimap_pos(grab())
            if not _p:
                time.sleep(0.2)
                continue
            if abs(_p[1] - _floor_y_init) <= 8:
                print(f'[hunt-init] 시작 위치 mm={_p} (2층 OK)')
                break
            if _p[1] < _floor_y_init - 6:
                print(f'[hunt-init] 시작 위치 mm={_p} → 위 platform — drop_down')
                drop_down()
                time.sleep(0.5)
            elif _p[1] > _floor_y_init + 10:
                print(f'[hunt-init] 시작 위치 mm={_p} → 1층 — 회수 phase 8-11로 복귀')
                _collect_phase_f1_to_hunt(skip_patrol=True)
                break

    last_mm_x       = None
    last_mm_move_ts = time.time()

    floor1_y          = MINIMAP_CFG.get('floor1_y_baseline') if MINIMAP_CFG else None
    on_floor2_since   = None
    last_drop_down    = 0.0
    fell_to_f1_since  = None
    none_streak_hunt  = 0     # mm=None 연속 카운터 — 다른 유저 겹침 감지
    last_none_recovery = 0.0  # mm=None drop_down 복구 마지막 시각
    drop_attempts     = 0     # drop_down 누적 시도 (실패 무한 방지)

    last_log_ts = 0.0
    last_force_reverse = time.time()
    last_key_refresh = time.time()
    con_check_until = 0.0

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

        # 0-d) 인벤 가득 → auto_shop
        if frame % INV_TRIGGER_CHECK_EVERY == 0 and inv_trigger_full(screen):
            release_all()
            print('[hunt] 인벤 트리거 → auto_shop()')
            auto_shop()
            last_mm_move_ts = time.time()
            on_floor2_since = None
            hold_all(stuck_dir)
            last_key_refresh = time.time()
            continue

        # 0-e) 회수 루트 (사냥 재개 시점부터 1분 30초)
        if now - last_collect >= COLLECTION_INTERVAL:
            release_all()
            print(f'[hunt] 회수 트리거 ({(now - last_collect):.0f}s 경과)')
            collection_route()
            last_collect = time.time()  # 회수 끝난 시점부터 다시 카운트
            last_mm_move_ts = time.time()
            on_floor2_since = None
            hold_all(stuck_dir)
            last_key_refresh = time.time()
            continue

        # 미니맵 좌표
        mm_pos = find_char_minimap_pos(screen)
        mm_x, mm_y = (mm_pos if mm_pos else (None, None))
        if mm_x is not None:
            none_streak_hunt = 0
            if last_mm_x is None or abs(mm_x - last_mm_x) > STUCK_MINIMAP_DELTA:
                last_mm_x = mm_x
                last_mm_move_ts = now
            if floor1_y is None:
                floor1_y = mm_y
        else:
            # mm=None 지속 — 잠수 유저 등 다른 점에 본인 노란 점이 묻혀 검출 실패
            # 30 cycle (~3초) 이상 None + 마지막 복구 후 5초 지났으면 drop_down으로 위치 강제 변동
            none_streak_hunt += 1
            if none_streak_hunt >= 30 and now - last_none_recovery > 5.0:
                print(f'[recovery] mm=None {none_streak_hunt}회 — 다른 유저 겹침 가정 → drop_down')
                release_all()
                rsleep(0.05, 0.2)
                drop_down()
                last_none_recovery = now
                none_streak_hunt = 0
                last_mm_move_ts = now
                hold_all(stuck_dir)
                last_key_refresh = time.time()
                continue

        # 2층 위 감지 → 아래 점프 (사냥라인 위로 올라간 경우)
        # 단계: 1-3 drop_down → 4-6 down_teleport → 7-8 jump_teleport(L/R) → 9-10 teleport(L/R) → 11+ 무한 재시도
        # (밧줄/사다리/특수 platform 등에서 어떻게든 빠져나오기 위해 STOP 안 함)
        if mm_y is not None and floor1_y is not None and mm_y < floor1_y - FLOOR2_DELTA_Y:
            if on_floor2_since is None:
                on_floor2_since = now
            elif now - on_floor2_since > FLOOR2_HOLD_SECONDS and now - last_drop_down > DROP_DOWN_COOLDOWN:
                drop_attempts += 1
                release_all()
                rsleep(0.05, 0.2)
                if drop_attempts <= 3:
                    print(f'[*] 사냥라인 위 감지 (mm_y={mm_y}) → drop_down #{drop_attempts}')
                    drop_down()
                elif drop_attempts <= 6:
                    print(f'[*] drop_down 안 통함 → down_teleport #{drop_attempts - 3} (mm_y={mm_y})')
                    down_teleport()
                elif drop_attempts == 7:
                    print(f'[*] down_teleport 안 통함 → jump_teleport(LEFT) (mm_y={mm_y})')
                    jump_teleport(LEFT)
                elif drop_attempts == 8:
                    print(f'[*] → jump_teleport(RIGHT) (mm_y={mm_y})')
                    jump_teleport(RIGHT)
                elif drop_attempts == 9:
                    print(f'[*] → teleport(LEFT) 옆 텔포 (mm_y={mm_y})')
                    teleport(LEFT)
                elif drop_attempts == 10:
                    print(f'[*] → teleport(RIGHT) 옆 텔포 (mm_y={mm_y})')
                    teleport(RIGHT)
                else:
                    try:
                        winsound.Beep(2500, 200)
                    except Exception:
                        pass
                    print(f'[!] 모든 fallback 실패 (mm_y={mm_y}) — 사이클 리셋 후 재시도')
                    drop_attempts = 0
                last_drop_down = now
                on_floor2_since = now
                last_mm_move_ts = now
                hold_all(stuck_dir)
                last_key_refresh = time.time()
                continue
        else:
            on_floor2_since = None
            drop_attempts = 0  # 사냥라인으로 정상 복귀 → 리셋

        # 1층 낙하 감지 → v1 회복
        if mm_y is not None and floor1_y is not None and mm_y > floor1_y + FELL_TO_FLOOR1_DELTA_Y:
            if fell_to_f1_since is None:
                fell_to_f1_since = now
            elif now - fell_to_f1_since > FELL_HOLD_SECONDS:
                print(f'[*] 1층 낙하 감지 (mm_y={mm_y}) → v1 복귀')
                release_all()
                rsleep(0.05, 0.2)
                _collect_phase_f1_to_hunt(skip_patrol=True)  # 낙하 복귀 — 1층 왕복 생략
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

        # 펫 먹이
        if now - last_petfeed > PET_FEED_INTERVAL:
            print(f'[pet] 먹이 2개 시전 ({PET_FEED_KEY!r})')
            release_all()
            rsleep(0.25, 0.2)
            tap(PET_FEED_KEY, 0.10)
            rsleep(0.40, 0.2)
            tap(PET_FEED_KEY, 0.10)
            rsleep(0.20, 0.2)
            last_petfeed = now + random.uniform(-15.0, 15.0)
            hold_all(stuck_dir)
            last_key_refresh = time.time()

        # 위치 기반 끝 도달 — 방향키만 swap (hold), attack+tp는 그대로 hold 유지 (face lock 유지)
        if mm_x is not None:
            at_left_end  = stuck_dir == LEFT  and mm_x <= PATROL_LEFT_BOUND
            at_right_end = stuck_dir == RIGHT and mm_x >= PATROL_RIGHT_BOUND
            # 양 끝 도달 시 release_all + teleport(점프 없음) + hold_all
            if at_left_end or at_right_end:
                new_dir = RIGHT if at_left_end else LEFT
                print(f'[edge] mm_x={mm_x} {stuck_dir} 끝 → 즉시 {new_dir} (텔포만)')
                release_all()
                teleport(new_dir)
                stuck_dir = new_dir
                last_mm_move_ts = now
                last_force_reverse = now
                last_key_refresh = time.time()
                hold_all(stuck_dir)
                continue

        # stuck 감지 (끝 박힘 폴백) → release_all + teleport(점프 없음) + hold_all
        mm_stuck = mm_x is not None and now - last_mm_move_ts > STUCK_MINIMAP_SECONDS
        if mm_stuck:
            stuck_dir = LEFT if stuck_dir == RIGHT else RIGHT
            print(f'[stuck-rev] mm_x={mm_x} → {stuck_dir} 반전 (텔포만, 점프 없음)')
            release_all()
            teleport(stuck_dir)
            last_mm_move_ts = now
            last_force_reverse = now
            last_key_refresh = time.time()
            hold_all(stuck_dir)
            continue

        # 시간 기반 강제 반전 (안전장치)
        if now - last_force_reverse > jitter(PATROL_REVERSE_SECONDS, 0.15):
            stuck_dir = LEFT if stuck_dir == RIGHT else RIGHT
            last_force_reverse = now
            last_key_refresh = now
            print(f'[periodic] 반전 → {stuck_dir} (모든 키 리프레시)')
            release_all()
            rsleep(0.05, 0.2)
            hold_all(stuck_dir)

        # 주기 키 리프레시 — 같은 키 오래 hold 시 게임 입력 거부 방지
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

    print('=' * 60)
    print('  macro_red_2kill — 몹 2방 사양 (회수 80s, 2층 계단 z bounce 1회)')
    print('=' * 60)
    print(f'게임 영역: {GAME_REGION}')
    print(f'키: 공격={ATTACK_KEY!r}  텔포={TELEPORT_KEY!r}  점프={JUMP_KEY!r}  줍기={PICKUP_KEY!r}  펫먹이={PET_FEED_KEY!r}')
    print(f'펫 먹이 주기: {PET_FEED_INTERVAL:.0f}초')
    if MINIMAP_CFG:
        print(f'미니맵 설정: rect={MINIMAP_CFG["minimap_rect"]} color={MINIMAP_CFG["char_color_bgr"]} tol={MINIMAP_CFG.get("tolerance",25)}')
        base = MINIMAP_CFG.get('floor1_y_baseline')
        print(f'사냥라인 Y={base}  패트롤 X={PATROL_LEFT_BOUND}-{PATROL_RIGHT_BOUND}')
        print(f'회수 주기={COLLECTION_INTERVAL:.0f}s')
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
              f'성공 mm_y <= {SAFE_ZONE_TARGET_Y}')
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
