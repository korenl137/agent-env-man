#!/usr/bin/env python3
"""Measure delivery, publication, detach and recovery on disposable installations.

Existing --source content is read only: real collection uses generated sources.
Git commands always use disposable local repositories/remotes. Timing excludes
fixture preparation, interpreter startup and separate diagnostic instrumentation.
"""

from collections import Counter
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch

import tomlkit

try:
    from scripts.benchmark_payload_inspection import run, count_inspections
except ModuleNotFoundError:
    from benchmark_payload_inspection import run, count_inspections
from agent_env_man.git_source import Git
from agent_env_man.storage import State, observation
from agent_env_man.payload_policy import saved

_checkpoint = None


def retain(result):
    if _checkpoint is not None:
        _checkpoint(result)


def git(path, *args):
    result = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def measure(config, args, source, target, samples, prepare=lambda: None, check=lambda result: None, label=None):
    prepare()
    check(run(config, *args))
    times = []
    for _ in range(samples):
        prepare()
        started = perf_counter()
        result = run(config, *args)
        times.append(perf_counter() - started)
        check(result)
    prepare()
    calls, elapsed, resolution_calls, resolution_elapsed = Counter(), Counter(), Counter(), Counter()
    original = Git.run
    resolve = Path.resolve
    def observed_resolution(path, *arguments, **options):
        key = 'source' if path == source else 'other'
        resolution_calls[key] += 1
        started = perf_counter()
        try:
            return resolve(path, *arguments, **options)
        finally:
            resolution_elapsed[key] += perf_counter() - started
    def observed(self, path, *arguments, **options):
        key = arguments[0]
        if key == '-c':
            key = arguments[2]
        calls[key] += 1
        started = perf_counter()
        try:
            return original(self, path, *arguments, **options)
        finally:
            elapsed[key] += perf_counter() - started
    with patch.object(Git, 'run', observed), patch.object(Path, 'resolve', new=observed_resolution):
        inspections = count_inspections(config, args, source, target)
    check(result)
    measured = {'command': label or ' '.join(args), 'seconds': times,
                'median_seconds': statistics.median(times), 'inspections': inspections,
                'git_calls': dict(sorted(calls.items())), 'git_call_count': sum(calls.values()),
                'instrumented_git_seconds': dict(sorted(elapsed.items())),
                'path_resolution_calls': dict(sorted(resolution_calls.items())),
                'instrumented_path_resolution_seconds': dict(sorted(resolution_elapsed.items()))}
    print(f"Measured {measured['command']}: {measured['median_seconds']:.3f}s", file=sys.stderr, flush=True)
    return measured


def payload_suite(root, control, source, generated, samples, links, exclusions):
    results = []
    for permission in ('strict', 'best-effort'):
        fixture = root / permission
        fixture.mkdir()
        settings = control / permission
        settings.mkdir()
        config, catalog, targets = settings / 'machine.toml', settings / 'catalog.toml', fixture / 'targets'
        document = {'version': 2, 'payload': {'defaults': {'permissions': permission, 'exclude': exclusions}},
                    'sources': {'store': {'type': 'external'}}, 'directories': {
                        name: {'source': 'store', 'preserve_symlinks': links,
                               'install': {'root': 'test', 'mode': 'copy'}} for name in ('sample', 'alias')}}
        catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        run(config, 'bootstrap', str(catalog), '--external', f'store={source}', '--root', f'test={targets}')
        target = targets / 'sample'
        def add(args, **options):
            result = measure(config, args, source, target, samples, **options)
            result['permissions'] = permission
            results.append(result)
            retain(result)
        add(('bootstrap',), label='bootstrap external shared consumers')
        run(config, 'apply', '--item', 'sample')
        marker = target / '.aem-benchmark-edit'
        def edited_copy():
            marker.write_bytes(b'benchmark edit')
        def preview(result):
            if not result[0]['collection'][0]['changed']:
                raise RuntimeError('Collection preview missed fixture edit')
        add(('publish', 'sample', '--from-copy', '--dry-run'), prepare=edited_copy, check=preview)
        marker.unlink()
        if generated:
            counter = 0
            def edited_payload():
                nonlocal counter
                counter += 1
                (target / 'file-00000.txt').write_bytes(f'edit {counter}'.encode())
            def collected(result):
                if result[0]['status'] != 'published' or (source / 'file-00000.txt').read_bytes() != (target / 'file-00000.txt').read_bytes():
                    raise RuntimeError('Collection did not commit the copy edit')
            add(('publish', 'sample', '--from-copy'), prepare=edited_payload, check=collected)
        run(config, 'detach', 'sample')
        recovery_target, recovery_targets = target, targets
        document['directories']['sample']['install'].update(mode='link', root='detach')
        catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        # A mounted SMB/DrvFS destination can reject installed symlinks. Keep
        # detach links on local storage while their payload source stays mounted.
        targets = settings / 'detach-targets'
        run(config, 'bootstrap', '--root', f'detach={targets}')
        target = targets / 'sample'
        def linked_copy():
            if not target.is_symlink():
                run(config, 'apply', '--item', 'sample', '--replace', '--reattach')
        linked_copy()
        add(('detach', 'sample', '--dry-run'), prepare=linked_copy)
        def detached(result):
            if target.is_symlink() or not target.is_dir():
                raise RuntimeError('Detach did not materialize the fixture link')
        add(('detach', 'sample'), prepare=linked_copy, check=detached)
        target, targets = recovery_target, recovery_targets
        policy = {'permissions': permission}
        if links:
            policy.update(preserve_symlinks=True, source_relative='.')
        if exclusions:
            policy['exclusions'] = tuple(('', rule) for rule in exclusions)
        stage, backup = targets / '.aem-stage-benchmark', targets / 'sample.aem-backup-benchmark'
        def interrupted():
            if stage.exists():
                shutil.rmtree(stage)
            shutil.copytree(target, stage, symlinks=True)
            (stage / '.aem-new-content').write_bytes(b'staged')
            state = State(config.parent / (config.name + '.state'))
            state.data['pending'] = {'key': 'benchmark-recovery', 'target': str(target), 'stage': str(stage),
                                     'backup': str(backup), 'before': observation(target, **policy),
                                     'after': observation(stage, **policy), **saved(policy)}
            state.save()
        def recovered(result):
            state = State(config.parent / (config.name + '.state'))
            if stage.exists() or not target.is_dir() or state.data['pending']:
                raise RuntimeError('Recovery did not preserve target and remove stage')
        add(('recover',), prepare=interrupted, check=recovered, label='recover before first rename')
    return results


def git_suite(root, control, samples, files):
    fixture = root / 'git'
    fixture.mkdir()
    settings = control / 'git'
    settings.mkdir()
    # Keep the remote and producer local: --root isolates the cost of a mounted
    # managed checkout, without adding mounted bare-repository server I/O.
    seed, remote = settings / 'seed', settings / 'remote.git'
    seed.mkdir()
    git(settings, 'init', '--bare', str(remote))
    git(seed, 'init', '-b', 'main')
    for number in range(files):
        (seed / f'file-{number:05}.txt').write_bytes(b'x' * 4096)
    def commit(path):
        git(path, 'add', '--all')
        git(path, '-c', 'user.name=Benchmark', '-c', 'user.email=benchmark@example.invalid', 'commit', '-m', 'Fixture change')
    commit(seed)
    git(seed, 'remote', 'add', 'origin', str(remote))
    git(seed, 'push', 'origin', 'main')
    git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    config, catalog = settings / 'machine.toml', settings / 'catalog.toml'
    targets, checkouts = settings / 'targets', fixture / 'checkouts'
    catalog.write_text(tomlkit.dumps({'version': 2, 'sources': {'store': {'type': 'git', 'repository': str(remote)}},
        'directories': {name: {'source': 'store', 'install': {'root': 'test'}} for name in ('sample', 'alias')}}), encoding='utf-8')
    run(config, 'bootstrap', str(catalog), '--checkout-root', str(checkouts), '--root', f'test={targets}', '--timeout', '120')
    source, target = checkouts / '.aem-repositories/store', targets / 'sample'
    results = []
    def add(args, **options):
        result = measure(config, args, source, target, samples, **options)
        results.append(result)
        retain(result)
    add(('bootstrap', '--timeout', '120'), label='bootstrap existing Git shared consumers')
    run(config, 'apply', '--item', 'sample', '--item', 'alias')
    add(('update', 'sample', '--timeout', '120'), label='update unchanged local remote')
    number = 0
    def incoming():
        nonlocal number
        number += 1
        (seed / 'file-00000.txt').write_bytes(f'upstream {number}'.encode())
        commit(seed)
        git(seed, 'push', 'origin', 'main')
    def updated(result):
        if (source / 'file-00000.txt').read_bytes() != (seed / 'file-00000.txt').read_bytes():
            raise RuntimeError('Update did not deliver the incoming commit')
    add(('update', 'sample', '--timeout', '120'), prepare=incoming, check=updated, label='update incoming commit from local remote')
    add(('publish', 'sample', '--dry-run', '--timeout', '120'), label='publish sample --dry-run')
    def outgoing():
        nonlocal number
        number += 1
        (source / 'file-00000.txt').write_bytes(f'outgoing {number}'.encode())
        commit(source)
    def published(result):
        if result[0]['status'] != 'published' or git(remote, 'rev-parse', 'main') != git(source, 'rev-parse', 'HEAD'):
            raise RuntimeError('Publication did not advance the fixture remote')
    add(('publish', 'sample', '--timeout', '120'), prepare=outgoing, check=published, label='publish committed change to local remote')
    return results


def main():
    global _checkpoint
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--root', type=Path, help='Existing writable filesystem root for disposable source, target and Git fixtures')
    parser.add_argument('--samples', type=int, default=7)
    parser.add_argument('--files', type=int, default=200)
    parser.add_argument('--preserve-symlinks', action='store_true')
    parser.add_argument('--exclude', action='append', default=[])
    parser.add_argument('--suite', choices=('all', 'payload', 'git'), default='all')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.samples < 1 or args.files < 1:
        parser.error('samples and files must be positive')
    partial = []
    def checkpoint(result):
        partial.append(result)
        if args.output:
            args.output.write_text(json.dumps({'complete': False, 'results': partial}, indent=2) + '\n', encoding='utf-8')
    _checkpoint = checkpoint
    with tempfile.TemporaryDirectory(prefix='.aem-other-benchmark-', dir=args.root) as temporary, \
            tempfile.TemporaryDirectory(prefix='aem-other-controls-') as controls, patch.dict(os.environ, {
        'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}):
        root, control = Path(temporary), Path(controls)
        source = args.source.resolve() if args.source else root / 'source'
        if not args.source:
            source.mkdir()
            for number in range(args.files):
                (source / f'file-{number:05}.txt').write_bytes(b'x' * 4096)
        if not source.is_dir():
            parser.error('source must be an existing directory')
        results = []
        if args.suite in ('all', 'payload'):
            results += payload_suite(root, control, source, args.source is None, args.samples, args.preserve_symlinks, args.exclude)
        if args.suite in ('all', 'git'):
            results += git_suite(root, control, args.samples, args.files)
        report = {'python': platform.python_version(), 'platform': platform.platform(),
                  'complete': True,
                  'source_kind': 'existing-read-only' if args.source else 'generated-fixture',
                  'fixture_storage': 'selected-filesystem' if args.root else 'local-temporary',
                  'samples': args.samples, 'results': results}
    encoded = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(encoded, encoding='utf-8')
    print(encoded, end='')


if __name__ == '__main__':
    main()
