"""
The format is detailed under https://git-scm.com/docs/gitignore
"""
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Generator, Iterable, Optional, Tuple

GIT_EXE = "git.exe" if sys.platform == "win32" else "git"


def walk(path: Path, patterns: Iterable[str]) -> Generator[Path, None, None]:
    """
    Return all files that match some list of patterns by taking into account .gitignore.

    Note .gitignore is a suggestion, users can still force stuff into VCS, for 100% accuracy of what's
    within the repository one should use the ``git ls-files`` command (this will be also faster) - for
    example to get all Python source or extension use: ``git ls-files '*.py' '*.pyi'``.

    :param path:
    :param patterns:
    :return:
    """
    # first try to ask git what the files are
    gen = _walk_via_git(path, patterns)
    while True:
        try:
            yield next(gen)
        except StopIteration as stop:
            if stop.value is True:
                return
            break
    # if that fails fallback to walk the filesystem and our gitingore interpretation
    yield from _walk_via_ignore(path, patterns)


def _walk_via_git(path: Path, patterns: Iterable[str]) -> Generator[Path, None, bool]:
    # noinspection PyBroadException
    try:
        proc = subprocess.Popen(
            [GIT_EXE, "ls-files", "-c", "-m", *patterns],
            cwd=str(path),
            universal_newlines=True,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
        )
        out, _ = proc.communicate()
        out = out.rstrip()
        if not proc.returncode and out:
            for cur in out.split(os.linesep):
                full_path = path / cur
                yield full_path
            return True
    except Exception:
        pass
    return False


def _walk_via_ignore(path: Path, patterns: Iterable[str]) -> Generator[Path, None, None]:
    matcher = parse(path / ".gitignore")
    for _, dirs, files in os.walk(str(path)):
        for file in files:
            dest = path / file
            if not matcher(dest):
                if not patterns or any(fnmatch.fnmatch(str(dest), p) for p in patterns):
                    yield dest
                    continue
        for cur_dir in list(dirs):
            if matcher(Path(cur_dir).absolute()):
                dirs.remove(cur_dir)


def parse(full_path: Path, base_dir: Optional[Path] = None) -> Callable[[Path], bool]:
    if base_dir is None:
        base_dir = full_path.parent
    rules = []
    if not full_path.exists() or not full_path.is_file():
        return lambda file_path: False
    for counter, line in enumerate(full_path.read_text().splitlines(keepends=False), start=1):
        rule = rule_from_pattern(line, base_dir.absolute(), source=(full_path, counter))
        if rule:
            rules.append(rule)
    return lambda file_path: any(r.match(file_path) for r in rules)


class IgnoreRule:

    __slots__ = ("pattern", "regex", "negation", "directory_only", "anchored", "base_path", "source")

    def __init__(
        self,
        pattern: str,
        regex: str,
        negation: bool,
        directory_only: bool,
        anchored: bool,
        base_path: Optional[Path],
        source: Optional[Tuple[Path, int]],
    ):
        self.pattern = pattern
        self.regex = regex
        self.negation = negation
        self.directory_only = directory_only
        self.anchored = anchored  # Behavior flags
        self.base_path = base_path  # Meaningful for gitignore-style behavior
        self.source = source  # (file, line) tuple for reporting

    def match(self, abs_path: Path) -> bool:
        matched = False
        if self.base_path:
            rel_path = str(abs_path.relative_to(str(self.base_path)))
        else:
            rel_path = str(abs_path)
        if rel_path.startswith("./"):
            rel_path = rel_path[2:]
        if re.search(self.regex, rel_path):
            matched = True
        return matched


def rule_from_pattern(
    pattern: str, base_path: Optional[Path] = None, source: Optional[Tuple[Path, int]] = None
) -> Optional[IgnoreRule]:
    """
    Take a .gitignore match pattern, such as "*.py[cod]" or "**/*.bak",
    and return an IgnoreRule suitable for matching against files and
    directories. Patterns which do not match files, such as comments
    and blank lines, will return None.
    Because git allows for nested .gitignore files, a base_path value
    is required for correct behavior. The base path should be absolute.
    """
    if base_path and base_path != base_path.absolute():
        raise ValueError("base_path must be absolute")
    # Store the exact pattern for our repr and string functions
    orig_pattern = pattern
    # Early returns follow
    # Discard comments and seperators
    if pattern.strip() == "" or pattern[0] == "#":
        return None
    # Discard anything with more than two consecutive asterisks
    if pattern.find("***") > -1:
        return None
    # Strip leading bang before examining double asterisks
    if pattern[0] == "!":
        negation = True
        pattern = pattern[1:]
    else:
        negation = False
    # Discard anything with invalid double-asterisks -- they can appear
    # at the start or the end, or be surrounded by slashes
    for m in re.finditer(r"\*\*", pattern):
        start_index = m.start()
        if (
            start_index != 0
            and start_index != len(pattern) - 2
            and (pattern[start_index - 1] != "/" or pattern[start_index + 2] != "/")
        ):
            return None

    # Special-casing '/', which doesn't match any files or directories
    if pattern.rstrip() == "/":
        return None

    directory_only = pattern[-1] == "/"
    # A slash is a sign that we're tied to the base_path of our rule
    # set.
    anchored = "/" in pattern[:-1]
    if pattern[0] == "/":
        pattern = pattern[1:]
    if pattern[0] == "*" and pattern[1] == "*":
        pattern = pattern[2:]
        anchored = False
    if pattern[0] == "/":
        pattern = pattern[1:]
    if pattern[-1] == "/":
        pattern = pattern[:-1]
    regex = fnmatch_pathname_to_regex(pattern)
    if anchored:
        regex = "".join(["^", regex])
    return IgnoreRule(
        pattern=orig_pattern,
        regex=regex,
        negation=negation,
        directory_only=directory_only,
        anchored=anchored,
        base_path=base_path if base_path else None,
        source=source,
    )


WHITESPACE_RE = re.compile(r"(\\ )+$")


# Frustratingly, python's fnmatch doesn't provide the FNM_PATHNAME
# option that .gitignore's behavior depends on.
def fnmatch_pathname_to_regex(pattern: str) -> str:
    """
    Implements fnmatch style-behavior, as though with FNM_PATHNAME flagged;
    the path separator will not match shell-style '*' and '.' wildcards.
    """
    i, n = 0, len(pattern)
    non_sep = "".join(["[^", os.sep, "]"])
    res = []
    while i < n:
        c = pattern[i]
        i = i + 1
        if c == "*":
            try:
                if pattern[i] == "*":
                    i = i + 1
                    res.append(".*")
                    if pattern[i] == "/":
                        i = i + 1
                        res.append("".join([os.sep, "?"]))
                else:
                    res.append("".join([non_sep, "*"]))
            except IndexError:
                res.append("".join([non_sep, "*"]))
        elif c == "?":
            res.append(non_sep)
        elif c == "/":
            res.append(os.sep)
        elif c == "[":
            j = i
            if j < n and pattern[j] == "!":
                j = j + 1
            if j < n and pattern[j] == "]":
                j = j + 1
            while j < n and pattern[j] != "]":
                j = j + 1
            if j >= n:
                res.append("\\[")
            else:
                stuff = pattern[i:j].replace("\\", "\\\\")
                i = j + 1
                if stuff[0] == "!":
                    stuff = "".join("^" + stuff[1:])
                elif stuff[0] == "^":
                    stuff = "".join("\\" + stuff)
                res.append("[{}]".format(stuff))
        else:
            res.append(re.escape(c))
    res.insert(0, "(?ms)")
    res.append(r"\Z")
    return "".join(res)
