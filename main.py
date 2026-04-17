import math
import time
import threading
import os
import sys
import json
import argparse

DEFAULT_SETTINGS = {
    "game_deadzone": 7000,
    "max_velocity": 20000.0,
    "curve_exponent": 1.0,
    "input_smoothing": 0.5,
    "output_smoothing": 0.5,
    "movement_smoothing": 0.2,
    "noise_filter_ms": 15.0,
    "combo_delay_ms": 35.0,
    "sens_x": 100,
    "sens_y": 100,
}

_state_lock = threading.Lock()
_vgamepad_lock = threading.Lock()

override_active = False
accumulated_dx = 0.0
accumulated_dy = 0.0
last_mouse_time = time.perf_counter()
active_keys = set()
_last_button_states = {}
_key_states = {}

if sys.platform == "win32":
    from io_windows import WindowsGamepad, WindowsInput
    gamepad = WindowsGamepad()
    input_capture = WindowsInput()
elif sys.platform.startswith("linux"):
    from io_linux import LinuxGamepad, LinuxInput
    gamepad = LinuxGamepad()
    input_capture = LinuxInput()
else:
    print(f"Unsupported OS: {sys.platform}")
    exit(1)

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

def _format_hex(v):
    try:
        return f"0x{int(v, 16):02X}"
    except:
        return "0xFFFF"

MOVE_KEYS_MAP = {k: _format_hex(move_cfg.get(k, "0xFFFF")) for k in "WASD"}
MOVE_HEX_SET = set(MOVE_KEYS_MAP.values())

_combo_locks = {k: threading.Lock() for k in combo_cfg.keys()}
_combo_events = {k: threading.Event() for k in combo_cfg.keys()}

print(f"Loaded profile: {profile_name}")

def apply_action(action: str, is_down: bool, do_update: bool = True):
    global _last_button_states
    if _last_button_states.get(action) == is_down:
        return

    _last_button_states[action] = is_down
    with _vgamepad_lock:
        if action in ("LEFT_TRIGGER", "RIGHT_TRIGGER"):
            gamepad.set_trigger(action, 255 if is_down else 0)
        else:
            gamepad.press_button(action, is_down)

        if do_update:
            gamepad.update()

def execute_combo_sequence(sc_hex: str, actions: list):
    if not _combo_locks[sc_hex].acquire(blocking=False):
        return

    try:
        delay_sec = SETTINGS["combo_delay_ms"] / 1000.0
        for action in actions:
            apply_action(action, True, do_update=True)
            if delay_sec > 0:
                time.sleep(delay_sec)

        _combo_events[sc_hex].wait()

        for action in reversed(actions):
            apply_action(action, False, do_update=True)
    finally:
        _combo_locks[sc_hex].release()

def calculate_joystick_advanced(vx: float, vy: float):
    vx_sens = vx * (SETTINGS["sens_x"] / 100.0)
    vy_sens = vy * (SETTINGS["sens_y"] / 100.0)

    magnitude = math.sqrt(vx_sens**2 + vy_sens**2)
    if magnitude < 0.1:
        return 0.0, 0.0

    dir_x, dir_y = vx_sens / magnitude, vy_sens / magnitude
    norm_mag = min(1.0, magnitude / SETTINGS["max_velocity"])
    curved_mag = math.pow(norm_mag, SETTINGS["curve_exponent"])

    deadzone = SETTINGS["game_deadzone"]
    final_mag = deadzone + (curved_mag * (32767.0 - deadzone)) if curved_mag > 0 else 0.0
    final_mag = min(32767.0, final_mag)

    return final_mag * dir_x, final_mag * dir_y

def controller_loop():
    global accumulated_dx, accumulated_dy
    smoothed_vel_x = smoothed_vel_y = 0.0
    current_stick_x = current_stick_y = 0.0
    remainder_x = remainder_y = 0.0
    current_ls_x = current_ls_y = 0.0
    last_time = time.perf_counter()

    while True:
        current_time = time.perf_counter()
        dt = current_time - last_time

        if dt < 0.001:
            time.sleep(0.0005)
            continue
        last_time = current_time

        with _state_lock:
            raw_dx, raw_dy = accumulated_dx, accumulated_dy
            accumulated_dx = accumulated_dy = 0.0
            idle_secs = current_time - last_mouse_time

            w_pressed = MOVE_KEYS_MAP.get('W') in active_keys
            a_pressed = MOVE_KEYS_MAP.get('A') in active_keys
            s_pressed = MOVE_KEYS_MAP.get('S') in active_keys
            d_pressed = MOVE_KEYS_MAP.get('D') in active_keys

        inst_vel_x = raw_dx / dt if dt > 0 else 0
        inst_vel_y = -raw_dy / dt if dt > 0 else 0

        noise_filter_sec = SETTINGS["noise_filter_ms"] / 1000.0
        if idle_secs > noise_filter_sec:
            inst_vel_x = inst_vel_y = 0.0

        smooth_val = SETTINGS["input_smoothing"]
        alpha = 1.0 - math.pow(smooth_val, dt * 1000.0)
        smoothed_vel_x += alpha * (inst_vel_x - smoothed_vel_x)
        smoothed_vel_y += alpha * (inst_vel_y - smoothed_vel_y)

        goal_x, goal_y = calculate_joystick_advanced(smoothed_vel_x, smoothed_vel_y)

        out_smooth = SETTINGS["output_smoothing"]
        out_alpha = 1.0 - math.pow(out_smooth, dt * 1000.0)
        current_stick_x += out_alpha * (goal_x - current_stick_x)
        current_stick_y += out_alpha * (goal_y - current_stick_y)

        current_stick_x = max(-32768.0, min(32767.0, current_stick_x))
        current_stick_y = max(-32768.0, min(32767.0, current_stick_y))

        exact_x, exact_y = current_stick_x + remainder_x, current_stick_y + remainder_y
        final_x = int(max(-32768, min(32767, exact_x)))
        final_y = int(max(-32768, min(32767, exact_y)))
        remainder_x, remainder_y = exact_x - final_x, exact_y - final_y

        target_ls_x = target_ls_y = 0.0
        if w_pressed: target_ls_y += 1.0
        if s_pressed: target_ls_y -= 1.0
        if a_pressed: target_ls_x -= 1.0
        if d_pressed: target_ls_x += 1.0

        mag = math.sqrt(target_ls_x**2 + target_ls_y**2)
        if mag > 1.0:
            target_ls_x /= mag
            target_ls_y /= mag

        move_smooth = SETTINGS["movement_smoothing"]
        move_alpha = 1.0 - math.pow(move_smooth, dt * 1000.0)

        current_ls_x += move_alpha * (target_ls_x - current_ls_x)
        current_ls_y += move_alpha * (target_ls_y - current_ls_y)

        final_ls_x = int(current_ls_x * 32767)
        final_ls_y = int(current_ls_y * 32767)

        with _vgamepad_lock:
            gamepad.set_right_joystick(final_x, final_y)
            gamepad.set_left_joystick(final_ls_x, final_ls_y)
            gamepad.update()

def on_key_event(sc_hex: str, is_down: bool) -> bool:
    global override_active, _key_states

    if sc_hex in ("0xE038", "0x58"):
        if is_down and not _key_states.get(sc_hex, False):
            override_active = not override_active
            print(f"Bypass Mode: {'ON' if override_active else 'OFF'}")
            if override_active:
                with _state_lock:
                    active_keys.clear()
                for ev in _combo_events.values():
                    ev.set()
        _key_states[sc_hex] = is_down
        return True

    if override_active:
        return False

    is_change = _key_states.get(sc_hex) != is_down
    _key_states[sc_hex] = is_down

    if sc_hex in combo_cfg:
        if is_change:
            if is_down:
                _combo_events[sc_hex].clear()
                threading.Thread(
                    target=execute_combo_sequence,
                    args=(sc_hex, combo_cfg[sc_hex]),
                    daemon=True
                ).start()
            else:
                _combo_events[sc_hex].set()
        return True

    elif sc_hex in key_profile:
        apply_action(key_profile[sc_hex], is_down, do_update=True)
        return True

    elif sc_hex in MOVE_HEX_SET:
        with _state_lock:
            if is_down:
                active_keys.add(sc_hex)
            else:
                active_keys.discard(sc_hex)
        return True

    return False

def on_mouse_btn_event(btn_name: str, is_down: bool) -> bool:
    if override_active:
        return False

    if btn_name in mouse_cfg:
        apply_action(mouse_cfg[btn_name], is_down, do_update=True)
        return True

    return False

def on_mouse_move_event(dx: int, dy: int) -> bool:
    global accumulated_dx, accumulated_dy, last_mouse_time
    if override_active:
        return False

    with _state_lock:
        accumulated_dx += dx
        accumulated_dy += dy
        last_mouse_time = time.perf_counter()
    return True

if __name__ == "__main__":
    t = threading.Thread(target=controller_loop, daemon=True)
    t.start()
    input_capture.start(on_key=on_key_event, on_mouse_btn=on_mouse_btn_event, on_mouse_move=on_mouse_move_event)
