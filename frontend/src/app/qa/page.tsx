"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/auth/clerk";
import { getLocalAuthToken } from "@/auth/localAuth";
import {
  Loader2,
  Play,
  CheckCircle,
  XCircle,
  MinusCircle,
  Clock,
  AlertTriangle,
  FileText,
  Image,
} from "lucide-react";

import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useActiveBoard } from "@/lib/active-project";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

interface BoardOption {
  id: string;
  name: string;
}

interface TaskOption {
  id: string;
  title: string;
}

function getAuthToken(): string {
  return getLocalAuthToken() || "";
}

async function runTests(taskId: string, browsers?: string, grep?: string) {
  const token = getAuthToken();
  const params = new URLSearchParams({ task_id: taskId });
  if (browsers) params.set("browsers", browsers);
  if (grep) params.set("grep", grep);
  const res = await fetch(`${BASE_URL}/api/v1/qa/test?${params}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Test run failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function getTestReport(runId: string) {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/qa/test/${runId}/report`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch report");
  return res.json();
}

async function fetchBoards(): Promise<BoardOption[]> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/boards`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch boards");
  const data = await res.json();
  return data.items || [];
}

async function fetchBoardTasks(boardId: string): Promise<TaskOption[]> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/boards/${boardId}/tasks`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch board tasks");
  const data = await res.json();
  return data.items || [];
}

export default function QAPage() {
  const { isSignedIn } = useAuth();
  const [activeBoardId, setActiveBoardId] = useActiveBoard();
  const [boards, setBoards] = useState<BoardOption[]>([]);
  const [boardTasks, setBoardTasks] = useState<TaskOption[]>([]);
  const [taskId, setTaskId] = useState("");
  const [browsers, setBrowsers] = useState("");
  const [grep, setGrep] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<any>(null);
  const [reportRunId, setReportRunId] = useState<string | null>(null);
  const [report, setReport] = useState<any>(null);
  const [showReportDialog, setShowReportDialog] = useState(false);

  const loadBoardsAndTasks = useCallback(async () => {
    const nextBoards = await fetchBoards();
    setBoards(nextBoards);
    const boardId = activeBoardId || nextBoards[0]?.id || "";
    if (boardId && boardId !== activeBoardId) {
      setActiveBoardId(boardId);
    }
    const tasks = boardId ? await fetchBoardTasks(boardId) : [];
    setBoardTasks(tasks);
  }, [activeBoardId, setActiveBoardId]);

  useEffect(() => {
    if (isSignedIn) {
      void loadBoardsAndTasks();
    }
  }, [isSignedIn, loadBoardsAndTasks]);

  useEffect(() => {
    if (!isSignedIn) return;
    const intervalId = window.setInterval(() => {
      void loadBoardsAndTasks();
    }, 30000);
    return () => window.clearInterval(intervalId);
  }, [isSignedIn, loadBoardsAndTasks]);

  const handleRun = async () => {
    if (!taskId) return;
    setIsRunning(true);
    setError(null);
    setLastResult(null);
    try {
      const result = await runTests(taskId, browsers || undefined, grep || undefined);
      setLastResult(result);
      setReportRunId(result.run_id);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsRunning(false);
    }
  };

  const handleViewReport = async () => {
    if (!reportRunId) return;
    try {
      const data = await getTestReport(reportRunId);
      setReport(data);
      setShowReportDialog(true);
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to run QA tests.",
          forceRedirectUrl: "/qa",
          signUpForceRedirectUrl: "/qa",
        }}
        title="QA Testing"
        description="Run Playwright e2e tests and view test reports."
        headerActions={
          <select
            value={activeBoardId}
            onChange={(e) => setActiveBoardId(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select project</option>
            {boards.map((board) => (
              <option key={board.id} value={board.id}>{board.name}</option>
            ))}
          </select>
        }
        stickyHeader
      >
        {/* Run form */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">Run Tests</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Task *</label>
              <select
                value={taskId}
                onChange={(e) => setTaskId(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select task</option>
                {boardTasks.map((task) => (
                  <option key={task.id} value={task.id}>{task.title}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Browsers</label>
              <input
                type="text"
                value={browsers}
                onChange={(e) => setBrowsers(e.target.value)}
                placeholder="chromium,webkit,firefox"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Grep filter</label>
              <input
                type="text"
                value={grep}
                onChange={(e) => setGrep(e.target.value)}
                placeholder="Filter test names..."
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="flex items-end">
              <button
                onClick={handleRun}
                disabled={!taskId || isRunning}
                className={buttonVariants({ size: "md", variant: "primary" })}
              >
                {isRunning ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Play className="mr-2 h-4 w-4" />
                )}
                Run Tests
              </button>
            </div>
          </div>
        </div>

        {/* Last result */}
        {lastResult && (
          <div className="mt-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-slate-700">Test Results</h2>
              {reportRunId && (
                <button
                  onClick={handleViewReport}
                  className={buttonVariants({ size: "sm", variant: "outline" })}
                >
                  <FileText className="mr-1 h-3 w-3" />
                  Full Report
                </button>
              )}
            </div>
            <div className="grid grid-cols-4 gap-4">
              <div className="rounded-lg bg-slate-50 p-3 text-center">
                <p className="text-2xl font-bold text-slate-800">{lastResult.report?.total || 0}</p>
                <p className="text-xs text-slate-500">Total</p>
              </div>
              <div className="rounded-lg bg-green-50 p-3 text-center">
                <p className="text-2xl font-bold text-green-600">{lastResult.report?.passed || 0}</p>
                <p className="text-xs text-slate-500">Passed</p>
              </div>
              <div className="rounded-lg bg-red-50 p-3 text-center">
                <p className="text-2xl font-bold text-red-600">{lastResult.report?.failed || 0}</p>
                <p className="text-xs text-slate-500">Failed</p>
              </div>
              <div className="rounded-lg bg-amber-50 p-3 text-center">
                <p className="text-2xl font-bold text-amber-600">{lastResult.report?.skipped || 0}</p>
                <p className="text-xs text-slate-500">Skipped</p>
              </div>
            </div>
            {lastResult.tests && lastResult.tests.length > 0 && (
              <div className="mt-4 space-y-2">
                {lastResult.tests.map((test: any, i: number) => {
                  const Icon =
                    test.status === "passed"
                      ? CheckCircle
                      : test.status === "failed"
                      ? XCircle
                      : MinusCircle;
                  const color =
                    test.status === "passed"
                      ? "text-green-500"
                      : test.status === "failed"
                      ? "text-red-500"
                      : "text-slate-400";
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50 p-3"
                    >
                      <Icon className={cn("h-4 w-4 flex-shrink-0", color)} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-700 truncate">{test.title}</p>
                        {test.error && (
                          <p className="text-xs text-red-500 mt-0.5 truncate">{test.error}</p>
                        )}
                      </div>
                      <span className="text-xs text-slate-400 flex-shrink-0">
                        {test.duration_ms?.toFixed(0)}ms
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-lg bg-red-50 border border-red-200 p-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-500 flex-shrink-0" />
            <p className="text-sm text-red-600">{error}</p>
          </div>
        )}
      </DashboardPageLayout>

      {/* Report Dialog */}
      <Dialog open={showReportDialog} onOpenChange={setShowReportDialog}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Test Report</DialogTitle>
            <DialogDescription>Run {reportRunId}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {report && (
              <>
                <div className="flex items-center gap-3">
                  <span className={cn(
                    "px-2 py-0.5 rounded text-xs font-medium",
                    report.status === "succeeded" ? "bg-green-100 text-green-700"
                      : report.status === "failed" ? "bg-red-100 text-red-700"
                      : "bg-slate-100 text-slate-600"
                  )}>
                    {report.status}
                  </span>
                  {report.summary && (
                    <span className="text-xs text-slate-500">{report.summary}</span>
                  )}
                </div>
                {report.evidence && report.evidence.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-slate-600 mb-2">Evidence Files</p>
                    {report.evidence.map((ev: any, i: number) => {
                      const Icon = ev.type === "screenshot" ? Image : FileText;
                      return (
                        <div key={i} className="flex items-center gap-2 text-xs text-slate-500 py-1">
                          <Icon className="h-3 w-3" />
                          <span className="truncate">{ev.path}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
                {report.error && (
                  <div className="rounded-lg bg-red-50 border border-red-200 p-3">
                    <p className="text-xs text-red-600">{report.error}</p>
                  </div>
                )}
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
