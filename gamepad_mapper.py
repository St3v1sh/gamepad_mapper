"""
Mouse/Keyboard to Xbox 360 Controller Mapper

Requires:
  1. ViGEmBus Driver: https://github.com/ViGEm/ViGEmBus/releases (Must be installed)
  2. The Interception driver: https://github.com/oblitum/Interception (Requires Reboot)
  3. pip install vgamepad
  4. pip install interception-python
  5. pip install pywin32 (dependency of interception-python)

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
from interception import Interception
from interception.strokes import KeyStroke, MouseStroke
from interception.constants import KeyFlag, FilterKeyFlag, FilterMouseButtonFlag

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
    "movement_smoothing": 0.2,

    # Snaps stick to zero if no movement occurs within this window (ms).
    "noise_filter_ms": 15.0,

    # Delay between sequential buttons in a combo macro
    "combo_delay_ms": 35.0,

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

# Grouped DOWN and UP hex flags for each mouse button
MOUSE_BUTTON_FLAGS = {
    "LEFT": (0x001, 0x002),
    "RIGHT": (0x004, 0x008),
    "MIDDLE": (0x010, 0x020),
    "X1": (0x040, 0x080),
    "X2": (0x100, 0x200),
}

_state_lock = threading.Lock()
_vgamepad_lock = threading.Lock()

override_active = False
accumulated_dx = 0.0
accumulated_dy = 0.0
last_mouse_time = time.perf_counter()
active_keys = set()

gamepad = None
for i in range(5):
    try:
        gamepad = vg.VX360Gamepad()
        print("Virtual Xbox 360 Controller connected to ViGEmBus.")
        break
    except Exception as e:
        print(f"Connection attempt {i+1} failed: {e}. Retrying...")
        time.sleep(1.0)

if not gamepad:
    print("Error: Could not connect to ViGEmBus after multiple attempts.")
    exit(1)

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


def _normalize_hex_keys(d: dict):
    norm = {}
    for k, v in d.items():
        try:
            norm[f"0x{int(k, 16):02X}"] = v
        except ValueError:
            norm[k] = v
    return norm


key_profile = _normalize_hex_keys(current_profile.get("key_profile", {}))
combo_cfg = _normalize_hex_keys(current_profile.get("combos", {}))
mouse_cfg = current_profile.get("mouse_buttons", {})
move_cfg = current_profile.get("movement", {})

print(f"Loaded profile: {profile_name}")


def _format_hex(v):
    try:
        return f"0x{int(v, 16):02X}"
    except:
        return "0xFFFF"


# Map string keys to string hexes to perfectly match sc_hex values
MOVE_KEYS_MAP = {k: _format_hex(move_cfg.get(k, "0xFFFF")) for k in "WASD"}
MOVE_HEX_SET = set(MOVE_KEYS_MAP.values())

_last_button_states = {}

# Locks to prevent double-execution, and events to track key releases
_combo_locks = {k: threading.Lock() for k in combo_cfg.keys()}
_combo_events = {k: threading.Event() for k in combo_cfg.keys()}


def apply_action(action: str, is_down: bool, do_update: bool = True):
    global _last_button_states
    if _last_button_states.get(action) == is_down:
        return  # Skip if state hasn't changed

    _last_button_states[action] = is_down
    with _vgamepad_lock:
        if action in BTN_MAP:
            btn = BTN_MAP[action]
            gamepad.press_button(
                button=btn) if is_down else gamepad.release_button(button=btn)
        elif action == "RIGHT_TRIGGER":
            gamepad.right_trigger(value=255 if is_down else 0)
        elif action == "LEFT_TRIGGER":
            gamepad.left_trigger(value=255 if is_down else 0)

        # Allow skipping immediate updates for stacked packets (like mouse events)
        if do_update:
            gamepad.update()


def execute_combo_sequence(sc_hex: str, actions: list):
    """
    Executes a sequence of button presses on key down, waits for the key
    to be released, and then releases the combo buttons.
    """
    # Prevent overlapping runs if key is mashed
    if not _combo_locks[sc_hex].acquire(blocking=False):
        return

    try:
        delay_sec = SETTINGS["combo_delay_ms"] / 1000.0

        # 1. Press all buttons in order with a delay
        for action in actions:
            apply_action(action, True, do_update=True)
            if delay_sec > 0:
                time.sleep(delay_sec)

        # 2. Wait indefinitely until the physical key is released
        _combo_events[sc_hex].wait()

        # 3. Release all buttons in reverse order immediately (without delay)
        for action in reversed(actions):
            apply_action(action, False, do_update=True)
    finally:
        _combo_locks[sc_hex].release()


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
    deadzone = SETTINGS["game_deadzone"]
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

            # Use the global mapping against the active_keys strings
            w_pressed = MOVE_KEYS_MAP.get('W') in active_keys
            a_pressed = MOVE_KEYS_MAP.get('A') in active_keys
            s_pressed = MOVE_KEYS_MAP.get('S') in active_keys
            d_pressed = MOVE_KEYS_MAP.get('D') in active_keys

        # --- Right Stick (Mouse) Logic ---
        inst_vel_x = raw_dx / dt if dt > 0 else 0
        inst_vel_y = raw_dy / dt if dt > 0 else 0

        noise_filter_sec = SETTINGS["noise_filter_ms"] / 1000.0
        if idle_secs > noise_filter_sec:
            inst_vel_x = inst_vel_y = 0.0

        smooth_val = SETTINGS["input_smoothing"]
        alpha = 1.0 - math.pow(smooth_val, dt * 1000.0)
        smoothed_vel_x += alpha * (inst_vel_x - smoothed_vel_x)
        smoothed_vel_y += alpha * (inst_vel_y - smoothed_vel_y)

        goal_x, goal_y = calculate_joystick_advanced(
            smoothed_vel_x, smoothed_vel_y)

        out_smooth = SETTINGS["output_smoothing"]
        out_alpha = 1.0 - math.pow(out_smooth, dt * 1000.0)
        current_stick_x += out_alpha * (goal_x - current_stick_x)
        current_stick_y += out_alpha * (goal_y - current_stick_y)

        # Clamp to bounds immediately to stop "momentum ballooning" during fast flicks
        current_stick_x = max(-32768.0, min(32767.0, current_stick_x))
        current_stick_y = max(-32768.0, min(32767.0, current_stick_y))

        exact_x, exact_y = current_stick_x + remainder_x, current_stick_y + remainder_y
        final_x = int(max(-32768, min(32767, exact_x)))
        final_y = int(max(-32768, min(32767, exact_y)))
        remainder_x, remainder_y = exact_x - final_x, exact_y - final_y

        # --- Left Stick (Movement) Logic ---
        target_ls_x = target_ls_y = 0.0
        if w_pressed:
            target_ls_y += 1.0
        if s_pressed:
            target_ls_y -= 1.0
        if a_pressed:
            target_ls_x -= 1.0
        if d_pressed:
            target_ls_x += 1.0

        # Normalize the diagonal movement to a perfect circle
        mag = math.sqrt(target_ls_x**2 + target_ls_y**2)
        if mag > 1.0:
            target_ls_x /= mag
            target_ls_y /= mag

        # Simulate thumbstick analog roll (solves menu pixel skipping)
        move_smooth = SETTINGS["movement_smoothing"]
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

    c = Interception()
    c.set_filter(Interception.is_keyboard, FilterKeyFlag.FILTER_KEY_ALL)
    c.set_filter(Interception.is_mouse, FilterMouseButtonFlag.FILTER_MOUSE_ALL)

    _key_states = {}

    print("Interception started. Press Right Alt or F12 to toggle bypass mode.")

    while True:
        device = c.await_input()
        if device is None:
            continue

        stroke = c.devices[device].receive()
        swallow = False

        if Interception.is_keyboard(device) and isinstance(stroke, KeyStroke):
            sc, st = stroke.code, stroke.flags  # 'state' is now 'flags'

            is_e0 = bool(st & KeyFlag.KEY_E0)
            sc_hex = f"0x{'E0' if is_e0 else ''}{sc:02X}"

            is_down = not bool(st & KeyFlag.KEY_UP)

            # RALT (0xE038) or F12 (0x58) Toggle Bypass
            if sc_hex in ("0xE038", "0x58"):
                if is_down and not _key_states.get(sc_hex, False):
                    override_active = not override_active
                    print(f"Bypass Mode: {'ON' if override_active else 'OFF'}")
                    if override_active:
                        with _state_lock:
                            active_keys.clear()
                        # Safety: Wake up and release any combos waiting for a key release
                        for ev in _combo_events.values():
                            ev.set()

                _key_states[sc_hex] = is_down
                swallow = True

            elif not override_active:
                # Check if this state is actually a change to prevent auto-repeat spam
                is_change = _key_states.get(sc_hex) != is_down
                _key_states[sc_hex] = is_down

                if sc_hex in combo_cfg:
                    swallow = True
                    if is_change:
                        if is_down:
                            _combo_events[sc_hex].clear()
                            threading.Thread(
                                target=execute_combo_sequence,
                                args=(sc_hex, combo_cfg[sc_hex]),
                                daemon=True
                            ).start()
                        else:
                            # User released the key; trigger the thread to continue and release the sequence
                            _combo_events[sc_hex].set()

                elif sc_hex in key_profile:
                    swallow = True
                    apply_action(key_profile[sc_hex], is_down, do_update=True)

                # Use the pre-calculated MOVE_HEX_SET for speed
                elif sc_hex in MOVE_HEX_SET:
                    swallow = True
                    with _state_lock:
                        if is_down:
                            active_keys.add(sc_hex)
                        else:
                            active_keys.discard(sc_hex)

        elif Interception.is_mouse(device) and isinstance(stroke, MouseStroke):
            if not override_active:
                swallow = True
                mouse_changed = False

                for name, (down_flag, up_flag) in MOUSE_BUTTON_FLAGS.items():
                    if name in mouse_cfg:
                        if stroke.button_flags & down_flag:
                            apply_action(
                                mouse_cfg[name], True, do_update=False)
                            mouse_changed = True
                        elif stroke.button_flags & up_flag:
                            apply_action(
                                mouse_cfg[name], False, do_update=False)
                            mouse_changed = True

                if mouse_changed:
                    with _vgamepad_lock:
                        gamepad.update()

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
