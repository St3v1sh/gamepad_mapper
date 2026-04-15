"""
Mouse/Keyboard to Xbox 360 Controller Mapper
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

DEFAULT_SETTINGS = {
    # The inner deadzone of the game.
    "game_deadzone": 7000,

    # Sensitivity normalization.
    "max_velocity": 20000.0,

    # Non-linear curve. 1.0 = linear. >1.0 = finer control for small movements but more resistance.
    "curve_exponent": 1.0,

    # Smoothing (0.0 to 0.99). High values reduce jitter but add latency.
    "input_smoothing": 0.5,
    "output_smoothing": 0.5,

    # Analog stick roll for WASD (0.0 to 0.99). High values allow micro-taps.
    "movement_smoothing": 0.9,

    # Snaps stick to zero if no movement occurs within this window (ms).
    "noise_filter_ms": 15.0,

    "sens_x": 100,
    "sens_y": 100,
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

_state_lock = threading.Lock()
_vgamepad_lock = threading.Lock()

override_active = False
accumulated_dx = 0.0
accumulated_dy = 0.0
last_mouse_time = time.perf_counter()
active_keys = set()

gamepad = vg.VX360Gamepad()

# Load profile and settings
parser = argparse.ArgumentParser()
parser.add_argument("--profile", default="default")
args = parser.parse_args()

PROFILES = {}
if os.path.exists("profiles.json"):
    with open("profiles.json", "r") as f:
        PROFILES = json.load(f)

profile_name = args.profile.lower()
current_profile = PROFILES.get(profile_name, PROFILES.get("default", {}))

SETTINGS = DEFAULT_SETTINGS.copy()
SETTINGS.update(current_profile.get("settings", {}))

key_profile = current_profile.get("key_profile", {})
combo_cfg = current_profile.get("combos", {})
mouse_cfg = current_profile.get("mouse_buttons", {})
move_cfg = current_profile.get("movement", {})

print(f"Loaded profile: {profile_name}")


def apply_action(action: str, is_down: bool):
    with _vgamepad_lock:
        if action in BTN_MAP:
            btn = BTN_MAP[action]
            gamepad.press_button(
                button=btn) if is_down else gamepad.release_button(button=btn)
        elif action == "RIGHT_TRIGGER":
            gamepad.right_trigger(value=255 if is_down else 0)
        elif action == "LEFT_TRIGGER":
            gamepad.left_trigger(value=255 if is_down else 0)


def calculate_joystick_advanced(vx: float, vy: float):
    """Translates velocity (mickeys/sec) into joystick deflection."""
    vx_sens = vx * (SETTINGS["sens_x"] / 100.0)
    vy_sens = vy * (SETTINGS["sens_y"] / 100.0)

    magnitude = math.sqrt(vx_sens**2 + vy_sens**2)
    if magnitude < 0.1:
        return 0.0, 0.0

    dir_x, dir_y = vx_sens / magnitude, vy_sens / magnitude
    norm_mag = min(1.0, magnitude / SETTINGS["max_velocity"])
    curved_mag = math.pow(norm_mag, SETTINGS["curve_exponent"])

    # Start scaling immediately after the game's deadzone for better accuracy
    deadzone = SETTINGS.get("game_deadzone", 7000)
    final_mag = deadzone + \
        (curved_mag * (32767.0 - deadzone)) if curved_mag > 0 else 0.0
    final_mag = min(32767.0, final_mag)

    return final_mag * dir_x, final_mag * dir_y


def controller_loop():
    global accumulated_dx, accumulated_dy
    smoothed_vel_x = smoothed_vel_y = 0.0
    current_stick_x = current_stick_y = 0.0
    remainder_x = remainder_y = 0.0  # Stores decimal loss from float->int conversion

    # Left stick tracking variables
    current_ls_x = current_ls_y = 0.0

    move_keys = {k: int(move_cfg.get(k, "0x00"), 16) for k in "WASD"}
    last_time = time.perf_counter()

    while True:
        current_time = time.perf_counter()
        dt = current_time - last_time

        # Match 1000Hz polling rate
        if dt < 0.001:
            time.sleep(0.0005)
            continue
        last_time = current_time

        with _state_lock:
            raw_dx, raw_dy = accumulated_dx, accumulated_dy
            accumulated_dx = accumulated_dy = 0.0
            idle_secs = current_time - last_mouse_time

        # --- Right Stick (Mouse) Logic ---
        inst_vel_x = raw_dx / dt if dt > 0 else 0
        inst_vel_y = raw_dy / dt if dt > 0 else 0

        noise_filter_sec = SETTINGS.get("noise_filter_ms", 15.0) / 1000.0
        if idle_secs > noise_filter_sec:
            inst_vel_x = inst_vel_y = 0.0

        smooth_val = SETTINGS.get("input_smoothing", 0.5)
        alpha = 1.0 - math.pow(smooth_val, dt * 1000.0)
        smoothed_vel_x += alpha * (inst_vel_x - smoothed_vel_x)
        smoothed_vel_y += alpha * (inst_vel_y - smoothed_vel_y)

        goal_x, goal_y = calculate_joystick_advanced(
            smoothed_vel_x, smoothed_vel_y)

        out_smooth = SETTINGS.get("output_smoothing", 0.5)
        out_alpha = 1.0 - math.pow(out_smooth, dt * 1000.0)
        current_stick_x += out_alpha * (goal_x - current_stick_x)
        current_stick_y += out_alpha * (goal_y - current_stick_y)

        exact_x, exact_y = current_stick_x + remainder_x, current_stick_y + remainder_y
        final_x = int(max(-32768, min(32767, exact_x)))
        final_y = int(max(-32768, min(32767, exact_y)))
        remainder_x, remainder_y = exact_x - final_x, exact_y - final_y

        # --- Left Stick (Movement) Logic ---
        target_ls_x = target_ls_y = 0.0
        if move_keys.get('W') in active_keys:
            target_ls_y += 1.0
        if move_keys.get('S') in active_keys:
            target_ls_y -= 1.0
        if move_keys.get('A') in active_keys:
            target_ls_x -= 1.0
        if move_keys.get('D') in active_keys:
            target_ls_x += 1.0

        # Normalize the diagonal movement to a perfect circle
        mag = math.sqrt(target_ls_x**2 + target_ls_y**2)
        if mag > 1.0:
            target_ls_x /= mag
            target_ls_y /= mag

        # Simulate thumbstick analog roll (solves menu pixel skipping)
        move_smooth = SETTINGS.get("movement_smoothing", 0.85)
        move_alpha = 1.0 - math.pow(move_smooth, dt * 1000.0)

        current_ls_x += move_alpha * (target_ls_x - current_ls_x)
        current_ls_y += move_alpha * (target_ls_y - current_ls_y)

        final_ls_x = int(current_ls_x * 32767)
        final_ls_y = int(current_ls_y * 32767)

        # Output to gamepad
        with _vgamepad_lock:
            # -final_y because mice and sticks use inverted Y mathematical signs
            gamepad.right_joystick(x_value=final_x, y_value=-final_y)
            gamepad.left_joystick(x_value=final_ls_x, y_value=final_ls_y)
            gamepad.update()


def run_interception():
    global override_active, accumulated_dx, accumulated_dy, last_mouse_time

    c = interception()
    c.set_filter(interception.is_keyboard, 0xFFFF)
    c.set_filter(interception.is_mouse, 0xFFFF)

    print("Interception started. Press LALT to toggle bypass mode.")

    while True:
        device = c.wait()
        stroke = c.receive(device)
        swallow = False

        if interception.is_keyboard(device) and isinstance(stroke, key_stroke):
            sc, st = stroke.code, stroke.state

            # LALT Toggle Bypass
            if sc == 0x38:
                if st in (KEY_DOWN, KEY_E0_DOWN):
                    override_active = not override_active
                    print(f"Bypass Mode: {'ON' if override_active else 'OFF'}")
                    if override_active:
                        active_keys.clear()

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
                    active_keys.add(sc) if is_down else active_keys.discard(sc)

        elif interception.is_mouse(device) and isinstance(stroke, mouse_stroke):
            if not override_active:
                swallow = True
                for name, (flag, is_down) in MOUSE_FLAGS.items():
                    if stroke.state & flag and name in mouse_cfg:
                        apply_action(mouse_cfg[name], is_down)

                if not (stroke.flags & 0x001) and (stroke.x != 0 or stroke.y != 0):
                    with _state_lock:
                        accumulated_dx += stroke.x
                        accumulated_dy += stroke.y
                        last_mouse_time = time.perf_counter()

        if not swallow:
            c.send(device, stroke)


if __name__ == "__main__":
    t = threading.Thread(target=controller_loop, daemon=True)
    t.start()
    run_interception()
