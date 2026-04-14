"""
Mouse/Keyboard → Xbox 360 Controller Mapper
============================================
Requires:
  1. pip install vgamepad
  2. The Interception driver: https://github.com/oblitum/Interception
  3. Download `interception.py`, `consts.py`, and `stroke.py` from
     https://github.com/cobrce/interception_py and place in this directory.

Run as Administrator.

Usage: python gamepad_mapper.py --profile warframe
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
# 1. DEFAULT FALLBACK SETTINGS
# ==========================================

DEFAULT_SETTINGS = {
    "min_output_base": 100,
    "min_output_max": 5000,
    "transition_speed": 6000,
    "input_smoothing": 0.4,
    "output_smoothing": 3,
    "curve_exponent": 1.005,
    "sens_x": 600,
    "sens_y": 600,
}

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
# 2. SHARED STATE & PROFILE LOADING
# ==========================================

_state_lock = threading.Lock()
_vgamepad_lock = threading.Lock()

override_active = False
target_vel_x = 0.0
target_vel_y = 0.0
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

# Get selected profile or fallback to default
profile_name = args.profile.lower()
current_profile = PROFILES.get(profile_name, PROFILES.get("default", {}))

# Load settings from profile and merge with hardcoded defaults
SETTINGS = DEFAULT_SETTINGS.copy()
SETTINGS.update(current_profile.get("settings", {}))

# Load mapping configs
key_profile = current_profile.get("key_profile", {})
combo_cfg = current_profile.get("combos", {})
mouse_cfg = current_profile.get("mouse_buttons", {})
move_cfg = current_profile.get("movement", {})

print(f"Loaded profile: {profile_name}")
print(f"Sensitivity: X:{SETTINGS['sens_x']} Y:{SETTINGS['sens_y']}")

# ==========================================
# 3. CORE LOGIC
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


def calculate_joystick_natural(vx: float, vy: float):
    # 1. Sensitivity
    sx = (vx * (SETTINGS["sens_x"] / 5000.0) * 32768)
    sy = (-vy * (SETTINGS["sens_y"] / 5000.0) * 32768)

    magnitude = math.sqrt(sx**2 + sy**2)
    if magnitude < 0.001:
        return 0.0, 0.0

    dir_x, dir_y = sx / magnitude, sy / magnitude

    # 2. Natural Curve (Power function)
    normalized_mag = min(1.0, magnitude / 32768.0)
    curved_mag = math.pow(normalized_mag, SETTINGS["curve_exponent"]) * 32768

    # 3. Dynamic Floor (Lerp between base and max output)
    speed_factor = min(1.0, curved_mag / SETTINGS["transition_speed"])
    min_floor = SETTINGS["min_output_base"] + \
        (SETTINGS["min_output_max"] -
         SETTINGS["min_output_base"]) * speed_factor

    mapped_mag = min_floor + (curved_mag * ((32768 - min_floor) / 32768.0))
    return min(32768, mapped_mag) * dir_x, min(32768, mapped_mag) * dir_y

# ==========================================
# 4. CONTROLLER THREAD (~500 Hz)
# ==========================================


def controller_loop():
    global target_vel_x, target_vel_y
    current_stick_x = current_stick_y = 0.0
    alpha = 1.0 - (SETTINGS["output_smoothing"] / 10.0)
    move_keys = {k: int(move_cfg.get(k, "0x00"), 16) for k in "WASD"}

    while True:
        with _state_lock:
            vx, vy = target_vel_x, target_vel_y
            idle_secs = time.perf_counter() - last_mouse_time

        if idle_secs > 0.008:
            vx = vy = 0.0
            with _state_lock:
                target_vel_x = target_vel_y = 0.0

        goal_x, goal_y = calculate_joystick_natural(vx, vy)

        current_stick_x = (current_stick_x * (1.0 - alpha)) + (goal_x * alpha)
        current_stick_y = (current_stick_y * (1.0 - alpha)) + (goal_y * alpha)

        final_x = int(max(-32768, min(32767, current_stick_x)))
        final_y = int(max(-32768, min(32767, current_stick_y)))

        ls_y = ls_x = 0
        if move_keys['W'] in active_keys:
            ls_y += 32767
        if move_keys['S'] in active_keys:
            ls_y -= 32768
        if move_keys['A'] in active_keys:
            ls_x -= 32768
        if move_keys['D'] in active_keys:
            ls_x += 32767

        with _vgamepad_lock:
            gamepad.right_joystick(x_value=final_x, y_value=final_y)
            gamepad.left_joystick(x_value=ls_x, y_value=ls_y)
            gamepad.update()

        time.sleep(0.001)

# ==========================================
# 5. INTERCEPTION HOOK
# ==========================================


def run_interception():
    global override_active, target_vel_x, target_vel_y, last_mouse_time

    c = interception()
    c.set_filter(interception.is_keyboard, 0xFFFF)
    c.set_filter(interception.is_mouse, 0xFFFF)

    f_dx = f_dy = 0.0

    while True:
        device = c.wait()
        stroke = c.receive(device)
        swallow = False

        if interception.is_keyboard(device) and isinstance(stroke, key_stroke):
            sc, st = stroke.code, stroke.state

            if sc == 0x38:  # LALT Toggle
                if st in (KEY_DOWN, KEY_E0_DOWN):
                    override_active = True
                elif st in (KEY_UP, KEY_E0_UP):
                    override_active = False

            if not override_active:
                sc_hex = f"0x{sc:02X}"
                is_down = st in (KEY_DOWN, KEY_E0_DOWN)

                if sc_hex in combo_cfg:
                    swallow = True
                    for action in combo_cfg[sc_hex]:
                        apply_action(action, is_down)
                elif sc_hex in key_profile:
                    swallow = True
                    apply_action(key_profile[sc_hex], is_down)
                elif sc_hex in [move_cfg.get(k) for k in "WASD"]:
                    swallow = True
                    if is_down:
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
                    beta = 1.0 - SETTINGS["input_smoothing"]
                    f_dx = (f_dx * (1.0 - beta)) + (stroke.x * beta)
                    f_dy = (f_dy * (1.0 - beta)) + (stroke.y * beta)

                    with _state_lock:
                        target_vel_x, target_vel_y = f_dx, f_dy
                        last_mouse_time = time.perf_counter()

        if not swallow:
            c.send(device, stroke)


if __name__ == "__main__":
    t = threading.Thread(target=controller_loop, daemon=True)
    t.start()
    run_interception()
