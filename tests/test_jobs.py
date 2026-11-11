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
    assert order[-2:] == ["ldz_demand.models.forecast", "ldz_demand.publish"]


def test_publish_runs_only_if_the_forecasts_succeeded():
    def run(failing):
        calls = []

        def runner(command):
            calls.append(command[2])
            return subprocess.CompletedProcess(command, 4 if command[2] == failing else 0)

        return jobs.run("daily", runner), calls

    status, calls = run("ldz_demand.models.forecast")
    assert status == 4 and "ldz_demand.publish" not in calls          # a failed forecast: nothing pushed
    status, calls = run("ldz_demand.data.ingest.era5")                 # ERA5 failing (e.g. CDS): still publish
    assert status == 4 and calls[-1] == "ldz_demand.publish"


def test_a_step_with_unmet_needs_is_skipped_without_counting_as_a_failure():
    branch = (jobs.Step("a", "mod.a"), jobs.Step("b", "mod.b", needs=("a",)), jobs.Step("c", "mod.c", needs=("x",)))
    calls = []

    def runner(command):
        calls.append(command[2])
        return subprocess.CompletedProcess(command, 0)

    assert jobs.run_branch(branch, runner) == [0, 0, 0] and calls == ["mod.a", "mod.b"]  # c: x never ran


def test_the_daily_publish_step_pushes_only_where_a_target_is_set():
    (step,) = jobs.PUBLISH
    assert step.module == "ldz_demand.publish" and {"--push", "--if-configured"} <= set(step.args)
