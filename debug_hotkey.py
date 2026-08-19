"""One-off diagnostic for the F9-does-nothing issue on mac. Run with:

    venv/bin/python3 debug_hotkey.py

Prints Accessibility trust status, then listens for ANY key for 15
seconds -- press some letter keys, then try F9. Delete this file once
the real issue is found; it's not part of the shipped client.
"""

import sys
import time

try:
    from ApplicationServices import AXIsProcessTrustedWithOptions
    trusted = AXIsProcessTrustedWithOptions({})
    print(f"AXIsProcessTrustedWithOptions() -> {trusted}")
except ImportError as e:
    print(f"Could not import ApplicationServices: {e}")

from pynput import keyboard

try:
    from importlib.metadata import version
    print(f"pynput version: {version('pynput')}")
except Exception as e:
    print(f"Could not read pynput version: {e}")

seen = []


def on_press(key):
    seen.append(key)
    print(f"  pressed: {key!r}")


def on_release(key):
    print(f"  released: {key!r}")


print("\nListening for 15 seconds -- press some letter keys, then try F9...")
listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()

for remaining in range(15, 0, -1):
    sys.stdout.write(f"\r{remaining:2d}s remaining...")
    sys.stdout.flush()
    time.sleep(1)

listener.stop()
listener.join()

print(f"\n\nTotal keys captured: {len(seen)}")
if not seen:
    print("Nothing captured at all -- the global listener isn't receiving events.")
else:
    print(f"Captured: {seen}")
