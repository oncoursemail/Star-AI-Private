#!/usr/bin/env python3
"""Review/apply allowlisted systemd restart drop-ins; never start/enable/restart units.

Usage: python3 linux_recovery_admin.py HOST.json [--apply]
Apply requires an existing root session. No sudo, firewall, or reboot operations.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import tempfile

SYSTEM_DIR = Path('/etc/systemd/system')
BACKUP_DIR = Path('/var/backups/star-recovery-systemd')
DROPIN = '90-star-recovery.conf'
HEADER = '# Managed by linux_recovery_admin.py\n'
PROPERTIES = ('LoadState', 'ActiveState', 'SubState', 'UnitFileState', 'Type',
              'RemainAfterExit', 'Restart', 'RestartUSec', 'StartLimitIntervalUSec',
              'Wants', 'After', 'User', 'Group', 'DynamicUser')


def command(*args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): {result.stderr.strip()[:1600]}')
    return result.stdout


def properties(name):
    data = command('systemctl', 'show', name, '--no-pager',
                   '--property=' + ','.join(PROPERTIES))
    return dict(line.split('=', 1) for line in data.splitlines() if '=' in line)


def seconds(value):
    factors = {'us': .000001, 'ms': .001, 's': 1, 'min': 60, 'h': 3600,
               'd': 86400, 'w': 604800}
    matches = list(re.finditer(r'(\d+(?:\.\d+)?)\s*(us|ms|min|s|h|d|w)', value))
    if not matches or re.sub(r'(\d+(?:\.\d+)?)\s*(us|ms|min|s|h|d|w)', '', value).strip():
        raise ValueError('Unsupported RestartUSec value: ' + value)
    return sum(float(m[1]) * factors[m[2]] for m in matches)


def read_config(path):
    config = json.loads(Path(path).read_text())
    if config.get('hostname') != socket.gethostname():
        raise ValueError('Config hostname must match this host exactly')
    names = []
    for item in config.get('services', []):
        name = item.get('name', '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service', name) or name.endswith('@.service'):
            raise ValueError('Explicit service instance required: ' + name)
        if not isinstance(item.get('network_client', False), bool):
            raise ValueError('network_client must be true or false')
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError('Duplicate services are not allowed')
    for user in config.get('linger_users', []):
        if not isinstance(user, str) or not re.fullmatch(r'[a-z_][a-z0-9_-]*', user):
            raise ValueError('Explicit local username required')
        if pwd.getpwnam(user).pw_uid == 0:
            raise ValueError('Root user linger is not supported')
    return config


def make_plan(config):
    plan = {'hostname': config['hostname'], 'services': [], 'enable_linger': [],
            'actions': 'drop-ins + daemon-reload only; no service start/enable/restart'}
    for item in config.get('services', []):
        name = item['name']
        before = properties(name)
        entry = {'name': name, 'before': before}
        plan['services'].append(entry)
        if any(before.get(k) != v for k, v in {'LoadState': 'loaded', 'ActiveState': 'active',
               'SubState': 'running', 'UnitFileState': 'enabled'}.items()):
            entry['skip'] = 'Requires a currently running, persistently enabled service'
            continue
        if before.get('Type') == 'oneshot' or before.get('RemainAfterExit') == 'yes':
            entry['skip'] = 'One-shot/remaining-active units require a separate design'
            continue
        if before.get('Restart') not in ('no', 'on-failure', 'always'):
            entry['skip'] = 'Custom restart semantics require individual review'
            continue
        target = SYSTEM_DIR / (name + '.d') / DROPIN
        if any(p.is_symlink() for p in [target, *target.parents]):
            raise ValueError('Refusing symlink in managed drop-in path: ' + str(target))
        if target.exists() and not target.read_text().startswith(HEADER):
            raise ValueError('Refusing to overwrite an unowned drop-in: ' + str(target))
        restart = 'always' if before['Restart'] == 'always' else 'on-failure'
        delay = max(15.0, seconds(before['RestartUSec']))
        text = HEADER + '[Unit]\nStartLimitIntervalSec=0\n'
        if item.get('network_client'):
            text += 'Wants=network-online.target\nAfter=network-online.target\n'
        text += f'\n[Service]\nRestart={restart}\nRestartSec={delay:g}s\n'
        entry.update(path=str(target), content=text, restart=restart, delay=delay,
                     network=bool(item.get('network_client')), changed=not target.exists() or target.read_text() != text)
        with tempfile.TemporaryDirectory(prefix='star-recovery-verify-') as directory:
            staged = Path(directory) / name
            staged.write_text(command('systemctl', 'cat', name, '--no-pager') + '\n' + text)
            command('systemd-analyze', 'verify', str(staged))
    for user in dict.fromkeys(config.get('linger_users', [])):
        if not (Path('/var/lib/systemd/linger') / user).exists():
            plan['enable_linger'].append(user)
    return plan


def verify_effective(plan):
    for item in plan['services']:
        if 'skip' in item:
            continue
        after = properties(item['name'])
        if (after.get('Restart') != item['restart'] or seconds(after.get('RestartUSec', '')) != item['delay']
                or after.get('StartLimitIntervalUSec') not in ('0', '0s', '0us')
                or any(after.get(k) != item['before'].get(k) for k in ('User', 'Group', 'DynamicUser'))
                or (item['network'] and any('network-online.target' not in after.get(k, '').split() for k in ('Wants', 'After')))):
            raise RuntimeError('Effective settings did not match plan: ' + item['name'])


def apply_plan(plan):
    changes = [item for item in plan['services'] if item.get('changed')]
    if not changes and not plan['enable_linger']:
        verify_effective(plan)
        return {'status': 'already configured', 'restarts': 0}
    backup = BACKUP_DIR / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    if any(p.is_symlink() for p in [backup, *backup.parents]):
        raise ValueError('Refusing symlink in backup path')
    backup.mkdir(parents=True, mode=0o700)
    (backup / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    originals, linger = [], []
    try:
        for item in changes:
            target = Path(item['path'])
            old = backup / item['name']
            if target.exists():
                shutil.copy2(target, old)
            originals.append((target, old))
            target.parent.mkdir(mode=0o755, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False) as stream:
                temp = Path(stream.name)
                stream.write(item['content'])
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp, 0o644)
            os.replace(temp, target)
        if changes:
            command('systemctl', 'daemon-reload')
        verify_effective(plan)
        for user in plan['enable_linger']:
            linger.append(user)
            command('loginctl', 'enable-linger', user)
        return {'status': 'applied and verified', 'backup': str(backup), 'restarts': 0}
    except Exception as failure:
        rollback_errors = []
        for target, old in reversed(originals):
            try:
                shutil.copy2(old, target) if old.exists() else target.unlink(missing_ok=True)
            except Exception as error:
                rollback_errors.append(str(error))
        commands = ([('systemctl', 'daemon-reload')] if originals else [])
        commands += [('loginctl', 'disable-linger', user) for user in reversed(linger)]
        for args in commands:
            try:
                command(*args)
            except Exception as error:
                rollback_errors.append(str(error))
        if rollback_errors:
            raise RuntimeError('Rollback needs administrator attention: ' + '; '.join(rollback_errors)) from failure
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply and os.geteuid() != 0:
        parser.error('--apply requires an existing root session; no privilege escalation is attempted')
    plan = make_plan(read_config(args.config))
    print(json.dumps({'mode': 'apply' if args.apply else 'dry-run', 'plan': plan}, indent=2))
    if args.apply:
        print(json.dumps(apply_plan(plan), indent=2))


if __name__ == '__main__':
    main()
