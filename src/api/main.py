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


from fastapi import FastAPI    # pull FastAI class out of fastapi package

from src.api.dependencies import pool
from src.api.routers import repositories

# marks where a function pauses: everything above the yield runs when the
# server starts, everything below runs when it shuts down
from contextlib import asynccontextmanager   

# the pool is built with open=False, so importing dependencies.py dials
# nothing. This opens it when the server boots - not on import.
@asynccontextmanager
async def lifespan(app):
    pool.open()
    yield
    pool.close()
    
# lifespan=lifespan hands the function over: FastAPI runs its top half when
# uvicorn boots and its bottom half on shutdown. Without this it never runs.
app = FastAPI(lifespan=lifespan)     # create the application object, holds list of routes


@app.get("/health")     # Decorator line: register the function below as handler for Get/ health endpoint
def health():
    return {"status": "ok"}     # return a python dict, fastapi convert it into JSON and send with status 200 to client


# the router's own paths are glued onto this prefix: "" becomes
# /v1/repositories, "/{owner}/{repo}" becomes /v1/repositories/{owner}/{repo}
app.include_router(repositories.router, prefix="/v1/repositories")
