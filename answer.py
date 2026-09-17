# answer.py : question in, cited answer out.
#
# The third orchestrator. index.py walks and stores, retrieve.py searches,
# this one turns the chunks retrieve.py found into a written answer.
#
# It computes nothing itself - it assembles 2 strings: 
#   contents            the user's question + the chunks retrieved from the db
#   system_instruction  the rules and the lens task, read from prompts/
# 
# sends it to model, and checks what comes back. 
# The wording lives in prompts/, the search in retrieve.py, the API call in pipeline/llm.py.
#
# Run it:  python -m answer <repo_id> "<question>"

from retrieve import search
from pathlib import Path   # lets us build file paths without string juggling

# prompts/ sits next to this file. __file__ is answer.py's own location, so
# this points at the right folder no matter which directory you run from.
PROMPTS = Path(__file__).parent/"prompts"

import logging
import re
logger = logging.getLogger(__name__)

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



def answer(conn, embedder, llm, repo_id, question, k=8, lens="ask"):
    """Answer one question about one repository, with citations.
    
    IN
      conn      open psycopg connection, already prepare_connection'd
      embedder  Embedder instance - embeds the question
      llm       Llm instance - generates the answer
      repo_id   int - which repository to search
      question  str - what the reader asked
      k         int - how many chunks to retrieve
      lens      str - which prompt to use. "ask" reads prompts/ask.md

    OUT
      {"text":    str - the answer, containing [1] markers,
       "sources": list of the chunk dicts that were actually cited,
                  in citation-number order}
    """
    # retrieve the top k chunks for the ques: list of dict
    chunks = search(conn, embedder, repo_id, question, k)
    
    if not chunks:
        return {"text": REFUSAL, "sources": []}
    
    # get the skills/prompts for the given lens(task): one string
    system = load_prompt(lens)
    
    # format the chunks and add ques at bottom : one string
    contents = combine_chunks_and_questions(question, chunks)
    
    # give llm the contents and instructions to use contents and give response
    text = llm.generate(contents, system) # text: one string - the model's reply, with [1] [2] markers in the prose.
    
    # cited: set of ints, unordered, only numbers within 1..len(chunks).
    cited = validate_citations(text, len(chunks))
    
    # Turn each cited number back into its chunk. [1] is the first chunk but
    # chunks[0] is the first, so subtract 1. sorted() because a set has no order.
    sources = [] # append the whole dictionaries of cited chunks
    for number in sorted(cited):
        sources.append({**chunks[number-1], "citation": number})
        # **dictionary expands a dictionary inside new dict, we want the citation no. corresponding to the chunk too. 
    return {"text": text, "sources": sources}
    
    
import sys
import os
from dotenv import load_dotenv
from pipeline.embedder import Embedder
from pipeline.llm import Llm
from db.store import prepare_connection

import psycopg

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('usage: python -m answer <repo_id> "<question>"')
        sys.exit(1)
        
    repo_id = int(sys.argv[1])
    question = sys.argv[2]
    
    load_dotenv()
    
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("google_genai").setLevel(logging.ERROR)
    
    embedder = Embedder()
    llm = Llm()
    
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        prepare_connection(conn) # teaches connection the vector
        result = answer(conn, embedder, llm, repo_id, question)
        
    print(result["text"]) #result["text is a string"]
    print()
    
    for source in result["sources"]:
        #source = dictionary of source chunks with metadata + citation number
        print(f'[{source["citation"]}] {source["path"]}'
              f':{source["start_line"]}-{source["end_line"]}')
    
    
    
    
    
    

    
