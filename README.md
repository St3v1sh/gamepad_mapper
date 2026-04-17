# Mouse/Keyboard to Xbox 360 Mapper

This project allows you to map mouse and keyboard inputs to a virtual Xbox 360 controller for **Windows and Linux**. It is designed for games that lack native keyboard support.

It uses smoothing, non-linear response curves, and macro "combos".

## Features

- **Cross-Platform:** Native low-latency support for Windows (via Interception/vgamepad) and Linux (via evdev/uinput).
- **Smoothing:** Separate input and output smoothing to eliminate mouse jitter.
- **Response Curves:** Adjustable exponent curves for fine-grained control or flick-heavy movement.
- **Movement Emulation:** WASD inputs are converted into analog stick values with configurable smoothing to prevent menu skipping.
- **Combo Macros:** Map a single key to a sequence of controller inputs.
- **Profile System:** Easily swap between different game settings using a JSON configuration.
- **Bypass Mode:** Press **Right Alt** or **F12** to toggle the mapping on/off so you can use your PC normally without closing the script.

## Windows Prerequisites

1.  **ViGEmBus Driver:** [Download & Install](https://github.com/ViGEm/ViGEmBus/releases). This creates the virtual Xbox controller.
2.  **Interception Driver:**[Download & Install](https://github.com/oblitum/Interception/releases/latest).
3.  **Dependencies:**
    ```bash
    pip install vgamepad interception-python pywin32
    ```

## Linux Prerequisites

1.  **Dependencies:**
    ```bash
    pip install evdev
    ```
2.  **Permissions:** The script must be run as root (`sudo`) to interact with kernel-level input devices, or you must configure `udev` rules for `/dev/uinput` and `/dev/input/event*`.

## Usage

1.  Open a terminal (Command Prompt, PowerShell, or bash).
2.  Navigate to the project directory.
3.  Run the mapper:

    ```bash
    # Run with the default profile
    python main.py

    # Run with a specific profile from profiles.json
    python main.py --profile warframe
    ```
