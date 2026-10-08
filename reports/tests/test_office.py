import sys
import types
from unittest import mock

from django.test import SimpleTestCase

from reports.services import office


class JobError(Exception):
    pass


fake_pythoncom = types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)


@mock.patch.dict(sys.modules, {'pythoncom': fake_pythoncom})
class OfficeSessionTests(SimpleTestCase):
    def test_waits_for_the_job_before_it_then_gives_up(self):
        office.lock.acquire()
        try:
            with mock.patch.object(office, 'LOCK_WAIT', 0.05):
                with self.assertRaisesMessage(JobError, 'Excel is still busy with another report'):
                    with office.office_session('EXCEL.EXE', 'Excel', JobError):
                        pass
        finally:
            office.lock.release()

    def test_releases_the_lock_when_the_job_fails(self):
        with mock.patch.object(office, 'running_pids', return_value=set()):
            with self.assertRaises(ValueError):
                with office.office_session('EXCEL.EXE', 'Excel', JobError):
                    raise ValueError
        self.assertFalse(office.lock.locked())

    def test_watchdog_closes_only_the_process_its_job_started(self):
        pids = iter([{10}, {10, 22}])           # the user's Excel (10), then the job's (22)
        with mock.patch.object(office, 'running_pids', side_effect=lambda exe: next(pids)), \
                mock.patch.object(office, 'kill') as kill:
            watchdog = office.Watchdog('EXCEL.EXE', 0.01)
            watchdog.started()
            watchdog.timer.join(1)
        kill.assert_called_once_with(22)
        self.assertTrue(watchdog.fired)

    def test_a_job_that_finishes_in_time_is_left_alone(self):
        pids = iter([set(), {22}])
        with mock.patch.object(office, 'running_pids', side_effect=lambda exe: next(pids)), \
                mock.patch.object(office, 'kill') as kill:
            with office.office_session('EXCEL.EXE', 'Excel', JobError) as watchdog:
                watchdog.started()
        watchdog.timer.join(1)
        self.assertFalse(watchdog.fired)
        kill.assert_not_called()
