# ResearcherOS for macOS

This first desktop build opens the existing ResearcherOS web UI in its own
window. It starts a bundled Python server on free loopback ports and shuts the
server down when the application exits. The first launch asks for a workspace
folder; its path and other application settings live under
`~/Library/Application Support/ResearcherOS/`, outside the research projects.

## Development

From the repository root, create a Python 3.10+ virtual environment and install
`requirements.txt` plus `pyinstaller`. Then, in `desktop/`, run `npm ci` and
`npm start`. The shell uses `../.venv/bin/python` when available.

## Build

Run `npm run pack:mac` from `desktop/`. The script builds the Python server and
creates `desktop/dist/mac-arm64/ResearcherOS.app` on Apple Silicon. A release
build still needs an Apple Developer ID signature, notarization, an app icon,
and checks on a separate clean Mac. The current build is for local testing.

The desktop renderer has no Node.js access. External links open in the system
browser; they can later become isolated ResearcherOS browser tabs.
