"""Vstupní bod sestavené aplikace (PyInstaller) – totéž co příkaz `repo-doctor`."""

import sys

from repo_doctor.cli import main

if __name__ == "__main__":
    sys.exit(main())
