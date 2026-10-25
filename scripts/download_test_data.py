#!/usr/bin/env python3
"""Download the fixed fixtures over IPv6; resume partial files and verify MD5."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def matches(path, entry):
    if not path.exists() or path.stat().st_size != entry['bytes']:
        return False
    digest = hashlib.md5()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest() == entry['md5']

def download(entry):
    destination = ROOT / entry['relative_path']
    destination.parent.mkdir(parents=True, exist_ok=True)
    if matches(destination, entry):
        return entry['run'] + ': verified existing file'
    if destination.exists():
        raise RuntimeError(f'{destination}: existing file failed verification; preserve and inspect it first')
    partial = destination.with_suffix(destination.suffix + '.part')
    subprocess.run(['curl', '-6', '--noproxy', '*', '--fail', '--location',
                    '--retry', '5', '--connect-timeout', '30', '--speed-limit', '1024',
                    '--speed-time', '120', '--continue-at', '-', '--output', str(partial),
                    entry['download_url']], check=True)
    if not matches(partial, entry):
        raise RuntimeError(f'{partial}: size or MD5 mismatch')
    partial.replace(destination)
    return entry['run'] + ': downloaded and verified'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=4)
    args = parser.parse_args()
    entries = json.loads((ROOT / 'tests/metadata/selection.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for message in pool.map(download, entries):
            print(message, flush=True)
