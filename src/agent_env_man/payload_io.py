"""Bounded leaf I/O, activated only after observing a slow operation."""

from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore
from time import perf_counter


class PayloadReads:
    """Keep fast local I/O synchronous; overlap latency without transport checks.

    Completed futures give callers one ordered result interface. A slow leaf
    enables four readers for the remainder of this inspection, never a saved
    cache or an inference that file contents are unchanged.
    """

    def __init__(self):
        self.pool = None
        self.slots = BoundedSemaphore(8)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.pool is not None:
            self.pool.shutdown(wait=True)

    def submit(self, operation, *args, **kwargs):
        if self.pool is None:
            started = perf_counter()
            future = Future()
            try:
                future.set_result(operation(*args, **kwargs))
            except Exception as exc:
                future.set_exception(exc)
            if perf_counter() - started >= 0.002:
                self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="aem-payload")
            return future
        self.slots.acquire()
        try:
            future = self.pool.submit(operation, *args, **kwargs)
        except BaseException:
            self.slots.release()
            raise
        future.add_done_callback(lambda _: self.slots.release())
        return future
