import asyncio
import os
import sys

import pytest

from mathtutor.infrastructure import keychain_secret_store as keychain


async def test_keychain_runner_preserves_normal_output():
    code, stdout, stderr = await keychain._default_runner(
        [sys.executable, "-c", "import sys; print(sys.stdin.read()); print('diagnostic', file=sys.stderr)"],
        stdin=b"test-only-value")
    assert code == 0 and stdout.strip() == "test-only-value" and stderr.strip() == "diagnostic"


async def test_cancellation_during_timeout_cleanup_remains_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(keychain, "DEFAULT_TIMEOUT_SECONDS", 0.05)
    stopped, release = asyncio.Event(), asyncio.Event()
    stop = keychain._stop_process
    processes = []
    async def cleanup(process):
        await stop(process)
        processes.append(process)
        stopped.set()
        await release.wait()
    monkeypatch.setattr(keychain, "_stop_process", cleanup)
    task = asyncio.create_task(keychain._default_runner([sys.executable, "-c", "import time; time.sleep(60)"]))
    try:
        await asyncio.wait_for(stopped.wait(), timeout=3)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode is not None
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("mode", ["timeout", "cancel_twice", "exit_race"])
async def test_keychain_runner_reaps_real_sleeping_child_on_failure(tmp_path, monkeypatch, mode):
    created = []
    kill_calls = []
    create = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        process = await create(*args, **kwargs)
        created.append(process)
        kill = process.kill
        def record_kill():
            kill_calls.append(process.pid)
            kill()
        monkeypatch.setattr(process, "kill", record_kill)
        if mode == "exit_race":
            def already_exited():
                record_kill()
                raise ProcessLookupError("process exited during termination")
            monkeypatch.setattr(process, "terminate", already_exited)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    if mode == "timeout":
        monkeypatch.setattr(keychain, "DEFAULT_TIMEOUT_SECONDS", 0.05)
    ready = tmp_path / "ready"
    script = (
        "import os, pathlib, signal, sys, time\n"
        "if os.name == 'posix': signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "pathlib.Path(sys.argv[1]).touch()\n"
        "time.sleep(60)\n"
    )
    task = asyncio.create_task(keychain._default_runner([sys.executable, "-c", script, str(ready)]))
    try:
        if mode != "timeout":
            async with asyncio.timeout(5):
                while not ready.exists():
                    await asyncio.sleep(0.01)
            task.cancel()
            if mode == "cancel_twice":
                await asyncio.sleep(0.02)
                task.cancel()
        with pytest.raises(TimeoutError if mode == "timeout" else asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)
        assert len(created) == 1 and created[0].returncode is not None
        assert await asyncio.wait_for(created[0].wait(), timeout=0.2) == created[0].returncode
        if mode == "cancel_twice" and os.name == "posix":
            assert kill_calls, "A child ignoring SIGTERM must be killed after the grace period"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for process in created:
            if process.returncode is None:
                process.kill()
            await process.communicate()
