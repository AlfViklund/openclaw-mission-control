"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/auth/clerk";
import {
  Loader2,
  Play,
  Square,
  CheckCircle,
  XCircle,
  Clock,
  AlertTriangle,
  FileText,
  Terminal,
  Code,
  Eye,
} from "lucide-react";

import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Run {
  id: string;
  task_id: string;
  agent_id: string | null;
  runtime: string;
  stage: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  model: string | null;
  temperature: number | null;
  permissions_profile: string | null;
  evidence_paths: { type: string; path: string; size_bytes: number }[];
  summary: string | null;
  error_message: string | null;
  created_at: string;
}

const STATUS_CONFIG: Record<string, { icon: typeof CheckCircle; color: string; bg: string; label: string }> = {
  queued: { icon: Clock, color: "text-slate-500", bg: "bg-slate-100", label: "Queued" },
  running: { icon: Loader2, color: "text-blue-500", bg: "bg-blue-100", label: "Running" },
  succeeded: { icon: CheckCircle, color: "text-green-500", bg: "bg-green-100", label: "Succeeded" },
  failed: { icon: XCircle, color: "text-red-500", bg: "bg-red-100", label: "Failed" },
  canceled: { icon: Square, color: "text-amber-500", bg: "bg-amber-100", label: "Canceled" },
};

const STAGE_COLORS: Record<string, string> = {
  plan: "bg-blue-100 text-blue-700",
  build: "bg-purple-100 text-purple-700",
  test: "bg-green-100 text-green-700",
};

const RUNTIME_LABELS: Record<string, string> = {
  acp: "ACP (Gateway)",
  opencode_cli: "OpenCode CLI",
  openrouter: "OpenRouter API",
};

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

function getAuthToken(): string {
  return localStorage.getItem("mc_auth_token") || "";
}

async function fetchRuns(filters?: { task_id?: string; stage?: string; status?: string }): Promise<Run[]> {
  const token = getAuthToken();
  const params = new URLSearchParams();
  if (filters?.task_id) params.set("task_id", filters.task_id);
  if (filters?.stage) params.set("stage", filters.stage);
  if (filters?.status) params.set("status", filters.status);
  const res = await fetch(`${BASE_URL}/api/v1/runs?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch runs");
  const data = await res.json();
  return data.items || [];
}

async function createRun(taskId: string, stage: string, runtime: string, model?: string): Promise<Run> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/runs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ task_id: taskId, stage, runtime, model }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Create run failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function cancelRun(runId: string): Promise<Run> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/runs/${runId}/cancel`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Cancel failed");
  return res.json();
}

export default function RunsPage() {
  const { isSignedIn } = useAuth();
  const [runs, setRuns] = useState<Run[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStage, setFilterStage] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterTaskId, setFilterTaskId] = useState("");
  const [evidenceRun, setEvidenceRun] = useState<Run | null>(null);
  const [showEvidenceDialog, setShowEvidenceDialog] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [createTaskId, setCreateTaskId] = useState("");
  const [createStage, setCreateStage] = useState("plan");
  const [createRuntime, setCreateRuntime] = useState("acp");
  const [showCreateDialog, setShowCreateDialog] = useState(false);

  const loadRuns = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const filters: Record<string, string> = {};
      if (filterTaskId) filters.task_id = filterTaskId;
      if (filterStage) filters.stage = filterStage;
      if (filterStatus) filters.status = filterStatus;
      const data = await fetchRuns(filters);
      setRuns(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs");
    } finally {
      setIsLoading(false);
    }
  }, [filterTaskId, filterStage, filterStatus]);

  useEffect(() => {
    if (isSignedIn) loadRuns();
  }, [isSignedIn, loadRuns]);

  const handleCancel = async (run: Run) => {
    try {
      await cancelRun(run.id);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed");
    }
  };

  const handleCreate = async () => {
    if (!createTaskId) return;
    setIsCreating(true);
    setError(null);
    try {
      await createRun(createTaskId, createStage, createRuntime);
      setShowCreateDialog(false);
      setCreateTaskId("");
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to view runs.",
          forceRedirectUrl: "/runs",
          signUpForceRedirectUrl: "/runs",
        }}
        title="Run Evidence Store"
        description={`Tracking ${runs.length} execution run${runs.length === 1 ? "" : "s"} across all tasks.`}
        headerActions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowCreateDialog(true)}
              className={buttonVariants({ size: "md", variant: "primary" })}
            >
              <Play className="mr-2 h-4 w-4" />
              New Run
            </button>
          </div>
        }
        stickyHeader
      >
        {/* Filters */}
        <div className="flex flex-wrap gap-3 mb-4">
          <select
            value={filterStage}
            onChange={(e) => setFilterStage(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All stages</option>
            <option value="plan">Plan</option>
            <option value="build">Build</option>
            <option value="test">Test</option>
          </select>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All statuses</option>
            <option value="queued">Queued</option>
            <option value="running">Running</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
            <option value="canceled">Canceled</option>
          </select>
          <input
            type="text"
            value={filterTaskId}
            onChange={(e) => setFilterTaskId(e.target.value)}
            placeholder="Filter by task ID..."
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={loadRuns}
            className={buttonVariants({ size: "md", variant: "outline" })}
          >
            Apply
          </button>
        </div>

        {/* Runs list */}
        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
          </div>
        ) : runs.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
            <Terminal className="mx-auto h-12 w-12 text-slate-400" />
            <h3 className="mt-4 text-lg font-medium text-slate-700">No runs yet</h3>
            <p className="mt-2 text-sm text-slate-500">
              Create a run to start tracking agent executions.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {runs.map((run) => {
              const StatusIcon = STATUS_CONFIG[run.status]?.icon || Clock;
              const statusColor = STATUS_CONFIG[run.status]?.color || "text-slate-500";
              const statusBg = STATUS_CONFIG[run.status]?.bg || "bg-slate-100";
              return (
                <div
                  key={run.id}
                  className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <StatusIcon className={cn("h-5 w-5", statusColor, run.status === "running" && "animate-spin")} />
                      <div>
                        <div className="flex items-center gap-2">
                          <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", STAGE_COLORS[run.stage] || "bg-slate-100 text-slate-600")}>
                            {run.stage}
                          </span>
                          <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", statusBg, statusColor)}>
                            {STATUS_CONFIG[run.status]?.label || run.status}
                          </span>
                          <span className="text-xs text-slate-400">{RUNTIME_LABELS[run.runtime] || run.runtime}</span>
                        </div>
                        <p className="text-xs text-slate-400 mt-1">
                          Task: {run.task_id}
                          {run.model && ` · Model: ${run.model}`}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {run.evidence_paths.length > 0 && (
                        <button
                          onClick={() => { setEvidenceRun(run); setShowEvidenceDialog(true); }}
                          className="flex items-center gap-1 text-xs text-slate-600 hover:text-blue-600 transition-colors"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          Evidence ({run.evidence_paths.length})
                        </button>
                      )}
                      {run.status === "running" && (
                        <button
                          onClick={() => handleCancel(run)}
                          className="flex items-center gap-1 text-xs text-slate-600 hover:text-red-600 transition-colors"
                        >
                          <Square className="h-3.5 w-3.5" />
                          Cancel
                        </button>
                      )}
                      <span className="text-[10px] text-slate-400">
                        {new Date(run.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                  {run.error_message && (
                    <div className="mt-2 flex items-center gap-1 text-xs text-red-500">
                      <AlertTriangle className="h-3 w-3" />
                      {run.error_message}
                    </div>
                  )}
                  {run.summary && (
                    <p className="mt-2 text-xs text-slate-500">{run.summary}</p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {error && (
          <p className="mt-4 text-sm text-red-500">{error}</p>
        )}
      </DashboardPageLayout>

      {/* Create Run Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>New Run</DialogTitle>
            <DialogDescription>Start a new agent execution run.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Task ID *</label>
              <input
                type="text"
                value={createTaskId}
                onChange={(e) => setCreateTaskId(e.target.value)}
                placeholder="Task UUID"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Stage</label>
                <select
                  value={createStage}
                  onChange={(e) => setCreateStage(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="plan">Plan</option>
                  <option value="build">Build</option>
                  <option value="test">Test</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Runtime</label>
                <select
                  value={createRuntime}
                  onChange={(e) => setCreateRuntime(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="acp">ACP (Gateway)</option>
                  <option value="opencode_cli">OpenCode CLI</option>
                  <option value="openrouter">OpenRouter API</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowCreateDialog(false)}
                className={buttonVariants({ size: "md", variant: "outline" })}
                disabled={isCreating}
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={!createTaskId || isCreating}
                className={buttonVariants({ size: "md", variant: "primary" })}
              >
                {isCreating ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Play className="mr-2 h-4 w-4" />
                )}
                Start Run
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Evidence Dialog */}
      <Dialog open={showEvidenceDialog} onOpenChange={setShowEvidenceDialog}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Evidence</DialogTitle>
            <DialogDescription>
              {evidenceRun && `${evidenceRun.evidence_paths.length} evidence file${evidenceRun.evidence_paths.length === 1 ? "" : "s"} for run ${evidenceRun.id.slice(0, 8)}`}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {evidenceRun?.evidence_paths.map((ev, i) => {
              const Icon = ev.type === "prompt" ? FileText : ev.type === "events" ? Code : ev.type === "diff" ? Terminal : FileText;
              return (
                <div key={i} className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <Icon className="h-4 w-4 text-slate-500" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-700 truncate">{ev.type}</p>
                    <p className="text-[10px] text-slate-400 truncate">{ev.path}</p>
                  </div>
                  <span className="text-xs text-slate-400">{(ev.size_bytes / 1024).toFixed(1)} KB</span>
                </div>
              );
            })}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
