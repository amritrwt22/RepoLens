# answer.py : question in, cited answer out.
#
# The orchestrator for the ask path. index.py is the one for indexing; this is
# its mirror, and like that one it assembles nothing itself - it calls the five
# pipeline steps in order and owns the transaction boundary.
#
#   1  search     pipeline/retriever.py   the question -> the k nearest chunks
#   2  prompt     pipeline/prompter.py    those chunks + the question -> the prompt
#   3  generate   pipeline/llm.py         the prompt -> the answer and its citations
#   4  cite       pipeline/citations.py   the citations -> validated, linkable sources
#   5  store      db/ask_store.py         the question, the answer, every chunk
#
# Around those it looks the repository up by name, checks whether this exact
# question has been answered before, and on a miss stores what it produced.
#
# Run it:  python -m src.services.answer amritrwt22 RepoLens "<question>"

import json                    # dumps the schema to text, so sha256 can hash it

from src.pipeline.retriever import search
from src.pipeline.prompter import (
    load_prompt,
    prompt_version,
    combine_chunks_and_questions,
    ANSWER_SCHEMA,            # the shape llm.generate must return
)
from src.pipeline.citations import (
    REFUSAL, 
    validate_citations,
    build_sources,
)
from src.db.ask_store import (
    get_repository_by_name,
    get_cached_answer,
    store_question,
    store_retrieved_chunks,
)

class AskError(Exception):
    """A question could not be answered. The parent of every failure on the ask
    path, so a caller can write one `except AskError` instead of listing each
    kind - and a third case added later is caught by that same line.

    Derived from Exception, not BaseException: KeyboardInterrupt and SystemExit
    sit outside Exception so a catch-all cannot swallow a Ctrl-C. These are
    "something went wrong", not "the program should stop"."""
    
class RepositoryNotFound(AskError):
    """No such repository has ever been submitted. The URL is wrong."""
    
class RepositoryNotIndexed(AskError):
    """Submitted, but never successfully indexed - commit_sha is NULL, so there
    are no chunks to search. The caller shows the latest job's status."""


def answer(conn, embedder, llm, owner, repo, question, k=8, lens="ask"):
    """Answer one question about one repository, with citations.

    IN
      conn      open psycopg connection, already prepare_connection'd
      embedder  Embedder instance - embeds the question
      llm       Llm instance - generates the answer
      owner     str - "amritrwt22", from the URL
      repo      str - "RepoLens"
      question  str - what the reader asked
      k         int - how many chunks to retrieve
      lens      str - which prompt to use. "ask" reads prompts/ask.md

    OUT
      {"text":    str - the answer, containing [1] markers,
       "sources": list of dicts, one per cited chunk, in citation order:
                    {"citation": int, "path": str, "start_line": int,
                     "end_line": int, "github_url": str}}

    Raises RepositoryNotFound if no such repository was ever submitted, and
    RepositoryNotIndexed if it was submitted but has no finished index. Neither
    is caught here - this function does not know whether it is behind a CLI, an
    HTTP request or a test, so it reports and the caller decides.

    THE FLOW

      R1  look up the repository by name        read, no transaction
          -> id and commit_sha, or one of the two errors above

      R2  look for this exact answer already stored    read, no transaction
          -> HIT: return it. No embedding, no search, no Gemini, no write.
          -> MISS: continue

          embed -> search -> prompt -> generate -> validate citations
          the pipeline. Only runs on a miss.

      T1  store the question and all k retrieved chunks, then COMMIT
          Two inserts that land together. Only reached on success - if Gemini
          is unreachable the code raises before here, so failures are never
          cached.

    This function owns the transaction boundary; ask_store.py runs statements
    and never commits, the same way index.py owns them for store.py.
    """
    
    # R1. The ask starts from a URL, so turn the name into a row first.
    #     -> {"id": 2, "commit_sha": "df4863798627747b876f73c08d2c6c6a513d3aed"}
    #     -> None if no such repository was ever submitted
    repository = get_repository_by_name(conn, owner, repo)
    
    if repository is None:
        raise RepositoryNotFound(f"no such repository: {owner}/{repo}")
    
    if repository["commit_sha"] is None:
        raise RepositoryNotIndexed(f"{owner}/{repo} has not been indexed yet")
    
    repo_id = repository["id"]
    commit_sha = repository["commit_sha"]
    
    # R2. The cache is keyed on five things: the repository, the commit, the normalised
    # question, the model, and the prompt wording plus the schema. The first two came from R1,
    # the question is passed raw and normalised inside get_cached_answer.
    #     -> "gemini-3.5-flash-lite"
    #     -> "ddecad0a1f2bbdf8acc6291bb6d28bec3ed9ccd2cbad2eea7ff49afd84305488"

    system = load_prompt(lens)
    model = llm.model
    # The schema decides the answer as much as the wording does, so it is hashed
    # with it. sort_keys because the same schema must always give the same string.
    version = prompt_version(system + json.dumps(ANSWER_SCHEMA, sort_keys=True))
    
    # Returns the stored answer as a dict, or None when nobody has asked this before
    #     -> {"text": "...", "sources": [...]}   a hit
    #     -> None                                a miss
    cached = get_cached_answer(conn, repo_id, commit_sha, question, model, version)
    # query itself noirmalize the ques before lookup and insertion both. 
    
    if cached is not None:
        return cached
    
    # retrieve the top k chunks for the ques: list of dict
    query_vector, chunks = search(conn, embedder, repo_id, question, k)
    
    if not chunks:
        return {"text": REFUSAL, "sources": []}
    
    # format the chunks and add ques at bottom : one string
    contents = combine_chunks_and_questions(question, chunks)
    
    # give llm the contents, the rules, and the shape to answer. 
    # generate function calls api, get response as string, convert into dict
    # and return the output, so result hold :
    #     -> {"answer": "...[1]...", "citations": [1, 6]} dictionary.
    result = llm.generate(contents, system, ANSWER_SCHEMA) 
    
    answer_prose = result["answer"]    # str - what the reader sees, with inline markers [1]..
    citation_list = result["citations"] # list of ints - [1, 6]. Unchecked: the schema guarantees ints, not that they name real chunks
    
    # cited: set of ints, unordered, only numbers within 1..len(chunks).
    validated_citations = validate_citations(citation_list, answer_prose, len(chunks))
    
    sources = build_sources(owner, repo, commit_sha, chunks, validated_citations)
        
    # T1. Store the question, then the k chunks that were retrieved for it.
    #     -> an int, or None if another request stored this question first
    question_id = store_question(conn, repo_id, commit_sha, question, query_vector, answer_prose, sources, model, version)
    
    # question id is none if someone else already wrote this question, means the 
    # unique key of 5 values already was there, someone else won the race, no need to 
    # rewrite this ans either in ques table nor in retrieved chunks
    if question_id is not None:
        store_retrieved_chunks(conn, question_id, chunks, validated_citations)
    
    conn.commit()
    return {"text": answer_prose, "sources": sources}
    
    
import sys
import os
import logging
from dotenv import load_dotenv
from src.pipeline.embedder import Embedder
from src.pipeline.llm import Llm
from src.db.store import prepare_connection

import psycopg

if __name__ == "__main__":
    # argv[0] is the script itself, so three real arguments means len >= 4.
    if len(sys.argv) < 4:
        print('usage: python -m src.services.answer <owner> <repo> "<question>"')
        sys.exit(1)

    owner = sys.argv[1]
    repo = sys.argv[2]
    question = sys.argv[3]

    load_dotenv()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("google_genai").setLevel(logging.ERROR)

    embedder = Embedder()
    llm = Llm()

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        prepare_connection(conn)

        # answer() raises rather than returning an error: a forgotten check
        # carries on with a broken result, a forgotten catch crashes loudly.
        # What to do about it depends on the caller - 404 from an API, a message
        # from a CLI. This is a CLI.
        try:
            result = answer(conn, embedder, llm, owner, repo, question)
        except AskError as e:
            print(e)
            sys.exit(1)

    print(result["text"])
    print()

    for source in result["sources"]:
        print(f'[{source["citation"]}] {source["path"]}'
              f':{source["start_line"]}-{source["end_line"]}')
