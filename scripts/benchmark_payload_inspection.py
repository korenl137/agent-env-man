#!/usr/bin/env python3
"""Measure CLI inspections with disposable configuration and copy targets.

An optional existing directory is read only as an external source. Timed samples
run without instrumentation; a separate run counts full tree inspections and
permission-only scans. Each invocation reloads configuration/state in the same
Python process; interpreter startup is excluded. No existing configuration or
installation is consumed.
"""

import argparse
from collections import Counter
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import platform
import statistics
import tempfile
from time import perf_counter
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main as cli_main
from agent_env_man import manager, payload_links, permissions, storage


def run(config, *args):
    output, errors = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        code = cli_main(['--config', str(config), '--json', *args])
    if code:
        raise RuntimeError(f'{args}: {output.getvalue()}\n{errors.getvalue()}')
    return json.loads(output.getvalue())


def count_inspections(config, args, source, target):
    counts = Counter()
    fingerprint, scan, snapshot = storage.fingerprint, payload_links.scan, permissions.snapshot

    def location(path):
        return 'source' if Path(path) == source else 'target' if Path(path) == target else 'other'

    def hashed(path, **policy):
        if not policy.get('preserve_symlinks'):
            counts[f'content:{location(path)}'] += 1
        return fingerprint(path, **policy)

    def scanned(path, **policy):
        kind = 'permissions' if policy.get('modes_only') else 'copy' if policy.get('destination') is not None else 'content'
        counts[f'{kind}:{location(path)}'] += 1
        return scan(path, **policy)

    def modes(path, **policy):
        # POSIX snapshots delegate to scan; Windows snapshots have their own walk.
        if os.name == 'nt':
            counts[f'permissions:{location(path)}'] += 1
        return snapshot(path, **policy)

    with ExitStack() as stack:
        stack.enter_context(patch.object(storage, 'fingerprint', hashed))
        stack.enter_context(patch.object(manager, 'fingerprint', hashed))
        stack.enter_context(patch.object(payload_links, 'scan', scanned))
        stack.enter_context(patch.object(permissions, 'snapshot', modes))
        run(config, *args)
    return dict(sorted(counts.items()))


def benchmark(source, root, samples, preserve_symlinks, exclusions):
    results = []
    for permission in ('strict', 'best-effort'):
        fixture = root / permission
        fixture.mkdir()
        catalog, config = fixture / 'catalog.toml', fixture / 'machine.toml'
        targets = fixture / 'targets'
        catalog.write_text(tomlkit.dumps({
            'version': 2,
            'payload': {'defaults': {'permissions': permission, 'exclude': exclusions}},
            'sources': {'store': {'type': 'external'}},
            'directories': {'sample': {'source': 'store', 'preserve_symlinks': preserve_symlinks,
                                      'install': {'root': 'test', 'mode': 'copy'}}},
        }), encoding='utf-8')
        run(config, 'bootstrap', str(catalog), '--external', f'store={source}', '--root', f'test={targets}')
        run(config, 'apply', '--item', 'sample')
        target = targets / 'sample'
        for args in [('status',), ('apply', '--item', 'sample', '--dry-run'), ('apply', '--item', 'sample'),
                     ('apply', '--item', 'sample', '--replace')]:
            replacing = '--replace' in args
            def prepare_sample():
                if replacing:
                    # This copy belongs only to the fixture. An explicit replace
                    # restores it from the read-only source on every sample.
                    (target / '.aem-benchmark-edit').write_bytes(b'fixture edit')
            prepare_sample()
            expected = run(config, *args)
            if args[0] == 'status':
                if expected['items'][0]['status'] != 'current':
                    raise RuntimeError('Fixture status is not current')
            elif expected[0]['action'] != ('install' if replacing else 'record'):
                raise RuntimeError('Fixture requires a content change')
            times = []
            for _ in range(samples):
                prepare_sample()
                started = perf_counter()
                actual = run(config, *args)
                times.append(perf_counter() - started)
                if actual != expected:
                    raise RuntimeError('Command output changed between samples')
            prepare_sample()
            results.append({'permissions': permission, 'command': ' '.join(args),
                            'seconds': times, 'median_seconds': statistics.median(times),
                            'inspections': count_inspections(config, args, source, target)})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Existing read-only directory; omit to generate local content')
    parser.add_argument('--samples', type=int, default=7)
    parser.add_argument('--files', type=int, default=200, help='Generated local file count')
    parser.add_argument('--preserve-symlinks', action='store_true')
    parser.add_argument('--exclude', action='append', default=[])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.samples < 1 or args.files < 1:
        parser.error('samples and files must be positive')
    with tempfile.TemporaryDirectory(prefix='aem-inspection-benchmark-') as temporary:
        root = Path(temporary)
        source = args.source.resolve() if args.source else root / 'source'
        if args.source:
            if not source.is_dir():
                parser.error('source must be an existing directory')
        else:
            source.mkdir()
            for number in range(args.files):
                (source / f'file-{number:05}.txt').write_bytes(b'x' * 4096)
        report = {'python': platform.python_version(), 'platform': platform.platform(),
                  'source_kind': 'existing' if args.source else 'generated-local',
                  'preserve_symlinks': args.preserve_symlinks, 'samples': args.samples,
                  'results': benchmark(source, root, args.samples, args.preserve_symlinks, args.exclude)}
    encoded = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(encoded, encoding='utf-8')
    print(encoded, end='')


if __name__ == '__main__':
    main()
