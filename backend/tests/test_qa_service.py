"""Tests for QAService pre-flight checks and test execution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.qa import PlaywrightRunner, TestReport


class TestPlaywrightRunnerPreflight:
    """Tests for PlaywrightRunner pre-flight checks."""

    @pytest.mark.asyncio
    async def test_returns_error_when_npx_not_found(self, monkeypatch) -> None:
        monkeypatch.setattr("app.services.qa.shutil.which", lambda _cmd: None)

        runner = PlaywrightRunner(test_dir="/tmp/project")
        report = await runner.run_tests()

        assert isinstance(report, TestReport)
        assert report.error
        assert "npx not found" in report.error
        assert report.total == 0

    @pytest.mark.asyncio
    async def test_returns_error_when_playwright_not_installed(self, monkeypatch) -> None:
        import subprocess

        monkeypatch.setattr("app.services.qa.shutil.which", lambda _cmd: "/usr/bin/npx")

        def fake_run(*args, **kwargs):
            return SimpleNamespace(returncode=1, stderr="command not found: playwright")

        monkeypatch.setattr("app.services.qa.subprocess", SimpleNamespace(run=fake_run, TimeoutExpired=TimeoutError))

        runner = PlaywrightRunner(test_dir="/tmp/project")
        report = await runner.run_tests()

        assert isinstance(report, TestReport)
        assert report.error
        assert "Playwright not installed" in report.error


class TestPlaywrightRunnerExecution:
    """Tests for PlaywrightRunner test execution with browsers."""

    @pytest.mark.asyncio
    async def test_multiple_browsers_use_separate_project_flags(self, monkeypatch) -> None:
        import subprocess

        monkeypatch.setattr("app.services.qa.shutil.which", lambda _cmd: "/usr/bin/npx")
        monkeypatch.setattr(
            "app.services.qa.subprocess",
            SimpleNamespace(
                run=lambda *a, **k: SimpleNamespace(returncode=0, stderr=""),
                TimeoutExpired=TimeoutError,
            ),
        )

        captured_cmd: list[str] = []

        class FakeProc:
            def __init__(self, *cmd, **kwargs):
                captured_cmd.extend(cmd)
                self.stdout = None
                self.stderr = None
                self.returncode = 0

            async def communicate(self):
                return (b'{"suites": [], "stats": {"tests": 0}}', b"")

        monkeypatch.setattr(
            "app.services.qa.asyncio.create_subprocess_exec",
            lambda *cmd, **kw: FakeProc(*cmd, **kw),
        )

        runner = PlaywrightRunner(test_dir="/tmp/project")
        await runner.run_tests(browsers=["chromium", "firefox"])

        projects = [i for i, c in enumerate(captured_cmd) if c == "--project"]
        assert len(projects) == 2
        assert captured_cmd[projects[0] + 1] == "chromium"
        assert captured_cmd[projects[1] + 1] == "firefox"
