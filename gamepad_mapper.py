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
from interception import interception_filter_key_state, interception_filter_mouse_state

# ==========================================
# 1. SETTINGS & PROFILES
# ==========================================

SETTINGS = {
    "deadzone": 0,  # Minimum mapped deflection (out of 32768)
    "smoothing": 3,  # EMA smoothing strength, 0 (instant) to 9 (max)
    "noise_filter": 0,  # Ignore raw mouse deltas <= this value
    "sens_x": 600,  # Horizontal sensitivity (out of 5000 scale)
    "sens_y": 600,  # Vertical sensitivity
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

# Mouse bitflag translation
MOUSE_FLAGS = {
    "LEFT_DOWN": (0x001, True),
    "LEFT_UP": (0x002, False),
    "RIGHT_DOWN": (0x004, True),
    "RIGHT_UP": (0x008, False),
    "MIDDLE_DOWN": (0x010, True),
    "MIDDLE_UP": (0x020, False),
    "X1_DOWN": (0x040, True),
    "X1_UP": (0x080, False),
}

# Scan codes (from interception driver internals)
KEY_DOWN = 0x00
KEY_UP = 0x01
KEY_E0_DOWN = 0x02
KEY_E0_UP = 0x03
MOUSE_MOVE_ABSOLUTE = 0x001

# Default profiles created if profiles.json is missing
FALLBACK_PROFILES = {
    "warframe": {
        "key_profile": {
            "0x01": "XUSB_GAMEPAD_START",
            "0x06": "XUSB_GAMEPAD_DPAD_LEFT",
            "0x0F": "XUSB_GAMEPAD_RIGHT_THUMB",
            "0x10": "XUSB_GAMEPAD_DPAD_UP",
            "0x12": "XUSB_GAMEPAD_X",
            "0x1D": "XUSB_GAMEPAD_LEFT_THUMB",
            "0x21": "XUSB_GAMEPAD_B",
            "0x2A": "XUSB_GAMEPAD_LEFT_SHOULDER",
            "0x2C": "XUSB_GAMEPAD_DPAD_DOWN",
            "0x39": "XUSB_GAMEPAD_RIGHT_SHOULDER",
            "0x3B": "XUSB_GAMEPAD_BACK"
        },
        "combos": {
            "0x02": ["XUSB_GAMEPAD_DPAD_RIGHT", "XUSB_GAMEPAD_A"],
            "0x03": ["XUSB_GAMEPAD_DPAD_RIGHT", "XUSB_GAMEPAD_X"],
            "0x04": ["XUSB_GAMEPAD_DPAD_RIGHT", "XUSB_GAMEPAD_B"],
            "0x05": ["XUSB_GAMEPAD_DPAD_RIGHT", "XUSB_GAMEPAD_Y"]
        },
        "mouse_buttons": {
            "LEFT_DOWN": "RIGHT_TRIGGER", "LEFT_UP": "RIGHT_TRIGGER",
            "RIGHT_DOWN": "LEFT_TRIGGER", "RIGHT_UP": "LEFT_TRIGGER",
            "MIDDLE_DOWN": "XUSB_GAMEPAD_A", "MIDDLE_UP": "XUSB_GAMEPAD_A",
            "X1_DOWN": "XUSB_GAMEPAD_Y", "X1_UP": "XUSB_GAMEPAD_Y"
        },
        "movement": {"W": "0x11", "A": "0x1E", "S": "0x1F", "D": "0x20"}
    },
    "default": {
        "key_profile": {
            "0x11": "XUSB_GAMEPAD_DPAD_UP", "0x1F": "XUSB_GAMEPAD_DPAD_DOWN",
            "0x1E": "XUSB_GAMEPAD_DPAD_LEFT", "0x20": "XUSB_GAMEPAD_DPAD_RIGHT",
            "0x39": "XUSB_GAMEPAD_A", "0x2A": "XUSB_GAMEPAD_B", "0x13": "XUSB_GAMEPAD_X"
        },
        "combos": {}, "mouse_buttons": {}, "movement": {}
    }
}

# ==========================================
# 2. CLI PARSING & PROFILE LOADING
# ==========================================

parser = argparse.ArgumentParser(
    description="Gamepad Mapper with reWASD Profiles.")
parser.add_argument("--profile", default="default",
                    help="Select profile (e.g., 'warframe')")
args = parser.parse_args()

PROFILES = FALLBACK_PROFILES
if os.path.exists("profiles.json"):
    try:
        with open("profiles.json", "r") as f:
            PROFILES = json.load(f)
    except Exception as e:
        print(f"Error reading profiles.json: {e}. Using hardcoded fallbacks.")
else:
    # Auto-generate file if missing
    with open("profiles.json", "w") as f:
        json.dump(FALLBACK_PROFILES, f, indent=4)

active_pname = args.profile.lower()
if active_pname not in PROFILES:
    print(f"Profile '{active_pname}' not found. Defaulting to 'default'.")
    active_pname = "default"

current_profile = PROFILES[active_pname]
key_profile = current_profile.get("key_profile", {})
combo_cfg = current_profile.get("combos", {})
mouse_cfg = current_profile.get("mouse_buttons", {})
move_cfg = current_profile.get("movement", {})

print(f"Active Profile: {active_pname.upper()}")

# ==========================================
# 3. SHARED STATE
# ==========================================

_state_lock = threading.Lock()
_vgamepad_lock = threading.Lock()

override_active = False
mouse_target_x = 0.0
mouse_target_y = 0.0
last_mouse_time = time.perf_counter()
active_keys = set()

gamepad = vg.VX360Gamepad()

# ==========================================
# 4. MATH & ACTION HANDLERS
# ==========================================


def apply_action(action: str, is_down: bool):
    """Safely updates either buttons or trigger axes based on profile actions."""
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


def evaluate_curve(x: float, points: list) -> float:
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
    if abs(dx) <= SETTINGS["noise_filter"]:
        dx = 0
    if abs(dy) <= SETTINGS["noise_filter"]:
        dy = 0
    if dx == 0 and dy == 0:
        return 0.0, 0.0

    multiplier_x = (SETTINGS["sens_x"] / 5000.0) * 32768
    multiplier_y = (SETTINGS["sens_y"] / 5000.0) * 32768
    sx, sy = dx * multiplier_x, -dy * multiplier_y
    magnitude = math.sqrt(sx ** 2 + sy ** 2)
    if magnitude == 0:
        return 0.0, 0.0

    dir_x, dir_y = sx / magnitude, sy / magnitude
    mapped_mag = evaluate_curve(magnitude, CURVES[ACTIVE_CURVE])
    if mapped_mag > 0:
        dz = SETTINGS["deadzone"]
        mapped_mag = dz + mapped_mag * ((32768 - dz) / 32768.0)
    return mapped_mag * dir_x, mapped_mag * dir_y

# ==========================================
# 5. CONTROLLER THREAD  (~500 Hz)
# ==========================================


def controller_loop():
    global mouse_target_x, mouse_target_y
    current_x = current_y = 0.0
    alpha = 1.0 - (SETTINGS["smoothing"] / 10.0)

    # Convert hex codes to int for fast lookup
    w_key = int(move_cfg.get("W", "0x00"), 16)
    s_key = int(move_cfg.get("S", "0x00"), 16)
    a_key = int(move_cfg.get("A", "0x00"), 16)
    d_key = int(move_cfg.get("D", "0x00"), 16)

    while True:
        with _state_lock:
            target_x, target_y = mouse_target_x, mouse_target_y
            idle_secs = time.perf_counter() - last_mouse_time

        if idle_secs > 0.01:
            with _state_lock:
                mouse_target_x = mouse_target_y = 0.0
            target_x = target_y = 0.0

        # Right Stick smoothing (Mouse)
        current_x = current_x * (1.0 - alpha) + target_x * alpha
        current_y = current_y * (1.0 - alpha) + target_y * alpha
        stick_x = max(-32768, min(32767, int(current_x)))
        stick_y = max(-32768, min(32767, int(current_y)))

        # Left Stick mapping (Keyboard WASD)
        ls_y = ls_x = 0
        if w_key and w_key in active_keys:
            ls_y += 32767
        if s_key and s_key in active_keys:
            ls_y -= 32768
        if a_key and a_key in active_keys:
            ls_x -= 32768
        if d_key and d_key in active_keys:
            ls_x += 32767
        ls_y = max(-32768, min(32767, ls_y))
        ls_x = max(-32768, min(32767, ls_x))

        with _vgamepad_lock:
            gamepad.right_joystick(x_value=stick_x, y_value=stick_y)
            gamepad.left_joystick(x_value=ls_x, y_value=ls_y)
            gamepad.update()

        time.sleep(0.002)

# ==========================================
# 6. INTERCEPTION HOOK
# ==========================================


def run_interception():
    global override_active, mouse_target_x, mouse_target_y, last_mouse_time

    c = interception()
    c.set_filter(interception.is_keyboard,
                 interception_filter_key_state.INTERCEPTION_FILTER_KEY_ALL.value)
    c.set_filter(interception.is_mouse,
                 interception_filter_mouse_state.INTERCEPTION_FILTER_MOUSE_ALL.value)

    print("Mapper is running.")
    print("  Hold LALT (0x38)  → pass inputs through normally (override mode).")
    print("  Release LALT      → resume gamepad translation.")
    print("  Close this window to exit.\n")

    while True:
        device = c.wait()
        stroke = c.receive(device)
        swallow = False

        if interception.is_keyboard(device) and isinstance(stroke, key_stroke):
            sc = stroke.code
            st = stroke.state

            # Override/Bypass toggle key LALT (0x38)
            if sc == 0x38:
                if st in (KEY_DOWN, KEY_E0_DOWN):
                    override_active = True
                    print("[Override ON]  — keyboard & mouse pass through.")
                elif st in (KEY_UP, KEY_E0_UP):
                    override_active = False
                    print("[Override OFF] — translating to gamepad.")

            if not override_active:
                sc_hex = f"0x{sc:02X}"

                # Handling Combos (like ability macros)
                if sc_hex in combo_cfg:
                    swallow = True
                    for action in combo_cfg[sc_hex]:
                        apply_action(action, st in (KEY_DOWN, KEY_E0_DOWN))

                # Regular Key Mapping
                elif sc_hex in key_profile:
                    swallow = True
                    apply_action(key_profile[sc_hex],
                                 st in (KEY_DOWN, KEY_E0_DOWN))

                # Movement Key Mapping
                elif sc_hex in move_cfg.values():
                    swallow = True
                    if st in (KEY_DOWN, KEY_E0_DOWN):
                        active_keys.add(sc)
                    elif st in (KEY_UP, KEY_E0_UP):
                        active_keys.discard(sc)

        elif interception.is_mouse(device) and isinstance(stroke, mouse_stroke):
            if not override_active:
                swallow = True

                # Check bitflags for bound mouse buttons
                for name, (flag, is_down) in MOUSE_FLAGS.items():
                    if stroke.state & flag and name in mouse_cfg:
                        apply_action(mouse_cfg[name], is_down)

                # Mouse Movement
                is_relative_move = not (stroke.flags & MOUSE_MOVE_ABSOLUTE)
                if is_relative_move and (stroke.x != 0 or stroke.y != 0):
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
