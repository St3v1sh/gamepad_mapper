# Mouse/Keyboard to Xbox 360 Mapper

This project allows you to map mouse and keyboard inputs to a virtual Xbox 360 controller for **WINDOWS ONLY**. It is designed for games that lack native keyboard support.

It uses smoothing, non-linear response curves, and macro "combos".

## Features

- **Smoothing:** Separate input and output smoothing to eliminate mouse jitter.
- **Response Curves:** Adjustable exponent curves for fine-grained control or flick-heavy movement.
- **Movement Emulation:** WASD inputs are converted into analog stick values with configurable smoothing to prevent menu skipping.
- **Combo Macros:** Map a single key to a sequence of controller inputs (useful for complex game abilities).
- **Profile System:** Easily swap between different game settings using a JSON configuration.
- **Bypass Mode:** Press **Right Alt** or **F12** to toggle the mapping on/off so you can use your PC normally without closing the script.

## Prerequisites

1.  **ViGEmBus Driver:** [Download & Install](https://github.com/ViGEm/ViGEmBus/releases). This creates the virtual Xbox controller.
2.  **Interception Driver:** [Download & Install](https://github.com/oblitum/Interception/releases/latest).
3.  **Working in Python 3.11.5**
4.  **Dependencies:**
    ```bash
    pip install vgamepad
    pip install interception-python
    pip install pywin32
    ```

## Usage

1.  Open a terminal (Command Prompt or PowerShell) **as Administrator**.
2.  Navigate to the project directory.
3.  Run the mapper:

    ```bash
    # Run with the default profile
    python gamepad_mapper.py

    # Run with a specific profile from profiles.json
    python gamepad_mapper.py --profile warframe
    ```

## Configuration (`profiles.json`)

Each profile contains four sections:

- **`settings`**: Controls sensitivity, deadzones, smoothing, and curves.
- **`key_profile`**: Maps keyboard hex codes to Xbox buttons (e.g., `"0x12": "XUSB_GAMEPAD_X"`).
- **`mouse_buttons`**: Maps mouse clicks (LEFT, RIGHT, MIDDLE, X1) to triggers or buttons.
- **`combos`**: Defines a list of buttons to be pressed in sequence when a key is tapped.

---

## Keyboard Scan Code (Hex) Reference Chart

The Interception driver uses **Scan Code Set 1**. Below is a mapping of the most common keys to their hex values for use in `profiles.json`.

#### Main Keys

| Key           | Hex    | Key               | Hex    | Key             | Hex    |
| :------------ | :----- | :---------------- | :----- | :-------------- | :----- |
| **Esc**       | `0x01` | **A**             | `0x1E` | **F1**          | `0x3B` |
| **1**         | `0x02` | **S**             | `0x1F` | **F2**          | `0x3C` |
| **2**         | `0x03` | **D**             | `0x20` | **F3**          | `0x3D` |
| **3**         | `0x04` | **F**             | `0x21` | **F4**          | `0x3E` |
| **4**         | `0x05` | **G**             | `0x22` | **F5**          | `0x3F` |
| **5**         | `0x06` | **H**             | `0x23` | **F6**          | `0x40` |
| **6**         | `0x07` | **J**             | `0x24` | **F7**          | `0x41` |
| **7**         | `0x08` | **K**             | `0x25` | **F8**          | `0x42` |
| **8**         | `0x09` | **L**             | `0x26` | **F9**          | `0x43` |
| **9**         | `0x0A` | **;**             | `0x27` | **F10**         | `0x44` |
| **0**         | `0x0B` | **'**             | `0x28` | **F11**         | `0x57` |
| **-**         | `0x0C` | **` (Tilde)**     | `0x29` | **F12**         | `0x58` |
| **=**         | `0x0D` | **\ (Backslash)** | `0x2B` | **Left Shift**  | `0x2A` |
| **Backspace** | `0x0E` | **Z**             | `0x2C` | **Right Shift** | `0x36` |
| **Tab**       | `0x0F` | **X**             | `0x2D` | **Left Ctrl**   | `0x1D` |
| **Q**         | `0x10` | **C**             | `0x2E` | **Left Alt**    | `0x38` |
| **W**         | `0x11` | **V**             | `0x2F` | **Space**       | `0x39` |
| **E**         | `0x12` | **B**             | `0x30` | **Caps Lock**   | `0x3A` |
| **R**         | `0x13` | **N**             | `0x31` | **Num Lock**    | `0x45` |
| **T**         | `0x14` | **M**             | `0x32` | **Scroll Lock** | `0x46` |
| **Y**         | `0x15` | **,**             | `0x33` | **Enter**       | `0x1C` |
| **U**         | `0x16` | **.**             | `0x34` |                 |        |
| **I**         | `0x17` | **/**             | `0x35` |                 |        |
| **O**         | `0x18` |                   |        |                 |        |
| **P**         | `0x19` |                   |        |                 |        |
| **[**         | `0x1A` |                   |        |                 |        |
| **]**         | `0x1B` |                   |        |                 |        |

#### Extended Keys

| Key             | Hex      | Key            | Hex      |
| :-------------- | :------- | :------------- | :------- |
| **Right Alt**   | `0xE038` | **Insert**     | `0xE052` |
| **Right Ctrl**  | `0xE01D` | **Delete**     | `0xE053` |
| **Right Enter** | `0xE01C` | **Home**       | `0xE047` |
| **Up Arrow**    | `0xE048` | **End**        | `0xE04F` |
| **Down Arrow**  | `0xE050` | **Page Up**    | `0xE049` |
| **Left Arrow**  | `0xE04B` | **Page Down**  | `0xE051` |
| **Right Arrow** | `0xE04D` | **Divide (/)** | `0xE035` |

#### Numpad Keys

| Key          | Hex    | Key              | Hex    |
| :----------- | :----- | :--------------- | :----- |
| **Numpad 0** | `0x52` | **Numpad 6**     | `0x4D` |
| **Numpad 1** | `0x4F` | **Numpad 7**     | `0x47` |
| **Numpad 2** | `0x50` | **Numpad 8**     | `0x48` |
| **Numpad 3** | `0x51` | **Numpad 9**     | `0x49` |
| **Numpad 4** | `0x4B` | **Numpad Plus**  | `0x4E` |
| **Numpad 5** | `0x4C` | **Numpad Minus** | `0x4A` |
| **Numpad .** | `0x53` | **Numpad Star**  | `0x37` |

## Example Profile: Warframe Mobile

The example profile `warframe` is for the mobile app version of the game Warframe with my controller scheme.

<img width="1608" height="698" alt="image" src="https://github.com/user-attachments/assets/de1001e5-8329-4330-a3d2-a6569fab6aaa" />
