# src/api/main.py : the FastAPI application, and the only file that knows
# every route exists.
#
# `app` holds a list of paths and the function handling each. A request comes
# in, FastAPI scans that list, calls what matches. No match is a 404 - not an
# error, just "nothing here".
#
# THE LIST
#
#   /openapi.json              FastAPI's own, the machine-readable spec
#   /docs                      FastAPI's own, the interactive page
#   /docs/oauth2-redirect      FastAPI's own
#   /redoc                     FastAPI's own, a second docs style
#
#   /health                    ours, written below with @app.get
#   /v1/repositories           ours, mounted from routers/repositories.py
#
# Four exist before you write anything - that is why /docs works on an empty
# app. Ours reach the list two ways: written here with @app.get, or mounted
# with include_router.
#
# A router file cannot use @app.get, because `app` lives here - it would have
# to import main, and main must import it back to register anything. So each
# router builds its own APIRouter, imports nothing from here, and this file
# empties it into app. Imports run one way only.

import logging
from contextlib import asynccontextmanager   # splits a function at its yield

from fastapi import FastAPI                  # pull FastAPI class out of fastapi package
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

from src.api.dependencies import pool
from src.api.routers import repositories

logger = logging.getLogger(__name__)


# the pool is built with open=False, so importing dependencies.py dials
# nothing. This opens it when the server boots - not on import. Everything
# above the yield runs at startup, everything below at shutdown.
@asynccontextmanager
async def lifespan(app):
    pool.open()
    yield
    pool.close()


# lifespan=lifespan hands the function over: FastAPI runs its top half when
# uvicorn boots and its bottom half on shutdown. Without this it never runs.
app = FastAPI(lifespan=lifespan)     # the application object, holds the list of routes


# ---------------------------------------------------------------------------
# NOTE: both handlers below are GLOBAL - registered once on app, used by every
# route. No handler repeats them.
# ---------------------------------------------------------------------------

# 503 - a dependency is down, not a bug here. Retrying can work.
#
#   OperationalError   postgres stopped, wrong port, bad credentials, no
#                      such database - anything that cannot reach or use it
#   PoolTimeout        all connections busy and the timeout expired
@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeout)
async def dependency_unavailable(request, exc):
    # log two things, because the status code alone is not actionable:
    #   1) request.url.path - which endpoint failed. Four routes share this
    #      database, so "something broke" does not narrow it down
    #   2) exc - what broke: the port, the password, or the host
    logger.error("503 on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "the database is unavailable, try again shortly"},
    )


# 500 - the code is broken, not a dependency. Nothing for the client to retry.
#
# Exception is the parent of everything you would ever raise - including our
# own GitError and AskError - so this catches whatever the handler above did
# not. Its own parent is BaseException, which we do NOT catch: that also holds
# KeyboardInterrupt and SystemExit, which mean "stop the program", not
# "something went wrong".
@app.exception_handler(Exception)
async def unhandled(request, exc):
    # log two things, because the response deliberately says nothing - an
    # exception can name columns, hosts or internal fields:
    #   1) request.url.path - which endpoint failed
    #   2) exc_info=True - the traceback: file, line, call chain
    #
    # no exc here - the traceback already ends with it
    logger.error("500 on %s", request.url.path, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "internal error"},
    )


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.get("/health")     # register the function below as the handler for GET /health
def health():
    return {"status": "ok"}     # a python dict; FastAPI converts it to JSON and sends 200


# the router's own paths are glued onto this prefix: "" becomes
# /v1/repositories, "/{owner}/{repo}" becomes /v1/repositories/{owner}/{repo}
app.include_router(repositories.router, prefix="/v1/repositories")
