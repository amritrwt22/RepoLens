# prompter.py — ask pipeline, step 2: build the two strings the model is sent.
#
#   system     read from prompts/ - the rules, the tone, the citation format,
#              the refusal sentence. The same for every question under one lens.
#   contents   the numbered chunk blocks, then the question. Different each time.
#
# They stay separate because the API takes them separately: system_instruction
# and contents, not one concatenated prompt.
#
# Also hashes the system string into a version, so that editing a prompt
# invalidates the answers it produced rather than relying on somebody
# remembering to bump a constant.
#
# Pure string assembly. It touches no database and no API, so it is testable
# with a list of dicts and a string literal.


import hashlib                 # sha256, for turning the prompt text into a version string
from pathlib import Path       # lets us build file paths without string juggling


# prompts/ sits at the repo root, this file is two levels down in src/pipeline,
# so walk up twice. Built from __file__ rather than a relative path, so it
# resolves the same whichever directory the command is run from.
PROMPTS = Path(__file__).parent.parent.parent / "prompts"

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
      chunks  list of dicts from retriever.search(), nearest first:
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