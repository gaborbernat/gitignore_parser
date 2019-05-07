import textwrap

from setuptools import setup

setup(
    package_dir={"": "src"},
    use_scm_version={
        "write_to": "src/vcs_ignore/version.py",
        "write_to_template": textwrap.dedent(
            '''
        """contains version information"""
        from __future__ import unicode_literals

        from typing import Text

        __version__ = "{version}"  # type: Text
        '''
        ).lstrip(),
    },
)
