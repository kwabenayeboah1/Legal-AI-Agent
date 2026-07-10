"""
Session-local observability for Gemini API usage in the AML pipeline.

APITracker does NOT enforce any quota and does NOT talk to the Gemini API to
discover real limits — it is a self-contained counter that main.py pokes
every time it makes a call (record_call), learns the $ cost of (record_cost),
or gets rate-limited by (handle_429). DAILY_LIMIT/MINUTE_LIMIT below are soft,
manually-set display thresholds for the `display()` readout — on a
pay-as-you-go Gemini key there is no hard daily/per-minute cap to check
against, so these exist purely so the "Daily used X/Y" line has a denominator
to show progress against. If Google's actual enforced limits change, or you
move to a metered plan with real caps, update these two constants to match —
nothing else in this file needs to change.

Wiring (see main.py):
  - one `APITracker()` instance is created at module load and reused for the
    whole batch run (i.e. counts are for the whole `python main.py` process,
    not per-case)
  - `record_call()` before/after every `client.models.generate_content` /
    `chat.send_message` call
  - `record_cost(calculate_api_cost(...))` after every response with usage
    metadata
  - `handle_429(err)` inside the 429 exception handler in `batch_process()`,
    to both log the hit and get back how many seconds to sleep
  - `display()` once at the very end of the run, to print the session summary
"""
import time
import re
from collections import deque
from datetime import date

from tqdm import tqdm


class APITracker:
    # Soft display thresholds only — see module docstring. Not fetched from
    # the API and not enforced; raise/lower these to whatever level you want
    # the "used X/Y" readout to warn against.
    DAILY_LIMIT  = 100
    MINUTE_LIMIT = 5

    # Width of the rolling window used for calls_this_minute, in seconds.
    RATE_WINDOW_SECONDS = 60

    def __init__(self):
        self.session_calls  = 0                # total calls since this process started
        self.daily_calls    = 0                # calls since _session_date last rolled over
        self._session_date  = date.today()     # calendar day daily_calls is counted against
        self._minute_window = deque()          # timestamps of calls in the last RATE_WINDOW_SECONDS
        self._last_call_at  = None             # time.time() of the most recent record_call()
        self.session_cost   = 0.0              # running total from record_cost(), USD

    def record_call(self):
        """Call once immediately before/after every Gemini API request.

        Rolls daily_calls over to 0 if the wall-clock date has changed since
        the tracker (or the process) started — lets a long-running overnight
        batch keep an accurate "today" count without needing a restart.
        """
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
        """Drop timestamps older than RATE_WINDOW_SECONDS from _minute_window
        so calls_this_minute reflects a true trailing-60s count rather than
        an ever-growing total."""
        cutoff = time.time() - self.RATE_WINDOW_SECONDS
        while self._minute_window and self._minute_window[0] < cutoff:
            self._minute_window.popleft()

    @property
    def calls_this_minute(self) -> int:
        """Number of record_call() hits in the trailing RATE_WINDOW_SECONDS."""
        self._clean_window()
        return len(self._minute_window)

    def display(self):
        """Print a one-shot session summary to the console via tqdm.write
        (tqdm.write, not print, so it doesn't clobber an active progress bar).
        Called once at the end of a `python main.py` run — not per-case."""
        last       = f"{time.time() - self._last_call_at:.1f}s ago" if self._last_call_at else "—"
        pct_daily  = (self.daily_calls / self.DAILY_LIMIT) * 100
        pct_minute = (self.calls_this_minute / self.MINUTE_LIMIT) * 100

        tqdm.write("")
        tqdm.write("  API Usage ─────────────────────────────────────")
        tqdm.write(f"  Session calls :  {self.session_calls}")
        tqdm.write(f"  Daily used    :  {self.daily_calls:>4} / {self.DAILY_LIMIT}  ({pct_daily:.1f}%)")
        tqdm.write(f"  Last minute   :  {self.calls_this_minute:>4} / {self.MINUTE_LIMIT}  ({pct_minute:.1f}%)")
        tqdm.write(f"  Last call     :  {last}")
        tqdm.write(f"  Session cost  :  ${self.session_cost:.5f}")
        tqdm.write("  ────────────────────────────────────────────────")

    def handle_429(self, error) -> int:
        """Log a rate-limit (HTTP 429) hit and return how many seconds to
        sleep before retrying.

        Gemini's 429 error payload includes a `retryDelay` field (e.g.
        `retryDelay: "34s"`) telling the caller how long to back off — this
        pulls that number out of the stringified error via regex. Falls back
        to a flat 60s if the field isn't present/parseable (e.g. the error
        shape changes in a future SDK version), so a malformed match never
        crashes the batch run.

        Caller (main.py's batch_process) is responsible for actually
        sleeping; this only computes and logs the wait time.
        """
        match = re.search(r'retryDelay[^\d]*(\d+)s', str(error))
        wait  = int(match.group(1)) if match else 60

        tqdm.write("")
        tqdm.write(f"  ⚠  Rate limit hit")
        tqdm.write(f"     Daily used : {self.daily_calls} / {self.DAILY_LIMIT}")
        tqdm.write(f"     Waiting    : {wait}s before retry")
        return wait