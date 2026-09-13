"""A wall-clock budget for the network work behind one request.

Every fetch path retries three times with a 120 second socket timeout, and
nothing bounds the total. A caller running a fleet of sites against an
unresponsive upstream does not get a failure it can see; it gets a job that
runs for days. This gives a request a deadline, and makes both retry loops
respect it.

The budget is ambient rather than an argument because ``fetch_year`` is a
published extension point -- ``sources.register`` lets anyone add a source --
and threading a parameter through it would break every third-party
implementation. A context variable reaches them without their cooperation,
and is inherited correctly by ``asyncio`` tasks while *not* leaking into
threads, which is what we want: the registry auto-updater runs on its own
thread and has no business inside a caller's request budget.
"""
import time
from contextlib import contextmanager
from contextvars import ContextVar

from ..exceptions import FetchDeadlineExceeded

_budget = ContextVar("eeweather_fetch_budget", default=None)


@contextmanager
def fetch_budget(seconds):
    """Bound the network work inside this block to ``seconds`` of wall clock.

    ``None`` means unbounded, which is the behaviour without a budget.
    """
    if seconds is None:
        yield
        return
    if seconds <= 0:
        raise ValueError(
            "A fetch budget must be a positive number of seconds,"
            " got {!r}.".format(seconds)
        )

    token = _budget.set((time.monotonic() + seconds, seconds))
    try:
        yield
    finally:
        _budget.reset(token)


def remaining():
    """Seconds left in the budget, or None when there is no budget.

    Never more than the budget itself. Without the clamp that is only
    *nearly* true: deadline - now is floating point, and where the clock
    reads the same value twice -- which it does on any platform whose
    monotonic counter is coarser than the gap between two calls, Windows
    among them -- the subtraction can round to a hair above the budget.
    Small enough not to matter to a timeout, large enough to break an
    invariant, so make it an invariant.
    """
    entry = _budget.get()
    if entry is None:
        return None

    deadline, seconds = entry

    return min(deadline - time.monotonic(), seconds)


def check(what):
    """Raise FetchDeadlineExceeded when the budget is spent.

    Called before starting network work, so a request that is already over
    budget fails immediately instead of opening one more socket.
    """
    entry = _budget.get()
    if entry is None:
        return
    if remaining() <= 0:
        raise FetchDeadlineExceeded(entry[1], what)


def timeout_for(default):
    """A socket timeout no longer than the budget can afford.

    Bounds each individual read, so the overshoot past a deadline is at most
    one timeout rather than tries x timeout. It cannot be exact: ``requests``
    applies a timeout per socket operation, not to a whole response, so a
    slow trickle of bytes can still outlast it.
    """
    left = remaining()
    if left is None:
        return default

    return min(default, max(left, 0.001))


def sleep_within(seconds):
    """Back off between retries, but never past the deadline."""
    left = remaining()
    if left is None:
        time.sleep(seconds)
        return
    if left <= 0:
        return

    time.sleep(min(seconds, left))
