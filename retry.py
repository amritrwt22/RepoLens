# retry.py — survive the API's rate limits.

import time
import logging
from google.genai import errors

logger = logging.getLogger(__name__)
WINDOW_SECONDS = 60 # measured: the quota comes back all at once, ~60s

class RetryPolicy:
    
    def run(self, call):
        """ 'call' is a function taking no arguments - like c++ lambda
        for now it just calls it, retry in step 2.
        """
        while True:
            try:
                return call()
            
            except errors.APIError as e:
                # Anything other than 429 is our fault - a bad request, a wrong key, a wrong model. Retrying repeats it.
                if e.code != 429:
                    raise 
                
                logger.warning("quota exhausted, waiting %d", WINDOW_SECONDS)
                time.sleep(WINDOW_SECONDS)
                # after 60 seconds, loop continues. call()  →  429  →  sleep 60s  →  back to top  →  call()  →  works  →  return

                
                
                
    