# retry.py — survive the API's rate limits.
#
# Only handles 429 (quota exhausted). Everything else is re-raised, because
# a 400/401/403 means OUR request is wrong and retrying repeats the failure.
#
# Measured on gemini-embedding-001, free tier: the token quota is 30,000/min
# and comes back ALL AT ONCE at a ~60s boundary — 0 tokens available at 15s
# and at 30s, full budget at 60s, across three identical runs. So we wait for
# a known boundary rather than guessing with exponential backoff.

import time
import logging

from google.genai import errors

logger = logging.getLogger(__name__)


WINDOW_SECONDS = 60     # measured — the quota returns all at once, not gradually
MAX_WAITS = 3           # a healthy run needs exactly 1 wait per exhausted window


class RetryPolicy:

    def run(self, call):
        """Run `call`, waiting out quota resets.

        `call` is a function taking no arguments — like a C++ lambda. We take
        a function rather than a result so we can run it again.

        Raises whatever the API raised, once we stop trying. The caller
        decides what that means: skip the batch, or fail the whole job.
        """
        # Local, not on the instance — each call starts with a fresh count,
        # so one batch's waits never count against the next batch.
        waits = 0

        while True:
            try:
                return call()

            except errors.APIError as e:
                # Not a rate limit: a bad request, a wrong key, a wrong model
                # name. Waiting cannot fix any of those.
                if e.code != 429:
                    raise

                waits = waits + 1
                if waits > MAX_WAITS:
                    logger.error("quota still exhausted after %d waits, giving up",
                                 MAX_WAITS)
                    raise

                logger.warning("quota exhausted, waiting %ds (%d/%d)",
                               WINDOW_SECONDS, waits, MAX_WAITS)
                time.sleep(WINDOW_SECONDS)
                # Reaching the end of `except` returns to the top of the loop,
                # which calls again.
