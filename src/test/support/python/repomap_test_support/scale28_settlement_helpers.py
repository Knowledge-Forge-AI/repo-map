from __future__ import annotations

import os
import time


def slow_exit_child(delay_s: float):
    time.sleep(delay_s)
    os._exit(1)


def hanging_child():
    while True:
        time.sleep(0.1)
