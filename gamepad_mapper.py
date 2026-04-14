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

Profile Usage:
  Run with no arguments to use the "default" profile:
      python gamepad_mapper.py

  Pass the --profile flag to select your loaded reWASD profile:
      python gamepad_mapper.py --profile warframe
"""

import math
import time
import threading
import os
import json
import argparse
import vgamepad as vg
from interception import interception, key_stroke, mouse_stroke

# ==========================================
# 1. SETTINGS
# ==========================================

SETTINGS = {
    # The floor used for micro-movements (pixel-perfect aiming)
    "min_output_base": 10,

    # The floor used for fast movements (snappy turning)
    "min_output_max": 5000,

    # The magnitude (speed) at which we transition from base to max floor
    "transition_speed": 6000,

    # Lower smoothing (2-3) helps with fine-grain control
    "smoothing": 3,
    "sens_x": 600,           # Horizontal sensitivity
    "sens_y": 600,           # Vertical sensitivity
}

CURVES = {
    "Default": [(0, 0), (32768, 32768)],
    "Delay": [(0, 0), (9469,  8519),  (27784, 18677), (32768, 32768)],
    "Aggressive": [(0, 0), (9344,  8847),  (19311, 25886), (32768, 32768)],
    "Smooth": [(0, 0), (17941, 18350), (27908, 20316), (32768, 32768)],
    "Instant": [(0, 0), (8098,  8847),  (8099,  14090), (32768, 32768)],
}

ACTIVE_CURVE = "Default"

# Standard VGamepad button mappings lookup
BTN_MAP = {
    "XUSB_GAMEPAD_START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "XUSB_GAMEPAD_BACK": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    "XUSB_GAMEPAD_LEFT_THUMB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    "XUSB_GAMEPAD_RIGHT_THUMB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
    "XUSB_GAMEPAD_LEFT_SHOULDER": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "XUSB_GAMEPAD_RIGHT_SHOULDER": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "XUSB_GAMEPAD_A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "XUSB_GAMEPAD_B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "XUSB_GAMEPAD_X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "XUSB_GAMEPAD_Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "XUSB_GAMEPAD_DPAD_UP": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    "XUSB_GAMEPAD_DPAD_DOWN": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    "XUSB_GAMEPAD_DPAD_LEFT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    "XUSB_GAMEPAD_DPAD_RIGHT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
}

MOUSE_FLAGS = {
    "LEFT_DOWN": (0x001, True), "LEFT_UP": (0x002, False),
    "RIGHT_DOWN": (0x004, True), "RIGHT_UP": (0x008, False),
    "MIDDLE_DOWN": (0x010, True), "MIDDLE_UP": (0x020, False),
    "X1_DOWN": (0x040, True), "X1_UP": (0x080, False),
}

KEY_DOWN, KEY_UP, KEY_E0_DOWN, KEY_E0_UP = 0x00, 0x01, 0x02, 0x03

# ==========================================
# 2. SHARED STATE & PROFILE
# ==========================================

_state_lock = threading.Lock()
_vgamepad_lock = threading.Lock()

override_active = False
mouse_target_x = 0.0
mouse_target_y = 0.0
last_mouse_time = time.perf_counter()
active_keys = set()

gamepad = vg.VX360Gamepad()

parser = argparse.ArgumentParser()
parser.add_argument("--profile", default="default")
args = parser.parse_args()

PROFILES = {}
if os.path.exists("profiles.json"):
    with open("profiles.json", "r") as f:
        PROFILES = json.load(f)

current_profile = PROFILES.get(
    args.profile.lower(), PROFILES.get("default", {}))
key_profile = current_profile.get("key_profile", {})
combo_cfg = current_profile.get("combos", {})
mouse_cfg = current_profile.get("mouse_buttons", {})
move_cfg = current_profile.get("movement", {})

# ==========================================
# 3. DYNAMIC MATH
# ==========================================


def apply_action(action: str, is_down: bool):
    with _vgamepad_lock:
        if action in BTN_MAP:
            btn = BTN_MAP[action]
            if is_down:
                gamepad.press_button(button=btn)
            else:
                gamepad.release_button(button=btn)
        elif action == "RIGHT_TRIGGER":
            gamepad.right_trigger(value=255 if is_down else 0)
        elif action == "LEFT_TRIGGER":
            gamepad.left_trigger(value=255 if is_down else 0)


def calculate_joystick(dx: int, dy: int):
    # Base Sensitivity scaling
    multiplier_x = (SETTINGS["sens_x"] / 5000.0) * 32768
    multiplier_y = (SETTINGS["sens_y"] / 5000.0) * 32768
    sx, sy = dx * multiplier_x, -dy * multiplier_y

    magnitude = math.sqrt(sx ** 2 + sy ** 2)
    if magnitude == 0:
        return 0.0, 0.0

    dir_x, dir_y = sx / magnitude, sy / magnitude

    # Calculate how 'fast' the move is relative to our transition threshold
    speed_factor = min(1.0, magnitude / SETTINGS["transition_speed"])

    # Linear Interpolation (Lerp) between the micro floor and the macro floor
    min_floor = SETTINGS["min_output_base"] + \
        (SETTINGS["min_output_max"] -
         SETTINGS["min_output_base"]) * speed_factor

    # Shift the magnitude into the range [min_floor, 32768]
    # This prevents the "jump" and allows fine-grain adjustments at slow speeds
    mapped_mag = min_floor + (magnitude * ((32768 - min_floor) / 32768.0))

    return min(32768, mapped_mag) * dir_x, min(32768, mapped_mag) * dir_y

# ==========================================
# 4. CONTROLLER THREAD (~500 Hz)
# ==========================================


def controller_loop():
    global mouse_target_x, mouse_target_y
    current_x = current_y = 0.0
    alpha = 1.0 - (SETTINGS["smoothing"] / 10.0)

    w_key = int(move_cfg.get("W", "0x00"), 16)
    s_key = int(move_cfg.get("S", "0x00"), 16)
    a_key = int(move_cfg.get("A", "0x00"), 16)
    d_key = int(move_cfg.get("D", "0x00"), 16)

    while True:
        with _state_lock:
            target_x, target_y = mouse_target_x, mouse_target_y
            idle_secs = time.perf_counter() - last_mouse_time

        # Atomic decay to zero
        if idle_secs > 0.01:
            with _state_lock:
                mouse_target_x = mouse_target_y = 0.0
            target_x = target_y = 0.0

        current_x = current_x * (1.0 - alpha) + target_x * alpha
        current_y = current_y * (1.0 - alpha) + target_y * alpha

        stick_x = max(-32768, min(32767, int(current_x)))
        stick_y = max(-32768, min(32767, int(current_y)))

        # Left Stick (Movement)
        ls_y = ls_x = 0
        if w_key and w_key in active_keys:
            ls_y += 32767
        if s_key and s_key in active_keys:
            ls_y -= 32768
        if a_key and a_key in active_keys:
            ls_x -= 32768
        if d_key and d_key in active_keys:
            ls_x += 32767

        with _vgamepad_lock:
            gamepad.right_joystick(x_value=stick_x, y_value=stick_y)
            gamepad.left_joystick(x_value=ls_x, y_value=ls_y)
            gamepad.update()

        time.sleep(0.002)

# ==========================================
# 5. INTERCEPTION HOOK
# ==========================================


def run_interception():
    global override_active, mouse_target_x, mouse_target_y, last_mouse_time
    c = interception()
    c.set_filter(interception.is_keyboard, 0xFFFF)
    c.set_filter(interception.is_mouse, 0xFFFF)

    while True:
        device = c.wait()
        stroke = c.receive(device)
        swallow = False

        if interception.is_keyboard(device) and isinstance(stroke, key_stroke):
            sc, st = stroke.code, stroke.state
            if sc == 0x38:  # LALT Bypass
                if st in (KEY_DOWN, KEY_E0_DOWN):
                    override_active = True
                elif st in (KEY_UP, KEY_E0_UP):
                    override_active = False

            if not override_active:
                sc_hex = f"0x{sc:02X}"
                if sc_hex in combo_cfg:
                    swallow = True
                    for action in combo_cfg[sc_hex]:
                        apply_action(action, st in (KEY_DOWN, KEY_E0_DOWN))
                elif sc_hex in key_profile:
                    swallow = True
                    apply_action(key_profile[sc_hex],
                                 st in (KEY_DOWN, KEY_E0_DOWN))
                elif sc_hex in [move_cfg.get(k) for k in "WASD"]:
                    swallow = True
                    if st in (KEY_DOWN, KEY_E0_DOWN):
                        active_keys.add(sc)
                    else:
                        active_keys.discard(sc)

        elif interception.is_mouse(device) and isinstance(stroke, mouse_stroke):
            if not override_active:
                swallow = True
                for name, (flag, is_down) in MOUSE_FLAGS.items():
                    if stroke.state & flag and name in mouse_cfg:
                        apply_action(mouse_cfg[name], is_down)

                if not (stroke.flags & 0x001) and (stroke.x != 0 or stroke.y != 0):
                    tx, ty = calculate_joystick(stroke.x, stroke.y)
                    with _state_lock:
                        mouse_target_x, mouse_target_y = tx, ty
                        last_mouse_time = time.perf_counter()

        if not swallow:
            c.send(device, stroke)


if __name__ == "__main__":
    t = threading.Thread(target=controller_loop, daemon=True)
    t.start()
    run_interception()
