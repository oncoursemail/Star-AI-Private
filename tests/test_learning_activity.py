import os

from star.learning_activity import FRESH_S, pc_learning_status

NOW = 1_000_000.0


def _home(path, status, log_age=None):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'STATUS.txt').write_text(status + '\n', encoding='utf-8')
    if log_age is not None:
        log = path / 'ns' / 'nightschool.log'
        log.parent.mkdir()
        log.write_text('x', encoding='utf-8')
        os.utime(log, (NOW - log_age, NOW - log_age))
    return path


def test_running_with_a_fresh_log_is_active(tmp_path):
    home = _home(tmp_path, '2026-10-21 01:02:03 running: night school on the graphics card (share 2/4)', log_age=60)
    assert pc_learning_status(home, now=NOW) == {'active': True, 'state': 'running'}


def test_waiting_is_not_active(tmp_path):
    home = _home(tmp_path, '2026-10-21 01:02:03 waiting: the owner is active (idle 0 of 20 min)', log_age=60)
    assert pc_learning_status(home, now=NOW) == {'active': False, 'state': 'waiting'}


def test_running_with_a_stale_or_missing_log_is_not_active(tmp_path):
    stale = _home(tmp_path / 'stale', '2026-10-21 01:02:03 running: night school', log_age=FRESH_S + 5)
    assert pc_learning_status(stale, now=NOW)['active'] is False
    no_log = _home(tmp_path / 'nolog', '2026-10-21 01:02:03 running: night school')
    assert pc_learning_status(no_log, now=NOW)['active'] is False


def test_not_installed(tmp_path):
    assert pc_learning_status(tmp_path / 'absent') == {'active': False, 'state': 'not installed'}
