#!/usr/bin/env python3
"""Fetch official, versioned ncbi-vdb and ISA-L source archives."""
from pathlib import Path
import subprocess
import tarfile

root = Path(__file__).resolve().parents[1]
deps = root / 'deps'
deps.mkdir(exist_ok=True)
packages = [
    ('ncbi-vdb-3.2.1', 'https://codeload.github.com/ncbi/ncbi-vdb/tar.gz/refs/tags/3.2.1'),
    ('isa-l-2.31.0', 'https://codeload.github.com/intel/isa-l/tar.gz/refs/tags/v2.31.0'),
]
for name, url in packages:
    source = deps / name
    if not source.is_dir():
        archive = deps / (name + '.tar.gz')
        subprocess.run(['curl', '-fL', '--retry', '2', url, '-o', str(archive)], check=True)
        with tarfile.open(archive) as tf:
            tf.extractall(deps, filter='data')
    print(source)
