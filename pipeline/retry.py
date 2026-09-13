# retry.py — survive the API's transient failures.
#
# Some failures are permanent: the identical request will fail forever.
# Some are transient: the identical request would succeed a moment later.
# This module tells them apart and waits out the second kind.
#
# THREE OUTCOMES
#
#   429  quota exhausted   recovery time is KNOWN, so we wait for the boundary
#   5xx  server error      recovery time is UNKNOWN, so the wait grows
#   4xx  our mistake       never retried — waiting cannot fix a wrong request
#
# WHY THE TWO RETRYABLE CASES DIFFER
#
# The 429 window was measured, not assumed. Exhaust the budget, wait N
# seconds, then see how much gets through:
#
#       wait 15s -> 0 tokens      wait 30s -> 0 tokens
#       wait 60s -> full budget           (three identical runs)
#
# All-or-nothing at a ~60s boundary. It is NOT a token bucket: a bucket
# refilling at 500/sec would have returned ~7,500 tokens at 15s. We got zero.
#
# Two consequences:
#   - retrying before ~50s is guaranteed to fail. There is no partial budget
#   - exponential backoff is the WRONG algorithm for this. Backoff exists for
#     unknown recovery times; ours is a known, sharp boundary
#
# A 5xx is the opposite: no idea how long, so the classic algorithm applies.
#
# RETRYING IS ONLY SAFE BECAUSE EMBEDDING IS IDEMPOTENT
#
# Running it twice gives the same vectors and changes nothing. Retrying a
# payment or an email would double-charge or double-send. Always the first
# question before adding retry to anything.

import time
import logging
import random

from google.genai import errors

logger = logging.getLogger(__name__)


# --- quota (429): a measured boundary, so a fixed wait ---------------------
WINDOW_SECONDS = 60          # measured — the budget returns all at once
MAX_QUOTA_RETRIES = 3        # a healthy run needs exactly 1 per exhausted
                             # window. 3 means something else is consuming the
                             # quota, and waiting longer will not fix that

# --- transient server errors (5xx): unknown duration, so the wait grows ----
#   500 internal error   502 bad gateway
#   503 unavailable      504 gateway timeout
# 501 (not implemented) is deliberately absent — that one is permanent.
RETRYABLE_SERVER = {500, 502, 503, 504}
MAX_SERVER_RETRIES = 4       # 1 + 2 + 4 + 8 ~= 15s of outage covered


class RetryPolicy:

    def run(self, call):
        """Run `call`, retrying through quota resets and transient failures.

        `call` takes no arguments — like a C++ lambda. We take a FUNCTION
        rather than a result precisely so we can run it again:

            run(embed(texts))          # wrong: already ran, nothing to retry
            run(lambda: embed(texts))  # right: a recipe we can re-run

        It also means this class never learns what it is retrying, so it can
        be tested with a function that just raises — no network, no API key.

        Raises whatever the API raised once we stop trying. Deciding what
        that MEANS is the caller's job: skip this batch and keep going, or
        fail the whole index. This class only reports honestly.
        """
        # Local, not on the instance: each call starts fresh, so one batch's
        # retries never count against the next.
        #
        # Two separate counters on purpose. A batch that hits one transient
        # 503 and then two ordinary quota waits should not give up — those
        # are unrelated failures and must not share a budget.
        quota_retries = 0
        server_retries = 0

        while True:
            try:
                return call()

            except errors.APIError as e:
                # 4xx arrives as ClientError, 5xx as ServerError; both
                # subclass APIError, and e.code is the status as an int.

                if e.code == 429:
                    quota_retries = quota_retries + 1
                    if quota_retries > MAX_QUOTA_RETRIES:
                        logger.error("quota still exhausted after %d retries, giving up",
                                     MAX_QUOTA_RETRIES)
                        raise

                    # Fixed, because the boundary was measured. No backoff and
                    # no jitter here: jitter is for spreading guesses, and
                    # randomising a known boundary either lands early (certain
                    # failure) or wastes time.
                    wait = WINDOW_SECONDS

                    logger.warning("quota exhausted, retrying in %.0fs (%d/%d)",
                                   wait, quota_retries, MAX_QUOTA_RETRIES)

                elif e.code in RETRYABLE_SERVER:
                    server_retries = server_retries + 1
                    if server_retries > MAX_SERVER_RETRIES:
                        logger.error("server error %s persisted after %d retries, giving up",
                                     e.code, MAX_SERVER_RETRIES)
                        raise

                    # Doubling: 1s, 2s, 4s, 8s.  ** is C++'s pow().
                    # server_retries is already incremented, so it is 1 on the
                    # first failure — hence the -1, or we would start at 2s.
                    #
                    # Cheap when the outage is short, restrained when it is
                    # long: a struggling service needs relief, not more load.
                    #
                    # Jitter (x0.8-1.2) so that concurrent clients do not all
                    # return at the same instant and rebuild the spike that
                    # caused the outage. Does nothing with one worker; costs
                    # one multiplication, and forgetting it later is a real
                    # class of production bug.
                    wait = 2 ** (server_retries - 1) * random.uniform(0.8, 1.2)

                    logger.warning("server error %s, retrying in %.1fs (%d/%d)",
                                   e.code, wait, server_retries, MAX_SERVER_RETRIES)

                else:
                    # 400 bad request, 401/403 bad key, 404 wrong model.
                    # Our fault. Retrying five times produces five identical
                    # failures and buries the real error.
                    #
                    # A bare `raise` re-throws the caught exception unchanged,
                    # keeping its original traceback — C++'s bare `throw;`.
                    raise

                # Both retryable branches fall through to here. Reaching the
                # end of `except` returns to the top of the loop, which calls
                # again.
                time.sleep(wait)
