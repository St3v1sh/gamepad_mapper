"""
Mouse/Keyboard → Xbox 360 Controller Mapper
============================================
Requires:
  1. pip install vgamepad
  2. The Interception driver: https://github.com/oblitum/Interception
  3. The cobrce Interception Python port. Download `interception.py`,
     `consts.py`, and `stroke.py` from
     https://github.com/cobrce/interception_py and place them in the
     SAME directory as this script. (Do NOT use
     `pip install interception-python` as it is a different package).

The Interception driver must be installed for input capture to work.
Run this script as Administrator.
"""

import math
import time
import threading
import vgamepad as vg
from interception import interception, key_stroke, mouse_stroke
from interception import interception_filter_key_state, interception_filter_mouse_state

# ==========================================
# 1. SETTINGS & PROFILES
# ==========================================

SETTINGS = {
    "deadzone": 100,        # Minimum mapped deflection (out of 32768)
    "smoothing": 5,         # EMA smoothing strength, 0 (instant) to 9 (max)
    "noise_filter": 1.0,    # Ignore raw mouse deltas <= this value
    "sens_x": 600,          # Horizontal sensitivity (out of 5000 scale)
    "sens_y": 600,          # Vertical sensitivity
}

CURVES = {
    "Default": [(0, 0), (32768, 32768)],
    "Delay": [(0, 0), (9469,  8519),  (27784, 18677), (32768, 32768)],
    "Aggressive": [(0, 0), (9344,  8847),  (19311, 25886), (32768, 32768)],
    "Smooth": [(0, 0), (17941, 18350), (27908, 20316), (32768, 32768)],
    "Instant": [(0, 0), (8098,  8847),  (8099,  14090), (32768, 32768)],
}

ACTIVE_CURVE = "Default"

KEY_PROFILE = {
    0x11: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,     # W
    0x1F: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,   # S
    0x1E: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,   # A
    0x20: vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,  # D
    0x39: vg.XUSB_BUTTON.XUSB_GAMEPAD_A,           # Space
    0x2A: vg.XUSB_BUTTON.XUSB_GAMEPAD_B,           # Left Shift
    0x13: vg.XUSB_BUTTON.XUSB_GAMEPAD_X,           # R
}

# Key state constants (from interception driver internals)
KEY_DOWN = 0x00  # Key pressed
KEY_UP = 0x01  # Key released
# Extended key pressed  (e.g. Right Ctrl, Right Alt, numpad)
KEY_E0_DOWN = 0x02
KEY_E0_UP = 0x03  # Extended key released
MOUSE_MOVE_ABSOLUTE = 0x001

# ==========================================
# 2. SHARED STATE
# ==========================================

_state_lock = threading.Lock()
_vgamepad_lock = threading.Lock()  # Prevent C-struct corruption in vgamepad

override_active = False
mouse_target_x = 0.0
mouse_target_y = 0.0
last_mouse_time = time.perf_counter()

gamepad = vg.VX360Gamepad()


# ==========================================
# 3. MATH FUNCTIONS
# ==========================================

def evaluate_curve(x: float, points: list) -> float:
    """Evaluate a piecewise-linear response curve at position x."""
    if x <= points[0][0]:
        return float(points[0][1])
    if x >= points[-1][0]:
        return float(points[-1][1])

    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        if x1 <= x <= x2:
            if x2 == x1:
                return float(y1)
            slope = (y2 - y1) / float(x2 - x1)
            return y1 + slope * (x - x1)
    return 0.0


def calculate_joystick(dx: int, dy: int):
    """Translate a raw mouse delta into a joystick (x, y) target value."""
    if abs(dx) <= SETTINGS["noise_filter"]:
        dx = 0
    if abs(dy) <= SETTINGS["noise_filter"]:
        dy = 0
    if dx == 0 and dy == 0:
        return 0.0, 0.0

    # Scale raw delta into the 0–32768 range using sensitivity setting
    multiplier_x = (SETTINGS["sens_x"] / 5000.0) * 500
    multiplier_y = (SETTINGS["sens_y"] / 5000.0) * 500

    sx = dx * multiplier_x
    sy = -dy * multiplier_y   # Invert Y: mouse-up → stick-up

    magnitude = math.sqrt(sx ** 2 + sy ** 2)
    if magnitude == 0:
        return 0.0, 0.0

    dir_x = sx / magnitude
    dir_y = sy / magnitude

    # Apply response curve
    mapped_mag = evaluate_curve(magnitude, CURVES[ACTIVE_CURVE])

    # Re-apply deadzone so the stick doesn't jump from 0 to deadzone
    if mapped_mag > 0:
        dz = SETTINGS["deadzone"]
        mapped_mag = dz + mapped_mag * ((32768 - dz) / 32768.0)

    return mapped_mag * dir_x, mapped_mag * dir_y


# ==========================================
# 4. CONTROLLER THREAD  (~500 Hz)
# ==========================================

def controller_loop():
    """
    Reads the shared mouse target, applies EMA smoothing, decays to zero when
    the mouse is idle, and pushes the result to the virtual gamepad at ~500 Hz.
    """
    global mouse_target_x, mouse_target_y

    current_x = 0.0
    current_y = 0.0

    # alpha=0 means no smoothing (instant follow); alpha→1 means heavy lag.
    alpha = 1.0 - (SETTINGS["smoothing"] / 10.0)

    while True:
        with _state_lock:
            target_x = mouse_target_x
            target_y = mouse_target_y
            idle_secs = time.perf_counter() - last_mouse_time

        # Decay target to zero if no mouse event has arrived in the last 10 ms
        if idle_secs > 0.01:
            with _state_lock:
                mouse_target_x = 0.0
                mouse_target_y = 0.0
            target_x = target_y = 0.0

        # Exponential Moving Average
        current_x = current_x * (1.0 - alpha) + target_x * alpha
        current_y = current_y * (1.0 - alpha) + target_y * alpha

        stick_x = max(-32768, min(32767, int(current_x)))
        stick_y = max(-32768, min(32767, int(current_y)))

        # Protect ViGEmBus update across threads
        with _vgamepad_lock:
            gamepad.left_joystick(x_value=stick_x, y_value=stick_y)
            gamepad.update()

        time.sleep(0.002)  # ~500 Hz


# ==========================================
# 5. INTERCEPTION HOOK
# ==========================================

def run_interception():
    """
    Blocks real keyboard/mouse input, translates it to virtual gamepad events,
    and optionally passes it through when override mode is active (Left Alt).
    """
    global override_active, mouse_target_x, mouse_target_y, last_mouse_time

    c = interception()
    c.set_filter(
        interception.is_keyboard,
        interception_filter_key_state.INTERCEPTION_FILTER_KEY_ALL.value
    )
    c.set_filter(
        interception.is_mouse,
        interception_filter_mouse_state.INTERCEPTION_FILTER_MOUSE_ALL.value
    )

    print("Mapper is running.")
    print("  Hold LEFT ALT  → pass inputs through normally (override mode).")
    print("  Release LEFT ALT → resume gamepad translation.")
    print("  Close this window to exit.\n")

    while True:
        device = c.wait()
        stroke = c.receive(device)
        swallow = False

        # ── KEYBOARD ────────────────────────────────────────────────────────
        if interception.is_keyboard(device) and isinstance(stroke, key_stroke):
            sc = stroke.code   # Hardware scan code
            st = stroke.state  # KEY_DOWN / KEY_UP / KEY_E0_DOWN / KEY_E0_UP

            # Left Alt (scan code 0x38) toggles override mode
            if sc == 0x38:
                if st in (KEY_DOWN, KEY_E0_DOWN):
                    override_active = True
                    print("[Override ON]  — keyboard & mouse pass through.")
                elif st in (KEY_UP, KEY_E0_UP):
                    override_active = False
                    print("[Override OFF] — translating to gamepad.")

            if not override_active and sc in KEY_PROFILE:
                swallow = True
                btn = KEY_PROFILE[sc]
                if st in (KEY_DOWN, KEY_E0_DOWN):
                    with _vgamepad_lock:
                        gamepad.press_button(button=btn)
                elif st in (KEY_UP, KEY_E0_UP):
                    with _vgamepad_lock:
                        gamepad.release_button(button=btn)
                # gamepad.update() is handled by controller_loop gracefully.

        # ── MOUSE ────────────────────────────────────────────────────────────
        elif interception.is_mouse(device) and isinstance(stroke, mouse_stroke):
            if not override_active:
                swallow = True  # Freeze the real system cursor
                is_relative_move = not (stroke.flags & MOUSE_MOVE_ABSOLUTE)

                if is_relative_move and (stroke.x != 0 or stroke.y != 0):
                    tx, ty = calculate_joystick(stroke.x, stroke.y)
                    with _state_lock:
                        mouse_target_x = tx
                        mouse_target_y = ty
                        last_mouse_time = time.perf_counter()

        # Pass the stroke back to Windows only when we did NOT swallow it
        if not swallow:
            c.send(device, stroke)


# ==========================================
# 6. ENTRY POINT
# ==========================================

if __name__ == "__main__":
    # Start the gamepad smoothing/update thread (daemon → exits with main)
    t = threading.Thread(target=controller_loop, daemon=True)
    t.start()

    # Block in the interception loop (this is the main thread)
    run_interception()
