# pipeline/clone.py : turn a GitHub URL into a folder on disk.
#
# Runs before walk.py. The folder it produces is temporary — a repository's
# permanent copy is its rows in Postgres, so the clone is deleted as soon as
# indexing has read it.
#
# How all of this works, from the basics: docs/19-cloning_a_repo/cloning.html

# urlparse splits a URL into .scheme / .netloc / .path, so nothing here counts
# slashes. Standard library, nothing to install.
from urllib.parse import urlparse

import tempfile   # standard library module for temporary files and folders

import subprocess   # runs other programs as child processes — git is a program, not a library
from contextlib import contextmanager   # turns a yield-function into a `with` block

def parse_github_url(url):
    """Pull the owner and repository name out of a GitHub URL.

    IN   url    str — "https://github.com/amritrwt22/RepoLens"
    OUT  (owner, repo)   ("amritrwt22", "RepoLens")

    Only that exact shape is accepted; nothing is trimmed or guessed at, so a
    trailing slash, a file or branch URL, the .git clone URL and the ssh form
    are all refused.

    Raises ValueError showing the accepted format, since whoever typed the URL
    reads that message.
    """
    parsed = urlparse(url)

    # "/amritrwt22/RepoLens" -> ["amritrwt22", "RepoLens"]
    segments = parsed.path.lstrip("/").split("/")

    # The length check must stay ahead of segments[1]: a one-segment path would
    # otherwise raise IndexError instead of the message below.
    if (parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or len(segments) != 2
            or segments[1].endswith(".git")):
        raise ValueError(
            f"bad repository URL: {url}\n"
            "use: https://github.com/<owner>/<repo>\n"
            "for example: https://github.com/amritrwt22/RepoLens"
        )

    return segments[0], segments[1]


class GitError(Exception):
    """A git command failed. The parent of every failure in this file, so a
    caller can write one `except GitError` instead of listing each kind."""

class CloneError(GitError):
    """git could not clone the repository."""

class CommitError(GitError):
    """git could not read the commit the folder is sitting on."""

def clone_into(url, path):
    """Clone a repository into an empty folder.

    IN   url    str — "https://github.com/amritrwt22/RepoLens"
         path   str — an empty folder to clone into

    Returns nothing. Afterwards the folder holds the repository's files.

    Raises CloneError if git fails. Four reasons, and they cannot be told
    apart: the repository does not exist, it is private, the URL is one git
    rejects, or there is no network.
    """
    # subprocess.run starts git as a child process, waits for it to end, then
    # builds a CompletedProcess object out of what happened and returns it.
    # Storing it is the only way to see any of that — without a name the object
    # is thrown away the moment it comes back.
    #
    # Four fields on it:
    #   result.args         the command we gave it
    #   result.returncode   0 if git succeeded, 128 if the repo was not found
    #   result.stdout       None — git's output went to the terminal, not to us
    #   result.stderr       None — same. Both would hold git's text if we ever
    #                       passed capture_output=True, which we have not needed
    result = subprocess.run(
        ["git", "clone", "--depth", "1", url, path]
    )

    # Every program ends with an exit code: 0 means it worked, any other number
    # means it failed. run() never looks at it, so without this check a failed
    # clone looks like a good one.
    #
    # Raised rather than handled here: this function has only a url and a path,
    # so it has no job row to write to and no idea whether it is running under
    # a terminal, a worker or a test. It reports; the caller decides.
    #
    # CloneError rather than a plain Exception, so the caller can tell a failed
    # clone apart from anything else that goes wrong around it.
    if result.returncode != 0:
        raise CloneError(f"could not clone {url} — git exited {result.returncode}")

def read_head_commit(path):
    """Read the commit a cloned folder is sitting on.

    IN   path   str — a folder containing a git repository
    OUT  str    the full 40-character sha,
                "e44361b584d136ce7526a2604ca225f63729ad14"

    The sha identifies exactly which version of the code is in that folder.
    It goes into repositories.commit_sha, and into every citation link so a
    cited line points at the file as it was when indexed.

    Raises CommitError if git cannot resolve HEAD, which happens when the
    repository has no commits.
    """
    # -C runs git as if it were started in that folder. rev-parse turns a name
    # into the sha it refers to, and HEAD is the commit currently checked out.
    #
    # capture_output=True is what puts git's output into result.stdout. Without
    # it that field is None — git prints straight to the terminal and python
    # never holds it. clone_into did not need this; here the sha IS the output.
    #
    # text=True makes that output a string. Without it stdout is bytes:
    # b'e44361b...' rather than 'e44361b...'
    result = subprocess.run(
        ["git", "-C", path, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )

    # HEAD points at the current branch, which holds a sha. A repository with
    # no commits has the pointer but nothing to point at, so git echoes the
    # name back — the literal string "HEAD" — and exits 128.
    if result.returncode != 0:
        raise CommitError(f"could not read the commit in {path} — git exited {result.returncode}")

    # git prints the sha followed by a newline. Left in, it would end up in the
    # database and inside every citation URL.
    return result.stdout.strip()

@contextmanager
def clone_repo(url):
    """Clone a repository, hand it over, then delete the folder.

    IN   url    str — "https://github.com/amritrwt22/RepoLens"
    OUT  yields (path, owner, repo, sha) for the duration of a `with` block

        with clone_repo(url) as (path, owner, repo, sha):
            walk, chunk, embed, store

    Raises ValueError for a URL that is not a GitHub repository, CloneError if
    git cannot clone it, CommitError if it has no commits. None are caught here
    — this function has no job row to write to and no idea who called it.
    """
    # Before the folder, so its name can carry the owner and repo. A leaked
    # folder is then searchable and says which clone it was:
    #   repolens_amritrwt22_RepoLens_pt775icj
    owner, repo = parse_github_url(url)

    # TemporaryDirectory calls mkdtemp underneath, so the folder is still made
    # by the OS with a random name and mode 700. What it adds is the deleting:
    # this `with` removes the folder on the way out, whether the block below
    # finished or raised.
    with tempfile.TemporaryDirectory(prefix=f"repolens_{owner}_{repo}_") as path:
        clone_into(url, path)
        sha = read_head_commit(path)

        # Hand the four values over and PAUSE here. This function stays alive,
        # suspended, while the caller's `with` block runs, then resumes on the
        # line after it ends — which falls out of the `with` above and deletes.
        yield path, owner, repo, sha
