# retrieve.py : M5 orchestrator - a question in, cited chunks out.
#
# The mirror of index.py. That one walks, chunks, embeds and stores; this one
# embeds a question and searches for k nearest chunks. It owns no SQL and no API logic of its own -
# it only decides the order things happen in.
#
# Run it:  python -m retrieve <repo_id> "<question>"

import os                        # os.environ — the process's environment variables
import sys                       # sys.argv — the command line, as a list of strings

from dotenv import load_dotenv   # reads .env into os.environ
import psycopg                   # python to postgres driver

from src.db.store import prepare_connection      # teaches one connection the vector type
from src.db.search import search_chunks          # the <=> query
from src.pipeline.embedder import Embedder       # question -> 768-float vector


def search(conn, embedder, repo_id, question, k=8):
    """Turn a question into the k most similar chunks in one repository.

    IN
      conn      open psycopg connection, already prepare_connection'd
      embedder  an Embedder instance - holds the API client, created once
      repo_id   int - which repository to search inside
      question  plain english, e.g. "how does authentication work?"
      k         how many chunks to return

    OUT
      list of k dicts, nearest first - exactly what search_chunks returns:
        {"chunk_id": 64, "path": "Server/index.js",
         "start_line": 1, "end_line": 60,
         "content": "<the 60 lines>", "distance": 0.0689}
    """
    # embed_query uses CODE_RETRIEVAL_QUERY. The chunks in the table were
    # embedded with RETRIEVAL_DOCUMENT. Asymmetric on purpose - the same text
    # under the other task type produces a different vector, and search gets
    # quietly worse with no error anywhere.
    query_vector = embedder.embed_query(question)

    return search_chunks(conn, repo_id, query_vector, k)

if __name__ == "__main__":
    # argv[0] is the script itself, so two real arguments means len >= 3.
    if len(sys.argv) < 3:
        print('usage: python -m retrieve <repo_id> "<question>"')
        sys.exit(1)

    repo_id = int(sys.argv[1])       # argv is always strings; the column is an integer
    question = sys.argv[2]

    load_dotenv()                    # .env -> os.environ

    # Built before the connection so a missing API key fails before we open one.
    embedder = Embedder()

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        prepare_connection(conn)     # teach this connection the vector type
        results = search(conn, embedder, repo_id, question)

    # results is a list of dicts - keys are listed in search()'s docstring.
    # Printed after the with block, so the connection is already closed.
    for chunk in results:
        print(f"{chunk['distance']:.4f}  {chunk['path']}"
              f":{chunk['start_line']}-{chunk['end_line']}")



# The entry block creates the three long-lived things and hands them down:
# the connection, the vector type on it, and the Embedder. prepare_connection
# applies per connection, not per program - a new connection needs it again.
#
# The Embedder is built OUTSIDE search() so one API client serves the whole
# process. search() runs once per question, at M7 once per web request, so
# building it inside would rebuild the client every time. index.py creates its
# Embedder inside index_repository only because that runs once per process.
#
# search() embeds with CODE_RETRIEVAL_QUERY while the stored chunks used
# RETRIEVAL_DOCUMENT - asymmetric on purpose, and the wrong one raises no
# error, it just makes results quietly worse. It returns k dicts, nearest
# first: chunk_id, path, start_line, end_line, content, distance.