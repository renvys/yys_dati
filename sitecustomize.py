"""Project-local Python bootstrap for dependency discovery.

This lets `python main.py` work even when the virtual environment is not
activated, as long as the project-local `.venv` exists.
"""

from __future__ import annotations

import os
import site
import sys


def _add_project_venv_site_packages():
    project_root = os.path.dirname(os.path.abspath(__file__))
    venv_site_packages = os.path.join(project_root, ".venv", "Lib", "site-packages")

    if not os.path.isdir(venv_site_packages):
        return

    normalized = os.path.normcase(os.path.normpath(venv_site_packages))
    existing = {
        os.path.normcase(os.path.normpath(path))
        for path in sys.path
        if isinstance(path, str) and path
    }
    if normalized in existing:
        return

    site.addsitedir(venv_site_packages)


_add_project_venv_site_packages()
