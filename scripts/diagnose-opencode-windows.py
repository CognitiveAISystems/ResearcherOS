"""Reproduce Windows command limits and exercise the real OpenCode adapter offline.

Run on Windows: python scripts/diagnose-opencode-windows.py --output result.json
On other systems --self-test checks the harness, without claiming Windows results.
The child replaces the model with a hash echo; no credentials or API calls are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from koi.adapters import agent_backends

CHILD = '''import hashlib, json, pathlib, sys
args = sys.argv[1:]
if "--help" in args:
    print("--agent --model --format --file")
else:
    text = pathlib.Path(args[args.index("--file") + 1]).read_text(encoding="utf-8") if "--file" in args else args[-1]
    result = {"characters": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    print(json.dumps({"type": "text", "part": {"text": json.dumps(result)}}))
'''


def digest(text):
    return {"characters": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def invoke(command, expected):
    row = {"command_utf16_units": len(subprocess.list2cmdline(command).encode("utf-16-le")) // 2}
    try:
        proc = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", timeout=20, stdin=subprocess.DEVNULL)
        row.update(exit_code=proc.returncode, stdout_bytes=len(proc.stdout.encode()), stderr_bytes=len(proc.stderr.encode()))
        try:
            event = json.loads(proc.stdout)
            row["intact"] = proc.returncode == 0 and json.loads(event["part"]["text"]) == expected
        except (ValueError, KeyError, TypeError):
            row["intact"] = False
    except OSError as exc:
        row.update(intact=False, error_type=type(exc).__name__, winerror=getattr(exc, "winerror", None))
    except subprocess.TimeoutExpired:
        row.update(intact=False, error_type="TimeoutExpired")
    return row


def diagnose(self_test=False):
    windows = sys.platform == "win32"
    if not windows and not self_test:
        raise SystemExit("Requires Windows. --self-test only validates the harness on the current OS.")
    rows = []
    with tempfile.TemporaryDirectory(prefix="researcheros-win-diagnostic-") as directory:
        root = Path(directory)
        child = root / "echo-cli.py"
        child.write_text(CHILD, encoding="utf-8")
        wrapper = root / "echo-cli.cmd"
        wrapper.write_text(f'@echo off\n"{sys.executable}" "{child}" %*\n', encoding="utf-8")
        task = root / "task.txt"
        for size in (500, 28500, 50000):
            # Safe ASCII isolates the length limit from cmd quoting and Unicode issues.
            text = "x" * size
            expected = digest(text)
            task.write_text(text, encoding="utf-8")
            for transport, prefix in (("native-exe", [sys.executable, str(child)]), ("cmd-wrapper", [str(wrapper)])):
                if transport == "cmd-wrapper" and not windows:
                    continue
                for via_file in (False, True):
                    command = prefix + ["run", "--agent", "plan", "--format", "json"] + (["Read attached task", "--file", str(task)] if via_file else [text])
                    row = {"size": size, "transport": transport, "via_file": via_file, **invoke(command, expected)}
                    should_work = via_file or (size < (8191 if transport == "cmd-wrapper" else 32767)) or not windows
                    row["matches_expectation"] = row["intact"] == should_work
                    rows.append(row)
            if windows:
                with patch.object(agent_backends, "_opencode_bin", return_value=str(wrapper)), patch.dict(os.environ, {"KOI_OPENCODE_ARGS": "", "KOI_OPENCODE_MODEL": ""}):
                    answer = agent_backends.run_opencode(text, cwd=root, timeout=20)
                intact = bool(answer) and json.loads(answer) == expected
                rows.append({"size": size, "transport": "fixed-run_opencode", "intact": intact, "matches_expectation": intact})
    return {"platform": platform.platform(), "python": platform.python_version(), "windows_executed": windows,
            "scope": "OS command transport and real adapter with an offline echo CLI; no live OpenCode/provider request",
            "passed": all(row["matches_expectation"] for row in rows), "cases": rows}


def diagnose_real_cli(binary):
    """No credentials: explicitly request the free model shown in the user's example."""
    binary = str(binary.resolve())
    version = subprocess.run([binary, '--version'], capture_output=True, encoding='utf-8', errors='replace', timeout=20)
    flags = sorted(agent_backends._opencode_run_flags(binary))
    rows = []
    with tempfile.TemporaryDirectory(prefix='researcheros-real-opencode-') as directory:
        root = Path(directory)
        for size in (500, 28500):
            prompt = 'Reply with just OK. The following whitespace is padding.\n' + ' ' * size
            # The old onboarding path used plain output and unconditionally passed --standalone.
            command = [binary, '--standalone', 'run', '--model', 'opencode/big-pickle', '--agent', 'plan', prompt]
            try:
                proc = subprocess.run(command, cwd=root, capture_output=True, encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL, timeout=90)
                rows.append({'path': 'old-onboarding', 'size': len(prompt), 'exit_code': proc.returncode,
                             'stdout_tail': proc.stdout[-1200:], 'stderr_tail': proc.stderr[-1200:]})
            except (OSError, subprocess.TimeoutExpired) as exc:
                rows.append({'path': 'old-onboarding', 'size': len(prompt), 'error': type(exc).__name__, 'winerror': getattr(exc, 'winerror', None)})
            try:
                with patch.object(agent_backends, '_opencode_bin', return_value=binary), patch.dict(os.environ, {'KOI_OPENCODE_ARGS': '', 'KOI_OPENCODE_MODEL': ''}):
                    answer = agent_backends.run_opencode(prompt, cwd=root, model='opencode/big-pickle', timeout=90)
                rows.append({'path': 'fixed-adapter', 'size': len(prompt), 'answer': answer})
            except agent_backends.AgentBackendError as exc:
                rows.append({'path': 'fixed-adapter', 'size': len(prompt), 'provider_error': str(exc)[:1200]})
    return {'platform': platform.platform(), 'windows_executed': sys.platform == 'win32', 'version': version.stdout.strip(),
            'supported_optional_flags': flags, 'scope': 'Real installed OpenCode, explicit opencode/big-pickle, no account credentials supplied', 'cases': rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--real-opencode", type=Path)
    args = parser.parse_args()
    result = diagnose_real_cli(args.real_opencode) if args.real_opencode else diagnose(args.self_test)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    raise SystemExit(0 if result.get("passed", True) else 1)
