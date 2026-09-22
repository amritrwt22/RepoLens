# eval/refusal.py : does the model admit when it does not know?
#
# The other half of the eval. run.py tests retrieval - did the right file come
# back. This tests generation - when nothing relevant exists, does the model
# say so instead of inventing an answer.
#
# It uses the "unanswerable" group in questions.json: questions about things
# this repository genuinely does not contain. There is no correct file, so
# recall means nothing for them, which is why run.py skips them.
#
# Two checks per question, both deterministic. No LLM judge:
#   1. the refusal sentence appears in the answer
#   2. the answer cites nothing - there was nothing to cite
#
# This costs one generation call per question, unlike run.py which costs none.
#
# Run it:  python -m eval.refusal <repo_id>

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from src.services.answer import REFUSAL, answer
from src.db.store import prepare_connection
from src.pipeline.embedder import Embedder
from src.pipeline.llm import Llm

HERE = Path(__file__).parent
QUESTIONS = HERE / "questions.json"
REPORT = HERE / "last-refusal.md"


def check(conn, embedder, llm, repo_id, question):
    """Ask one unanswerable question and see whether the model refuses.

    IN
      question  dict from questions.json
                {"id": "billing", "q": "...", "files": []}

    OUT
      dict:
        {"refused":  bool - the exact refusal sentence appears,
         "n_cited":  int  - how many chunks the answer cited. Should be 0,
         "text":     str  - what it actually said, kept so a failure is
                            readable without re-running and re-paying}
    """
    result = answer(conn, embedder, llm, repo_id, question["q"])

    return {
        "refused": REFUSAL in result["text"],
        "n_cited": len(result["sources"]),
        "text": result["text"],
    }


def run(conn, embedder, llm, repo_id):
    """Run every unanswerable question and write the report.

    IN
      repo_id  int - which indexed repository to search

    OUT
      None - writes eval/last-refusal.md and prints a one-line summary.
    """
    groups = json.load(open(QUESTIONS, encoding="utf-8"))
    questions = groups["unanswerable"]

    lines = []
    lines.append(f"# Refusal check - repo {repo_id}")
    lines.append("")
    lines.append(f"Run {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("A question this repository cannot answer should produce the refusal")
    lines.append("sentence and cite nothing.")
    lines.append("")

    passed = 0

    for question in questions:
        outcome = check(conn, embedder, llm, repo_id, question)

        # Both must hold. A refusal that cites chunks is still wrong - it means
        # the model refused while claiming evidence it did not use.
        ok = outcome["refused"] and outcome["n_cited"] == 0
        if ok:
            passed += 1

        lines.append(f"### {question['id']} - {'PASS' if ok else '**FAIL**'}")
        lines.append("")
        lines.append(f"**Q:** {question['q']}")
        lines.append("")
        lines.append(f"- refused: {outcome['refused']}")
        lines.append(f"- chunks cited: {outcome['n_cited']} (expected 0)")
        lines.append("")
        lines.append("**Answer given:**")
        lines.append("")
        lines.append("```")
        lines.append(outcome["text"])
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"**{passed}/{len(questions)} refused correctly.**")

    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"{passed}/{len(questions)} refused correctly")
    print(f"written: {REPORT}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m eval.refusal <repo_id>")
        sys.exit(1)

    repo_id = int(sys.argv[1])

    load_dotenv()

    embedder = Embedder()
    llm = Llm()

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        prepare_connection(conn)
        run(conn, embedder, llm, repo_id)
