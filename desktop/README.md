# ResearcherOS for macOS

This first desktop build opens the existing ResearcherOS web UI in its own
window. It starts a bundled Python server on free loopback ports and shuts the
server down when the application exits. The first launch asks for a workspace
folder; its path and other application settings live under
`~/Library/Application Support/researchos-desktop/`, outside the research projects.

## Install from a clone

Double-click `Установить ResearcherOS.command` in the repository root in Finder.
The installer downloads checksum-verified uv and Node.js archives, provisions a
private Python 3.12 environment under `.tools/mac-installer/`, and builds the app.
It installs into `~/Applications/ResearcherOS.app` and creates a Desktop symlink.
No Homebrew, global Python/Node installation, or administrator password is needed.
An internet connection is required. Apple Silicon and Intel have separate native
build paths; both must be validated on their respective hardware before release.

Close the app, run `git pull`, and run the installer again to update. Project
folders and `~/Library/Application Support/researchos-desktop/` are not replaced.
The `.command` launcher saves a timestamped log under `.run/logs/` and keeps
Terminal open on both success and failure. A running app blocks replacement.

The supplied artwork is preserved in `assets/icon-source.png`; `icon.png` is a
square, transparent canvas with the artwork fitted proportionally, and
`icon.icns` is the bundled macOS icon. No image generation is used.

## Development

From the repository root, create a Python 3.10+ virtual environment and install
`requirements.txt` plus `pyinstaller`. Then, in `desktop/`, run `npm ci` and
`npm start`. The shell uses `../.venv/bin/python` when available.

## Build

Run `npm run pack:mac` from `desktop/`. The script builds the Python server and
creates `desktop/dist/mac-arm64/ResearcherOS.app` on Apple Silicon. The installer uses an ad-hoc signature, which does not identify the developer
to Apple. Public distribution still needs a Developer ID signature, notarization,
and checks on a separate clean Mac. The current build is for local testing.

The desktop renderer has no Node.js access. External links open in the system
browser; they can later become isolated ResearcherOS browser tabs.
