import time
import vgamepad as vg
from interception import Interception
from interception.strokes import KeyStroke, MouseStroke
from interception.constants import KeyFlag, FilterKeyFlag, FilterMouseButtonFlag
from interfaces import VirtualGamepad, InputCapture

WIN_BTN_MAP = {
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

MOUSE_BUTTON_FLAGS = {
    "LEFT": (0x001, 0x002),
    "RIGHT": (0x004, 0x008),
    "MIDDLE": (0x010, 0x020),
    "X1": (0x040, 0x080),
    "X2": (0x100, 0x200),
}

class WindowsGamepad(VirtualGamepad):
    def __init__(self):
        self.gamepad = None
        for i in range(5):
            try:
                self.gamepad = vg.VX360Gamepad()
                print("Virtual Xbox 360 Controller connected to ViGEmBus.")
                break
            except Exception as e:
                print(f"Connection attempt {i+1} failed: {e}. Retrying...")
                time.sleep(1.0)

        if not self.gamepad:
            print("Error: Could not connect to ViGEmBus after multiple attempts.")
            exit(1)

    def press_button(self, action: str, is_down: bool):
        if action in WIN_BTN_MAP:
            btn = WIN_BTN_MAP[action]
            if is_down:
                self.gamepad.press_button(button=btn)
            else:
                self.gamepad.release_button(button=btn)

    def set_trigger(self, action: str, value: int):
        if action == "LEFT_TRIGGER":
            self.gamepad.left_trigger(value=value)
        elif action == "RIGHT_TRIGGER":
            self.gamepad.right_trigger(value=value)

    def set_left_joystick(self, x: int, y: int):
        self.gamepad.left_joystick(x_value=x, y_value=y)

    def set_right_joystick(self, x: int, y: int):
        self.gamepad.right_joystick(x_value=x, y_value=y)

    def update(self):
        self.gamepad.update()


class WindowsInput(InputCapture):
    def start(self, on_key, on_mouse_btn, on_mouse_move):
        c = Interception()
        c.set_filter(Interception.is_keyboard, FilterKeyFlag.FILTER_KEY_ALL)
        c.set_filter(Interception.is_mouse, FilterMouseButtonFlag.FILTER_MOUSE_ALL)

        while True:
            device = c.await_input()
            if device is None:
                continue

            stroke = c.devices[device].receive()
            swallow = False

            if Interception.is_keyboard(device) and isinstance(stroke, KeyStroke):
                is_e0 = bool(stroke.flags & KeyFlag.KEY_E0)
                sc_hex = f"0x{'E0' if is_e0 else ''}{stroke.code:02X}"
                is_down = not bool(stroke.flags & KeyFlag.KEY_UP)

                swallow = on_key(sc_hex, is_down)

            elif Interception.is_mouse(device) and isinstance(stroke, MouseStroke):
                mouse_handled = False
                for btn_name, (down_flag, up_flag) in MOUSE_BUTTON_FLAGS.items():
                    if stroke.button_flags & down_flag:
                        if on_mouse_btn(btn_name, True):
                            swallow = True
                            mouse_handled = True
                    elif stroke.button_flags & up_flag:
                        if on_mouse_btn(btn_name, False):
                            swallow = True
                            mouse_handled = True

                if not mouse_handled and not (stroke.flags & 0x001) and (stroke.x != 0 or stroke.y != 0):
                    if on_mouse_move(stroke.x, stroke.y):
                        swallow = True

            if not swallow:
                c.send(device, stroke)
