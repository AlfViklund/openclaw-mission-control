"""QA service for running Playwright tests and parsing results."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.core.time import utcnow
from app.models.artifacts import Artifact
from app.models.runs import Run
from app.models.tasks import Task
from app.services.artifact_storage import save_artifact_file
from app.services.runs import complete_run, create_run, start_run

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

EVIDENCE_DIR = Path(__file__).resolve().parents[4] / "storage" / "evidence" / "qa"

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a single test case."""

    title: str
    status: str  # passed, failed, skipped, timedOut
    duration: float  # milliseconds
    error: str | None = None
    path: str = ""


@dataclass
class TestReport:
    """Parsed Playwright test report."""

    __test__ = False

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration: float = 0.0
    tests: list[TestResult] = field(default_factory=list)
    raw_path: str = ""
    screenshot_paths: list[str] = field(default_factory=list)
    error: str = ""


class PlaywrightRunner:
    """Runs Playwright tests and parses JSON reports."""

    def __init__(self, test_dir: str | None = None):
        self._test_dir = test_dir

    async def run_tests(
        self,
        *,
        browsers: list[str] | None = None,
        grep: str | None = None,
        timeout: int = 120000,
    ) -> TestReport:
        """Run Playwright tests and return parsed report."""
        npx = shutil.which("npx")
        if not npx:
            report = TestReport()
            report.error = "npx not found on PATH — Playwright cannot run"
            return report

        try:
            ver = subprocess.run(
                [npx, "playwright", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if ver.returncode != 0:
                report = TestReport()
                report.error = f"Playwright not installed: {ver.stderr.strip()}"
                return report
        except subprocess.TimeoutExpired:
            report = TestReport()
            report.error = "Timed out checking Playwright installation"
            return report

        run_id = str(uuid4())
        output_dir = EVIDENCE_DIR / run_id
        output_dir.mkdir(parents=True, exist_ok=True)

        report_path = output_dir / "report.json"
        screenshot_dir = output_dir / "screenshots"
        screenshot_dir.mkdir(exist_ok=True)

        cmd = [
            npx, "playwright", "test",
            "--reporter=json",
            f"--output={screenshot_dir}",
        ]
        if browsers:
            for browser in browsers:
                browser_name = browser.strip()
                if browser_name:
                    cmd.extend(["--project", browser_name])
        if grep:
            cmd.extend(["--grep", grep])

        start = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._test_dir,
            )
            stdout, stderr = await proc.communicate()

            report = self._parse_report(stdout)
            report.duration = (time.time() - start) * 1000
            report.raw_path = str(report_path)

            report_path.write_text(json.dumps({
                "total": report.total,
                "passed": report.passed,
                "failed": report.failed,
                "skipped": report.skipped,
                "duration_ms": report.duration,
                "tests": [
                    {"title": t.title, "status": t.status, "duration_ms": t.duration, "error": t.error}
                    for t in report.tests
                ],
            }, indent=2))

            screenshots = list(screenshot_dir.glob("*.png"))
            report.screenshot_paths = [str(s) for s in screenshots]

            return report

        except FileNotFoundError:
            return TestReport(
                failed=1,
                tests=[TestResult(
                    title="Playwright not found",
                    status="failed",
                    duration=0,
                    error="npx playwright not found. Install Playwright first.",
                )],
            )
        except Exception as exc:
            return TestReport(
                failed=1,
                tests=[TestResult(
                    title="Test runner error",
                    status="failed",
                    duration=0,
                    error=str(exc),
                )],
            )

    def _parse_report(self, stdout: bytes) -> TestReport:
        """Parse Playwright JSON report output."""
        report = TestReport()

        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            return report

        if isinstance(data, dict):
            suites = data.get("suites", [])
        elif isinstance(data, list):
            suites = data
        else:
            return report

        for suite in suites:
            for spec in suite.get("specs", []):
                for test in spec.get("tests", []):
                    for result in test.get("results", []):
                        status = result.get("status", "unknown")
                        duration = result.get("duration", 0)
                        error = None
                        if result.get("errors"):
                            error = "\n".join(
                                e.get("message", "") for e in result["errors"]
                            )

                        test_result = TestResult(
                            title=spec.get("title", ""),
                            status=status,
                            duration=duration,
                            error=error,
                            path=spec.get("file", ""),
                        )
                        report.tests.append(test_result)
                        report.total += 1

                        if status == "passed":
                            report.passed += 1
                        elif status == "failed":
                            report.failed += 1
                        elif status in ("skipped", "pending"):
                            report.skipped += 1

        return report


class QAService:
    """Orchestrates QA test execution for tasks."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._test_dir: str | None = None

    async def run_tests_for_task(
        self,
        task_id: UUID,
        *,
        agent_id: UUID | None = None,
        test_dir: str | None = None,
        browsers: list[str] | None = None,
        grep: str | None = None,
    ) -> dict:
        """Run QA tests for a task and store results."""
        self._test_dir = test_dir
        task = await Task.objects.by_id(task_id).first(self._session)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        run = await create_run(
            self._session,
            task_id=task_id,
            agent_id=agent_id or task.assigned_agent_id,
            runtime="opencode_cli",
            stage="test",
        )
        run = await start_run(self._session, run)

        runner = PlaywrightRunner(test_dir=self._test_dir)
        report = await runner.run_tests(browsers=browsers, grep=grep)

        evidence_paths = []
        if report.raw_path:
            evidence_paths.append({
                "type": "test_report",
                "path": report.raw_path,
                "size_bytes": 0,
            })
        for ss in report.screenshot_paths:
            evidence_paths.append({
                "type": "screenshot",
                "path": ss,
                "size_bytes": 0,
            })

        success = report.failed == 0 and report.total > 0
        summary = (
            f"Tests: {report.passed} passed, {report.failed} failed, "
            f"{report.skipped} skipped ({report.duration:.0f}ms)"
        )

        await complete_run(
            self._session,
            run,
            success=success,
            summary=summary,
            evidence_paths=evidence_paths,
            error_message=summary if report.failed > 0 else None,
        )

        await self._save_report_as_artifact(task_id, report, run.id)

        return {
            "run_id": str(run.id),
            "report": {
                "total": report.total,
                "passed": report.passed,
                "failed": report.failed,
                "skipped": report.skipped,
                "duration_ms": report.duration,
            },
            "tests": [
                {
                    "title": t.title,
                    "status": t.status,
                    "duration_ms": t.duration,
                    "error": t.error,
                }
                for t in report.tests
            ],
        }

    async def run_tests_for_existing_run(
        self,
        run: Run,
        *,
        test_dir: str | None = None,
        browsers: list[str] | None = None,
        grep: str | None = None,
    ) -> tuple[TestReport, list[dict], bool, str]:
        """Execute tests for an already-created pipeline run."""
        self._test_dir = test_dir
        report = await PlaywrightRunner(test_dir=self._test_dir).run_tests(
            browsers=browsers,
            grep=grep,
        )

        evidence_paths: list[dict] = []
        if report.raw_path:
            evidence_paths.append(
                {
                    "type": "test_report",
                    "path": report.raw_path,
                    "size_bytes": 0,
                }
            )
        for screenshot in report.screenshot_paths:
            evidence_paths.append(
                {
                    "type": "screenshot",
                    "path": screenshot,
                    "size_bytes": 0,
                }
            )

        success = report.failed == 0 and report.total > 0
        summary = (
            f"Tests: {report.passed} passed, {report.failed} failed, "
            f"{report.skipped} skipped ({report.duration:.0f}ms)"
        )

        await self._save_report_as_artifact(run.task_id, report, run.id)
        return report, evidence_paths, success, summary

    async def _save_report_as_artifact(
        self,
        task_id: UUID,
        report: TestReport,
        run_id: UUID,
    ) -> None:
        """Save test report as an artifact attached to the task."""
        task = await Task.objects.by_id(task_id).first(self._session)
        if not task or not task.board_id:
            return

        report_content = json.dumps(
            {
                "run_id": str(run_id),
                "total": report.total,
                "passed": report.passed,
                "failed": report.failed,
                "skipped": report.skipped,
                "duration_ms": report.duration,
                "tests": [
                    {
                        "title": t.title,
                        "status": t.status,
                        "duration_ms": t.duration,
                        "error": t.error,
                    }
                    for t in report.tests
                ],
            },
            indent=2,
        )

        try:
            storage_path, size_bytes, checksum = save_artifact_file(
                board_id=str(task.board_id),
                filename=f"test_report_{run_id}.json",
                content=report_content.encode(),
            )

            artifact = Artifact(
                board_id=task.board_id,
                task_id=task_id,
                type="test_report",
                source="generated",
                filename=f"test_report_{run_id}.json",
                mime_type="application/json",
                size_bytes=size_bytes,
                storage_path=storage_path,
                checksum=checksum,
            )
            self._session.add(artifact)
            await self._session.commit()
        except Exception:
            logger.exception("Failed to save test report artifact for task %s", task_id)
