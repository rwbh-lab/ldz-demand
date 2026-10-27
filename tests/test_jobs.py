import importlib.util
import subprocess
import threading

from ldz_demand import jobs


def test_every_step_is_a_runnable_module():
    for job in jobs.JOBS:
        for step in jobs.steps(job):
            assert importlib.util.find_spec(step.module) is not None, (job, step.module)


def test_every_step_runs_and_the_first_failure_is_reported():
    calls, lock = [], threading.Lock()

    def runner(command):
        with lock:
            calls.append(command[2])
        return subprocess.CompletedProcess(command, 3 if command[2] == "ldz_demand.data.ingest.national_gas" else 0)

    assert jobs.run("daily", runner) == 3
    assert sorted(calls) == sorted(step.module for step in jobs.steps("daily"))  # later steps still ran


def test_all_steps_succeeding_is_success():
    assert jobs.run("daily", lambda command: subprocess.CompletedProcess(command, 0)) == 0


def test_branches_run_side_by_side_and_the_forecasts_wait_for_both():
    started = threading.Barrier(2, timeout=5)  # both first steps must be running at once
    order, lock = [], threading.Lock()
    firsts = {branch[0].module for branch in jobs.DAILY[0]}

    def runner(command):
        if command[2] in firsts:
            started.wait()
        with lock:
            order.append(command[2])
        return subprocess.CompletedProcess(command, 0)

    assert jobs.run("daily", runner) == 0
    assert order[-1] == "ldz_demand.models.forecast"
