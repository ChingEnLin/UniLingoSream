""" Run a callback when AppKit tears down via NSApp `terminate:`.

The AppKit overlay's Quit menu calls `terminate:`, which exits at the C level and skips
Python's atexit handlers. Anything that must happen on that path registers here *as well
as* with atexit (atexit still covers the tk backend and Ctrl+C).

No-op when AppKit is unavailable (non-macOS / CI), where atexit already suffices.
"""

import logging

logger = logging.getLogger(__name__)

_observers = []  # keep observers alive for the process lifetime


def on_terminate(fn):
    """ Call `fn()` on NSApplicationWillTerminateNotification. Returns True if registered.

    queue=None runs the block synchronously on the posting thread, i.e. before exit().
    """
    try:
        from Foundation import NSNotificationCenter
        from AppKit import NSApplicationWillTerminateNotification
    except ImportError:
        return False
    _observers.append(
        NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            NSApplicationWillTerminateNotification, None, None, lambda note: fn()
        )
    )
    return True


if __name__ == "__main__":
    # Self-check: a registered callback must actually fire when the notification posts.
    try:
        from Foundation import NSNotificationCenter
        from AppKit import NSApplicationWillTerminateNotification
    except ImportError:
        assert on_terminate(lambda: None) is False, "must no-op without AppKit"
        print("mac_terminate self-check passed (AppKit absent; no-op path)")
    else:
        fired = []
        assert on_terminate(lambda: fired.append(1)) is True, "should register"
        NSNotificationCenter.defaultCenter().postNotificationName_object_(
            NSApplicationWillTerminateNotification, None
        )
        assert fired == [1], f"callback did not fire: {fired}"
        print("mac_terminate self-check passed")
