# Third-party notices

FilePilot's own source is available under the MIT license in `LICENSE`.

The Windows package includes Python, PySide6 / Shiboken6 / Qt, SQLite and their
runtime dependencies. These components retain their respective licenses and
copyrights. Bundled license texts are in `third_party/` (inside `_internal/` in
the directory-based executable distribution).

- Python: https://docs.python.org/3/license.html
- Qt for Python: https://doc.qt.io/qtforpython-6/licenses.html
- Qt: https://www.qt.io/licensing/open-source-lgpl-obligations
- SQLite: https://www.sqlite.org/copyright.html
- PyInstaller: https://pyinstaller.org/en/stable/license.html

Build tools are installed in an isolated project directory during local
validation; they do not change the system Python environment. Windows fonts
are loaded from the user's operating system when needed and are not bundled.

This file identifies components and points to their own notices. It does not
relicense third-party components under FilePilot's MIT license.
