import os
import time
import select
import atexit
from evdev import UInput, ecodes, InputDevice, list_devices, AbsInfo
from interfaces import VirtualGamepad, InputCapture

HEX_TO_ECODE = {
    "0x01": ecodes.KEY_ESC, "0x02": ecodes.KEY_1, "0x03": ecodes.KEY_2, "0x04": ecodes.KEY_3,
    "0x05": ecodes.KEY_4, "0x06": ecodes.KEY_5, "0x07": ecodes.KEY_6, "0x08": ecodes.KEY_7,
    "0x09": ecodes.KEY_8, "0x0A": ecodes.KEY_9, "0x0B": ecodes.KEY_0, "0x0C": ecodes.KEY_MINUS,
    "0x0D": ecodes.KEY_EQUAL, "0x0E": ecodes.KEY_BACKSPACE, "0x0F": ecodes.KEY_TAB,
    "0x10": ecodes.KEY_Q, "0x11": ecodes.KEY_W, "0x12": ecodes.KEY_E, "0x13": ecodes.KEY_R,
    "0x14": ecodes.KEY_T, "0x15": ecodes.KEY_Y, "0x16": ecodes.KEY_U, "0x17": ecodes.KEY_I,
    "0x18": ecodes.KEY_O, "0x19": ecodes.KEY_P, "0x1A": ecodes.KEY_LEFTBRACE,
    "0x1B": ecodes.KEY_RIGHTBRACE, "0x1C": ecodes.KEY_ENTER, "0x1D": ecodes.KEY_LEFTCTRL,
    "0x1E": ecodes.KEY_A, "0x1F": ecodes.KEY_S, "0x20": ecodes.KEY_D, "0x21": ecodes.KEY_F,
    "0x22": ecodes.KEY_G, "0x23": ecodes.KEY_H, "0x24": ecodes.KEY_J, "0x25": ecodes.KEY_K,
    "0x26": ecodes.KEY_L, "0x27": ecodes.KEY_SEMICOLON, "0x28": ecodes.KEY_APOSTROPHE,
    "0x29": ecodes.KEY_GRAVE, "0x2A": ecodes.KEY_LEFTSHIFT, "0x2B": ecodes.KEY_BACKSLASH,
    "0x2C": ecodes.KEY_Z, "0x2D": ecodes.KEY_X, "0x2E": ecodes.KEY_C, "0x2F": ecodes.KEY_V,
    "0x30": ecodes.KEY_B, "0x31": ecodes.KEY_N, "0x32": ecodes.KEY_M, "0x33": ecodes.KEY_COMMA,
    "0x34": ecodes.KEY_DOT, "0x35": ecodes.KEY_SLASH, "0x36": ecodes.KEY_RIGHTSHIFT,
    "0x37": ecodes.KEY_KPASTERISK, "0x38": ecodes.KEY_LEFTALT, "0x39": ecodes.KEY_SPACE,
    "0x3A": ecodes.KEY_CAPSLOCK, "0x3B": ecodes.KEY_F1, "0x3C": ecodes.KEY_F2,
    "0x3D": ecodes.KEY_F3, "0x3E": ecodes.KEY_F4, "0x3F": ecodes.KEY_F5, "0x40": ecodes.KEY_F6,
    "0x41": ecodes.KEY_F7, "0x42": ecodes.KEY_F8, "0x43": ecodes.KEY_F9, "0x44": ecodes.KEY_F10,
    "0x45": ecodes.KEY_NUMLOCK, "0x46": ecodes.KEY_SCROLLLOCK, "0x47": ecodes.KEY_KP7,
    "0x48": ecodes.KEY_KP8, "0x49": ecodes.KEY_KP9, "0x4A": ecodes.KEY_KPMINUS,
    "0x4B": ecodes.KEY_KP4, "0x4C": ecodes.KEY_KP5, "0x4D": ecodes.KEY_KP6,
    "0x4E": ecodes.KEY_KPPLUS, "0x4F": ecodes.KEY_KP1, "0x50": ecodes.KEY_KP2,
    "0x51": ecodes.KEY_KP3, "0x52": ecodes.KEY_KP0, "0x53": ecodes.KEY_KPDOT,
    "0x57": ecodes.KEY_F11, "0x58": ecodes.KEY_F12,
    "0xE038": ecodes.KEY_RIGHTALT, "0xE01D": ecodes.KEY_RIGHTCTRL, "0xE01C": ecodes.KEY_KPENTER,
    "0xE048": ecodes.KEY_UP, "0xE050": ecodes.KEY_DOWN, "0xE04B": ecodes.KEY_LEFT,
    "0xE04D": ecodes.KEY_RIGHT, "0xE052": ecodes.KEY_INSERT, "0xE053": ecodes.KEY_DELETE,
    "0xE047": ecodes.KEY_HOME, "0xE04F": ecodes.KEY_END, "0xE049": ecodes.KEY_PAGEUP,
    "0xE051": ecodes.KEY_PAGEDOWN, "0xE035": ecodes.KEY_KPSLASH,
}
ECODE_TO_HEX = {v: k for k, v in HEX_TO_ECODE.items()}

MOUSE_BTN_TO_STR = {
    ecodes.BTN_LEFT: "LEFT", ecodes.BTN_RIGHT: "RIGHT",
    ecodes.BTN_MIDDLE: "MIDDLE", ecodes.BTN_SIDE: "X1", ecodes.BTN_EXTRA: "X2"
}

LINUX_BTN_MAP = {
    "XUSB_GAMEPAD_START": ecodes.BTN_START,
    "XUSB_GAMEPAD_BACK": ecodes.BTN_SELECT,
    "XUSB_GAMEPAD_LEFT_THUMB": ecodes.BTN_THUMBL,
    "XUSB_GAMEPAD_RIGHT_THUMB": ecodes.BTN_THUMBR,
    "XUSB_GAMEPAD_LEFT_SHOULDER": ecodes.BTN_TL,
    "XUSB_GAMEPAD_RIGHT_SHOULDER": ecodes.BTN_TR,
    "XUSB_GAMEPAD_A": ecodes.BTN_A,
    "XUSB_GAMEPAD_B": ecodes.BTN_B,
    "XUSB_GAMEPAD_X": ecodes.BTN_X,
    "XUSB_GAMEPAD_Y": ecodes.BTN_Y,
}

class LinuxGamepad(VirtualGamepad):
    def __init__(self):
        # Initializing axes with fuzz=0 and flat=0 is essential to prevent lag and "choppy" mouse movement
        capabilities = {
            ecodes.EV_KEY:[
                ecodes.BTN_A, ecodes.BTN_B, ecodes.BTN_X, ecodes.BTN_Y,
                ecodes.BTN_START, ecodes.BTN_SELECT, ecodes.BTN_MODE,
                ecodes.BTN_THUMBL, ecodes.BTN_THUMBR, ecodes.BTN_TL, ecodes.BTN_TR
            ],
            ecodes.EV_ABS:[
                (ecodes.ABS_X, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_Y, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_RX, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_RY, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_Z, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_RZ, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_HAT0X, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_HAT0Y, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
            ]
        }
        try:
            self.device = UInput(events=capabilities, name="Microsoft X-Box 360 pad", vendor=0x045e, product=0x028e, version=0x0110)
            # Force an initial sync and wait for the OS to register the new device node
            self.device.syn()
            time.sleep(0.5)
            print("Virtual Xbox 360 Controller connected via evdev/uinput.")
        except Exception as e:
            print(f"Error creating uinput device: {e}")
            exit(1)

        self.hat_x = 0
        self.hat_y = 0

    def press_button(self, action: str, is_down: bool):
        val = 1 if is_down else 0
        if action in LINUX_BTN_MAP:
            self.device.write(ecodes.EV_KEY, LINUX_BTN_MAP[action], val)
        elif action.startswith("XUSB_GAMEPAD_DPAD_"):
            if action == "XUSB_GAMEPAD_DPAD_UP":
                self.hat_y = -1 if is_down else 0
                self.device.write(ecodes.EV_ABS, ecodes.ABS_HAT0Y, self.hat_y)
            elif action == "XUSB_GAMEPAD_DPAD_DOWN":
                self.hat_y = 1 if is_down else 0
                self.device.write(ecodes.EV_ABS, ecodes.ABS_HAT0Y, self.hat_y)
            elif action == "XUSB_GAMEPAD_DPAD_LEFT":
                self.hat_x = -1 if is_down else 0
                self.device.write(ecodes.EV_ABS, ecodes.ABS_HAT0X, self.hat_x)
            elif action == "XUSB_GAMEPAD_DPAD_RIGHT":
                self.hat_x = 1 if is_down else 0
                self.device.write(ecodes.EV_ABS, ecodes.ABS_HAT0X, self.hat_x)

    def set_trigger(self, action: str, value: int):
        if action == "LEFT_TRIGGER":
            self.device.write(ecodes.EV_ABS, ecodes.ABS_Z, value)
        elif action == "RIGHT_TRIGGER":
            self.device.write(ecodes.EV_ABS, ecodes.ABS_RZ, value)

    def set_left_joystick(self, x: int, y: int):
        self.device.write(ecodes.EV_ABS, ecodes.ABS_X, x)
        self.device.write(ecodes.EV_ABS, ecodes.ABS_Y, -y) # Evdev standard: negative is UP

    def set_right_joystick(self, x: int, y: int):
        self.device.write(ecodes.EV_ABS, ecodes.ABS_RX, x)
        self.device.write(ecodes.EV_ABS, ecodes.ABS_RY, -y)

    def update(self):
        self.device.syn()


class LinuxInput(InputCapture):
    def __init__(self):
        self.grabbed_devices = []
        self.pt_device = None
        self.trackpad_states = {}

    def _is_target_device(self, dev):
        name = dev.name.lower()
        if "gamepad_mapper" in name or "x-box" in name:
            return False

        caps = dev.capabilities()
        has_keys = ecodes.EV_KEY in caps
        has_rel = ecodes.EV_REL in caps
        has_abs = ecodes.EV_ABS in caps

        if has_keys and (ecodes.BTN_GAMEPAD in caps[ecodes.EV_KEY] or ecodes.BTN_SOUTH in caps[ecodes.EV_KEY]):
            return False

        is_kb = has_keys and (ecodes.KEY_A in caps[ecodes.EV_KEY] or ecodes.KEY_SPACE in caps[ecodes.EV_KEY])
        is_mouse = has_rel and (ecodes.REL_X in caps[ecodes.EV_REL] or ecodes.REL_Y in caps[ecodes.EV_REL])

        is_trackpad = False
        if has_abs:
            abs_axes = [axis[0] for axis in caps[ecodes.EV_ABS]]
            # Catch Surface Trackpad via standard or MultiTouch position axes
            if ecodes.ABS_X in abs_axes or ecodes.ABS_MT_POSITION_X in abs_axes:
                is_trackpad = True

        return is_kb or is_mouse or is_trackpad

    def _cleanup(self):
        for dev in self.grabbed_devices:
            try:
                dev.ungrab()
            except:
                pass
        if self.pt_device:
            self.pt_device.close()

    def start(self, on_key, on_mouse_btn, on_mouse_move):
        atexit.register(self._cleanup)

        # Grab all physical keyboards and mice to block their input to the OS
        for path in list_devices():
            dev = InputDevice(path)
            if self._is_target_device(dev):
                try:
                    dev.grab()
                    self.grabbed_devices.append(dev)
                    print(f"Grabbed: [{dev.path}] {dev.name}")
                except Exception as e:
                    print(f"Failed to grab {dev.name}: {e}")

        if not self.grabbed_devices:
            print("No valid input devices found. Are you running as root?")
            exit(1)

        # Create a passthrough virtual device to route "bypassed" input back to the OS
        pt_caps = {
            ecodes.EV_KEY: set([ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE, ecodes.BTN_SIDE, ecodes.BTN_EXTRA, ecodes.BTN_TOUCH]),
            ecodes.EV_REL: set([ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL])
        }
        for dev in self.grabbed_devices:
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps:
                pt_caps[ecodes.EV_KEY].update(caps[ecodes.EV_KEY])

        pt_caps_list = {k: list(v) for k, v in pt_caps.items() if v}
        try:
            self.pt_device = UInput(events=pt_caps_list, name="gamepad_mapper_passthrough")
        except Exception as e:
            print(f"Error creating passthrough device: {e}")
            exit(1)

        print("Kernel-level evdev capture active. Press Right Alt or F12 to toggle.")

        while True:
            r, _, _ = select.select(self.grabbed_devices, [], [])
            for dev in r:
                for event in dev.read():
                    swallow = False

                    # Handle Buttons/Keys
                    if event.type == ecodes.EV_KEY and event.value in (0, 1):
                        is_down = event.value == 1

                        if event.code == ecodes.BTN_TOUCH:
                            if not is_down and dev.path in self.trackpad_states:
                                self.trackpad_states[dev.path] = {'x': None, 'y': None}
                            # Dummy call to check if mapping logic is bypassed
                            swallow = on_mouse_move(0, 0)
                        elif event.code in MOUSE_BTN_TO_STR:
                            swallow = on_mouse_btn(MOUSE_BTN_TO_STR[event.code], is_down)
                        elif event.code in ECODE_TO_HEX:
                            swallow = on_key(ECODE_TO_HEX[event.code], is_down)

                        if not swallow:
                            self.pt_device.write(ecodes.EV_KEY, event.code, event.value)

                    # Handle Relative Movement (Standard Mice)
                    elif event.type == ecodes.EV_REL:
                        if event.code == ecodes.REL_X:
                            swallow = on_mouse_move(event.value, 0)
                            if not swallow: self.pt_device.write(ecodes.EV_REL, ecodes.REL_X, event.value)
                        elif event.code == ecodes.REL_Y:
                            swallow = on_mouse_move(0, event.value)
                            if not swallow: self.pt_device.write(ecodes.EV_REL, ecodes.REL_Y, event.value)
                        elif event.code in (ecodes.REL_WHEEL, ecodes.REL_HWHEEL):
                            self.pt_device.write(ecodes.EV_REL, event.code, event.value)

                    # Handle Absolute Coordinates (Surface Trackpad)
                    elif event.type == ecodes.EV_ABS and event.code in (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_MT_POSITION_X, ecodes.ABS_MT_POSITION_Y):
                        if dev.path not in self.trackpad_states:
                            self.trackpad_states[dev.path] = {'x': None, 'y': None}

                        state = self.trackpad_states[dev.path]
                        dx, dy = 0, 0

                        # Unify MT and standard ABS axes
                        if event.code in (ecodes.ABS_X, ecodes.ABS_MT_POSITION_X):
                            if state['x'] is not None: dx = event.value - state['x']
                            state['x'] = event.value
                        elif event.code in (ecodes.ABS_Y, ecodes.ABS_MT_POSITION_Y):
                            if state['y'] is not None: dy = event.value - state['y']
                            state['y'] = event.value

                        # Ignore high-velocity jumps (finger lifts/re-places)
                        if abs(dx) > 500 or abs(dy) > 500:
                            dx, dy = 0, 0

                        if dx != 0 or dy != 0:
                            swallow = on_mouse_move(dx, dy)
                            if not swallow:
                                if dx != 0: self.pt_device.write(ecodes.EV_REL, ecodes.REL_X, dx)
                                if dy != 0: self.pt_device.write(ecodes.EV_REL, ecodes.REL_Y, dy)

                    # Ensure any written events are flushed
                    elif event.type == ecodes.EV_SYN:
                        self.pt_device.syn()
