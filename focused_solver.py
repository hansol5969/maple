"""
포커스 중인 윈도우의 슬라이더 캡차를 푸는 스크립트.

흐름:
  1. 대상 윈도우 포커스 (캡차 표시된 상태)
  2. 본 스크립트 실행 → ENTER
  3. [1/3] 캡차 배경 영역(BG) 마우스 드래그
  4. [2/3] 좌측에 떠 있는 퍼즐 조각(PIECE) 마우스 드래그
  5. [3/3] 슬라이더 핸들 위치 클릭
  6. 자동 분석 → 드래그

중단: 마우스를 화면 좌상단(0,0)으로 (pyautogui Failsafe), 또는 영역 선택 중 ESC

요구 패키지: pyautogui, pillow, opencv-python, numpy
설치: C:/Python314/python.exe -m pip install opencv-python numpy pillow pyautogui

주의: 멀티 모니터 환경이면 캡차가 *주 모니터* 위에 있어야 합니다
      (오버레이가 주 모니터만 덮도록 되어 있음).
"""

from __future__ import annotations
import ctypes, random, sys, time
import tkinter as tk

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

pyautogui.PAUSE = 0
pyautogui.MINIMUM_DURATION = 0
pyautogui.FAILSAFE = True


# ---------------- 영역/포인트 선택 오버레이 ----------------
def _overlay(prompt: str):
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-alpha", 0.35)
    root.attributes("-topmost", True)
    root.configure(bg="black")
    canvas = tk.Canvas(root, cursor="cross", bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    tk.Label(
        root, text=prompt, font=("Malgun Gothic", 18),
        bg="yellow", fg="black", padx=12, pady=6,
    ).place(relx=0.5, y=20, anchor="n")
    return root, canvas


def pick_region(prompt: str) -> tuple[int, int, int, int] | None:
    """드래그한 사각형 → (x, y, w, h) 화면 좌표."""
    root, canvas = _overlay(prompt)
    state = {"rect": None}
    out: dict = {}

    def on_press(e):
        out["x1"], out["y1"] = e.x_root, e.y_root
        if state["rect"]:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(
            e.x, e.y, e.x, e.y, outline="red", width=2
        )

    def on_drag(e):
        if state["rect"]:
            x1 = out["x1"] - root.winfo_rootx()
            y1 = out["y1"] - root.winfo_rooty()
            canvas.coords(state["rect"], x1, y1, e.x, e.y)

    def on_release(e):
        out["x2"], out["y2"] = e.x_root, e.y_root
        root.after(60, root.destroy)

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda e: (out.clear(), root.destroy()))
    root.mainloop()

    if "x2" not in out:
        return None
    x1, y1 = min(out["x1"], out["x2"]), min(out["y1"], out["y2"])
    x2, y2 = max(out["x1"], out["x2"]), max(out["y1"], out["y2"])
    if x2 - x1 < 5 or y2 - y1 < 5:
        return None
    return (x1, y1, x2 - x1, y2 - y1)


def pick_point(prompt: str) -> tuple[int, int] | None:
    root, canvas = _overlay(prompt)
    out: dict = {}

    def on_click(e):
        out["x"], out["y"] = e.x_root, e.y_root
        root.after(60, root.destroy)

    canvas.bind("<ButtonPress-1>", on_click)
    root.bind("<Escape>", lambda e: (out.clear(), root.destroy()))
    root.mainloop()
    if "x" not in out:
        return None
    return (out["x"], out["y"])


# ---------------- 퍼즐 매칭 (Canny + template matching) ----------------
def find_gap_x_in_bg(
    bg_rgb: np.ndarray, piece_rgb: np.ndarray, search_start: int
) -> tuple[int, float]:
    """
    BG 안에서 PIECE 모양이 매칭되는 X (좌상단) 좌표를 BG 좌표계로 반환.
    search_start: 이 X 미만은 검색하지 않음 (조각 자기 자신과의 매칭 회피).
    """
    bg_gray = cv2.cvtColor(bg_rgb, cv2.COLOR_RGB2GRAY)
    piece_gray = cv2.cvtColor(piece_rgb, cv2.COLOR_RGB2GRAY)
    bg_edge = cv2.Canny(bg_gray, 100, 200)
    piece_edge = cv2.Canny(piece_gray, 100, 200)

    if (
        piece_edge.shape[0] > bg_edge.shape[0]
        or piece_edge.shape[1] > bg_edge.shape[1]
    ):
        raise ValueError("PIECE가 BG보다 큽니다 — 영역 선택을 다시 해주세요.")

    search_start = max(0, min(search_start, bg_edge.shape[1] - piece_edge.shape[1] - 1))
    bg_search = bg_edge[:, search_start:]
    if bg_search.shape[1] < piece_edge.shape[1]:
        raise ValueError("검색 영역이 너무 좁습니다 — BG를 더 넓게 잡아주세요.")

    res = cv2.matchTemplate(bg_search, piece_edge, cv2.TM_CCOEFF_NORMED)
    _, score, _, max_loc = cv2.minMaxLoc(res)
    return max_loc[0] + search_start, float(score)


# ---------------- 사람스러운 드래그 ----------------
def human_drag(start_x: int, start_y: int, distance: int) -> None:
    pyautogui.moveTo(start_x, start_y, duration=0.4, tween=pyautogui.easeInOutQuad)
    time.sleep(0.25)
    pyautogui.mouseDown()
    time.sleep(0.18)

    current = 0
    while current < distance:
        remaining = distance - current
        dx = min(random.randint(40, 90), remaining)
        dy = random.randint(-6, 6)
        dur = random.randint(40, 90) / 100
        pyautogui.moveRel(dx, dy, duration=dur, tween=pyautogui.easeInOutSine)
        current += dx

    time.sleep(0.35)
    pyautogui.mouseUp()


# ---------------- 메인 ----------------
def main():
    print("=" * 60)
    print("  포커스 윈도우 슬라이더 캡차 솔버")
    print("=" * 60)
    print("  Failsafe: 마우스를 화면 좌상단(0,0)으로 옮기면 즉시 중단")
    input("\n대상 윈도우 포커스 후 ENTER...")

    bg = pick_region("[1/3] 캡차 배경(BG) 영역을 드래그하세요")
    if not bg:
        print("취소됨."); return
    bx, by, bw, bh = bg
    print(f"  BG    = ({bx},{by}) {bw}×{bh}")

    pc = pick_region("[2/3] 좌측의 퍼즐 조각(PIECE) 영역을 드래그하세요")
    if not pc:
        print("취소됨."); return
    px, py, pw, ph = pc
    print(f"  PIECE = ({px},{py}) {pw}×{ph}")

    sl = pick_point("[3/3] 슬라이더 핸들 위치를 클릭하세요")
    if not sl:
        print("취소됨."); return
    sx, sy = sl
    print(f"  SLIDER= ({sx},{sy})")

    time.sleep(0.4)  # 오버레이 잔상 제거

    bg_img = np.array(pyautogui.screenshot(region=(bx, by, bw, bh)))
    piece_img = np.array(pyautogui.screenshot(region=(px, py, pw, ph)))

    # 조각의 BG 내 좌표 (조각이 BG 위에 떠 있다고 가정)
    piece_x_in_bg = px - bx
    # 자기 자신과의 매칭을 피하기 위해 조각 오른쪽 끝부터 탐색
    search_start = max(0, piece_x_in_bg + pw // 2)

    try:
        gap_x_in_bg, score = find_gap_x_in_bg(bg_img, piece_img, search_start)
    except ValueError as e:
        print(f"  매칭 실패: {e}"); return

    print(f"  매칭 score={score:.3f}, gap_x(BG 기준)={gap_x_in_bg}, "
          f"piece_x(BG 기준)={piece_x_in_bg}")

    distance = gap_x_in_bg - piece_x_in_bg
    print(f"  드래그 거리: {distance}px")

    if score < 0.35:
        print(f"  매칭 신뢰도 낮음(score<{0.35}). 영역 다시 잡아주세요.")
        return
    if distance < 5:
        print("  거리가 너무 짧음 — 영역 선택 확인.")
        return

    try:
        human_drag(sx, sy, distance)
        print("  드래그 완료.")
    except pyautogui.FailSafeException:
        print("  사용자 중단.")


if __name__ == "__main__":
    main()
