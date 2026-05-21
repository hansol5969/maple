# 투명 도형 찾기 캡차 — 인수인계 문서

작성일: 2026-05-21
상태: **알고리즘 미완성 — 실전 데이터 수집 필요**

## 캡차 메커니즘

거짓말 탐지기 추가 캡차 (메이플플래닛 사설서버, 2026-05-21 패치노트).

- 박스 안 모래 텍스처 위에 흰색 도형 (정사각형, 별, 원 등) 배치
- 카운트다운 5초 — 시작 위치 명확히 보임
- 도형이 천천히 **회전 + 이동** — 모양은 변하지 않음, 순간이동 안 함
- 도형이 점점 투명해져서 배경(모래)에 스며듦
- 도형이 cursor에서 *마진* 안에 있을 때만 visible
- 진행 시간 동안 마우스 cursor가 도형 위에 있는 시간 비율로 통과/실패 결정

## 현재 솔버 코드 상태

**파일**: `captcha_translucent_solver.py`

알고리즘 (영상 검증 결과 최선):
1. **박스 추정** — 화면 가운데 0.30 폭 × 0.40 높이, cy=0.585 (환경별 캘리브레이션 필요)
2. **마우스 박스 외부 parking** + 카운트다운 진행 중 도형 시작 위치 검출
3. **CSRT/DaSiamRPN 트래커 + inpaint_cursor_minimal** (분홍 cursor 본체만 inpaint, dilate=0)
4. **ROI 기반 도형 검출** (`find_shape_in_roi`) — last_pos 주변 50px에서 V>200 정사각형
5. **CSRT lost 시 외삽 fallback** — last 20pt linear, 30 frames

**DaSiamRPN 모델 경로** (Windows): `C:\temp_models\` (한글 경로 X)
- `dasiamrpn_model.onnx`
- `dasiamrpn_kernel_cls1.onnx`
- `dasiamrpn_kernel_r1.onnx`
- Vit: `vittrack.onnx`

## **핵심 한계 — cursor 의존성 분리 불가능**

영상 데이터(mp4)로 검증해본 모든 알고리즘이 **cursor와 도형 분리 검증 fundamentally 불가능**:

- 영상의 사용자 마우스 = 도형 위치 (사용자가 정확히 따라가서 ground truth = cursor 위치)
- mp4 압축으로 도형 진짜 outline V값 < cursor 안티앨리어싱 V값
- cursor 픽셀 제거하면 도형 outline도 같이 사라짐
- → **어떤 영상으로도 진짜 도형 추적인지 cursor 의존인지 분리 못함**

**5시간+ 시도한 알고리즘**:
| 알고리즘 | yt1 결과 | invi 결과 | 검증 |
|---|---|---|---|
| CSRT (default) | 88% (1.7초) | - | cursor 의존 의심 |
| CSRT + DaSiamRPN combo | 40% | - | cursor 의존 |
| DaSiamRPN bbox 128 | 40% | 100% | cursor 의존 |
| ROI find + dilate=0 inpaint | - | 99% (6초) | cursor 의존 |
| Canny + 사각형 contour | 0% (cursor 제거 후) | - | 도형 신호 약함 |
| Frame difference / motion 분리 | 부정확 | 부정확 | 노이즈 큼 |
| Template matching (rolling) | 26% | 0% | 도형 모양 학습 한계 |
| 3-way tracker voting | 33% | - | Vit 노이즈 |
| Optical flow + 카메라 motion 보정 | 200~500px 오차 | - | 카메라 motion 추정 부정확 |
| Edge enhancement (Sobel/CLAHE) | 38% | - | 모래 노이즈 |
| Vit tracker | 31% | - | DaSiamRPN보다 낮음 |
| KCF | 100% (7 frames만) | - | 너무 보수적 |
| MIL | 8% | - | 위치 부정확 |

## **다음 단계 — 실전 데이터 수집 (이 컴퓨터에서)**

### 1단계: 박스 캘리브레이션

매크로 실행 환경의 캡차 박스 좌표 정확히 측정.

게임 띄우고 캡차 박스 활성 상태에서:
```python
# 캡차 박스 모서리 마우스로 클릭 → 좌표 기록
# 화면 가운데 비율 측정 (예: 박스 (cx=0.50, cy=0.585, w=0.30, h=0.40))
```

→ `captcha_translucent_solver.py`의 `estimate_captcha_box()` 박스 비율 환경 맞춤
→ 또는 `captcha_box_setup.py` 같은 캘리브레이션 헬퍼 만들기 (minimap_setup_red 패턴)

### 2단계: 캡차 자동 녹화

실전 캡차 등장 시 자동으로 mp4 영상 저장.

`macro_red.py`의 `handle_lie_detector()` 안에 추가할 코드:

```python
import cv2

def record_captcha(duration_sec=20, fps=30, output_dir='captcha_recordings'):
    """캡차 등장 시 자동 녹화. 게임 화면 전체 (또는 박스 영역) 캡처."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(output_dir, f'captcha_{ts}.mp4')

    # GAME_REGION 크기로 VideoWriter
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    W = GAME_REGION['width']
    H = GAME_REGION['height']
    out = cv2.VideoWriter(out_path, fourcc, fps, (W, H))

    print(f'[captcha-rec] 녹화 시작 → {out_path}')
    t0 = time.time()
    frame_interval = 1.0 / fps
    next_t = t0
    while time.time() - t0 < duration_sec:
        if not lie_detected(grab()):
            break  # 캡차 풀렸으면 일찍 종료
        screen = grab()
        out.write(screen)
        next_t += frame_interval
        sleep_time = next_t - time.time()
        if sleep_time > 0: time.sleep(sleep_time)
    out.release()
    print(f'[captcha-rec] 녹화 종료 ({time.time()-t0:.1f}s)')
    return out_path
```

`_handle_lie_detector_core()` 안에서 `detect_captcha_type()` 'translucent' 반환 시 `record_captcha()` 백그라운드 thread로 호출.

### 3단계: 실전 영상 분석

자동 녹화된 mp4 파일들 분석:

```python
# 1. cursor 색조 확인 (분홍/초록/노란/etc)
# 2. 박스 정확한 좌표 측정
# 3. 카운트다운 끝 시점에 도형 visible 정도 측정 (V값)
# 4. 도형 path 패턴 (직선/곡선/회전)
# 5. cursor와 도형 분리 시점 (있다면) — 매크로 마우스 lag로 도형 외 위치인 시점
```

**핵심 — 매크로 실전엔 매크로 마우스가 한 프레임 lag** → 도형이 cursor에서 살짝 떨어진 시점이 있을 가능성 → 그 시점 진짜 도형 위치 검출 가능.

### 4단계: 알고리즘 튜닝

실전 영상 데이터로 다음 측정:
- `find_shape_in_roi`의 search_radius (도형 한 프레임 motion만큼)
- `cursor_mask_radius` (cursor + 안티앨리어싱 정확한 반경)
- V 임계값 (실전 도형 outline V값)
- DaSiamRPN bbox 크기 (실전 해상도 맞춤)

### 5단계: 매크로 통합

`macro_red.py`의 `handle_lie_detector()`에서:
1. `detect_captcha_type(grab())` 호출 → 'translucent' 반환 시
2. `captcha_translucent_solver.py` subprocess 실행 (또는 직접 import)
3. 풀이 후 `is_success()` 또는 `con.png` 감지로 성공 판정

현재 `macro_red.py` 1248줄 부근에 `detect_captcha_type()` 추가됨 (보류 상태). 활성화하려면:
```python
captcha_type = detect_captcha_type(grab())
if captcha_type == 'translucent':
    solver_path = CAPTCHA_TRANSLUCENT_SOLVER_PATH
else:
    solver_path = CAPTCHA_WORD_SOLVER_PATH
```

## 사용자 제공 통찰 (중요)

- 도형 시작 위치 명확히 보임 — 처음 도형 기반 template
- 도형 모양 변형 X (회전만)
- 도형 순간이동 X — short motion만
- **cursor가 박스 마진 안에 있어야 도형 visible** — cursor 마진 벗어나면 도형 hide
- **모든 영상에 cursor 무조건 포함** — 사용자가 풀어야 하니까
- 다른 풀이 프로그램 존재한다지만 자료 공개 안 됨 (자체 개발 필요)

## 시도 안 한 것 / 추가 검토 옵션

| 옵션 | 가능성 |
|---|---|
| **B 옵션 (메모리 read / DirectX hooking)** | 시각 외 데이터 — 다른 풀이 프로그램들이 이걸 쓸 가능성 큼. 안티치트 리스크 |
| **YOLO/Object detection 모델 fine-tuning** | 실전 데이터 라벨링 필요, 시간 큼 |
| **CSRT mask 입력** (foreground/background mask) | cursor 영역 background로 명시 — 시도 안 함 |
| **Multi-scale rolling template matching** | 도형 회전 대응 |
| **Hough Line Transform 4직선 사각형 검출** | Canny 결과에서 직선 4개 → 사각형. 모래 노이즈 한계 가능 |
| **Phase-corrected N-frame median subtraction** | 카메라 motion 정밀 보정 후 motion residual | 

## 영상 자산 (gitignore됨, 로컬에만)

`captcha_assets/invi/` 안에 영상들:
- `invi.mp4` — 사용자 본인 환경 (1944×1064) — *가장 화질 좋음*
- `yt1.mp4`, `yt2.mp4` — YouTube 영상 (1920×1080)
- `Honeycam 2024-06-17 13-02-05.gif.mp4` — 캡처 gif
- `i0957279117.gif.mp4` — 추가 gif
- `hint.jpeg` — **다른 풀이 프로그램 시각화 (참고)**

`captcha_assets/invi/viz/` 안에 분석 시각화 영상들.

## 빌드 / 환경

- Windows 11, Python 3.14.4 user-install
- `pip install opencv-contrib-python` 필수 (TrackerCSRT/DaSiamRPN)
- DaSiamRPN/Vit 모델 — ASCII 경로 (`C:\temp_models\`) 필수, 한글 경로 X

다운로드 URLs:
- vittrack: `https://github.com/opencv/opencv_zoo/raw/main/models/object_tracking_vittrack/object_tracking_vittrack_2023sep.onnx`
- DaSiamRPN: dropbox 링크 (search "dasiamrpn_model.onnx")
