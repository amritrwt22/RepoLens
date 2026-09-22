# eval/run.py : capture what retrieval returns for every eval question.
#
# Runs each question in questions.json through the same search() the product
# uses, and writes everything to eval/last-run.md - the question, the files we
# expected, and every chunk that came back with its distance.
#
# It calculates nothing. Scoring comes later, off this file. Capture first so
# the raw result is on disk and can be re-read without spending quota again.
#
# Questions with an empty "files" list are unanswerable on purpose and are
# skipped - there is no correct file to compare against.
#
# Run it:  python -m eval.run <repo_id>

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from src.db.store import prepare_connection
from src.pipeline.embedder import Embedder
from src.services.retrieve import search

HERE = Path(__file__).parent
QUESTIONS = HERE / "questions.json"
REPORT = HERE / "last-run.md"

K = 8


def run(conn, embedder, repo_id):
    """Run every answerable question and write the raw results to a file.

    IN
      conn      open psycopg connection, already prepare_connection'd
      embedder  Embedder instance
      repo_id   int - which indexed repository to search

    OUT
      None - writes eval/last-run.md
    """
    # groups: dict of group name -> list of question dicts
    #   {"id": "walk-skip", "q": "...", "files": ["pipeline/walk.py"]}
    groups = json.load(open(QUESTIONS, encoding="utf-8"))

    lines = []
    lines.append(f"# Retrieval eval - repo {repo_id}, k={K}")
    lines.append("")
    lines.append(f"Run {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    for group_name in groups:
        lines.append(f"## {group_name}")
        lines.append("")

        for question in groups[group_name]:
            # No correct file means nothing to compare against. Skip it.
            if not question["files"]:
                continue

            # chunks: list of dicts, nearest first
            #   {"chunk_id", "path", "start_line", "end_line", "content", "distance"}
            chunks = search(conn, embedder, repo_id, question["q"], K)

            lines.append(f"### {question['id']}")
            lines.append("")
            lines.append(f"**Q:** {question['q']}")
            lines.append("")
            lines.append("**Expected:** " + ", ".join(f"`{f}`" for f in question["files"]))
            lines.append("")
            lines.append("| # | distance | chunk |")
            lines.append("|---|---|---|")

            position = 1
            for chunk in chunks:
                lines.append(
                    f"| {position} | {chunk['distance']:.4f} | "
                    f"`{chunk['path']}:{chunk['start_line']}-{chunk['end_line']}` |"
                )
                position += 1

            lines.append("")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {REPORT}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m eval.run <repo_id>")
        sys.exit(1)

    repo_id = int(sys.argv[1])

    load_dotenv()

    embedder = Embedder()

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        prepare_connection(conn)
        run(conn, embedder, repo_id)
