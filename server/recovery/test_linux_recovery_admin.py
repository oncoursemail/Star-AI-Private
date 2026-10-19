import contextlib
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import linux_recovery_admin as recovery


class RecoveryAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.system = self.root / 'system'
        self.backups = self.root / 'backups'
        self.calls = []
        self.units = {}
        self.reject_verify = False
        self.override_effective = False
        for name, value in [('SYSTEM_DIR', self.system), ('BACKUP_DIR', self.backups)]:
            patcher = patch.object(recovery, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(recovery, 'command', self.command)
        patcher.start()
        self.addCleanup(patcher.stop)

    def add_unit(self, name, **changes):
        self.units[name] = dict(LoadState='loaded', ActiveState='active', SubState='running',
            UnitFileState='enabled', Type='simple', RemainAfterExit='no', Restart='on-failure',
            RestartUSec='5s', StartLimitIntervalUSec='10s', Wants='', After='',
            User='star', Group='star', DynamicUser='no', **changes)

    def command(self, *args):
        self.calls.append(args)
        if args[:2] == ('systemctl', 'show'):
            name = args[2]
            values = self.units[name].copy()
            target = self.system / (name + '.d') / recovery.DROPIN
            if target.exists():
                content = target.read_text()
                for line in content.splitlines():
                    if '=' in line:
                        key, value = line.split('=', 1)
                        mapping = {'Restart': 'Restart', 'RestartSec': 'RestartUSec',
                                   'StartLimitIntervalSec': 'StartLimitIntervalUSec',
                                   'Wants': 'Wants', 'After': 'After'}
                        if key in mapping:
                            values[mapping[key]] = value
                if self.override_effective and 'StartLimitIntervalSec=0' in content:
                    values['StartLimitIntervalUSec'] = '99s'
            return '\n'.join(key + '=' + value for key, value in values.items())
        if args[:2] == ('systemctl', 'cat'):
            return '[Service]\nType=simple\nExecStart=/usr/bin/true\nUser=star\n'
        if args[:2] == ('systemd-analyze', 'verify'):
            if self.reject_verify:
                raise RuntimeError('Unit verification rejected')
            return ''
        if args == ('systemctl', 'daemon-reload'):
            return ''
        raise AssertionError('Unexpected command: ' + repr(args))

    def config(self, names):
        return {'hostname': socket.gethostname(), 'services': [
            {'name': name, 'network_client': True} for name in names], 'linger_users': []}

    def test_default_cli_dry_run_never_changes_units(self):
        self.add_unit('star-brain.service')
        config = self.root / 'config.json'
        config.write_text(json.dumps(self.config(list(self.units))))
        with patch('sys.argv', ['linux_recovery_admin.py', str(config)]), contextlib.redirect_stdout(io.StringIO()) as output:
            recovery.main()
        self.assertEqual(json.loads(output.getvalue())['mode'], 'dry-run')
        self.assertFalse(self.system.exists())
        self.assertFalse(self.backups.exists())
        self.assertNotIn(('systemctl', 'daemon-reload'), self.calls)

    def test_apply_preserves_always_and_long_delay_and_is_idempotent(self):
        self.system.mkdir()
        self.add_unit('docker.service')
        self.units['docker.service']['Restart'] = 'always'
        self.add_unit('star-night-school.service')
        self.units['star-night-school.service']['RestartUSec'] = '2min'
        config = self.config(list(self.units))
        result = recovery.apply_plan(recovery.make_plan(config))
        self.assertEqual(result['restarts'], 0)
        docker = (self.system / 'docker.service.d' / recovery.DROPIN).read_text()
        night = (self.system / 'star-night-school.service.d' / recovery.DROPIN).read_text()
        self.assertIn('Restart=always', docker)
        self.assertIn('RestartSec=120s', night)
        self.assertEqual(recovery.apply_plan(recovery.make_plan(config))['status'], 'already configured')
        self.assertEqual(len(list(self.backups.iterdir())), 1)
        self.assertEqual(self.calls.count(('systemctl', 'daemon-reload')), 1)
        self.assertFalse(any(any(word in args for word in ['start', 'stop', 'restart', 'enable']) for args in self.calls))

    def test_disabled_failed_oneshot_units_remain_untouched(self):
        for name in ['disabled.service', 'failed.service', 'timer-job.service']:
            self.add_unit(name)
        self.units['disabled.service']['UnitFileState'] = 'disabled'
        self.units['failed.service']['ActiveState'] = 'failed'
        self.units['timer-job.service']['Type'] = 'oneshot'
        plan = recovery.make_plan(self.config(list(self.units)))
        self.assertTrue(all('skip' in entry for entry in plan['services']))
        recovery.apply_plan(plan)
        self.assertFalse(self.system.exists())

    def test_verification_rejection_happens_before_mutation(self):
        self.add_unit('star-brain.service')
        self.reject_verify = True
        with self.assertRaisesRegex(RuntimeError, 'verification rejected'):
            recovery.make_plan(self.config(list(self.units)))
        self.assertFalse(self.system.exists())
        self.assertFalse(self.backups.exists())

    def test_effective_mismatch_restores_old_dropin(self):
        self.add_unit('star-brain.service')
        target = self.system / 'star-brain.service.d' / recovery.DROPIN
        target.parent.mkdir(parents=True)
        original = recovery.HEADER + '[Service]\nRestartSec=20s\n'
        target.write_text(original)
        self.override_effective = True
        with self.assertRaisesRegex(RuntimeError, 'Effective settings'):
            recovery.apply_plan(recovery.make_plan(self.config(list(self.units))))
        self.assertEqual(target.read_text(), original)
        self.assertEqual(self.calls.count(('systemctl', 'daemon-reload')), 2)
        self.assertEqual(next(self.backups.glob('*/star-brain.service')).read_text(), original)

    def test_wildcard_and_wrong_host_are_rejected(self):
        config = self.root / 'config.json'
        config.write_text(json.dumps(self.config(['star-*.service'])))
        with self.assertRaisesRegex(ValueError, 'Explicit service'):
            recovery.read_config(config)
        config.write_text(json.dumps({'hostname': 'not-this-host', 'services': []}))
        with self.assertRaisesRegex(ValueError, 'hostname'):
            recovery.read_config(config)
        self.assertEqual(self.calls, [])

    def test_nonroot_apply_refused_before_host_inspection(self):
        with patch('sys.argv', ['linux_recovery_admin.py', 'unused.json', '--apply']), \
                patch.object(recovery.os, 'geteuid', return_value=1000), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as failure:
                recovery.main()
        self.assertEqual(failure.exception.code, 2)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
