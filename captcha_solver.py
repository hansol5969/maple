"""
메이플플래닛 "거짓말 탐지기" 슬라이더 캡차 솔버.

화면에서:
  1) slider_handle.png 매칭 → 캡차 다이얼로그 위치 anchor
  2) 다이얼로그 안에서 slot 색깔 mask → slot 중심 X
  3) slider handle을 slot 중심 X로 드래그 (Y 유지)
  4) confirm 버튼 클릭

사용:
  python captcha_solver.py            # 한 번 풀고 종료
  python captcha_solver.py --watch    # 캡차 자동 감시 (3초마다 체크)

자산: captcha_assets/{slider_handle.png, slot.png, confirm_button.png}
"""
from __future__ import annotations
import argparse, ctypes, os, random, sys, time

# stdout/stderr UTF-8 강제 — CP949 콘솔에서 em dash 등 유니코드 print 시 UnicodeEncodeError 방지
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
ASSETS = os.path.join(ROOT, "captcha_assets")

# 캡차 다이얼로그 내부 상대 좌표 (옛 게임창 3126 기준 786,800 → 새 1995 기준 0.638 스케일)
DIALOG_W, DIALOG_H = 502, 511
SLIDER_REL = (30, 310)   # 슬라이더 초기 위치 (드래그 후엔 바뀜 → anchor로 부적합)
CONFIRM_REL = (362, 353) # 확인 버튼 위치 — 드래그해도 안 바뀜 → anchor로 사용


# ---------- DirectInput scancode ENTER (macro.py와 동일 방식) ----------
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
    _fields_ = [('uMsg', ctypes.c_ulong),
                ('wParamL', ctypes.c_short),
                ('wParamH', ctypes.c_ushort)]


class _InputUnion(ctypes.Union):
    _fields_ = [('ki', _KbInput), ('mi', _MouseInput), ('hi', _HwInput)]


class _Input(ctypes.Structure):
    _fields_ = [('type', ctypes.c_ulong), ('ii', _InputUnion)]


_KEYEVENTF_KEYUP    = 0x0002
_KEYEVENTF_SCANCODE = 0x0008
_INPUT_KEYBOARD     = 1
_SCAN_ENTER         = 0x1C


def send_enter_scancode():
    """게임에 ENTER 키 송신 (DirectInput scancode)."""
    extra = ctypes.c_ulong(0)
    # down
    ki = _KbInput(0, _SCAN_ENTER, _KEYEVENTF_SCANCODE, 0, ctypes.pointer(extra))
    inp = _Input(_INPUT_KEYBOARD, _InputUnion(ki=ki))
    ctypes.windll.user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))
    time.sleep(0.04)
    # up
    ki = _KbInput(0, _SCAN_ENTER,
                  _KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP,
                  0, ctypes.pointer(extra))
    inp = _Input(_INPUT_KEYBOARD, _InputUnion(ki=ki))
    ctypes.windll.user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


# ---------- 이미지 IO (한글 경로 우회) ----------
def load_bgr(path: str) -> np.ndarray:
    pil = Image.open(path).convert("RGB")
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


# ---------- 색 통계 ----------
def slot_mean_color(slot_bgr: np.ndarray) -> np.ndarray:
    """slot.png 중심 60% 영역의 평균 BGR."""
    h, w = slot_bgr.shape[:2]
    region = slot_bgr[h // 5:h - h // 5, w // 5:w - w // 5].reshape(-1, 3)
    return region.mean(axis=0)


# ---------- slot 검출 ----------
def _subpixel_peak(res, x, y):
    """matchTemplate 결과의 정수 픽 좌표 (x, y) 주변 quadratic fit으로 sub-pixel 보정."""
    H, W = res.shape
    if not (0 < x < W - 1 and 0 < y < H - 1):
        return float(x), float(y)
    # 중심 vs 좌우/상하 차이로 quadratic vertex
    cx = res[y, x]
    dx = (res[y, x + 1] - res[y, x - 1]) * 0.5
    dxx = res[y, x + 1] - 2 * cx + res[y, x - 1]
    dy = (res[y + 1, x] - res[y - 1, x]) * 0.5
    dyy = res[y + 1, x] - 2 * cx + res[y - 1, x]
    sx = x - (dx / dxx) if abs(dxx) > 1e-6 else float(x)
    sy = y - (dy / dyy) if abs(dyy) > 1e-6 else float(y)
    # 경계 안에 있어야 (수렴 실패 시 정수 fallback)
    if abs(sx - x) > 1.0 or abs(sy - y) > 1.0:
        return float(x), float(y)
    return sx, sy


def find_slot_in_dialog(dialog_bgr: np.ndarray, slot_templates: list,
                        thr: float = 0.55):
    """
    슬롯 검출 — 여러 real_slot template 매칭, sub-pixel 정확도.
    반환: (x_subpix, y_subpix, w, h, score, name) — float 좌표
    """
    best = None
    for name, tmpl in slot_templates:
        res = cv2.matchTemplate(dialog_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if best is None or score > best["score"]:
            th, tw = tmpl.shape[:2]
            sx, sy = _subpixel_peak(res, loc[0], loc[1])
            best = {"x": sx, "y": sy, "w": tw, "h": th,
                    "score": float(score), "name": name}
    if best is None or best["score"] < thr:
        return None
    return (best["x"], best["y"], best["w"], best["h"],
            best["score"], best["name"])


# ---------- 화면에서 anchor (slider handle) 찾기 ----------
def match_template(scene_bgr: np.ndarray, tmpl_bgr: np.ndarray,
                   thr: float = 0.7) -> tuple[int, int, int, int, float] | None:
    sg = cv2.cvtColor(scene_bgr, cv2.COLOR_BGR2GRAY)
    tg = cv2.cvtColor(tmpl_bgr, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(sg, tg, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score < thr:
        return None
    x, y = loc
    h, w = tg.shape
    return x, y, w, h, float(score)


def grab_screen() -> np.ndarray:
    pil = pyautogui.screenshot()
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


# ---------- 사람스러운 드래그 ----------
def human_drag(start: tuple[int, int], end: tuple[int, int]) -> None:
    sx, sy = start; ex, ey = end
    pyautogui.moveTo(sx, sy, duration=0.3, tween=pyautogui.easeInOutQuad)
    time.sleep(0.2)
    pyautogui.mouseDown()
    time.sleep(0.15)

    dx_total = ex - sx
    cur_x = sx
    while abs(cur_x - ex) > 3:
        remaining = ex - cur_x
        step = max(-90, min(90, remaining))
        if abs(remaining) > 10:
            step = int(step * random.uniform(0.5, 1.0))
        if step == 0:
            break
        dy = random.randint(-2, 2)
        pyautogui.moveRel(step, dy,
                          duration=random.uniform(0.05, 0.12),
                          tween=pyautogui.easeInOutSine)
        cur_x += step

    # 마지막 정밀 보정 — pyautogui는 미세 어긋남 가능 → SetCursorPos로 픽셀 정확
    pyautogui.moveTo(ex, ey, duration=0.15, tween=pyautogui.easeInOutSine)
    ctypes.windll.user32.SetCursorPos(int(ex), int(ey))  # 픽셀 정확 보장
    time.sleep(0.30)  # 안정화 시간 늘림 (게임이 위치 인식할 시간)
    pyautogui.mouseUp()


# ---------- 메인 풀이 ----------
class Solver:
    def __init__(self):
        self.slider_tmpl = load_bgr(os.path.join(ASSETS, "slider_handle.png"))
        self.confirm_tmpl = load_bgr(os.path.join(ASSETS, "confirm_button.png"))
        # multi-template: 가능한 모든 real_slot_*.png 로드 → 각 위치에서 max score
        # 한 template에 오버피팅 안 되도록 5장 모두 사용
        self.slot_tmpls = []
        for fname in sorted(os.listdir(ASSETS)):
            if fname.startswith("real_slot_") and fname.endswith(".png"):
                self.slot_tmpls.append((fname, load_bgr(os.path.join(ASSETS, fname))))
        if not self.slot_tmpls:
            # fallback: 옛 slot.png 사용
            self.slot_tmpls = [("slot.png", load_bgr(os.path.join(ASSETS, "slot.png")))]
        print(f"[init] slot templates: {len(self.slot_tmpls)}장 "
              f"({', '.join(n for n, _ in self.slot_tmpls)})")

    def find_dialog(self, scene_bgr: np.ndarray):
        """
        slider handle 매칭으로 다이얼로그 좌상단 추정.
        슬라이더 모양은 절대 변하지 않으므로 가장 안정적인 anchor.
        매번 새 캡차에서 슬라이더는 좌측 시작 위치(SLIDER_REL).
        """
        m = match_template(scene_bgr, self.slider_tmpl, thr=0.0)
        if not m:
            print("[skip] match_template 결과 없음")
            return None
        sx, sy, sw, sh, score = m
        print(f"[match] slider handle best score={score:.3f} at ({sx},{sy})")

        # 임계값 0.50 — 매우 관대. 슬라이더 모양은 같으니 score 0.5+면 진짜 슬라이더
        if score < 0.50:
            print(f"[skip] slider score {score:.2f} < 0.50 — 캡차 화면 없는 듯")
            return None

        ax = sx - SLIDER_REL[0]
        ay = sy - SLIDER_REL[1]
        H, W = scene_bgr.shape[:2]
        ax = max(0, min(ax, W - DIALOG_W))
        ay = max(0, min(ay, H - DIALOG_H))
        return ax, ay, sx, sy, sw, sh, score

    def _save_debug_screen(self, scene_bgr, reason: str):
        """디버그 화면 저장은 비활성 — 캡차 안정 작동 확인됨."""
        pass

    def solve_once(self) -> bool:
        scene = grab_screen()
        d = self.find_dialog(scene)
        if not d:
            print("[skip] 캡차 미발견 (slider handle 매칭 실패)")
            self._save_debug_screen(scene, "no_dialog")
            return False
        ax, ay, sx, sy, sw, sh, sc = d
        print(f"[anchor] dialog=({ax},{ay})  slider=({sx},{sy}) score={sc:.2f}")

        # 다이얼로그 영역 crop
        dialog = scene[ay:ay + DIALOG_H, ax:ax + DIALOG_W]
        if dialog.shape[0] < DIALOG_H or dialog.shape[1] < DIALOG_W:
            print("[fail] 다이얼로그 영역이 화면 밖")
            self._save_debug_screen(scene, "out_of_bounds")
            return False

        slot = find_slot_in_dialog(dialog, self.slot_tmpls, thr=0.55)
        if slot is None:
            print("[fail] slot 검출 실패 (모든 template score < 0.55)")
            self._save_debug_screen(scene, "no_slot")
            return False
        slx, sly, slw, slh, slot_score, best_tpl = slot
        # sub-pixel float 좌표 → 화면 픽셀로 round
        slot_cx_screen = int(round(ax + slx + slw / 2))
        slot_cy_screen = int(round(ay + sly + slh / 2))
        print(f"[slot] rel=({slx:.2f},{sly:.2f}) size={slw}x{slh} "
              f"best_tpl={best_tpl} score={slot_score:.3f} "
              f"center=({slot_cx_screen},{slot_cy_screen})")

        # confirm 위치 — 다이얼로그 안에서만 검색
        m_conf = match_template(dialog, self.confirm_tmpl, thr=0.7)
        if not m_conf:
            print("[fail] confirm 버튼 검출 실패")
            self._save_debug_screen(scene, "no_confirm")
            return False
        cx_rel, cy_rel, cw, ch, cs = m_conf
        confirm_x = ax + cx_rel + cw // 2
        confirm_y = ay + cy_rel + ch // 2
        print(f"[confirm] ({confirm_x},{confirm_y}) score={cs:.2f}")

        # 드래그: slider 중심 → (slot_cx, slider_cy)
        slider_cx = sx + sw // 2
        slider_cy = sy + sh // 2
        target_x = slot_cx_screen
        target_y = slider_cy  # Y 유지 (좌우 슬라이더)
        distance = target_x - slider_cx
        if distance < 5:
            # 슬라이더가 이미 slot 위치 또는 우측에 있음 (이전 시도 결과)
            # → 이번 캡차는 풀이 불가, 새 캡차 받도록 fail
            print(f"[skip] 드래그 거리 {distance}px — 슬라이더가 이미 옮겨짐 "
                  f"(slider_cx={slider_cx} slot_cx={slot_cx_screen})")
            self._save_debug_screen(scene, "bad_distance")
            return False
        print(f"[drag] {distance}px → ({target_x},{target_y})")

        try:
            human_drag((slider_cx, slider_cy), (target_x, target_y))
        except pyautogui.FailSafeException:
            print("[abort] 사용자 중단")
            return False

        time.sleep(0.6)

        # 확인 클릭
        print(f"[click] confirm")
        pyautogui.moveTo(confirm_x, confirm_y, duration=0.3,
                         tween=pyautogui.easeInOutSine)
        time.sleep(0.15)
        pyautogui.click()

        # 1초 대기 후 ENTER 송신 (다음 단계 dialog 닫기 등)
        time.sleep(1.0)
        print("[enter] sending ENTER scancode")
        send_enter_scancode()
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true",
                    help="캡차 자동 감시 모드 (3초 간격)")
    ap.add_argument("--auto", action="store_true",
                    help="즉시 1회 풀이 후 종료 (macro.py 연동용)")
    ap.add_argument("--interval", type=float, default=3.0)
    args = ap.parse_args()

    print("=" * 60)
    print("  메이플플래닛 캡차 솔버")
    print("=" * 60)
    print("  Failsafe: 마우스를 화면 좌상단(0,0)으로")

    solver = Solver()

    if args.auto:
        ok = solver.solve_once()
        sys.exit(0 if ok else 1)

    if args.watch:
        print(f"\n감시 모드 — {args.interval}초 간격 체크. Ctrl+C 종료.")
        try:
            while True:
                try:
                    if solver.solve_once():
                        print("[done] 풀이 시도 완료. 5초 대기.")
                        time.sleep(5.0)
                    else:
                        time.sleep(args.interval)
                except pyautogui.FailSafeException:
                    print("[abort] failsafe."); return
                except Exception as e:
                    print(f"[err] {type(e).__name__}: {e}")
                    time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n중단."); return
    else:
        input("캡차가 화면에 보이는 상태에서 ENTER...")
        ok = solver.solve_once()
        print(f"\n결과: {'시도 완료' if ok else '실패'}")


if __name__ == "__main__":
    main()
