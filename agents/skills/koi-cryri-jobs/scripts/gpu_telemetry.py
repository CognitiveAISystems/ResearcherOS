#!/usr/bin/env python3
"""Sample real GPU metrics in a job, or plot the last five hours locally."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

PREFIX = 'CRYRI_GPU_SAMPLE '
UTC = timezone.utc


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Timestamp must be an ISO string')
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('Timestamps must include a timezone')
    return d.astimezone(UTC)


def number(s):
    try:
        x = float(s.strip())
        return x if math.isfinite(x) else None
    except ValueError:
        return None


def gpu_sample(run_name, executable='nvidia-smi'):
    record = {'timestamp': datetime.now(UTC).isoformat(), 'run_name': run_name, 'gpus': []}
    try:
        result = subprocess.run([executable, '--query-gpu=index,uuid,memory.used,memory.total,utilization.gpu',
                                 '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=15, check=True)
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) != 5:
                continue
            index, gpu, used, total, util = [s.strip() for s in row]
            used, total, util = number(used), number(total), number(util)
            record['gpus'].append({'index': index, 'uuid': gpu,
                                   'memory_used_mib': used if used is not None and used >= 0 else None,
                                   'memory_total_mib': total if total is not None and total > 0 else None,
                                   'utilization_pct': util if util is not None and 0 <= util <= 100 else None})
        if not record['gpus']:
            record['error'] = 'no_gpu_metrics'
    except (OSError, subprocess.SubprocessError) as e:
        record['error'] = type(e).__name__  # Never print command stderr/environment.
    return record


def sample(args):
    if args.interval <= 0:
        raise ValueError('interval must be positive')
    if 'volovikova' not in args.run_name.lower():
        raise ValueError('run-name must include volovikova')
    stop = threading.Event()
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *_: stop.set())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('a', buffering=1) as f:
        while not stop.is_set():
            row = gpu_sample(args.run_name)
            line = json.dumps(row, separators=(',', ':'))
            f.write(line + '\n')
            print(PREFIX + line, flush=True)
            if args.once:
                break
            stop.wait(args.interval)


def run(args):
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        raise ValueError('run requires -- followed by the workload command')
    if args.interval <= 0 or 'volovikova' not in args.run_name.lower():
        raise ValueError('Use a positive interval and a volovikova run-name')
    monitor = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'sample',
                                '--output', str(args.output), '--run-name', args.run_name,
                                '--interval', str(args.interval)])
    workload = None
    previous = {}
    def forward(sig, _frame):
        if workload is not None and workload.poll() is None:
            os.killpg(workload.pid, sig)
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, forward)
        workload = subprocess.Popen(command, start_new_session=True)
        return workload.wait()
    finally:
        monitor.terminate()
        try:
            monitor.wait(timeout=20)
        except subprocess.TimeoutExpired:
            monitor.kill()
            monitor.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def read_samples(path):
    rows, errors = [], 0
    if not path.exists():
        return rows, errors
    for line in path.read_text(errors='replace').splitlines():
        if PREFIX in line:
            line = line.split(PREFIX, 1)[1]
        elif not line.startswith('{'):
            continue
        try:
            row = json.loads(line)
            timestamp(row['timestamp'])
            if not isinstance(row.get('gpus'), list):
                raise ValueError('missing GPU list')
            rows.append(row)
        except (ValueError, KeyError, TypeError):
            errors += 1
    return rows, errors


def summarize(rows, *, end, hours=5, interval=60, threshold=20, expected_gpus=None):
    if hours <= 0 or interval <= 0 or not 0 <= threshold <= 100:
        raise ValueError('Invalid analysis window, interval or threshold')
    start = end - timedelta(hours=hours)
    devices = {}
    for row in rows:
        t = timestamp(row['timestamp'])
        if not start - timedelta(seconds=interval) <= t <= end:
            continue
        for gpu in row['gpus']:
            if not isinstance(gpu, dict) or not gpu.get('uuid'):
                continue
            devices.setdefault(gpu['uuid'], {})[t] = gpu
    summaries, series = [], {}
    for gpu_id, points in sorted(devices.items()):
        points = sorted(points.items())  # Duplicate log/file samples count once.
        series[gpu_id] = points
        covered, util_sum, memory_sum, memory_covered, last_valid = 0, 0, 0, 0, None
        for i, (t, gpu) in enumerate(points):
            next_t = points[i + 1][0] if i + 1 < len(points) else end
            right = min(next_t, t + timedelta(seconds=interval), end)
            weight = max(0, (right - max(start, t)).total_seconds())
            util = gpu.get('utilization_pct')
            if isinstance(util, (int, float)) and math.isfinite(util) and 0 <= util <= 100:
                covered += weight
                util_sum += util * weight
                last_valid = t
            memory = gpu.get('memory_used_mib')
            if isinstance(memory, (int, float)) and math.isfinite(memory) and memory >= 0:
                memory_sum += memory * weight
                memory_covered += weight
        coverage = covered / (hours * 3600)
        fresh = last_valid is not None and (end - last_valid).total_seconds() <= 2 * interval
        sufficient = coverage >= .8 and fresh
        mean = util_sum / covered if covered else None
        verdict = ('poor' if mean < threshold else 'healthy') if sufficient else 'insufficient_data'
        summaries.append({'uuid': gpu_id, 'samples': len(points), 'coverage': coverage,
                          'fresh': fresh, 'mean_utilization_pct': mean,
                          'mean_memory_gib': memory_sum / memory_covered / 1024 if memory_covered else None,
                          'verdict': verdict})
    missing = expected_gpus is not None and len(summaries) != expected_gpus
    verdicts = {s['verdict'] for s in summaries}
    complete = bool(summaries) and not missing and 'insufficient_data' not in verdicts
    verdict = ('poor' if 'poor' in verdicts else 'healthy') if complete else 'insufficient_data'
    return {'window_start': start.isoformat(), 'window_end': end.isoformat(),
            'threshold_pct': threshold, 'expected_gpus': expected_gpus,
            'gpu_count_mismatch': missing, 'verdict': verdict, 'gpus': summaries}, series


def report(args):
    rows, errors = read_samples(args.input)
    end = timestamp(args.until) if args.until else datetime.now(UTC)
    summary, series = summarize(rows, end=end, hours=args.hours, interval=args.interval,
                                threshold=args.threshold, expected_gpus=args.expected_gpus)
    summary['parse_errors'] = errors
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    for gpu_id, points in series.items():
        xs, utilization, memory = [], [], []
        for i, (t, g) in enumerate(points):
            if i and (t - points[i - 1][0]).total_seconds() > args.interval * 2:
                xs.append(t); utilization.append(None); memory.append(None)
            xs.append(t)
            utilization.append(g.get('utilization_pct'))
            used = g.get('memory_used_mib')
            memory.append(used / 1024 if isinstance(used, (int, float)) else None)
        label = gpu_id if len(gpu_id) < 20 else gpu_id[:18]
        axes[0].plot(xs, utilization, label=label, linewidth=1)
        axes[1].plot(xs, memory, label=label, linewidth=1)
    axes[0].axhline(args.threshold, color='firebrick', linestyle='--', label=f'Alert below {args.threshold:g}%')
    axes[0].set(ylabel='GPU utilization (%)', ylim=(-2, 102))
    axes[1].set(ylabel='GPU memory used (GiB)', xlabel='Time (UTC)')
    axes[1].set_xlim(timestamp(summary['window_start']), end)
    for ax in axes:
        ax.grid(alpha=.25)
        if series:
            ax.legend(loc='upper left', fontsize=8)
        else:
            ax.text(.5, .5, 'No GPU measurements', ha='center', transform=ax.transAxes)
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=UTC))
    fig.suptitle(f'{args.title} — {summary["verdict"]}')
    fig.tight_layout()
    fig.savefig(args.output_dir / 'gpu.png', dpi=150)
    plt.close(fig)
    print(json.dumps(summary, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for mode in ('sample', 'run'):
        p = sub.add_parser(mode)
        p.add_argument('--output', type=Path, required=True)
        p.add_argument('--run-name', required=True)
        p.add_argument('--interval', type=float, default=60)
        if mode == 'sample':
            p.add_argument('--once', action='store_true')
        else:
            p.add_argument('command', nargs=argparse.REMAINDER)
    p = sub.add_parser('report')
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--expected-gpus', type=int)
    p.add_argument('--threshold', type=float, default=20)
    p.add_argument('--hours', type=float, default=5)
    p.add_argument('--interval', type=float, default=60)
    p.add_argument('--until')
    p.add_argument('--title', default='Cryri GPU')
    args = parser.parse_args()
    if args.action == 'sample':
        sample(args)
    elif args.action == 'run':
        sys.exit(run(args))
    else:
        report(args)


if __name__ == '__main__':
    main()
