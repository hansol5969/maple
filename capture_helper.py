"""
템플릿 캡처 보조 도구
실행: python capture_helper.py
- 5초 카운트다운 후 게임창 전체를 스크린샷으로 저장 (capture_full.png)
- 그 이미지를 그림판/캡처도구 등에서 열어서 필요한 부분만 잘라
  templates/nickname.png, templates/mob1.png, templates/mob2.png 로 저장하면 됨
"""

import time
import sys
sys.path.insert(0, '.')
import macro
import mss
import cv2
import numpy as np

print(f'게임 영역: {macro.GAME_REGION}')
print('5초 후 캡처합니다. 게임 창에 포커스 두세요.')
for i in range(5, 0, -1):
    print(i)
    time.sleep(1)

with mss.mss() as sct:
    img = np.array(sct.grab(macro.GAME_REGION))
    bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    cv2.imwrite('capture_full.png', bgr)

print('저장됨: capture_full.png')
print('이걸 열어서:')
print('  1) 본인 캐릭터 닉네임 글자만 잘라 → templates/nickname.png')
print('  2) 사냥할 몹 한 마리 본체만 잘라 → templates/mob1.png')
print('  3) (다른 종류 몹 있으면) → templates/mob2.png')
