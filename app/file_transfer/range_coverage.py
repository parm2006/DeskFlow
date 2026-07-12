import threading


class RangeCoverage:
    def __init__(self, size):
        if size < 0:
            raise ValueError("range size cannot be negative")
        self.size = size
        self._intervals = []
        self._covered = 0
        self._lock = threading.Lock()

    def add(self, offset, count):
        if offset < 0 or count < 0 or offset > self.size or offset + count > self.size:
            raise ValueError("range is outside the declared size")
        if count == 0:
            return self.covered
        start, end = offset, offset + count
        with self._lock:
            merged = []
            for current_start, current_end in self._intervals:
                if current_end < start:
                    merged.append((current_start, current_end))
                elif end < current_start:
                    merged.append((start, end))
                    start, end = current_start, current_end
                else:
                    start = min(start, current_start)
                    end = max(end, current_end)
            merged.append((start, end))
            self._intervals = merged
            self._covered = sum(item_end - item_start for item_start, item_end in merged)
            return self._covered

    @property
    def intervals(self):
        with self._lock:
            return tuple(self._intervals)

    @property
    def covered(self):
        with self._lock:
            return self._covered

    @property
    def complete(self):
        return self.covered == self.size
