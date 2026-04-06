"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Eye,
  Loader2,
  Play,
  RefreshCcw,
  XCircle,
} from "lucide-react";

import { getLocalAuthToken } from "@/auth/localAuth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
const STAGES = ["plan", "build"] as const;

type RunRecord = {
  id: string;
  runtime: string;
  stage: string;
  status: string;
  summary?: string | null;
  error_message?: string | null;
  failure_kind?: string | null;
  retryable?: boolean;
  created_at: string;
  evidence_paths: { type: string; path: string; size_bytes: number }[];
};

type PipelineStageState = {
  stage: string;
  status: string;
  latest_run?: RunRecord | null;
};

type PipelineSummary = {
  task_id: string;
  task_status: string;
  work_state?: string | null;
  can_start_work: boolean;
  use_start_work: boolean;
  recommended_runtime: string;
  next_required_stage?: string | null;
  requires_approval: boolean;
  approval_reason?: string | null;
  ready_for_review: boolean;
  latest_failed_stage?: string | null;
  latest_failure_kind?: string | null;
  runtime_ready: boolean;
  runtime_blocker_code?: string | null;
  runtime_blocker?: string | null;
  execution_mode: string;
  cooldown_until?: string | null;
  cooldown_message?: string | null;
  degraded_allowed: boolean;
  recommended_action?: string | null;
  queue_state?: string | null;
  queue_position?: number | null;
  latest_completion_report?: CompletionReport | null;
  stages: PipelineStageState[];
};

type CompletionReport = {
  summary: string;
  files_touched: string[];
  checks_run: string[];
  checks_result: string;
  artifacts: string[];
  known_risks: string[];
};

type Props = {
  taskId: string;
  boardId: string;
  canWrite: boolean;
  onTaskUpdated?: (task: { status?: string }) => void;
};

function getAuthToken(): string {
  return getLocalAuthToken() || "";
}

async function fetchPipelineSummary(taskId: string): Promise<PipelineSummary> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/pipeline/tasks/${taskId}/summary`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error("Failed to load pipeline summary");
  }
  return res.json();
}

async function executeNext(taskId: string) {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/pipeline/tasks/${taskId}/execute-next`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Execute failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function startWork(taskId: string) {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/pipeline/tasks/${taskId}/start-work`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Start work failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function requestReview(taskId: string) {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/pipeline/tasks/${taskId}/request-review`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Review request failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function submitCompletionReport(
  boardId: string,
  taskId: string,
  report: CompletionReport,
) {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/boards/${boardId}/tasks/${taskId}/comments`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      kind: "completion_report",
      completion_report: report,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Completion report failed: ${res.status} ${text}`);
  }
  return res.json();
}

function stageVisualStatus(stage: PipelineStageState): string {
  if (stage.status === "running") return "running";
  if (stage.status === "failed") return "failed";
  if (stage.status === "succeeded") return "succeeded";
  return "pending";
}

function runtimeLabel(runtime: string | undefined): string {
  if (runtime === "opencode_cli") return "OpenCode CLI";
  if (runtime === "acp") return "ACP";
  if (runtime === "openrouter") return "OpenRouter";
  return runtime || "Unknown";
}

function splitListInput(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatCooldown(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString();
}

export function PipelineVisualization({
  taskId,
  boardId,
  canWrite,
  onTaskUpdated,
}: Props) {
  const [summary, setSummary] = useState<PipelineSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isExecuting, setIsExecuting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showEvidenceForm, setShowEvidenceForm] = useState(false);
  const [reportSummary, setReportSummary] = useState("");
  const [checksResult, setChecksResult] = useState("");
  const [filesTouchedText, setFilesTouchedText] = useState("");
  const [checksRunText, setChecksRunText] = useState("");
  const [artifactsText, setArtifactsText] = useState("");
  const [knownRisksText, setKnownRisksText] = useState("");

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const nextSummary = await fetchPipelineSummary(taskId);
      setSummary(nextSummary);
      setActionError(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to load pipeline state");
    } finally {
      setIsLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!summary?.latest_completion_report) return;
    setReportSummary(summary.latest_completion_report.summary);
    setChecksResult(summary.latest_completion_report.checks_result);
    setFilesTouchedText(summary.latest_completion_report.files_touched.join("\n"));
    setChecksRunText(summary.latest_completion_report.checks_run.join("\n"));
    setArtifactsText(summary.latest_completion_report.artifacts.join("\n"));
    setKnownRisksText(summary.latest_completion_report.known_risks.join("\n"));
  }, [summary?.latest_completion_report]);

  const completionReportDraft = useMemo<CompletionReport>(
    () => ({
      summary: reportSummary.trim(),
      files_touched: splitListInput(filesTouchedText),
      checks_run: splitListInput(checksRunText),
      checks_result: checksResult.trim(),
      artifacts: splitListInput(artifactsText),
      known_risks: splitListInput(knownRisksText),
    }),
    [artifactsText, checksResult, checksRunText, filesTouchedText, knownRisksText, reportSummary],
  );

  const completionReportValid = useMemo(() => {
    return Boolean(
      completionReportDraft.summary &&
        completionReportDraft.checks_result &&
        (completionReportDraft.checks_run.length > 0 ||
          completionReportDraft.artifacts.length > 0),
    );
  }, [completionReportDraft]);

  const actionLabel = useMemo(() => {
    if (!summary) return "Run next step";
    switch (summary.recommended_action) {
      case "start_work":
        return "Start work";
      case "retry_stage":
        return `Retry ${summary.next_required_stage ?? "stage"}`;
      case "run_next_step":
        return `Run ${summary.next_required_stage ?? "next step"}`;
      case "request_review":
        return "Request review";
      case "request_degraded_review":
        return "Request degraded review";
      case "submit_completion_evidence":
        return "Submit completion evidence";
      case "await_lead_review":
        return "Waiting for lead review";
      case "wait_for_runtime_recovery":
        return "Pipeline cooldown";
      default:
        break;
    }
    return "Pipeline complete";
  }, [summary]);

  const canRunPrimaryAction = useMemo(() => {
    if (!canWrite || !summary) return false;
    if (summary.recommended_action === "submit_completion_evidence") {
      return !showEvidenceForm || completionReportValid;
    }
    return ["start_work", "run_next_step", "retry_stage", "request_review", "request_degraded_review"].includes(
      summary.recommended_action ?? "",
    );
  }, [canWrite, completionReportValid, showEvidenceForm, summary]);

  const handlePrimaryAction = useCallback(async () => {
    if (!summary || !canWrite) return;
    setIsExecuting(true);
    setActionError(null);
    try {
      if (summary.recommended_action === "submit_completion_evidence") {
        if (!showEvidenceForm) {
          setShowEvidenceForm(true);
          return;
        }
        if (!completionReportValid) {
          throw new Error("Completion report needs a summary, checks result, and at least one check or artifact.");
        }
        await submitCompletionReport(boardId, taskId, completionReportDraft);
      } else if (summary.recommended_action === "start_work") {
        await startWork(taskId);
        onTaskUpdated?.({ status: "in_progress" });
      } else if (summary.recommended_action === "run_next_step" || summary.recommended_action === "retry_stage") {
        await executeNext(taskId);
      } else if (
        summary.recommended_action === "request_review" ||
        summary.recommended_action === "request_degraded_review"
      ) {
        const updated = await requestReview(taskId);
        onTaskUpdated?.(updated.task_summary ? { status: "review" } : updated);
      }
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Pipeline action failed");
    } finally {
      setIsExecuting(false);
    }
  }, [
    summary,
    canWrite,
    showEvidenceForm,
    completionReportValid,
    boardId,
    taskId,
    completionReportDraft,
    onTaskUpdated,
    load,
  ]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
      </div>
    );
  }

  const visibleStages: PipelineStageState[] =
    summary?.stages ??
    STAGES.map((stage) => ({
      stage,
      status: "pending",
      latest_run: null,
    }));

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Execution
          </p>
          <p className="mt-1 text-sm text-slate-700">
            Normal task flow runs through OpenCode CLI. `/runs` stays available for evidence and manual debug.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => void handlePrimaryAction()}
            disabled={!canRunPrimaryAction || isExecuting}
          >
            {isExecuting ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="mr-2 h-3.5 w-3.5" />
            )}
            {actionLabel}
          </Button>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={isExecuting}>
            <RefreshCcw className="mr-2 h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </div>

      {!summary?.runtime_ready && summary?.runtime_blocker ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">
                Runtime blocked{summary.runtime_blocker_code ? ` · ${summary.runtime_blocker_code}` : ""}
              </p>
              <p className="mt-1 text-xs">{summary.runtime_blocker}</p>
              {summary.cooldown_message ? (
                <p className="mt-1 text-xs">{summary.cooldown_message}</p>
              ) : null}
              {summary.cooldown_until ? (
                <p className="mt-1 text-xs">Retry after {formatCooldown(summary.cooldown_until)}.</p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {summary?.requires_approval && summary.approval_reason ? (
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">
          {summary.approval_reason}
        </div>
      ) : null}

      {summary?.queue_state === "queued" ? (
        <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-600">
          This task has a queued run
          {summary.queue_position ? ` · position ${summary.queue_position}` : ""}.
          Only one board run executes at a time.
        </div>
      ) : null}

      {actionError ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
          {actionError}
        </div>
      ) : null}

      {summary?.latest_completion_report ? (
        <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-700">
          <p className="font-semibold text-slate-900">Completion evidence</p>
          <p className="mt-1">{summary.latest_completion_report.summary}</p>
          <p className="mt-2 text-slate-500">
            Checks: {summary.latest_completion_report.checks_result}
            {summary.latest_completion_report.checks_run.length
              ? ` · ${summary.latest_completion_report.checks_run.join(", ")}`
              : ""}
          </p>
        </div>
      ) : null}

      {showEvidenceForm || summary?.recommended_action === "submit_completion_evidence" ? (
        <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Completion report
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Use this when the runtime is blocked but the task is code-complete and ready for lead review.
            </p>
          </div>
          <Textarea
            value={reportSummary}
            onChange={(event) => setReportSummary(event.target.value)}
            placeholder="Summarize what was completed."
            className="min-h-[96px]"
          />
          <Input
            value={checksResult}
            onChange={(event) => setChecksResult(event.target.value)}
            placeholder="Checks result, e.g. npm test passed"
          />
          <Textarea
            value={checksRunText}
            onChange={(event) => setChecksRunText(event.target.value)}
            placeholder={"Checks run, one per line\nnpm test\nnpm run lint"}
            className="min-h-[84px]"
          />
          <Textarea
            value={filesTouchedText}
            onChange={(event) => setFilesTouchedText(event.target.value)}
            placeholder={"Files touched, one per line\nsrc/app.ts\nsrc/lib/api.ts"}
            className="min-h-[84px]"
          />
          <Textarea
            value={artifactsText}
            onChange={(event) => setArtifactsText(event.target.value)}
            placeholder={"Artifacts, one per line\ncoverage/report.txt"}
            className="min-h-[84px]"
          />
          <Textarea
            value={knownRisksText}
            onChange={(event) => setKnownRisksText(event.target.value)}
            placeholder={"Known risks, one per line\nNeeds lead sanity check on migrations"}
            className="min-h-[84px]"
          />
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-3">
        {visibleStages.map((stage) => {
          const visualStatus = stageVisualStatus(stage);
          const Icon =
            visualStatus === "succeeded"
              ? CheckCircle
              : visualStatus === "running"
                ? Loader2
                : visualStatus === "failed"
                  ? XCircle
                  : Clock;
          const tone =
            visualStatus === "succeeded"
              ? "border-green-200 bg-green-50 text-green-700"
              : visualStatus === "running"
                ? "border-blue-200 bg-blue-50 text-blue-700"
                : visualStatus === "failed"
                  ? "border-rose-200 bg-rose-50 text-rose-700"
                  : "border-slate-200 bg-white text-slate-600";
          return (
            <div key={stage.stage} className={cn("rounded-xl border p-3", tone)}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Icon
                    className={cn(
                      "h-4 w-4",
                      visualStatus === "running" ? "animate-spin" : undefined,
                    )}
                  />
                  <span className="text-sm font-semibold capitalize">{stage.stage}</span>
                </div>
                <span className="text-[10px] uppercase tracking-wide">
                  {visualStatus}
                </span>
              </div>
              {stage.latest_run ? (
                <div className="mt-2 space-y-1 text-xs">
                  <p className="text-slate-700">
                    {runtimeLabel(stage.latest_run.runtime)}
                    {stage.latest_run.failure_kind
                      ? ` · ${stage.latest_run.failure_kind.replace(/_/g, " ")}`
                      : ""}
                  </p>
                  {stage.latest_run.summary ? (
                    <p className="line-clamp-3 text-slate-600">{stage.latest_run.summary}</p>
                  ) : null}
                  {stage.latest_run.error_message ? (
                    <p className="line-clamp-3 text-rose-700">{stage.latest_run.error_message}</p>
                  ) : null}
                  {stage.latest_run.evidence_paths.length > 0 ? (
                    <p className="inline-flex items-center gap-1 text-slate-500">
                      <Eye className="h-3 w-3" />
                      {stage.latest_run.evidence_paths.length} evidence item
                      {stage.latest_run.evidence_paths.length === 1 ? "" : "s"}
                    </p>
                  ) : null}
                </div>
              ) : (
                <p className="mt-2 text-xs text-slate-500">
                  No {stage.stage} run yet.
                </p>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <span>Recommended runtime: {runtimeLabel(summary?.recommended_runtime)}</span>
        {summary?.execution_mode === "degraded" ? <span>Degraded review fallback available.</span> : null}
        {summary?.latest_failed_stage ? (
          <span>
            Latest failure: {summary.latest_failed_stage}
            {summary.latest_failure_kind ? ` · ${summary.latest_failure_kind.replace(/_/g, " ")}` : ""}
          </span>
        ) : null}
        {summary?.ready_for_review ? <span>Ready for review.</span> : null}
      </div>
    </div>
  );
}
