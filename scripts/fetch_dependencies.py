#!/usr/bin/env python3
"""Fetch the official, versioned ncbi-vdb source archive."""
from pathlib import Path
import subprocess
import tarfile

root = Path(__file__).resolve().parents[1]
deps = root / 'deps'
deps.mkdir(exist_ok=True)
version = '3.2.1'
source = deps / f'ncbi-vdb-{version}'
if not source.is_dir():
    archive = deps / f'ncbi-vdb-{version}.tar.gz'
    subprocess.run(['curl', '-fL', '--retry', '2',
        f'https://codeload.github.com/ncbi/ncbi-vdb/tar.gz/refs/tags/{version}', '-o', str(archive)], check=True)
    with tarfile.open(archive) as tf:
        tf.extractall(deps, filter='data')
print(source)
