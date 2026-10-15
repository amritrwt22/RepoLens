# answer.py : question in, cited answer out.
#
# The third orchestrator. index.py walks and stores, retrieve.py searches,
# this one turns the chunks retrieve.py found into a written answer.
#
# It computes little itself. It assembles 2 strings:
#   contents            the user's question + the chunks retrieved from the db
#   system_instruction  the rules and the lens task, read from prompts/
#
# sends them to the model, and checks what comes back.
#
# Around that it owns the ask path: look the repository up by name, check
# whether this exact question has been answered before, and on a miss store the
# answer and every chunk that was retrieved for it.
#
# The wording lives in prompts/, the search in retrieve.py, the API call in
# pipeline/llm.py, and every SQL statement in db/ans_store.py.
#
# Run it:  python -m src.services.answer amritrwt22 RepoLens "<question>"

from src.services.retrieve import search
from pathlib import Path   # lets us build file paths without string juggling
import hashlib   # sha256, for turning the prompt text into a version string
from src.db.ans_store import (
    get_repository_by_name,
    get_cached_answer,
    store_question,
    store_retrieved_chunks,
    github_url,
)

# prompts/ sits at the repo root, this file is two levels down in src/services,
# so walk up twice. Built from __file__ rather than a relative path, so it
# resolves the same whichever directory the command is run from.
PROMPTS = Path(__file__).parent.parent.parent / "prompts"

import logging
import re
logger = logging.getLogger(__name__)

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

def load_prompt(lens="ask"):
    """Read the system instruction for one lens.

    IN
      lens  str - which lens. "ask" reads prompts/ask.md

    OUT
      str - _system.md and the lens file joined with a blank line between.
            The whole string is sent to the model as system_instruction.
    """
    
    shared = (PROMPTS/ "_system.md").read_text()
    task = (PROMPTS/ f"{lens}.md").read_text()
    
    return shared + "\n\n" + task


def prompt_version(prompt_text):
    """Turn the prompt text into a version string for the cache key.

    IN   prompt_text  str - the combined prompt, from load_prompt()
    OUT  str  - 64 hex characters, e.g. "ae7ec60dad4a22200195c0412ecbca2b33bc9be43282022a1ac71d8aa4f7f595"

    Stored on every questions row and part of the cache key, so that editing a
    prompt invalidates the answers it produced. 

    Per-lens falls out for free: load_prompt("ask") returns _system.md + ask.md,
    load_prompt("setup") returns _system.md + setup.md. Different strings,
    different hashes. Editing one lens never invalidates another.

    sha256 rather than md5 only because linters flag md5 - nothing here is
    security-sensitive. 
    """
    # hashing works on bytes, not str. encode() gives UTF-8 bytes - the b prefix
    # marks them, and python prints readable ASCII as letters rather than numbers.
    #     'hello'  ->  b'hello'      which is [104, 101, 108, 108, 111]
    data = prompt_text.encode()
    
    # sha256() returns a hash object - .hexdigest() is what produces the digest.
    #     b'hello'  ->  <sha256 HASH object>
    hasher = hashlib.sha256(data)
    # hashlib is a module and sha256 a function inside it. sha256 builds an object
    # and hands it back, so hexdigest() used below is a method on that object.
    
    # the digest = output of hash(algo), sha256 outputs 256 bits hash,
    # hexdigest() convert it into hexadecimal format. 1 hexadecimal unit can have 16 possible values(4 bits)
    # so digest is 256/4 = 64 hexadecimal digits. 
    #     <object>  ->  '2cf24dba5fb0a30e26e83b2ac5b9e29e...'
    return hasher.hexdigest()
    

def format_chunks(chunks):
    """Turn the retrieved chunks into numbered <chunk> blocks for the prompt.
    
    IN
      chunks  list of dicts from retrieve.search(), nearest first:
              {"chunk_id": 64, "path": "Server/index.js",
               "start_line": 1, "end_line": 60,
               "content": "<the lines>", "distance": 0.2523}

    OUT
      str - one block per chunk, numbered from 1, separated by blank lines:

              <chunk id="1" path="Server/index.js" lines="1-60">
              <the lines>
              </chunk>
              ...2 line gap...
              <next chunk> so on...
            The id is the number the model cites. It is the position in this
            list, NOT chunk_id - a gap-free 1..k has no plausible wrong values.
    """
    
    blocks = []
    number = 1
    # Order is left exactly as search() returned it - nearest first - so [1] is
    # the closest match and the numbers match the ranking.
    for chunk in chunks:
        blocks.append(
            f'<chunk id="{number}" path="{chunk["path"]}" lines="{chunk["start_line"]}-{chunk["end_line"]}">\n'
            f'{chunk["content"]}\n'
            f'</chunk>'
        )
        number+=1
        
    # join glues the list into one string with a blank line between blocks.
    return "\n\n".join(blocks)

def combine_chunks_and_questions(question, chunks):
    """Assemble the user half of the prompt.

    IN
      question:  str - what the reader asked
      chunks:    list of dicts from retrieve.search(), nearest first

    OUT
      chunks+ques: - the formatted chunk blocks, then the question. Sent to the model
                as `contents`. The rules go separately, as system_instruction.

                CHUNKS
                <chunk id="1" ...>
                ...
                </chunk>

                QUESTION
                how does retry decide how long to wait?
    """
    # Chunks first, question last. A model reads the start and end of a prompt
    # most carefully and the middle least, so the chunks and the question each
    # sit in one of the two strong positions.
    
    return "CHUNKS\n" + format_chunks(chunks) + "\n\nQUESTIONS\n" + question

# Must match the sentence in prompts/_system.md exactly.
REFUSAL = "I don't have enough information in the available documents to answer this question."

def validate_citations(text, k):
    """Find the citation number in answer and discard impossible ones.
    
    IN
      text  str - the model's reply, containing markers like [1] [4]
      k     int - how many chunks were sent, so valid numbers are 1..k

    OUT
      set of ints - the valid numbers found, e.g. {1, 4}
                    An empty set means the answer cited nothing at all.
    """
    # findall returns every match as a string, in order: ["1", "4", "9"]
    found = re.findall(r"\[(\d+)\]", text) # () tells to capture digits only, else we get ["[1]", "[4]", "[9]"]
    
    valid = set()
    
    for marker in found:
        number = int(marker)
        
        if 1 <= number <= k:
            valid.add(number)
        else:
            logger.warning(
                "fabricated citation [%d] - only %d chunks were sent", number, k
            )
        
    if not valid and REFUSAL not in text:
        logger.warning("answer cites nothing and is not a refusal - ungrounded")
    
    return valid

def build_sources(owner, repo, commit_sha, chunks, cited):
    """Turn citation numbers into the payload a reader sees.

    IN   owner       str - "amritrwt22"
         repo        str - "RepoLens"
         commit_sha  str - the commit these chunks were indexed at
         chunks      list of dicts, nearest first - what search() returns:
                       {"chunk_id": int, "path": str, "start_line": int,
                        "end_line": int, "content": str, "distance": float}
         cited       set of ints - which numbers the answer used, {1, 3}

    OUT  list of dicts, in citation order:
           {"citation": int, "path": str, "start_line": int,
            "end_line": int, "github_url": str}

    Only the cited chunks. All k go to retrieved_chunks for analytics; these are
    the ones the reader is shown.

    No chunk content. This list is stored in questions.sources and returned whole
    on every cache hit, so it holds what renders a citation and nothing more -
    the code itself is already in code_chunks.
    """
    sources = []

    # sorted() because cited is a set and has no order - the reader sees [1]
    # before [3], so the list should match.
    for number in sorted(cited):

        # [1] means the FIRST chunk, which is chunks[0], so subtract one.
        chunk = chunks[number - 1]

        sources.append({
            "citation": number,
            "path": chunk["path"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "github_url": github_url(owner, repo, commit_sha, chunk["path"],
                                     chunk["start_line"], chunk["end_line"]),
        })

    return sources

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
    # question, the model, and the prompt wording. The first two came from R1,
    # the question is passed raw and normalised inside get_cached_answer.
    #     -> "gemini-3.5-flash-lite"
    #     -> "ae7ec60dad4a22200195c0412ecbca2b33bc9be43282022a1ac71d8aa4f7f595"
    system = load_prompt(lens)
    model = llm.model
    version = prompt_version(system)
    
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
    
    # give llm the contents and instructions to use contents and give response
    text = llm.generate(contents, system) # text: one string - the model's reply, with [1] [2] markers in the prose.
    
    # cited: set of ints, unordered, only numbers within 1..len(chunks).
    cited = validate_citations(text, len(chunks))
    
    sources = build_sources(owner, repo, commit_sha, chunks, cited)
        
    # T1. Store the question, then the k chunks that were retrieved for it.
    #     -> an int, or None if another request stored this question first
    question_id = store_question(conn, repo_id, commit_sha, question, query_vector, text, sources, model, version)
    
    # question id is none if someone else already wrote this question, means the 
    # unique key of 5 values already was there, someone else won the race, no need to 
    # rewrite this ans either in ques table nor in retrieved chunks
    if question_id is not None:
        store_retrieved_chunks(conn, question_id, chunks, cited)
    
    conn.commit()
    return {"text": text, "sources": sources}
    
    
import sys
import os
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
