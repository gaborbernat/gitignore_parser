import os
import subprocess
from collections import namedtuple
from pathlib import Path
from typing import Any, Callable, Dict, Sequence

import pytest
from _pytest.monkeypatch import MonkeyPatch

from vcs_ignore.git import walk
from vcs_ignore.git._impl import GIT_EXE


@pytest.fixture()
def build(tmp_path):
    def _build(files):
        for file, content in files.items():
            dest = tmp_path / file
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        return tmp_path

    return _build


TestCase = namedtuple("TestCase", ["files", "patterns", "found"])
WALK_TESTS = {
    "one_file_match_no_ignore": TestCase({"a.py": ""}, ["*.py"], ["a.py"]),
    "one_file_no_match_no_ignore": TestCase({"a.py": ""}, ["*.pyi"], []),
    "one_file_match_ignore": TestCase({"a.py": "", ".gitignore": "*.pyi"}, ["*.py"], ["a.py"]),
    "one_file_no_match_ignore": TestCase({"a.py": "", ".gitignore": "*.xy"}, ["*.pyi"], []),
    "one_file_no_match_via_ignore": TestCase({"a.py": "", ".gitignore": "*.py"}, ["*.py"], []),
}


@pytest.mark.parametrize("case", WALK_TESTS.values(), ids=list(WALK_TESTS.keys()))
def test_walk(case: TestCase, build: Callable[[Dict[str, str]], Path]) -> None:
    path = build(case.files)
    result = [f for f in walk(path, case.patterns)]
    expected = [path / f for f in case.found]
    assert result == expected


IS_INSIDE_CI = "CI_RUN" in os.environ


def need_executable(name: str, check_cmd: Sequence[str]) -> Any:
    """skip running this locally if executable not found, unless we're inside the CI"""

    def wrapper(fn):
        fn = getattr(pytest.mark, name)(fn)
        if not IS_INSIDE_CI:
            # locally we disable, so that contributors don't need to have everything setup
            # noinspection PyBroadException
            try:
                fn.version = subprocess.check_output(check_cmd)
            except Exception as exception:
                return pytest.mark.skip(reason="{} is not available due {}".format(name, exception))(fn)
        return fn

    return wrapper


def requires(*cmd: str):
    _cmd = list(cmd)

    def wrapper(fn):
        return need_executable(_cmd[0], _cmd)(fn)

    return wrapper


@requires(GIT_EXE, "--version")
@pytest.mark.parametrize("case", WALK_TESTS.values(), ids=list(WALK_TESTS.keys()))
def test_walk_git(case: TestCase, build: Callable[[Dict[str, str]], Path], monkeypatch: MonkeyPatch) -> None:
    path = build(case.files)
    monkeypatch.chdir(path)
    git("git", "init")
    git("git", "add", "-A", ".")
    git("git", "commit", "-m", "create")

    result = [str(f.relative_to(path)) for f in walk(path, case.patterns)]
    expected = [str(f) for f in case.found]
    assert result == expected


def git(*cmd: str) -> None:
    env = os.environ.copy()
    env["GIT_COMMITTER_NAME"] = "committer joe"
    env["GIT_AUTHOR_NAME"] = "author joe"
    env["EMAIL"] = "joe@bloomberg.com"
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, env=env)
    out, err = proc.communicate()
    assert not proc.returncode, "{}{}".format(out, err)


def test_git_call_fails(build: Callable[[Dict[str, str]], Path], monkeypatch: MonkeyPatch) -> None:
    case = TestCase({"a.py": ""}, ["*.py"], ["a.py"])
    path = build(case.files)
    bad_git = path / GIT_EXE
    from vcs_ignore.git import _impl

    monkeypatch.setattr(_impl, "GIT_EXE", str(bad_git))

    result = [f for f in walk(path, case.patterns)]
    expected = [path / f for f in case.found]
    assert result == expected
