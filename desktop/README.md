# ResearcherOS desktop

This first desktop build opens the existing ResearcherOS web UI in its own
window. It starts a bundled Python server on free loopback ports and shuts the
server down when the application exits. The first launch walks through existing
research projects or connecting a local Git repository, then asks where research
data should live. Its path and other application settings live under
`~/Library/Application Support/researchos-desktop/`, outside the research projects.

Both agent chats have a microphone button. Recording stops on a second click or
after two minutes; the pulse and audio level show that recording is active.
Speech is transcribed by the bundled local Faster Whisper engine and inserted
into the composer for review, never sent automatically. The multilingual base
model downloads once on first use into the application data directory. Audio
is removed from the temporary directory after transcription. The same CPU path
is packaged for macOS, Windows, and Linux.

## Install from a clone

The `main` branch uses **Quick Navigation** as its only interface. The gear
button opens settings for managing current and archived trees. Older saved
interface selections are ignored. The `beta` branch retains experimental
interface modes.

Double-click `installers/Установить ResearcherOS.command` in Finder.
The installer downloads checksum-verified uv and Node.js archives, provisions a
private Python 3.12 environment under `.tools/mac-installer/`, and builds the app.
It installs into `~/Applications/ResearcherOS.app` and creates a Desktop symlink.
No Homebrew, global Python/Node installation, or administrator password is needed.
An internet connection is required. Apple Silicon and Intel have separate native
build paths; both must be validated on their respective hardware before release.

Close the app, run `git pull`, and run the installer again to update. Project
folders and `~/Library/Application Support/researchos-desktop/` are not replaced.
The installer opens the app in reconfiguration mode, so the onboarding wizard
appears again even when a workspace was previously selected. Users can keep
the current workspace; their project files are never deleted by this flow.
The macOS onboarding first accepts an existing `tree/` directory. Otherwise it
attaches a repository with an existing research branch or creates the orphan
`koi-project` branch for a new repository. Research worktrees are placed at
`~/Documents/tree/<project>/koi-structure/`.
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

## Windows and Linux builds

The desktop UI and local Python server are shared across platforms. Windows and
Linux packages must be built on their respective operating systems because
PyInstaller does not cross-compile. The `Desktop Windows and Linux` GitHub
Actions workflow builds a Windows NSIS installer and a Linux AppImage, verifies
the bundled API and UI, then launches the packaged application in a clean runner.
Branch builds are available as workflow artifacts. Tagged releases publish verified installers to GitHub Releases. This is an automated
smoke check; installation, onboarding, Git integration, and updates still need
manual checks on a user desktop before release.

Build the Linux package on Ubuntu 22.04 (glibc 2.35) or an equivalent baseline,
not on a newer distribution. AppImage does not bundle glibc: a Python runtime
built on Ubuntu 24.04 can fail before startup on Ubuntu/Pop!_OS 22.04. CI builds
on Ubuntu 22.04 and tests that same AppImage on Ubuntu 22.04 and 24.04. The Linux
package targets Intel/AMD x86_64; ARM needs a separate build.

For a local build on Windows or Linux, install Python 3.12, Node.js 22, and Git.
From the repository root, install `requirements.txt` and `pyinstaller==6.16.0`,
then run `python desktop/build_server.py`. In `desktop/`, run `npm ci` and either
`npm run pack:win` or `npm run pack:linux`. The packages appear in
`desktop/dist/`. The installer does not supply Git, which is required to attach
research repositories.

## Release channels (Windows and Linux)

Push `vX.Y.Z` on a commit reachable from `main` for a stable release, or
`vX.Y.Z-beta-test.N` on a commit reachable from `beta` for an A/B-test release.
The `beta` branch keeps its name. `beta-test` identifies the distribution channel;
it does not implement assignment to experiment variants. Each experiment release
is marked Pre-release and explicitly excluded from Latest.

For example, after these workflow changes are present in the relevant branch:

```bash
# Stable, from the reviewed main commit:
git tag v0.2.0 <main-commit>
git push origin v0.2.0

# A/B testing, from the reviewed beta commit:
git tag v0.3.0-beta-test.1 <beta-commit>
git push origin v0.3.0-beta-test.1
```

Use a new tag for each release; do not move published tags. The workflow validates
the tag and branch ancestry before building, sets the packaged version from the
tag, and publishes only after Windows and Linux checks pass. Releases include
checksums, the source commit, and a link to the build. The standard GITHUB_TOKEN
with contents:write in the publishing job is sufficient; no extra token is needed.
Branch pushes and manual workflow runs build artifacts without publishing releases.
To retry a failed tagged build, rerun that workflow. If a release already exists,
publication fails rather than replacing its assets; use a new version for changes.

Stable downloads: https://github.com/CognitiveAISystems/ResearcherOS/releases/latest

A/B-test downloads: choose a `beta-test` prerelease at
https://github.com/CognitiveAISystems/ResearcherOS/releases

Windows and Linux installers are distributed through Releases, outside Git.
macOS still uses the source installer; signed,
notarized DMG distribution is a separate step requiring Apple Developer credentials
and validation on Apple Silicon and Intel hardware. In-place upgrades still need
manual validation; back up research data before the first upgrade.
