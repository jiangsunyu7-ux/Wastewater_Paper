#!/usr/bin/env python3
"""Execute a command once and record wall time and Unix child resource usage."""
import argparse, datetime, json, os, resource, subprocess, time
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--receipt', required=True)
p.add_argument('command', nargs=argparse.REMAINDER)
a = p.parse_args()
command = a.command[1:] if a.command and a.command[0] == '--' else a.command
if not command:
    p.error('command required')
path = Path(a.receipt)
if path.exists():
    p.error('cost receipt exists; preserve it and use a new receipt')
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
tick = time.monotonic()
child = subprocess.Popen(command)
code = child.wait()
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
out = dict(started_utc=started, finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
           command=command, exit_code=code, wall_seconds=time.monotonic()-tick,
           user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime,
           max_rss_kib=usage.ru_maxrss,
           memory_scope='Unix RUSAGE_CHILDREN high-water; this wrapper executes exactly one command')
path.parent.mkdir(parents=True, exist_ok=True)
temp = path.with_name(path.name + '.tmp')
with temp.open('w') as handle:
    json.dump(out, handle, indent=2); handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
os.replace(temp, path)
raise SystemExit(code)
