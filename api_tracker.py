import time
import re
from collections import deque
from datetime import date


class APITracker:
    DAILY_LIMIT  = 100
    MINUTE_LIMIT = 5

    def __init__(self):
        self.session_calls  = 0
        self.daily_calls    = 0
        self._session_date  = date.today()
        self._minute_window = deque()
        self._last_call_at  = None
        self.session_cost   = 0.0

    def record_call(self):
        now   = time.time()
        today = date.today()
        if today != self._session_date:
            self.daily_calls   = 0
            self._session_date = today
        self.session_calls += 1
        self.daily_calls   += 1
        self._last_call_at  = now
        self._minute_window.append(now)
        self._clean_window()

    def record_cost(self, amount: float):
        """Accumulates estimated cost for the session. Call alongside calculate_api_cost()
        wherever a Gemini call is made, so the running total in display() is accurate."""
        if amount:
            self.session_cost += amount

    def _clean_window(self):
        cutoff = time.time() - 60
        while self._minute_window and self._minute_window[0] < cutoff:
            self._minute_window.popleft()

    @property
    def calls_this_minute(self):
        self._clean_window()
        return len(self._minute_window)

    def display(self):
        last       = f"{time.time() - self._last_call_at:.1f}s ago" if self._last_call_at else "—"
        pct_daily  = (self.daily_calls / self.DAILY_LIMIT) * 100
        pct_minute = (self.calls_this_minute / self.MINUTE_LIMIT) * 100

        from tqdm import tqdm
        tqdm.write("")
        tqdm.write("  API Usage ─────────────────────────────────────")
        tqdm.write(f"  Session calls :  {self.session_calls}")
        tqdm.write(f"  Daily used    :  {self.daily_calls:>4} / {self.DAILY_LIMIT}  ({pct_daily:.1f}%)")
        tqdm.write(f"  Last minute   :  {self.calls_this_minute:>4} / {self.MINUTE_LIMIT}  ({pct_minute:.1f}%)")
        tqdm.write(f"  Last call     :  {last}")
        tqdm.write(f"  Session cost  :  ${self.session_cost:.5f}")
        tqdm.write("  ────────────────────────────────────────────────")

    def handle_429(self, error) -> int:
        match = re.search(r'retryDelay[^\d]*(\d+)s', str(error))
        wait  = int(match.group(1)) if match else 60

        from tqdm import tqdm
        tqdm.write("")
        tqdm.write(f"  ⚠  Rate limit hit")
        tqdm.write(f"     Daily used : {self.daily_calls} / {self.DAILY_LIMIT}")
        tqdm.write(f"     Waiting    : {wait}s before retry")
        return wait