# vcs_ignore
A spec-compliant VCS parser for Python 3.5+, supports:

- git

## Installation

    pip install vcs_ignore

## Usage
Suppose `~/project/.gitignore` contains the following:

    __pycache__/
    *.py[cod]

Then:

    >>> from vcs_ignore import parse_git
    >>> matches = parse_git('~/project/.gitignore')
    >>> matches('~/project/main.py')
    False
    >>> matches('~/project/main.pyc')
    True
    >>> matches('~/project/dir/main.pyc')
    True
    >>> matches('~/project/__pycache__')
    True
