# chunk.py — M2: split a file's text into overlapping line windows.
#
# Pure function: text in, chunks out. It knows nothing about the
# filesystem, the embedding API, or the database — that keeps it
# testable with a string literal, and swappable for tree-sitter
# chunking in Phase 2 without touching anything else.
#
# See docs/rag-pipeline.md for where this sits in the pipeline.

# Defaults, overridable per call so Phase 2 can sweep values
# against the eval set without editing this file.
CHUNK_LINES = 60
OVERLAP_LINES = 10


def chunk_text(content, chunk_lines=CHUNK_LINES, overlap_lines=OVERLAP_LINES):
    """Split one file's text into overlapping line windows.

    Returns a list of:
        {"start_line": int, "end_line": int, "content": str}

    Line numbers are 1-based and inclusive — the numbers an editor shows.

    The file path is deliberately absent: in the database a chunk is
    linked to its file by file_id, and the path lives in `files`.
    """
    # Guard: if overlap >= chunk size the stride becomes 0 or negative
    # and the loop below never advances. Fail loudly, at the call site.
    if overlap_lines >= chunk_lines:
        raise ValueError(
            f"overlap_lines ({overlap_lines}) must be less than "
            f"chunk_lines ({chunk_lines})"
        )

    # How far to move forward between chunks. 60 - 10 = 50, and the
    # 10-line difference between stride and window size IS the overlap.
    stride = chunk_lines - overlap_lines

    # splitlines() splits on newlines and drops the newline characters.
    # lines[0] is the file's line 1.
    lines = content.splitlines()

    # An empty file produces no chunks, rather than one empty chunk that
    # would get embedded and pollute search results.
    if not lines:
        return []

    chunks = []
    start = 0  # 0-based index into `lines`

    while start < len(lines):
        # min() stops the final window running off the end of the file.
        end = min(start + chunk_lines, len(lines))

        chunks.append({
            # `start` is a 0-based index; editors count lines from 1.
            "start_line": start + 1,
            # `end` is already correct as a 1-based inclusive line number,
            # because Python slicing is exclusive: lines[0:60] is lines 1-60.
            "end_line": end,
            "content": "\n".join(lines[start:end]),
        })

        # We just emitted the last line of the file. Stop here — otherwise
        # the loop would keep producing the same short tail forever.
        if end == len(lines):
            break

        start += stride

    return chunks


# Runs only when this file is executed directly, not when another module
# imports chunk_text from it. The import sits inside so that importing
# chunk_text never drags in the walker.
if __name__ == "__main__":
    import sys
    from pathlib import Path

    from walk import find_source_files

    root = Path(sys.argv[1])

    total_files = 0
    total_chunks = 0
    most_chunked = None  # (chunk count, path, line count)

    # The walker yields one file; we chunk it and immediately throw the
    # file away. Only one file's text is in memory at a time.
    for f in find_source_files(root):
        chunks = chunk_text(f["content"])

        total_files += 1
        total_chunks += len(chunks)

        if most_chunked is None or len(chunks) > most_chunked[0]:
            most_chunked = (len(chunks), f["path"], f["line_count"])

    print(f"files:        {total_files}")
    print(f"chunks:       {total_chunks}")
    print(f"avg per file: {total_chunks / total_files:.1f}")
    print()
    print(f"most chunked: {most_chunked[1]}")
    print(f"              {most_chunked[2]} lines -> {most_chunked[0]} chunks")
