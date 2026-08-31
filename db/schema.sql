CREATE EXTENSION IF NOT EXISTS vector;

/*
Given :

Walker yields, per file:
{"path": "Server/index.js", "language": "JavaScript",
 "line_count": 125, "content": "<full text>"}

Chunker returns, per chunk:
{"start_line": 51, "end_line": 110, "content": "<60 lines>"}
*/

/*
first table for repo -
id(PK) repo_name status                     (status: queued -> indexing -> ready or failed)
file_count chunk_count total_lines.         (these 3 comes when indexing finishes)
uploaded_at indexed_at                      (set when status=queued & status=ready)
error                                       (tells why chunking failed)

Queries: see docs/01-schema_db_cosine_similarity/schema-design.md

Indexes: none needed
Every query on this table is WHERE id = $1.
id is the primary key, and Postgres creates an index for a primary key automatically. So it's already covered.
NOTE : you add index for query u actually run, not for a column which feel imp. Each index slow down write and takes storage
*/

CREATE TABLE repositories(
    id          serial primary key,
    name        text not null,

    status      text not null default 'queued'
                CHECK (status IN ('queued', 'indexing', 'ready', 'failed')),
    
    error       text,

    file_count  integer,
    chunk_count integer,
    total_lines integer,

    uploaded_at timestamptz not null default now(),
    indexed_at  timestamptz
);



/*
second table for files -

id(PK) repo_id(FK)            (no file inset whose repo_id doesnt exist, on delete cascade delete children auto when parent deleted)
path                          (file path relative to root, includes file_name)
language line_count           (computed by walker, given in the dict)

content                       (whole file's text, we dont store repo, only files, so if someone wishes to see the complete file can use this)

Queries: see docs/01-schema_db_cosine_similarity/schema-design.md

INDEX:
This is the first index we've added that isn't automatic, and it's justified by the language-breakdown and file-tree queries — both filter by repository_id, and neither can use the primary key.
Without it, "show the file tree for repo 7" would scan every file of every repository ever uploaded.
The source-viewer query uses WHERE id, already covered by the PK.

UNIQUE (repo_id, path) - 2 files with same path in a repo is bug
*/

CREATE TABLE files (
    id                  serial primary key,
    repository_id       integer not null references repositories(id) on delete cascade,

    path                text not null,
    language            text,
    line_count          integer,

    content             text not null,

    UNIQUE (repository_id, path)
);
CREATE INDEX ON files (repository_id);




/*
third table for code_chunks -
id(PK) 
repo_id(FK) file_id(FK)         (repo_id can be find with file_id but we still keep it becz every search filter by repo_id, if we dont write repo_id we need to do join everytime in query(denormalization))

content                         (content of chunk, redundant but we need chunk for every query to know exactly what text the vector belongs to immediately)

start_line end_line             

embedding                       ( vector(768) dimensions, sort by <=> cosine dist, cosine dist = 1 - cosine similarity, cosine_similarity = cos(theta) : increases as theta decreases, vector in same direction are most similar cos(0)=1)


The query it exists for

SELECT c.id, c.content, c.start_line, c.end_line, f.path,
       c.embedding <=> $2 AS distance
FROM code_chunks c
JOIN files f ON f.id = c.file_id
WHERE c.repository_id = $1
ORDER BY distance
LIMIT 8;

The query takes all the chunks, find cosine dist of each stored chunk's vector with the search vector. Then join with files table to get parent files of each chunk, then order the files by distance and take top 8 => we get top 8 similar chunks+file_path 
The join is only to fetch path for the citation — the filter stays on code_chunks, which is the point of storing repository_id here.

INDEXES :
on repo_id  - search filter (every similarity search need to be done in same repo)
on file_id  - for joining to file table for getting file info of the chunk


one more index we will build later: CREATE INDEX ON code_chunks USING hnsw (embedding vector_cosine_ops);
hnsw - built after data is loaded
vector_consine_ops : must match the query operator (<=> cosine)
its needed when thousands of vectors. 1 repo is just 355 rows, scanning it is faster than consulting the index

CONSTRAINT:

optional - unique(file_id, start_line) : 2 chunks of a file starting at same line is bug
*/


CREATE TABLE code_chunks (
    id                      serial primary key,
    repository_id           integer not null references repositories(id) on delete cascade,
    file_id                 integer not null references files(id) on delete cascade,

    content                 text not null,
    start_line              integer not null,
    end_line                integer not null,

    embedding               vector(768), 

    UNIQUE(file_id, start_line) 
);
CREATE INDEX ON code_chunks (repository_id);
CREATE INDEX ON code_chunks (file_id);
