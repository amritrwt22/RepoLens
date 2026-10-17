# citations.py — ask pipeline, step 4: the model's [1] markers become real links.
#
# The model only ever writes a number. Everything a reader sees - the file path,
# the line range, the URL - is looked up here from the chunks that were sent, so
# a citation cannot point at a file that does not exist.
#
# Three steps:
#   validate_citations   drop any number outside 1..k
#   build_sources        turn the survivors into renderable entries
#   github_url           the permanent link for one chunk's lines
#
# Validation is arithmetic rather than judgement: the numbers are a gap-free
# 1..k, so anything outside that range is impossible and gets dropped before it
# is ever displayed.
#
# Pure functions. No database, no API - testable with a string and a list of dicts.

import logging

logger = logging.getLogger(__name__)

# Must match the sentence in prompts/_system.md exactly.
REFUSAL = "I don't have enough information in the available documents to answer this question."

def validate_citations(citations, text, k):
    """Discard citation numbers that cannot refer to a chunk that was sent.

    IN
      citations  list of ints - the model's citations field, e.g. [1, 6]
      text       str - the answer prose. Only read to tell a refusal apart
                 from an ungrounded answer.
      k          int - how many chunks were sent, so valid numbers are 1..k

    OUT
      set of ints - the valid numbers found, e.g. {1, 6}
                    An empty set means the answer cited nothing at all.
    """
   
    valid = set()
    
    for number in citations:
        
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

def github_url(owner, repo, commit_sha, path, start_line, end_line):
    """Build a permanent GitHub link to one chunk's lines.

    IN   owner       "amritrwt22"
         repo        "RepoLens"
         commit_sha  the full 40-character sha the repo was indexed at
         path        "src/pipeline/retry.py", relative to the repo root
         start_line  1
         end_line    60

    OUT  str

        https://github.com/amritrwt22/RepoLens/blob/df48637.../src/pipeline/retry.py#L1-L60

    The full sha rather than a branch name is what makes it permanent. /blob/main
    points at whatever that file is today, so a citation would quietly start
    pointing at the wrong lines the moment someone edits it. The sha freezes it.

    Stored in questions.sources rather than rebuilt on every read, because that
    column is returned whole on every cache hit. retrieved_chunks deliberately
    does NOT store it - that table is read by analytics queries, so it keeps the
    raw path and lines and derives the URL only if something asks.
    """
    return (f"https://github.com/{owner}/{repo}/blob/{commit_sha}"
            f"/{path}#L{start_line}-L{end_line}")