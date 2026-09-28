class AdaptiveConcurrency:
    """Reduce provider pressure after failures and recover after stable success."""

    def __init__(self, maximum: int, *, recovery_successes: int = 3) -> None:
        self.maximum = max(1, maximum)
        self.current = self.maximum
        self.recovery_successes = max(1, recovery_successes)
        self._successes = 0

    def record(self, succeeded: bool) -> None:
        if not succeeded:
            self.current = max(1, self.current - 1)
            self._successes = 0
            return
        self._successes += 1
        if self._successes >= self.recovery_successes:
            self.current = min(self.maximum, self.current + 1)
            self._successes = 0
