from abc import ABC, abstractmethod
from typing import Callable

class VirtualGamepad(ABC):
    @abstractmethod
    def press_button(self, action: str, is_down: bool):
        """Press or release a mapped gamepad button."""
        pass

    @abstractmethod
    def set_trigger(self, action: str, value: int):
        """Set a trigger axis (0 to 255). Action should be 'LEFT_TRIGGER' or 'RIGHT_TRIGGER'."""
        pass

    @abstractmethod
    def set_left_joystick(self, x: int, y: int):
        """Set left joystick axes. Range: -32768 to 32767."""
        pass

    @abstractmethod
    def set_right_joystick(self, x: int, y: int):
        """Set right joystick axes. Range: -32768 to 32767."""
        pass

    @abstractmethod
    def update(self):
        """Flush the state out to the virtual device."""
        pass

class InputCapture(ABC):
    @abstractmethod
    def start(self,
              on_key: Callable[[str, bool], bool],
              on_mouse_btn: Callable[[str, bool], bool],
              on_mouse_move: Callable[[int, int], bool]):
        """
        Begins capturing input and blocking it from the OS.
        Callbacks should return True to swallow the event, False to pass it through.
        - on_key(sc_hex: str, is_down: bool)
        - on_mouse_btn(btn_name: str, is_down: bool)
        - on_mouse_move(dx: int, dy: int)
        """
        pass
