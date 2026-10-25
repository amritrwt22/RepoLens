# src/dependencies.py : shared resources a request can ask for.
#
# FastAPI's version of middleware — a function that returns a value, which a
# handler asks for by name:
#
#     def list_repos(conn = Depends(get_connection)):
#
# pool            one ConnectionPool for the whole process
# get_connection  hands a request one connection from it, and takes it back
#                 when the response is built
#
# So a handler's signature lists everything it needs, instead of reading
# req.conn and having to find which middleware put it there.

import os

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

from src.db.store import prepare_connection

load_dotenv()

pool = ConnectionPool(os.environ["DATABASE_URL"],
    
    min_size=2,         # kept open when idle, so the first request is instant
    max_size=10,        # never opens an 11th — request 11 waits
    max_idle=300,       # seconds before closing connections above min_size
    max_lifetime=3600,  # seconds — recycle hourly so nothing goes stale
    timeout=5.0,        # seconds to wait for a free one, then PoolTimeout
    
    configure=prepare_connection, # run once per connection - registers pgvector to conn so conn can understand vector
    
    # Creating the object normally also opens the connections. We want those
    # two separate:
    #
    #     ConnectionPool(...)   build the object   <- runs on import
    #     pool.open()           dial Postgres      <- runs at startup, from main.py
    # open=False make sure the first part is done only, second part we do manually later. 
    #
    open=False,   # during import, the whole imported file runs, and that might cause to creation of
    # connection pool at import in any of file, ideally importing a file should never touch network.
    # open=False make sure that when this file is imported, connectionPool object is made, but 
    # connections arent opened, becz if the database is down, this could give confusing import
    # error " connection refused ", so this pool is opened only once in main.py         
)

# yield pauses the function to that point so conn can be used by handler which called get_connection(), 
# to resume to further code, we need to use next(gen), this call is made by the fastapi when response is made by handler
# then the function will resume, and since function end after yield line, so it ends as soon as it resumes.
def get_connection():
    """Lend one pooled connection for the length of a request."""
    # with  = the lending. Entering borrows, leaving gives back - even on an error.
    # yield = pauses here and hands conn to the handler. The with stays open.
    #
    # The function isn't finished, just parked on that line. FastAPI restarts it
    # from there once the response is built: it runs off the end, leaves the with,
    # and the connection goes back. The handler returning does not do this.
    with pool.connection() as conn:
        yield conn