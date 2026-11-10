"""Install a DMG into an isolated directory and smoke-test its native app."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import subprocess
import tempfile


def verify(dmg: Path) -> None:
    subprocess.run(['hdiutil', 'verify', str(dmg)], check=True)
    with tempfile.TemporaryDirectory(prefix='researchos-dmg-') as directory:
        root = Path(directory)
        mount = root / 'mount'
        mount.mkdir()
        subprocess.run(['hdiutil', 'attach', str(dmg), '-readonly', '-nobrowse',
                        '-mountpoint', str(mount)], check=True)
        try:
            app = root / 'ResearcherOS.app'
            subprocess.run(['ditto', str(mount / 'ResearcherOS.app'), str(app)], check=True)
        finally:
            subprocess.run(['hdiutil', 'detach', str(mount)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        arch = 'arm64' if platform.machine() == 'arm64' else 'x86_64'
        for executable in (app / 'Contents/MacOS/ResearcherOS',
                           app / 'Contents/Resources/server/researchos-server'):
            subprocess.run(['lipo', str(executable), '-verify_arch', arch], check=True)
        subprocess.run([str(app / 'Contents/MacOS/ResearcherOS'),
                        f'--user-data-dir={root / "user-data"}'],
                       env=dict(os.environ, RESEARCHOS_SMOKE_TEST='1', KOI_DATA_DIR=str(root / 'data')),
                       timeout=90, check=True)
        print(f'DMG install, signature, native {arch} server and application launch OK')


if __name__ == '__main__':
    images = list((Path(__file__).resolve().parent / 'dist').glob('*.dmg'))
    if len(images) != 1:
        raise SystemExit(f'Expected one DMG, found {len(images)}')
    verify(images[0])
