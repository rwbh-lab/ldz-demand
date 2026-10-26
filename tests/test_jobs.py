import importlib.util
import subprocess

from ldz_demand import jobs


def test_every_step_is_a_runnable_module():
    for job, steps in jobs.JOBS.items():
        for step in steps:
            assert importlib.util.find_spec(step.module) is not None, (job, step.module)


def test_every_step_runs_and_the_first_failure_is_reported():
    calls = []

    def runner(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, 3 if len(calls) == 2 else 0)

    assert jobs.run("weekly", runner) == 3
    assert len(calls) == len(jobs.JOBS["weekly"])  # later steps still ran


def test_all_steps_succeeding_is_success():
    assert jobs.run("daily", lambda command: subprocess.CompletedProcess(command, 0)) == 0
