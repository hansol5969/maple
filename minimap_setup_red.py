"""macro_red.py 전용 미니맵 셋업.

사용: python minimap_setup_red.py

→ minimap_config_red.json 에 저장 (macro_red.py 가 사용).
조작/단축키는 minimap_setup.py 와 동일.
"""
import os
import sys

import minimap_setup


def run():
    minimap_setup.CONFIG_PATH = 'minimap_config_red.json'
    minimap_setup.WINDOW_NAME = 'minimap_setup (red)'
    try:
        minimap_setup.main()
    except KeyboardInterrupt:
        print('\n인터럽트 → 종료')
    finally:
        minimap_setup.cleanup_windows()
    sys.stdout.flush()
    os._exit(0)


if __name__ == '__main__':
    run()
