"""투명 도형 찾기 캡차 자동 풀이기.

메이플 플래닛 거짓말 탐지기의 "투명 도형 찾기" 시스템:
  1) 화면 가운데에 어두운 박스 + 갈색 모래 텍스처
  2) 5초 카운트다운
  3) 컬러 도형(원/별/네모/다이아 등) 등장, 점점 투명해지며 이동
  4) 마우스 커서를 도형 위에 올려둔 시간 비율로 통과 결정
  5) 통과 시 노란색 "SUCCESS" 표시 후 박스 자동 닫힘

알고리즘:
  - 박스 외부 마우스 parking으로 시작 도형 위치 검출 (V>200 큰 정사각형)
  - 매크로 마우스를 도형 위치로 이동 → 카운트다운 끝 대기
  - 카운트다운 끝나면 도형 위치 50x50 bbox로 CSRT 트래커 초기화
  - 매 프레임:
      a) 매크로 마우스(분홍 커서) 좌표 주변 작은 영역만 모래 평균 색으로 대체
         → 분홍 커서가 도형 추적 시그니처를 가리는 거 방지
      b) CSRT 트래커 update → 새 위치로 마우스 이동
  - SUCCESS 노란 텍스트 감지 시 종료. opencv-contrib-python 필요.
"""
import time
import ctypes
import cv2
import numpy as np


# 게임 화면 대비 캡차 박스 위치 비율 (도형 움직임 범위 충분히 포함)
BOX_CX_RATIO = 0.500
BOX_CY_RATIO = 0.585
BOX_W_RATIO  = 0.30
BOX_H_RATIO  = 0.40

# 모래 텍스처 색상 (캡차 박스 검출용)
SAND_HUE_MIN, SAND_HUE_MAX = 8, 28
SAND_SAT_MIN = 60
SAND_VAL_MIN = 40

# 도형 검출 파라미터 — 박스 영역 대비 비율로 동적 산출
SHAPE_SAT_MIN     = 80     # 채도 임계 (모래보다 채도 높은 색만)
SHAPE_MIN_AREA_RATIO = 0.0005  # 박스 면적의 0.05%
SHAPE_MAX_AREA_RATIO = 0.10    # 박스 면적의 10%


def _area_range(captcha_img):
    """주어진 캡차 박스 크기에 맞는 도형 면적 범위 산출."""
    box_area = captcha_img.shape[0] * captcha_img.shape[1]
    return (max(50, int(box_area * SHAPE_MIN_AREA_RATIO)),
            max(500, int(box_area * SHAPE_MAX_AREA_RATIO)))

# SUCCESS 텍스트 (노란색 큰 글자)
SUCCESS_HUE_MIN, SUCCESS_HUE_MAX = 20, 40
SUCCESS_MIN_PIXELS = 4000

# 타임아웃
COUNTDOWN_TIMEOUT_SEC = 10   # 도형 등장 대기
TRACKING_TIMEOUT_SEC  = 25   # 추적 최대 시간
POLL_INTERVAL_SEC     = 0.03 # ~30fps

# 트래커 — 영상 검증 베스트 알고리즘
CSRT_INIT_BBOX_SIZE  = 100  # CSRT bbox 100x100 (도형 50x50 + context)
DSR_INIT_BBOX_SIZE   = 128  # DaSiamRPN bbox 128x128 (Siamese 네트워크 최적)
CURSOR_REPLACE_PX    = 7    # 모래 색 대체 반경 (구버전 fallback용)
CURSOR_HUE_PINK      = (140, 180)  # 메이플 분홍 cursor hue 범위
EXTRAP_MAX_FRAMES    = 30   # 외삽 fallback 길이
EXTRAP_LAST_N_PTS    = 20

# DaSiamRPN 모델 경로 (ASCII 경로 필요 — 한글 경로에선 ONNX 못 읽음)
DSR_MODEL_PATH      = r'C:\temp_models\dasiamrpn_model.onnx'
DSR_KERNEL_CLS1     = r'C:\temp_models\dasiamrpn_kernel_cls1.onnx'
DSR_KERNEL_R1       = r'C:\temp_models\dasiamrpn_kernel_r1.onnx'


def _sand_mean_color(captcha_img):
    """캡차 박스 안 모래 평균 BGR."""
    hsv = cv2.cvtColor(captcha_img, cv2.COLOR_BGR2HSV)
    sand = ((hsv[:, :, 0] >= SAND_HUE_MIN) & (hsv[:, :, 0] <= SAND_HUE_MAX) &
            (hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 40) & (hsv[:, :, 2] < 200))
    if not sand.any():
        return np.array([60, 80, 120], np.uint8)
    return captcha_img[sand].mean(axis=0).astype(np.uint8)


def replace_cursor_pixel(captcha_img, cursor_pos, sand_color, radius=CURSOR_REPLACE_PX):
    """매크로 마우스 좌표 주변 작은 원형 영역만 모래 평균 색으로 대체.
    (구버전 — inpaint_cursor_minimal로 대체 권장)
    """
    if cursor_pos is None:
        return captcha_img
    out = captcha_img.copy()
    mask = np.zeros(captcha_img.shape[:2], dtype=np.uint8)
    cv2.circle(mask, (int(cursor_pos[0]), int(cursor_pos[1])), radius, 255, -1)
    out[mask > 0] = sand_color
    return out


def inpaint_cursor_minimal(captcha_img, cursor_hue_range=(140, 180)):
    """분홍 cursor 픽셀 자체만 inpaint (dilate=0, 안티앨리어싱 보존).

    영상 검증 핵심: dilate=0이면 도형 outline 보존됨 → CSRT/DaSiamRPN가 진짜 도형
    시각 시그니처 학습. invi에서 100% on_target, median 4px 검증됨.
    dilate>=1이면 도형 outline 같이 가려져 추적 fail.
    """
    hsv = cv2.cvtColor(captcha_img, cv2.COLOR_BGR2HSV)
    h_min, h_max = cursor_hue_range
    if h_min <= h_max:
        m = (hsv[:, :, 0] >= h_min) & (hsv[:, :, 0] <= h_max)
    else:
        m = (hsv[:, :, 0] >= h_min) | (hsv[:, :, 0] <= h_max)
    m = m & (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 80)
    if not m.any():
        return captcha_img
    return cv2.inpaint(captcha_img, m.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)


def estimate_captcha_box(game_region):
    """게임 영역(GAME_REGION) 기준 캡차 박스 절대 좌표 추정."""
    gw, gh = game_region['width'], game_region['height']
    bw = int(gw * BOX_W_RATIO)
    bh = int(gh * BOX_H_RATIO)
    cx = game_region['left'] + int(gw * BOX_CX_RATIO)
    cy = game_region['top']  + int(gh * BOX_CY_RATIO)
    return {
        'left':   cx - bw // 2,
        'top':    cy - bh // 2,
        'width':  bw,
        'height': bh,
    }


def _box_relative_to_game(box, game_region):
    """절대 좌표 box를 game_region 기준 상대 좌표로 변환."""
    return (
        box['left'] - game_region['left'],
        box['top']  - game_region['top'],
        box['width'],
        box['height'],
    )


def _crop_box(game_img, box, game_region):
    rx, ry, bw, bh = _box_relative_to_game(box, game_region)
    rx = max(0, rx)
    ry = max(0, ry)
    return game_img[ry:ry+bh, rx:rx+bw]


def is_captcha_active(game_img, game_region):
    """캡차 박스 영역에 모래 텍스처가 충분히 있는지 확인."""
    box = estimate_captcha_box(game_region)
    crop = _crop_box(game_img, box, game_region)
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    sand = (
        (hsv[:, :, 0] >= SAND_HUE_MIN) & (hsv[:, :, 0] <= SAND_HUE_MAX) &
        (hsv[:, :, 1] >= SAND_SAT_MIN) &
        (hsv[:, :, 2] >= SAND_VAL_MIN)
    )
    ratio = np.count_nonzero(sand) / sand.size
    return ratio > 0.25  # 박스 영역의 25% 이상이 모래면 캡차 활성


def detect_shape_color(captcha_img):
    """캡차 박스 안에서 도형 색 추출. 마우스 커서는 박스 밖으로 미리 빼둬야 함.
    반환: ('white',) — 무채색 도형 / (h_min, h_max) — 컬러 도형 / None — 검출 실패

    흰색 우선 정책: 박스 안에 적당한 크기(SHAPE_MIN_AREA~SHAPE_MAX_AREA)의 흰색
    contour가 있으면 무조건 흰색 도형으로 판정. 카운트다운 "3"이나 "START"
    글자(청록/노랑)가 더 큰 면적이어도 도형 후보가 흰색이면 그게 우선.
    """
    hsv = cv2.cvtColor(captcha_img, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]

    min_a, max_a = _area_range(captcha_img)
    # 흰색 도형 마스크 — outline·채워진 형태 둘 다 잡힐 수 있게 V/S 너그럽게
    white = ((v > 180) & (s < 80) & (v < 252)).astype(np.uint8) * 255
    # 사각형 outline 등은 morphology close로 채움
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid_white = [c for c in contours if min_a <= cv2.contourArea(c) <= max_a]
    if valid_white:
        return ('white',)

    # 컬러 fallback — 채도 높은 + 모래 아닌 + 카운트다운 큰 숫자 아닌
    color = (s > SHAPE_SAT_MIN) & (v > 60) & (v < 240) & \
            ~((h >= SAND_HUE_MIN) & (h <= SAND_HUE_MAX))
    color_u8 = color.astype(np.uint8) * 255
    color_u8 = cv2.morphologyEx(color_u8, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(color_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid_color = [c for c in contours if min_a <= cv2.contourArea(c) <= max_a]
    if valid_color:
        biggest = max(valid_color, key=cv2.contourArea)
        mask = np.zeros(h.shape, dtype=np.uint8)
        cv2.drawContours(mask, [biggest], -1, 255, cv2.FILLED)
        hues = h[mask > 0]
        peak_hue = int(np.median(hues))
        return (max(0, peak_hue - 12), min(179, peak_hue + 12))
    return None


def _cursor_exclusion_circle(shape, cursor_pos, radius=12):
    """매크로 마우스 좌표 주변 작은 원형 제외 마스크.
    반경 12px가 분홍 커서 핵심만 가리면서 도형 outline은 보존 (영상 검증).
    """
    if cursor_pos is None:
        return None
    m = np.zeros(shape[:2], dtype=np.uint8)
    cv2.circle(m, (int(cursor_pos[0]), int(cursor_pos[1])), int(radius), 255, -1)
    return m > 0


# 도형 검출 핵심 파라미터 (영상 검증으로 튜닝됨)
SHAPE_V_MIN          = 200      # V 하한
SHAPE_S_MAX          = 70
SHAPE_AREA_MIN       = 800
SHAPE_AREA_MAX       = 3000
SHAPE_ASPECT_MAX     = 1.6      # 도형은 정사각형/원형 (aspect~1), 박스 가장자리 노이즈는 4+
SHAPE_BBOX_MIN_SIZE  = 30       # bbox 한 변이 너무 작으면 노이즈
SHAPE_BBOX_MAX_SIZE  = 100      # 너무 크면 노이즈


def find_shape_global(captcha_img, cursor_pos=None, cursor_mask_radius=25,
                      v_thresh=200, area_min=300, area_max=8000,
                      aspect_max=1.6):
    """**cursor 독립** 도형 검출 — 박스 *전체*에서 V>200 정사각형.

    cursor 영역만 마스크 제외 (cursor_mask_radius 픽셀, 안티앨리어싱 포함).
    last_pos 가중치 zero — 도형 위치 어디든 cursor 외에서 가장 큰 정사각형 cluster.

    cursor가 박힌 위치 외 영역에서 진짜 도형 outline 검출.
    """
    H, W = captcha_img.shape[:2]
    hsv = cv2.cvtColor(captcha_img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = ((v > v_thresh) & (s < 70) &
            ~((h >= SAND_HUE_MIN) & (h <= SAND_HUE_MAX))).astype(np.uint8) * 255

    # cursor 영역 안티앨리어싱까지 마스크 제외 (cursor 의존성 차단)
    if cursor_pos is not None:
        cv2.circle(mask, (int(cursor_pos[0]), int(cursor_pos[1])),
                   cursor_mask_radius, 0, -1)

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_score = 0
    for c in contours:
        a = cv2.contourArea(c)
        if a < area_min or a > area_max:
            continue
        x, y, w_, h_ = cv2.boundingRect(c)
        aspect = max(w_, h_) / max(1, min(w_, h_))
        if aspect > aspect_max:
            continue
        M = cv2.moments(c)
        if M['m00'] == 0:
            continue
        cx = int(M['m10'] / M['m00'])
        cy = int(M['m01'] / M['m00'])
        # 점수 = 면적 × 정사각형 가까움 (last_pos 가중치 zero)
        score = a * (1.0 / max(1.0, aspect))
        if score > best_score:
            best_score = score
            best = (cx, cy)
    return best


def find_shape_outline(captcha_img, cursor_pos=None):
    """투명해진 도형의 테두리(outline) 검출 — cursor 무관, 모양 기반.

    진짜 도형 outline 특징:
      - V>200 + 무채색 (S<70) + 모래 hue 외 픽셀
      - 모폴로지 close 후 area 800~3000
      - bbox aspect ~1 (정사각형/원/별 등 대칭 모양)
      - bbox 크기 30~100px (작은 노이즈/큰 박스 가장자리 모두 거부)

    cursor_pos 있으면 그 주변 12px만 제외 (분홍 커서 픽셀 노이즈 차단).
    cursor 위치에 가중치는 주지 않음 — 도형이 cursor에서 떨어져 있어도 잡힘.
    """
    hsv = cv2.cvtColor(captcha_img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    exclude = np.zeros(captcha_img.shape[:2], dtype=np.uint8)
    if cursor_pos is not None:
        cv2.circle(exclude, (int(cursor_pos[0]), int(cursor_pos[1])), 12, 255, -1)

    mask = ((v > SHAPE_V_MIN) & (s < SHAPE_S_MAX) &
            ~((h >= SAND_HUE_MIN) & (h <= SAND_HUE_MAX)) &
            ~(exclude > 0)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for c in contours:
        a = cv2.contourArea(c)
        if not (SHAPE_AREA_MIN <= a <= SHAPE_AREA_MAX):
            continue
        x, y, w_, h_ = cv2.boundingRect(c)
        # bbox 크기 필터 — 도형은 적당히 작은 정사각형 영역
        if not (SHAPE_BBOX_MIN_SIZE <= w_ <= SHAPE_BBOX_MAX_SIZE and
                SHAPE_BBOX_MIN_SIZE <= h_ <= SHAPE_BBOX_MAX_SIZE):
            continue
        # aspect ratio — 진짜 도형은 ~1, 박스 가장자리는 4+
        aspect = max(w_, h_) / max(1, min(w_, h_))
        if aspect > SHAPE_ASPECT_MAX:
            continue
        M = cv2.moments(c)
        if M['m00'] == 0:
            continue
        cx = int(M['m10'] / M['m00'])
        cy = int(M['m01'] / M['m00'])
        candidates.append((a, cx, cy, aspect))

    if not candidates:
        return None
    # 가장 정사각형에 가깝고 크기가 적당한 거 우선 (aspect 1 가까이)
    candidates.sort(key=lambda c: (abs(c[3] - 1.0), -c[0]))
    _, cx, cy, _ = candidates[0]
    return (cx, cy)


# 기존 함수 이름 호환용 alias
find_shape_near_cursor = find_shape_outline


def _shape_mask(hsv, shape_color, v_thresh=170, cursor_pos=None, cursor_radius=18):
    """shape_color에 해당하는 마스크.
    shape_color: ('white',) — 무채색 / (h_min, h_max) — 컬러
    v_thresh: 흰색 도형 검출 시 V 하한
    cursor_pos: 매크로의 마우스 좌표 (박스 상대) — 그 주변 원형 영역 제외
    """
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    if shape_color == ('white',):
        m = (v > v_thresh) & (s < 70) & (v < 250)
    else:
        h_min, h_max = shape_color
        if h_min <= h_max:
            base = (h >= h_min) & (h <= h_max)
        else:
            base = (h >= h_min) | (h <= h_max)
        m = base & (s > 30)
    cur = _cursor_exclusion_circle(hsv.shape, cursor_pos, cursor_radius)
    if cur is not None:
        m = m & ~cur
    return m


MAX_JUMP_PX = 50  # 30fps 가정 시 한 프레임당 최대 이동 거리


def find_shape_pos(captcha_img, shape_color, last_pos=None,
                   search_radius=80, v_thresh=170,
                   cursor_pos=None, cursor_radius=18):
    """캡차 박스에서 도형 위치 (cx, cy) 반환. 못 찾으면 None.

    - last_pos가 있으면 그 주변 search_radius ROI로 좁혀서 추적
    - 검출된 위치가 last_pos에서 MAX_JUMP_PX 초과 멀면 거부 (도형이 순간이동 안 함)
    - cursor_pos: 매크로 마우스 좌표 (박스 상대). 그 주변 cursor_radius 픽셀 제외
    """
    hsv = cv2.cvtColor(captcha_img, cv2.COLOR_BGR2HSV)
    mask = _shape_mask(hsv, shape_color, v_thresh=v_thresh,
                       cursor_pos=cursor_pos,
                       cursor_radius=cursor_radius).astype(np.uint8) * 255
    # outline 형태(흰색 사각형 등) 채우기 위해 morphology close
    if shape_color == ('white',):
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    else:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    if last_pos is not None:
        roi_mask = np.zeros_like(mask)
        x0 = max(0, last_pos[0] - search_radius)
        y0 = max(0, last_pos[1] - search_radius)
        x1 = min(mask.shape[1], last_pos[0] + search_radius)
        y1 = min(mask.shape[0], last_pos[1] + search_radius)
        roi_mask[y0:y1, x0:x1] = 255
        mask = cv2.bitwise_and(mask, roi_mask)

    min_a, max_a = _area_range(captcha_img)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [c for c in contours if min_a <= cv2.contourArea(c) <= max_a]
    if not valid:
        return None

    candidates = []
    for c in valid:
        M = cv2.moments(c)
        if M['m00'] == 0:
            continue
        cx = int(M['m10'] / M['m00'])
        cy = int(M['m01'] / M['m00'])
        candidates.append((cx, cy, cv2.contourArea(c)))
    if not candidates:
        return None

    if last_pos is None:
        cx, cy, _ = max(candidates, key=lambda t: t[2])
        return (cx, cy)

    lx, ly = last_pos
    best = min(candidates, key=lambda t: (t[0]-lx)**2 + (t[1]-ly)**2)
    dist = ((best[0]-lx)**2 + (best[1]-ly)**2) ** 0.5
    if dist > MAX_JUMP_PX:
        return None
    return (best[0], best[1])


def is_success(captcha_img):
    """캡차 박스에서 노란 SUCCESS 텍스트 감지."""
    hsv = cv2.cvtColor(captcha_img, cv2.COLOR_BGR2HSV)
    yellow = (
        (hsv[:, :, 0] >= SUCCESS_HUE_MIN) & (hsv[:, :, 0] <= SUCCESS_HUE_MAX) &
        (hsv[:, :, 1] >= 120) & (hsv[:, :, 2] >= 180)
    )
    return np.count_nonzero(yellow) >= SUCCESS_MIN_PIXELS


def move_cursor_abs(x, y):
    """SetCursorPos로 절대 좌표 마우스 이동 (DPI-aware 가정)."""
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


# 베지어 path 학습/외삽 파라미터 (default 인자에서 참조하므로 함수 정의 전에)
LEARN_FRAMES_AFTER_START = 30
JITTER_PX                 = 2.0
EXTRAPOLATION_MAX_SEC     = 15.0


def fit_path(trajectory, last_n=20, degree=1):
    """trajectory=[(t,x,y),...] 마지막 last_n 점으로 polynomial fit (degree).

    영상 검증 결과: last 20pt + linear가 외삽 30 frames(~1초) 동안 93% on_target.
    degree 높이면 빠르게 폭발 (last 20pt deg2/3는 외삽 정확도 떨어짐).
    """
    pts = trajectory[-last_n:] if len(trajectory) > last_n else trajectory
    if len(pts) < degree + 1:
        return None
    ts = np.array([p[0] for p in pts], dtype=np.float64)
    xs = np.array([p[1] for p in pts], dtype=np.float64)
    ys = np.array([p[2] for p in pts], dtype=np.float64)
    t0 = ts[0]
    ts_n = ts - t0
    fx = np.polyfit(ts_n, xs, degree)
    fy = np.polyfit(ts_n, ys, degree)
    def path(t_now):
        tn = t_now - t0
        return (float(np.polyval(fx, tn)), float(np.polyval(fy, tn)))
    return path


def apply_jitter(pos, jitter=JITTER_PX):
    """사람 손 떨림 수준 지터링. path 위 위치에 작은 가우시안 노이즈 추가."""
    if jitter <= 0:
        return pos
    jx = float(np.random.normal(0, jitter))
    jy = float(np.random.normal(0, jitter))
    return (pos[0] + jx, pos[1] + jy)


def _countdown_done(captcha_img, threshold=4000):
    """카운트다운 큰 흰 글자 사라졌는지 — V>240 총 픽셀 수가 threshold 미만이면 OK."""
    hsv = cv2.cvtColor(captcha_img, cv2.COLOR_BGR2HSV)
    big_white = (hsv[:, :, 2] > 240) & (hsv[:, :, 1] < 70)
    return int(np.count_nonzero(big_white)) < threshold


# 시작 도형 검출 — 카운트다운 중 큰 명확한 흰 정사각형/원
INITIAL_SHAPE_AREA_MIN = 5000
INITIAL_SHAPE_AREA_MAX = 20000
INITIAL_SHAPE_ASPECT_MAX = 1.6


def find_initial_shape(captcha_img):
    """카운트다운 중 도형 시작 위치 검출 — 마우스가 박스 외부에 있을 때.
    큰 흰 정사각형 (area 5000~20000, aspect ~1) 검출.
    """
    hsv = cv2.cvtColor(captcha_img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = ((v > 200) & (s < 70) &
            ~((h >= SAND_HUE_MIN) & (h <= SAND_HUE_MAX))).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for c in contours:
        a = cv2.contourArea(c)
        if not (INITIAL_SHAPE_AREA_MIN <= a <= INITIAL_SHAPE_AREA_MAX):
            continue
        x, y, w_, h_ = cv2.boundingRect(c)
        aspect = max(w_, h_) / max(1, min(w_, h_))
        if aspect > INITIAL_SHAPE_ASPECT_MAX:
            continue
        M = cv2.moments(c)
        if M['m00'] == 0:
            continue
        cx = int(M['m10'] / M['m00'])
        cy = int(M['m01'] / M['m00'])
        candidates.append((a, cx, cy))
    if not candidates:
        return None
    candidates.sort(key=lambda c: -c[0])
    return (candidates[0][1], candidates[0][2])


def solve(grab_game_fn, game_region, *, on_log=print):
    """캡차 풀이 메인 엔트리.

    알고리즘:
      1. 박스 추정, 마우스를 박스 가운데로 이동 (도형 시작 위치 부근)
      2. 카운트다운 끝 대기 (V>240 큰 글자 사라질 때까지)
      3. 매 프레임: 매크로 마우스 위치 기준 cursor 근처(100px 안)에서 진짜 도형 검출
         - V>200 + S<70 + ~sand + cursor 12px 제외 + area 1000~2500
      4. 도형 검출되면 마우스 그 위치로 이동, 못 찾으면 마우스 유지
      5. SUCCESS 텍스트 감지 시 종료
    """
    box = estimate_captcha_box(game_region)
    on_log(f'[captcha] 박스 추정 절대좌표: {box}')

    # 1) 마우스를 박스 외부로 이동 — 도형 검출 방해 방지
    parking_x = max(box['left'] - 20, game_region['left'] + 5)
    parking_y = box['top'] + box['height'] // 2
    move_cursor_abs(parking_x, parking_y)
    time.sleep(0.3)

    # 2) 카운트다운 중 도형 시작 위치 검출 (마우스가 박스 밖이라 분홍 방해 없음)
    on_log('[captcha] 도형 시작 위치 검출 중')
    deadline = time.time() + COUNTDOWN_TIMEOUT_SEC
    start_pos = None
    while time.time() < deadline:
        img = grab_game_fn()
        cap = _crop_box(img, box, game_region)
        if cap.size == 0:
            time.sleep(0.05)
            continue
        sp = find_initial_shape(cap)
        if sp is not None:
            start_pos = sp
            on_log(f'[captcha] 도형 시작 위치 = {sp}')
            break
        time.sleep(0.1)

    if start_pos is None:
        on_log('[captcha] 도형 시작 위치 검출 실패 — 캡차 없을 수도')
        return False

    # 3) 매크로 마우스를 도형 시작 위치로 이동
    cursor_rel = start_pos
    move_cursor_abs(box['left'] + start_pos[0], box['top'] + start_pos[1])
    time.sleep(0.1)

    # 4) 카운트다운 끝 대기 (V>240 큰 글자 사라질 때까지)
    on_log('[captcha] 카운트다운 끝 대기')
    deadline = time.time() + 8
    while time.time() < deadline:
        img = grab_game_fn()
        cap = _crop_box(img, box, game_region)
        if cap.size > 0 and _countdown_done(cap):
            on_log('[captcha] 카운트다운 끝')
            break
        time.sleep(0.1)

    # 5) 트래커 초기화 — inpaint_cursor_minimal (dilate=0) + CSRT/DaSiamRPN
    # 영상 검증: dilate=0이면 분홍 본체만 inpaint + 도형 outline 보존 → 100% 추적
    img = grab_game_fn()
    cap = _crop_box(img, box, game_region)
    if cap.size == 0:
        on_log('[captcha] 캡차 박스 캡처 실패')
        return False

    cap_clean = inpaint_cursor_minimal(cap, CURSOR_HUE_PINK)

    # DaSiamRPN 우선 (영상 검증: 99% on_target, 추적 길이 길음). 실패 시 CSRT.
    init_bbox = (max(0, cursor_rel[0] - DSR_INIT_BBOX_SIZE // 2),
                 max(0, cursor_rel[1] - DSR_INIT_BBOX_SIZE // 2),
                 DSR_INIT_BBOX_SIZE, DSR_INIT_BBOX_SIZE)
    tracker = None
    tracker_kind = None
    try:
        dp = cv2.TrackerDaSiamRPN_Params()
        dp.model = DSR_MODEL_PATH
        dp.kernel_cls1 = DSR_KERNEL_CLS1
        dp.kernel_r1 = DSR_KERNEL_R1
        tracker = cv2.TrackerDaSiamRPN.create(dp)
        tracker.init(cap_clean, init_bbox)
        tracker_kind = 'DaSiamRPN'
        on_log(f'[captcha] DaSiamRPN 초기화 bbox={init_bbox}')
    except Exception as e:
        on_log(f'[captcha] DaSiamRPN 실패({e}) → CSRT fallback')
        init_bbox = (max(0, cursor_rel[0] - CSRT_INIT_BBOX_SIZE // 2),
                     max(0, cursor_rel[1] - CSRT_INIT_BBOX_SIZE // 2),
                     CSRT_INIT_BBOX_SIZE, CSRT_INIT_BBOX_SIZE)
        try:
            tracker = cv2.TrackerCSRT.create()
            tracker.init(cap_clean, init_bbox)
            tracker_kind = 'CSRT'
            on_log(f'[captcha] CSRT 초기화 bbox={init_bbox}')
        except AttributeError:
            on_log('[captcha] 트래커 없음 — opencv-contrib-python 설치 필요')
            return False

    # 6) 매 프레임 추적 — ROI 기반 도형 검출 (힌트 알고리즘)
    # 핵심: last_pos 주변 ROI에서 cursor 외 영역의 V>200 사각형 = 도형
    # 매크로 마우스 한 프레임 lag → 도형 outline cursor 옆에 보임
    track_start = time.time()
    box_margin = 10
    lost_count = 0
    trajectory = [(0.0, cursor_rel[0], cursor_rel[1])]

    while time.time() - track_start < TRACKING_TIMEOUT_SEC:
        img = grab_game_fn()
        cap = _crop_box(img, box, game_region)
        if cap.size == 0:
            time.sleep(POLL_INTERVAL_SEC)
            continue

        if is_success(cap):
            on_log(f'[captcha] SUCCESS — 통과 ({time.time()-track_start:.1f}s)')
            return True

        # ROI 기반 도형 검출 — last_pos 주변에서 V>200 사각형 (cursor 외 영역)
        new_pos = find_shape_in_roi(
            cap, cursor_rel, search_radius=50,
            v_thresh=200, area_min=300, area_max=8000,
            aspect_max=1.6, cursor_pos=cursor_rel,
        )
        # fallback — 못 찾으면 V 임계값 낮춰서 더 약한 outline도 잡기
        if new_pos is None:
            new_pos = find_shape_in_roi(
                cap, cursor_rel, search_radius=60,
                v_thresh=160, area_min=200, area_max=8000,
                aspect_max=1.8, cursor_pos=cursor_rel,
            )

        if new_pos is not None:
            cx = max(box_margin, min(box['width']  - box_margin, new_pos[0]))
            cy = max(box_margin, min(box['height'] - box_margin, new_pos[1]))
            cursor_rel = (cx, cy)
            trajectory.append((time.time() - track_start, cx, cy))
            lost_count = 0
            jit = apply_jitter((cx, cy))
            move_cursor_abs(int(box['left'] + jit[0]), int(box['top'] + jit[1]))
        else:
            # 못 찾으면 — last 20pt linear 외삽 (짧게 30 frames)
            lost_count += 1
            if lost_count <= EXTRAP_MAX_FRAMES:
                path = fit_path(trajectory, last_n=EXTRAP_LAST_N_PTS, degree=1)
                if path is not None:
                    ex, ey = path(time.time() - track_start)
                    ex = max(box_margin, min(box['width']  - box_margin, ex))
                    ey = max(box_margin, min(box['height'] - box_margin, ey))
                    cursor_rel = (int(ex), int(ey))
                    jit = apply_jitter((ex, ey))
                    move_cursor_abs(int(box['left'] + jit[0]), int(box['top'] + jit[1]))
            # 외삽 한계 초과면 마우스 유지

        time.sleep(POLL_INTERVAL_SEC)

    on_log(f'[captcha] 추적 시간 초과')
    return False


if __name__ == '__main__':
    # 단독 실행 테스트 — macro_red.grab/GAME_REGION 사용
    import macro_red as m
    print('[test] 5초 후 캡차 풀이 시작 — 게임에서 캡차 띄워두기')
    time.sleep(5)
    ok = solve(m.grab, m.GAME_REGION)
    print(f'[test] 결과: {"통과" if ok else "실패"}')
