"""Switch the macOS system output device on launch, restore it on quit.

Collapses the manual "System Settings -> Sound -> pick Multi-Output Device" step:
point system output at the Multi-Output Device (which fans out to BlackHole + speakers)
so capture works, then put the original device back when the app exits.

Uses the SwitchAudioSource CLI (`brew install switchaudio-osx`). If it is missing we
warn and no-op, so the app still runs (the user just routes audio manually as before).
"""

import shutil
import logging
import subprocess

from module.utility.mac_terminate import on_terminate

logger = logging.getLogger(__name__)

_BIN = "SwitchAudioSource"


def _run(args):
    return subprocess.run(
        [_BIN, *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def current_output():
    """Return the current default output device name, or None if unavailable."""
    if shutil.which(_BIN) is None:
        return None
    try:
        return _run(["-c", "-t", "output"])
    except (subprocess.CalledProcessError, OSError) as e:
        logger.warning("Could not read current output device: %s", e)
        return None


def restore_on_terminate(name):
    """Restore output to `name` when AppKit tears down via NSApp `terminate:`.

    See module.utility.mac_terminate for why atexit alone is not enough.
    """
    return on_terminate(lambda: set_output(name))


def set_output(name):
    """Set the default output device by name. Returns True on success."""
    if shutil.which(_BIN) is None:
        logger.warning(
            "SwitchAudioSource not found; skipping auto audio routing. "
            "Install it (`brew install switchaudio-osx`) or set output to '%s' manually.",
            name,
        )
        return False
    try:
        _run(["-s", name, "-t", "output"])
        logger.info("System output switched to '%s'", name)
        return True
    except (subprocess.CalledProcessError, OSError) as e:
        logger.warning(
            "Could not switch output to '%s' (does the device exist?): %s", name, e
        )
        return False


if __name__ == "__main__":
    # Self-check: reading current output should not raise, and setting a
    # nonexistent device must fail cleanly (return False), never throw.
    logging.basicConfig(level=logging.INFO)
    prev = current_output()
    print("current output:", prev)
    assert set_output("__no_such_device__") is False
    if prev:
        assert set_output(prev) is True  # round-trip back to where we started

    # Prove the terminate observer fires synchronously and calls set_output.
    try:
        from Foundation import NSNotificationCenter
        from AppKit import NSApplicationWillTerminateNotification
    except ImportError:
        print("self-check ok (AppKit absent; observer path skipped)")
    else:
        fired = []
        _real, set_output = set_output, lambda name: fired.append(name)
        try:
            restore_on_terminate("target-device")
            NSNotificationCenter.defaultCenter().postNotificationName_object_(
                NSApplicationWillTerminateNotification, None
            )
        finally:
            set_output = _real
        assert fired == ["target-device"], f"observer did not restore: {fired}"
        print("self-check ok (observer fires on terminate)")
