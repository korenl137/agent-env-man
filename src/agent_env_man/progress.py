"""Optional operation observation, independent of Click and core mutations."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Event, Lock, Thread
import time


_observer = ContextVar("aem_progress", default=None)
DELAY = 1.0
POLL_INTERVAL = 0.25
MIN_INTERVAL = 1.0
REPEAT_INTERVAL = 5.0


@contextmanager
def phase(label, detail=None):
    observer = _observer.get()
    if observer is None:
        yield
        return
    observer.push(label, detail)
    try:
        yield
    finally:
        observer.pop()


def step(label, detail=None):
    observer = _observer.get()
    if observer is not None:
        observer.replace(label, detail)


def operation(label, detail=None):
    """Observe a synchronous core operation without coupling it to a terminal."""
    def decorate(function):
        @wraps(function)
        def observed(*args, **kwargs):
            if _observer.get() is None:
                return function(*args, **kwargs)
            name = label(*args, **kwargs) if callable(label) else label
            target = detail(*args, **kwargs) if callable(detail) else detail
            with phase(name, target):
                return function(*args, **kwargs)
        return observed
    return decorate


def finish(failed=False):
    observer = _observer.get()
    if observer is not None:
        observer.finish(failed)


class Progress:
    """Sample the current phase while core work, including a blocked read, runs.

    Only the calling operation changes the phase stack. The reporter thread
    observes a locked snapshot and writes complete lines to a captured sink;
    it never accesses configuration, state, or the Click context.
    """

    def __init__(self, command, sink, *, enabled=False, immediate=False):
        self.command, self.sink = command, sink
        self.enabled, self.immediate = enabled, immediate
        self.lock = Lock()
        self.stopped = Event()
        self.stack = [("Starting", None)]
        self.last = None
        self.last_time = 0.0
        self.shown = False
        self.thread = None

    def __enter__(self):
        self.started = time.monotonic() if self.enabled else 0.0
        self.token = _observer.set(self if self.enabled else None)
        if self.enabled:
            if self.immediate:
                self.tick(force=True)
            self.thread = Thread(target=self._watch, name="aem-progress", daemon=True)
            self.thread.start()
        return self

    def __exit__(self, kind, value, traceback):
        try:
            self.finish(failed=kind is not None)
        finally:
            _observer.reset(self.token)

    def push(self, label, detail):
        with self.lock:
            self.stack.append((label, detail))

    def pop(self):
        with self.lock:
            self.stack.pop()

    def replace(self, label, detail):
        with self.lock:
            self.stack[-1] = (label, detail)

    def _write(self, line):
        try:
            self.sink.write(line + "\n")
            self.sink.flush()
        except (OSError, ValueError):
            # A closed progress stream must not change an operation's outcome.
            self.stopped.set()

    def tick(self, *, force=False):
        with self.lock:
            now = time.monotonic()
            if not force and now - self.started < DELAY:
                return
            snapshot = tuple(self.stack[-2:])
            if not force and self.shown and now - self.last_time < MIN_INTERVAL:
                return
            if not force and snapshot == self.last and now - self.last_time < REPEAT_INTERVAL:
                return
            description = " / ".join(label + (f": {detail}" if detail else "")
                                     for label, detail in snapshot)
            line = f"[{self.command} {now - self.started:.1f}s] {description}"
            self.last, self.last_time, self.shown = snapshot, now, True
        # Terminal I/O must not hold the phase-state lock used by core work.
        self._write(line)

    def _watch(self):
        while not self.stopped.wait(POLL_INTERVAL):
            self.tick()

    def finish(self, failed=False):
        if not self.enabled or self.thread is None:
            return
        self.stopped.set()
        self.thread.join()
        self.thread = None
        if self.shown:
            elapsed = time.monotonic() - self.started
            self._write(f"[{self.command} {elapsed:.1f}s] {'Failed' if failed else 'Finished'}")
