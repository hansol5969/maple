"""
메이플플래닛 "거짓말 탐지기" word(코드 매칭) 캡차 솔버.

다이얼로그 구조:
  - 상단 정답박스: 4글자 영숫자 (큰 글씨)
  - 3×2 그리드: 6개 후보 버튼
  - 우측 하단: 파란 "확인" 버튼

풀이:
  1) 화면에서 파란 확인 버튼 anchor → 다이얼로그 origin/size 역산
  2) 정답박스 ROI + 6개 셀 ROI 추출 → 각각 4글자 인식
  3) 정답과 같은 코드 셀 → 클릭 → 확인 클릭

자산: captcha_assets/word/chars/{0-9, A-Z}.png (canonical 글자 템플릿)

사용:
  python word_captcha_solver.py            # 한 번 풀고 종료 (캡차 보이는 상태)
  python word_captcha_solver.py --auto     # macro_red.py 연동
  python word_captcha_solver.py --watch    # 감시 모드
"""
from __future__ import annotations
import argparse, ctypes, os, random, sys, time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass

import cv2
import numpy as np
import pyautogui
from PIL import Image

pyautogui.PAUSE = 0
pyautogui.MINIMUM_DURATION = 0
pyautogui.FAILSAFE = True

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "captcha_assets", "word")
CHARS_DIR = os.path.join(ASSETS, "chars")
LIE_TITLE_PATH = os.path.join(ROOT, "templates", "lie_title.png")

# 다이얼로그 내부 ROI 비율 (1779113674.png 기준 측정)
ROIS = {
    'ans': (0.17, 0.18, 0.83, 0.32),
    'c1':  (0.06, 0.33, 0.35, 0.45),
    'c2':  (0.38, 0.33, 0.69, 0.45),
    'c3':  (0.70, 0.33, 0.97, 0.45),
    'c4':  (0.06, 0.46, 0.35, 0.57),
    'c5':  (0.38, 0.46, 0.69, 0.57),
    'c6':  (0.70, 0.46, 0.97, 0.57),
}
CONFIRM_REL = (0.7115, 0.5766, 0.9244, 0.6490)  # 확인 버튼 비율
# lie_title.png가 다이얼로그 내 차지하는 비율 (학습 캡쳐 측정)
LIE_TITLE_REL = (0.06, 0.065, 0.275, 0.115)
DIALOG_HW_RATIO = 1.045  # H/W 비율 (525/503)
# Dialog sanity check (게임창 절반 이내 — false positive 차단)
DIALOG_MIN_W, DIALOG_MAX_W = 200, 1200
DIALOG_MIN_H, DIALOG_MAX_H = 200, 1200

H_NORM = 20  # 글자 정규화 높이 (chars 템플릿과 동일)
MATCH_THRESHOLD = 0.45  # 글자별 NCC 최소 신뢰도


# ---------- 화면 캡처 ----------
def grab_screen() -> np.ndarray:
    pil = pyautogui.screenshot()
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


# ---------- 선택 셀 검출 ----------
def detect_selected_cell(scene_bgr: np.ndarray, DL: int, DT: int, DW: int, DH: int):
    """파란 테두리가 있는 셀(이미 선택된 셀) 검출.

    셀 ROI를 살짝 확장(2%)해서 셀 테두리까지 포함 → 파란 테두리 픽셀 검출.
    파란 테두리: b-r >= 25 (진한 파랑, 옅은 다이얼로그 배경의 b-r=5-15 노이즈 제외).
    가장 파란 비율 셀이 다른 셀의 1.5배 이상 + 임계값 넘어야 신뢰.
    반환: (cell_name, blue_ratio) 또는 (None, 0)
    """
    PAD = 0.025  # ROI 외부 확장 비율 (셀 테두리 포함)
    ratios = {}
    for cn, rel in ROIS.items():
        if not cn.startswith('c'):
            continue
        rx0, ry0, rx1, ry1 = rel
        expanded = (rx0 - PAD, ry0 - PAD, rx1 + PAD, ry1 + PAD)
        x0, y0, x1, y1 = roi_bbox(DL, DT, DW, DH, expanded)
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(scene_bgr.shape[1], x1); y1 = min(scene_bgr.shape[0], y1)
        if x1 <= x0 or y1 <= y0:
            continue
        cell = scene_bgr[y0:y1, x0:x1]
        b, g, r = cell[:, :, 0].astype(int), cell[:, :, 1].astype(int), cell[:, :, 2].astype(int)
        blueness = b - r
        ratios[cn] = float((blueness >= 25).sum()) / blueness.size
    if not ratios:
        return (None, 0.0)
    best_cn = max(ratios, key=ratios.get)
    best_r = ratios[best_cn]
    others = sorted([r for cn, r in ratios.items() if cn != best_cn], reverse=True)
    second_r = others[0] if others else 0
    if best_r > 0.015 and best_r > second_r * 1.5:
        return (best_cn, best_r)
    return (None, 0.0)


# ---------- 확인 버튼 검출 ----------
def find_confirm_button(scene_bgr: np.ndarray):
    """파란 둥근 '확인' 버튼 검출.

    버튼 코어 색: R<150 G<170 B>180. 화면 전체 mask 후 가장 큰 연결요소.
    반환: (x0, y0, x1, y1, w, h) — 절대 좌표
    """
    b, g, r = scene_bgr[:, :, 0], scene_bgr[:, :, 1], scene_bgr[:, :, 2]
    mask = ((r < 150) & (g < 180) & (b > 180)).astype(np.uint8) * 255
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = None
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < 300 or w < 40 or h < 18:
            continue
        aspect = w / h
        if aspect < 1.5 or aspect > 5.0:
            continue
        if best is None or a > best[6]:
            best = (int(x), int(y), int(x + w - 1), int(y + h - 1), int(w), int(h), int(a))
    if best is None:
        return None
    return best[:6]


# ---------- 다이얼로그 위치/크기 추정 ----------
def derive_dialog(confirm_box):
    """확인 버튼 bbox → 다이얼로그 (left, top, W, H)."""
    cx0, cy0, cx1, cy1, cw, ch = confirm_box
    rx0, ry0, rx1, ry1 = CONFIRM_REL
    DW = cw / (rx1 - rx0)
    DH = ch / (ry1 - ry0)
    DL = cx0 - DW * rx0
    DT = cy0 - DH * ry0
    return int(round(DL)), int(round(DT)), int(round(DW)), int(round(DH))


# ---------- lie_title 기반 dialog 검출 ----------
_LIE_TITLE_CACHE = [None]  # lazy load


def _load_lie_title():
    if _LIE_TITLE_CACHE[0] is None and os.path.exists(LIE_TITLE_PATH):
        _LIE_TITLE_CACHE[0] = cv2.imread(LIE_TITLE_PATH)
    return _LIE_TITLE_CACHE[0]


def find_lie_title(scene_bgr: np.ndarray):
    """templates/lie_title.png 매칭 → 다이얼로그 헤더 위치.

    lie title은 다이얼로그 좌상단 고정 위치라 다이얼로그 anchor로 가장 신뢰성 높음.
    confirm button(파란 박스)은 게임 내 다른 UI에도 비슷한 게 있어 false positive 가능.
    반환: (x, y, w, h, score) 또는 None
    """
    tpl = _load_lie_title()
    if tpl is None:
        return None
    res = cv2.matchTemplate(scene_bgr, tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score < 0.5:
        return None
    th, tw = tpl.shape[:2]
    return (int(loc[0]), int(loc[1]), int(tw), int(th), float(score))


def derive_dialog_from_lie(lie_box):
    """lie_title bbox → 다이얼로그 (L, T, W, H).
    lie_title.png 크기는 고정 108x24, 다이얼로그 W ≈ lie_title W / 0.215.
    """
    lx, ly, lw, lh, _ = lie_box
    rx0, ry0, rx1, ry1 = LIE_TITLE_REL
    DW = lw / (rx1 - rx0)
    DH = DW * DIALOG_HW_RATIO  # 다이얼로그 H/W 비율
    DL = lx - DW * rx0
    DT = ly - DH * ry0
    return int(round(DL)), int(round(DT)), int(round(DW)), int(round(DH))


def dialog_is_sane(DW, DH) -> bool:
    return DIALOG_MIN_W <= DW <= DIALOG_MAX_W and DIALOG_MIN_H <= DH <= DIALOG_MAX_H


# ---------- ROI 추출 ----------
def roi_bbox(DL, DT, DW, DH, rel):
    rx0, ry0, rx1, ry1 = rel
    return (int(DL + DW * rx0), int(DT + DH * ry0),
            int(DL + DW * rx1), int(DT + DH * ry1))


# ---------- 텍스트 영역 추출 + H 정규화 ----------
def extract_text_norm(roi_gray: np.ndarray) -> np.ndarray | None:
    """ROI에서 글자 영역만 tight crop + H_NORM으로 정규화.

    1) dark 픽셀(<200) 기준 가로/세로 bbox
    2) bbox crop → H_NORM에 맞춰 비례 resize
    """
    dark = roi_gray < 200
    rows = dark.any(axis=1)
    cols = dark.any(axis=0)
    ys = np.where(rows)[0]
    xs = np.where(cols)[0]
    if len(ys) == 0 or len(xs) == 0:
        return None
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    text = roi_gray[y0:y1 + 1, x0:x1 + 1]
    h = text.shape[0]
    if h < 4:
        return None
    scale = H_NORM / h
    new_w = max(8, int(round(text.shape[1] * scale)))
    return cv2.resize(text, (new_w, H_NORM), interpolation=cv2.INTER_AREA)


# ---------- 템플릿 매칭 ----------
def split_text_to_glyphs(text: np.ndarray, n: int = 4) -> list:
    """텍스트(H_NORM 정규화)를 n글자 sub-images로 split.

    valley 그룹 기반: col_count가 임계값 이하인 연속 컬럼을 한 그룹으로 묶고,
    가장 넓은 n-1개를 글자 사이 split point로 사용.
    글자 폭/간격이 일정하지 않아도 robust.
    """
    dark = text < 200
    col_count = dark.sum(axis=0).astype(float)
    xs = np.where(col_count >= 1)[0]
    if len(xs) == 0:
        return [None] * n
    tx0, tx1 = int(xs.min()), int(xs.max())
    sub = col_count[tx0:tx1 + 1]
    L = len(sub)
    if L < n * 3:
        return [None] * n

    # valley 임계값: 가장 큰 stroke count의 20% 이하 = 글자 사이 공백
    valley_thr = max(1.0, float(sub.max()) * 0.20)
    is_valley = sub < valley_thr

    # 연속 valley 그룹화 (양 끝 그룹은 글자 사이가 아니므로 제외)
    valley_groups = []
    in_v, vs = False, 0
    for i in range(L):
        if is_valley[i] and not in_v:
            in_v, vs = True, i
        elif not is_valley[i] and in_v:
            in_v = False
            valley_groups.append((vs, i - 1))
    if in_v:
        valley_groups.append((vs, L - 1))
    # 양 끝 valley 제거 (글자 외부)
    while valley_groups and valley_groups[0][0] == 0:
        valley_groups.pop(0)
    while valley_groups and valley_groups[-1][1] == L - 1:
        valley_groups.pop()

    if len(valley_groups) >= n - 1:
        # 가장 폭 넓은 n-1 valley 선택 (확실한 글자 사이)
        valley_groups.sort(key=lambda g: -(g[1] - g[0]))
        chosen = sorted(valley_groups[:n - 1], key=lambda g: g[0])
        splits = [tx0 + (g[0] + g[1]) // 2 for g in chosen]
    else:
        # fallback: 등분점 부근 local min
        splits = []
        for k in range(1, n):
            center = int(L * k / n)
            win = max(2, int(L / (n * 2)))
            lo = max(0, center - win)
            hi = min(L - 1, center + win)
            local_min_off = int(np.argmin(sub[lo:hi + 1]))
            splits.append(tx0 + lo + local_min_off)
    bounds = [tx0] + splits + [tx1 + 1]
    glyphs = []
    for i in range(n):
        gx0, gx1 = bounds[i], bounds[i + 1] - 1
        sub = text[:, gx0:gx1 + 1]
        sub_dark = sub < 200
        cols = sub_dark.any(axis=0)
        cxs = np.where(cols)[0]
        if len(cxs) == 0:
            glyphs.append(None)
            continue
        gx_s = int(cxs.min())
        gx_e = int(cxs.max())
        glyph = sub[:, gx_s:gx_e + 1]
        # vertical tight crop
        rows = (glyph < 200).any(axis=1)
        rys = np.where(rows)[0]
        if len(rys) > 0:
            glyph = glyph[int(rys.min()):int(rys.max()) + 1]
        # H_NORM으로 다시 정규화
        gh = glyph.shape[0]
        if gh != H_NORM:
            scale = H_NORM / gh
            new_w = max(3, int(round(glyph.shape[1] * scale)))
            glyph = cv2.resize(glyph, (new_w, H_NORM), interpolation=cv2.INTER_AREA)
        glyphs.append(glyph)
    return glyphs


def to_binary(text: np.ndarray) -> np.ndarray:
    """글자 픽셀=0, 배경=255 binary. Otsu 적응형 threshold로 셀별 자동 분리.

    옅은 글자(선택 셀의 파란 테두리 안 등)도 셀 자체 평균 대비로 분리하여
    고정 threshold(200)로는 안 잡히는 글자도 추출.
    """
    # Otsu: 글자(어두움)/배경(밝음) 자동 분리 → 셀별 contrast 무관
    _, binary = cv2.threshold(text, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def match_cells_to_ans(ans_text: np.ndarray, cell_texts: dict) -> tuple[dict, list]:
    """ans 글자 4개와 cell 글자 4개를 같은 위치끼리 1:1 매칭 → 평균 score.

    cell도 4 split해서 비교 — 글자 모양만 보고 cell 내 다른 글자가 false positive로
    잘 매칭되는 것을 방지. ans 위치 k 글자는 cell 위치 k 글자와만 비교.
    binary 변환으로 글자 색 변동에 robust.
    반환: ({cell_name: avg_score}, ans_glyphs(binary))
    """
    ans_glyphs = split_text_to_glyphs(ans_text, n=4)
    ans_glyphs_bin = [to_binary(g) if g is not None else None for g in ans_glyphs]
    scores = {}
    for cn, ct in cell_texts.items():
        if ct is None:
            scores[cn] = -1.0
            continue
        cell_glyphs = split_text_to_glyphs(ct, n=4)
        per_glyph = []
        for ag_bin, cg in zip(ans_glyphs_bin, cell_glyphs):
            if ag_bin is None or cg is None:
                continue
            cg_bin = to_binary(cg)
            if ag_bin.shape[0] != cg_bin.shape[0]:
                continue
            # 폭 다르면 작은 쪽을 큰 쪽에 sliding
            if ag_bin.shape[1] <= cg_bin.shape[1]:
                small, large = ag_bin, cg_bin
            else:
                small, large = cg_bin, ag_bin
            if large.shape[1] < small.shape[1]:
                continue
            res = cv2.matchTemplate(large, small, cv2.TM_CCOEFF_NORMED)
            per_glyph.append(float(res.max()))
        scores[cn] = (sum(per_glyph) / len(per_glyph)) if per_glyph else -1.0
    return scores, ans_glyphs_bin


def recognize_code_36(roi_gray: np.ndarray, templates: dict) -> tuple[str, list]:
    """36 템플릿으로 4글자 코드 인식 (로깅/검증용).

    각 위치 등분점 부근 best NCC 매칭.
    """
    text = extract_text_norm(roi_gray)
    if text is None:
        return '????', [('?', 0.0)] * 4
    W = text.shape[1]
    score_maps = {}
    for ch, tpl in templates.items():
        t_h, t_w = tpl.shape
        if W < t_w:
            continue
        res = cv2.matchTemplate(text, tpl, cv2.TM_CCOEFF_NORMED)
        score_maps[ch] = res[0]

    code = ''
    per_char = []
    glyph_w = W / 4.0
    for k in range(4):
        cx_target = int(glyph_w * k)  # k번째 글자 시작 추정 위치
        slop = max(3, int(glyph_w * 0.35))
        best_ch = '?'
        best_sc = -1.0
        for ch, scores in score_maps.items():
            t_w = templates[ch].shape[1]
            lo = max(0, cx_target - slop)
            hi = min(len(scores) - 1, cx_target + slop)
            if lo > hi:
                continue
            local_best = float(np.max(scores[lo:hi + 1]))
            if local_best > best_sc:
                best_sc = local_best
                best_ch = ch
        per_char.append((best_ch, best_sc))
        code += best_ch if best_sc >= MATCH_THRESHOLD else '?'
    return code, per_char


# ---------- 마우스 ----------
def human_click(x: int, y: int, jitter: int = 2, hold: float = 0.05):
    jx = x + random.randint(-jitter, jitter)
    jy = y + random.randint(-jitter, jitter)
    pyautogui.moveTo(jx, jy, duration=random.uniform(0.15, 0.30),
                     tween=pyautogui.easeInOutSine)
    time.sleep(random.uniform(0.05, 0.15))
    pyautogui.mouseDown()
    time.sleep(hold + random.uniform(0, 0.05))
    pyautogui.mouseUp()


# ---------- 메인 솔버 ----------
class WordCaptchaSolver:
    def __init__(self):
        self.templates = {}
        if not os.path.isdir(CHARS_DIR):
            print(f"[err] {CHARS_DIR} 없음")
            return
        for fname in sorted(os.listdir(CHARS_DIR)):
            if not fname.endswith('.png'):
                continue
            ch = fname[:-4]
            if len(ch) != 1:
                continue
            img = cv2.imread(os.path.join(CHARS_DIR, fname), cv2.IMREAD_GRAYSCALE)
            if img is None or img.shape[0] != H_NORM:
                continue
            self.templates[ch] = img
        print(f"[init] char templates: {len(self.templates)}자 "
              f"({''.join(sorted(self.templates.keys()))})")

    def _save_debug(self, scene, reason: str):
        """캡차 실패 시 디버그 캡쳐 저장 (분석/템플릿 보강용)."""
        try:
            ts = int(time.time())
            out = os.path.join(ASSETS, f'_dbg_{reason}_{ts}.png')
            cv2.imwrite(out, scene)
            print(f"[dbg] saved: {out}")
        except Exception as e:
            print(f"[dbg] save fail: {e}")

    def solve_once(self) -> bool:
        scene = grab_screen()

        # 1차 anchor: lie_title (다이얼로그 헤더 — 가장 신뢰성 높음)
        lie = find_lie_title(scene)
        DL = DT = DW = DH = None
        cb = None
        if lie:
            lx, ly, lw, lh, lsc = lie
            print(f"[anchor] lie_title @ ({lx},{ly}) WxH={lw}x{lh} score={lsc:.2f}")
            DL, DT, DW, DH = derive_dialog_from_lie(lie)
            print(f"[dialog] from lie_title: origin=({DL},{DT}) WxH={DW}x{DH}")
            if not dialog_is_sane(DW, DH):
                print(f"[warn] dialog 크기 비합리 → 무시")
                DL = DT = DW = DH = None

        # 2차 anchor: confirm button (lie_title 매칭 실패/sane 아님 시 fallback)
        if DL is None:
            cb = find_confirm_button(scene)
            if cb is None:
                print("[skip] lie_title + confirm 모두 검출 실패 — word 캡차 아닐 수 있음")
                return False
            cx0, cy0, cx1, cy1, cw, ch = cb
            print(f"[anchor] confirm bbox=({cx0},{cy0})-({cx1},{cy1}) WxH={cw}x{ch}")
            DL, DT, DW, DH = derive_dialog(cb)
            print(f"[dialog] from confirm: origin=({DL},{DT}) WxH={DW}x{DH}")
            if not dialog_is_sane(DW, DH):
                print(f"[fail] dialog 크기 비합리 — confirm 잘못 검출")
                self._save_debug(scene, "bad_dialog")
                return False

        # confirm bbox 항상 필요 (마지막 클릭용) — 다이얼로그 안에서만 검색
        if cb is None:
            search_x0 = max(0, DL); search_y0 = max(0, DT)
            search_x1 = min(scene.shape[1], DL + DW)
            search_y1 = min(scene.shape[0], DT + DH)
            sub = scene[search_y0:search_y1, search_x0:search_x1]
            sub_cb = find_confirm_button(sub)
            if sub_cb is None:
                print("[fail] dialog 안에서 confirm 검출 실패")
                self._save_debug(scene, "no_confirm_in_dialog")
                return False
            cx0 = sub_cb[0] + search_x0
            cy0 = sub_cb[1] + search_y0
            cx1 = sub_cb[2] + search_x0
            cy1 = sub_cb[3] + search_y0
            cw = sub_cb[4]; ch = sub_cb[5]
            print(f"[confirm] dialog 안 ({cx0},{cy0})-({cx1},{cy1})")
        else:
            cx0, cy0, cx1, cy1, cw, ch = cb

        # 7개 ROI gray 추출 + H_NORM 정규화
        gray = cv2.cvtColor(scene, cv2.COLOR_BGR2GRAY)
        roi_grays = {}
        roi_texts = {}
        for name, rel in ROIS.items():
            rx0, ry0, rx1, ry1 = roi_bbox(DL, DT, DW, DH, rel)
            rx0 = max(0, rx0); ry0 = max(0, ry0)
            rx1 = min(gray.shape[1], rx1); ry1 = min(gray.shape[0], ry1)
            roi = gray[ry0:ry1, rx0:rx1]
            roi_grays[name] = roi
            roi_texts[name] = extract_text_norm(roi) if roi.size else None

        # 정답박스 코드 36-템플릿 인식 (로깅용)
        ans_code, ans_per_char = recognize_code_36(roi_grays['ans'], self.templates)
        print(f"[ocr] ans = {ans_code}  ({' '.join(f'{c}={s:.2f}' for c, s in ans_per_char)})")

        # 핵심: 정답박스 텍스트를 6 셀에 sliding 매칭
        if roi_texts['ans'] is None:
            print("[fail] 정답박스 텍스트 추출 실패")
            return False
        cell_texts = {cn: roi_texts[cn] for cn in ('c1','c2','c3','c4','c5','c6')}
        cell_scores, _ = match_cells_to_ans(roi_texts['ans'], cell_texts)
        print('[match] ' + ' '.join(f'{cn}={cell_scores[cn]:.2f}' for cn in ('c1','c2','c3','c4','c5','c6')))

        target = max(cell_scores, key=cell_scores.get)
        best_score = cell_scores[target]
        others = sorted([s for cn, s in cell_scores.items() if cn != target], reverse=True)
        second_score = others[0] if others else -1.0
        gap = best_score - second_score
        print(f'[match] best={target} score={best_score:.2f} 2nd={second_score:.2f} gap={gap:.2f}')

        # 매칭 신뢰 판정:
        # - 큰 격차(gap >= 0.2) + 합리적 점수(best >= 0.3) → 매칭 신뢰 (detect false positive 무시)
        # - 작은 격차 → detect_selected_cell이 잡혀있으면 그걸 우선 (이전 클릭 흔적)
        if gap >= 0.2 and best_score >= 0.3:
            print(f'[match-ok] 매칭 신뢰 (큰 격차)')
        else:
            selected, blue_ratio = detect_selected_cell(scene, DL, DT, DW, DH)
            if selected:
                if selected == target:
                    print(f'[selected] {selected} 선택 상태 + 매칭 일치')
                else:
                    print(f'[selected-fb] 매칭 약함(gap={gap:.2f}) → 선택 셀 {selected} (blue={blue_ratio:.3f}) 신뢰')
                    target = selected
            elif best_score < 0.3:
                print(f"[fail] best match score {best_score:.2f} < 0.3, 격차 {gap:.2f} — 정답 식별 실패")
                self._save_debug(scene, "low_score")
                return False
            else:
                print(f'[match-weak] 격차 작지만 매칭 결과 사용 ({target})')
        rx0, ry0, rx1, ry1 = roi_bbox(DL, DT, DW, DH, ROIS[target])
        click_x = (rx0 + rx1) // 2
        click_y = (ry0 + ry1) // 2
        print(f"[click] target={target} '{ans_code}' at ({click_x},{click_y})")
        human_click(click_x, click_y)
        time.sleep(random.uniform(0.4, 0.7))

        # 확인 버튼 클릭
        conf_x = (cx0 + cx1) // 2
        conf_y = (cy0 + cy1) // 2
        print(f"[click] confirm at ({conf_x},{conf_y})")
        human_click(conf_x, conf_y)
        time.sleep(0.8)
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--interval", type=float, default=3.0)
    args = ap.parse_args()

    print("=" * 60)
    print("  word 캡차 솔버")
    print("=" * 60)
    solver = WordCaptchaSolver()
    if not solver.templates:
        print("[err] 글자 템플릿 없음 → 종료")
        sys.exit(2)

    if args.auto:
        ok = solver.solve_once()
        sys.exit(0 if ok else 1)

    if args.watch:
        try:
            while True:
                try:
                    if solver.solve_once():
                        time.sleep(5.0)
                    else:
                        time.sleep(args.interval)
                except pyautogui.FailSafeException:
                    print("[abort] failsafe"); return
                except Exception as e:
                    print(f"[err] {type(e).__name__}: {e}")
                    time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n중단."); return
    else:
        input("캡차 화면 띄운 상태에서 ENTER...")
        ok = solver.solve_once()
        print(f"\n결과: {'시도 완료' if ok else '실패'}")


if __name__ == "__main__":
    main()
