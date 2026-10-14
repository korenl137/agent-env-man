"""Timestamp-only races get one fresh inspection without adopting real edits."""

from copy import deepcopy
import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_env_man import payload_links
from agent_env_man.model import Error
from agent_env_man.storage import copy_payload, observation
import test_directories as directory_tests


@unittest.skipIf(os.name == 'nt', 'POSIX guarded payload inspection')
class TimestampReinspection(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='aem-timestamps-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.leaf = self.source / 'file'
        self.leaf.write_bytes(b'original')
        self.policy = {'permissions': 'best-effort', 'exclusions': (('item', '**/._DAV'),)}

    def touch(self, path=None, *, ctime_only=False):
        path = path or self.leaf
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + (0 if ctime_only else 1000000000)))

    def changing_read(self, change, *, repeated=False):
        read = os.read
        calls = []
        def changing(fd, size):
            block = read(fd, size)
            if block:
                calls.append(fd)
                if repeated or len(calls) == 1:
                    change()
            return block
        return calls, patch.object(payload_links.os, 'read', side_effect=changing)

    def test_one_time_mtime_and_ctime_changes_preserve_combined_observation(self):
        for ctime_only in (False, True):
            with self.subTest(ctime_only=ctime_only):
                expected_modes, expected_entries = {}, {}
                expected = observation(self.source, modes=expected_modes, entries=expected_entries, **self.policy)
                calls, changing = self.changing_read(lambda: self.touch(ctime_only=ctime_only))
                modes, entries = {}, {}
                with changing:
                    actual = observation(self.source, modes=modes, entries=entries, **self.policy)
                self.assertEqual(actual, expected)
                self.assertEqual(modes, expected_modes)
                self.assertEqual(entries, expected_entries)
                self.assertEqual(len(calls), 2)

    def test_directory_time_change_without_exclusions_is_reinspected(self):
        policy = {'preserve_symlinks': True}
        expected = observation(self.source, **policy)
        calls, changing = self.changing_read(lambda: self.touch(self.source))
        with changing:
            self.assertEqual(observation(self.source, **policy), expected)
        self.assertEqual(len(calls), 2)

    def test_time_change_while_opening_is_reinspected(self):
        expected = observation(self.source, **self.policy)
        fstat = os.fstat
        inode = self.leaf.stat().st_ino
        changed = False
        def changing(fd):
            nonlocal changed
            info = fstat(fd)
            if info.st_ino == inode and not changed:
                changed = True
                self.touch()
                info = fstat(fd)
            return info
        with patch.object(payload_links.os, 'fstat', side_effect=changing):
            self.assertEqual(observation(self.source, **self.policy), expected)
        self.assertTrue(changed)

    def test_repeated_timestamp_changes_fail_without_exposing_captures(self):
        modes, entries = {'saved': 0o755}, {'saved': ('f', 0, b'saved')}
        before = deepcopy((modes, entries))
        calls, changing = self.changing_read(self.touch, repeated=True)
        with changing, self.assertRaisesRegex(Error, 'changed during inspection'):
            observation(self.source, modes=modes, entries=entries, **self.policy)
        self.assertEqual(len(calls), 2)
        self.assertEqual((modes, entries), before)

    def test_same_size_content_change_is_not_adopted_by_reinspection(self):
        calls, changing = self.changing_read(lambda: self.leaf.write_bytes(b'modified'))
        with changing, self.assertRaisesRegex(Error, 'changed during'):
            observation(self.source, **self.policy)
        self.assertEqual(self.leaf.read_bytes(), b'modified')

    def test_mode_inode_and_included_path_changes_remain_fatal(self):
        def replacement():
            replacement = self.source / 'replacement'
            replacement.write_bytes(b'original')
            replacement.replace(self.leaf)
        for change in (lambda: self.leaf.chmod(self.leaf.stat().st_mode ^ 0o100), replacement,
                       lambda: (self.source / 'new').write_bytes(b'included')):
            with self.subTest(change=change):
                calls, changing = self.changing_read(change)
                with changing, self.assertRaisesRegex(Error, 'changed during'):
                    observation(self.source, **self.policy)
                self.assertEqual(len(calls), 1)

    def test_time_change_during_final_identity_check_is_reinspected(self):
        expected = observation(self.source, **self.policy)
        stat = os.stat
        calls = 0
        def changing(path, *args, **kwargs):
            nonlocal calls
            if path == 'file' and kwargs.get('dir_fd') is not None:
                calls += 1
                if calls == 3:
                    self.touch()
            return stat(path, *args, **kwargs)
        with patch.object(payload_links.os, 'stat', side_effect=changing):
            self.assertEqual(observation(self.source, **self.policy), expected)
        self.assertGreater(calls, 3)

    def test_retry_rechecks_an_earlier_file_after_reading_later_siblings(self):
        later = self.source / 'later'
        later.write_bytes(b'sibling')
        leaf_inode, later_inode = self.leaf.stat().st_ino, later.stat().st_ino
        read = os.read
        reads = {leaf_inode: 0, later_inode: 0}
        def changing(fd, size):
            block = read(fd, size)
            if block:
                inode = os.fstat(fd).st_ino
                reads[inode] += 1
                if inode == leaf_inode and reads[inode] == 1:
                    self.touch()
                if inode == later_inode and reads[inode] == 2:
                    self.leaf.write_bytes(b'modified')
            return block
        with patch.object(payload_links.os, 'read', side_effect=changing), patch('agent_env_man.payload_io.perf_counter', return_value=0):
            with self.assertRaisesRegex(Error, 'changed during inspection'):
                observation(self.source, preserve_symlinks=True)
        self.assertEqual(reads, {leaf_inode: 2, later_inode: 2})

    def test_copy_restarts_stage_and_reports_only_successful_attempt(self):
        destination = self.root / 'stage'
        calls, changing = self.changing_read(self.touch)
        chmod = os.fchmod
        failures = []
        attempts = []
        def denied(fd, mode):
            attempts.append(fd)
            if len(attempts) == 1:
                raise OSError(errno.EPERM, 'first attempt only')
            chmod(fd, mode)
        with changing, patch.object(payload_links.os, 'fchmod', side_effect=denied):
            copy_payload(self.source, destination, permission_failures=failures, **self.policy)
        self.assertEqual(len(calls), 2)
        self.assertEqual(failures, [])
        self.assertEqual(observation(destination, **self.policy), observation(self.source, **self.policy))
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['source', 'stage'])

    def test_preexisting_copy_destination_is_preserved(self):
        destination = self.root / 'stage'
        destination.mkdir()
        (destination / 'user').write_bytes(b'keep')
        calls, changing = self.changing_read(self.touch)
        with changing, self.assertRaises(FileExistsError):
            copy_payload(self.source, destination, **self.policy)
        self.assertEqual((destination / 'user').read_bytes(), b'keep')
        self.assertEqual(calls, [])

    def test_timestamp_setter_failure_remains_fatal_without_retry(self):
        destination = self.root / 'stage'
        utime = os.utime
        def drift():
            info = self.leaf.stat()
            utime(self.leaf, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
        calls, changing = self.changing_read(drift)
        with changing, patch.object(payload_links.os, 'utime', side_effect=OSError(errno.ENOTSUP, 'time setter unavailable')):
            with self.assertRaisesRegex(OSError, 'time setter unavailable'):
                copy_payload(self.source, destination, **self.policy)
        self.assertEqual(len(calls), 1)

    def test_opaque_link_copy_reinspection_preserves_referent(self):
        link = self.source / 'alias'
        try:
            link.symlink_to('file')
        except OSError as exc:
            self.skipTest(f'Symlink creation unavailable: {exc}')
        readlink = os.readlink
        calls = 0
        def changing(path, *args, **kwargs):
            nonlocal calls
            target = readlink(path, *args, **kwargs)
            if path == 'alias':
                calls += 1
                if calls == 1:
                    info = link.lstat()
                    os.utime(link, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000), follow_symlinks=False)
            return target
        destination = self.source / 'copy'
        with patch.object(payload_links.os, 'readlink', side_effect=changing):
            copy_payload(link, destination, preserve_symlinks=True)
        self.assertEqual(calls, 2)
        self.assertEqual(os.readlink(destination), 'file')
        self.assertEqual(self.leaf.read_bytes(), b'original')


@unittest.skipIf(os.name == 'nt', 'POSIX guarded payload inspection')
class TimestampCommands(unittest.TestCase):
    setUp = directory_tests.Directories.setUp
    git = directory_tests.Directories.git
    commit = directory_tests.Directories.commit
    repository = directory_tests.Directories.repository
    save_catalog = directory_tests.Directories.save_catalog
    run_cli = directory_tests.Directories.run_cli
    write = directory_tests.Directories.write
    external = directory_tests.Directories.external
    manager = directory_tests.Directories.manager

    def test_failed_copy_reinspection_preserves_installation_and_ownership(self):
        self.document['directories']['cases']['permissions'] = 'best-effort'
        self.external()
        self.run_cli('apply', '--item', 'cases')
        leaf = self.external_root / 'first.md'
        leaf.write_bytes(b'incoming')
        before = observation(self.target, permissions='best-effort')
        records = deepcopy(self.manager().state.data['items'])
        read = os.read
        for content_change in (False, True):
            leaf.write_bytes(b'incoming')
            changed = False
            def changing(fd, size):
                nonlocal changed
                block = read(fd, size)
                info = os.fstat(fd)
                if (block and any(self.target.parent.glob('.aem-stage-*'))
                        and info.st_ino == leaf.stat().st_ino):
                    if content_change:
                        if not changed:
                            leaf.write_bytes(b'modified')
                            changed = True
                    else:
                        os.utime(leaf, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
                return block
            with self.subTest(content_change=content_change), patch.object(payload_links.os, 'read', side_effect=changing):
                self.assertIn('changed during', self.run_cli('apply', '--item', 'cases', code=1))
            self.assertEqual(observation(self.target, permissions='best-effort'), before)
            self.assertEqual(self.manager().state.data['items'], records)
            self.assertIsNone(self.manager().state.data['pending'])
            self.assertFalse(list(self.target.parent.glob('.aem-stage-*')))

    def test_one_time_timestamp_change_during_status_and_apply_succeeds(self):
        self.document['directories']['cases'].update(permissions='best-effort', exclude=['**/._DAV'])
        self.external()
        self.run_cli('apply', '--item', 'cases')
        leaf = self.external_root / 'first.md'
        identity = leaf.stat().st_dev, leaf.stat().st_ino
        read = os.read
        def execute(args, *, copying=False):
            changed = False
            def changing(fd, size):
                nonlocal changed
                block = read(fd, size)
                in_copy = copying and any(self.target.parent.glob('.aem-stage-*'))
                info = os.fstat(fd)
                if (block and not changed and (not copying or in_copy)
                        and (info.st_dev, info.st_ino) == identity):
                    changed = True
                    info = leaf.stat()
                    os.utime(leaf, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
                return block
            with patch.object(payload_links.os, 'read', side_effect=changing):
                result = self.run_cli(*args)
            self.assertTrue(changed)
            return result
        self.assertEqual(execute(('status',))['items'][0]['status'], 'current')
        leaf.write_text('incoming content', encoding='utf-8')
        self.assertEqual(execute(('apply', '--item', 'cases'), copying=True)[0]['action'], 'install')
        self.assertEqual((self.target / 'first.md').read_text(), 'incoming content')
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')
        self.assertIsNone(self.manager().state.data['pending'])
        self.assertFalse(list(self.target.parent.glob('.aem-stage-*')))
