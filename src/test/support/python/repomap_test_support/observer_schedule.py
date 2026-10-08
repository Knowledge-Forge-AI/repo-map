"""Observe real timer settlement without confusing callback and caller return."""

from threading import Event, Timer


class ObservedTimer(Timer):
    """Expose barriers around the real timer callback and join boundary."""

    def __init__(self, interval, function, args):
        self.join_started = Event()
        self.callback_finished = Event()

        def observed_callback():
            try:
                function(*args)
            finally:
                self.callback_finished.set()

        super().__init__(interval, observed_callback)

    def join(self, timeout=None):
        self.join_started.set()
        return super().join(timeout)


class ObserverSchedule:
    """Keep the sole timer observable; retain production timer semantics."""

    def __init__(self):
        self.timer = None

    def make_timer(self, interval, function, args):
        assert self.timer is None
        self.timer = ObservedTimer(interval, function, args)
        return self.timer

    def wait_for_operation_return(self):
        assert self.timer is not None
        assert self.timer.join_started.wait(1.0)

    def wait_for_request_settlement(self):
        assert self.timer is not None
        assert self.timer.callback_finished.wait(1.0)
