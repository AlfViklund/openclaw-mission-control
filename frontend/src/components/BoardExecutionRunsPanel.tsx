"use client";

import { useMemo, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { Activity, Play, RefreshCcw } from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  getListExecutionRunsApiV1BoardsBoardIdExecutionRunsGetQueryKey,
  useListExecutionArtifactsApiV1BoardsBoardIdExecutionRunsRunIdArtifactsGet,
  useCreateExecutionRunApiV1BoardsBoardIdExecutionRunsPost,
  useListExecutionRunsApiV1BoardsBoardIdExecutionRunsGet,
} from "@/api/generated/executions/executions";
import type { ExecutionArtifactRead, ExecutionRunRead } from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import { parseApiDatetime } from "@/lib/datetime";
import { cn } from "@/lib/utils";

type BoardExecutionRunsPanelProps = {
  boardId: string;
  taskId?: string | null;
  taskTitle?: string | null;
  canWrite?: boolean;
};

type RunFilter = "all" | "healthy" | "stale" | "resumable" | "heartbeatable";

type RuntimeSessionSummary = {
  sessionKey: string;
  latestRun: ExecutionRunRead;
  runCount: number;
  healthyCount: number;
  staleCount: number;
  resumableCount: number;
  heartbeatableCount: number;
};

type SessionFilter = "all" | "live" | "stale" | "resumable";

const formatTimestamp = (value?: string | null) => {
  if (!value) return "—";
  const date = parseApiDatetime(value);
  if (!date) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const previewBody = (value?: string | null) => {
  if (!value) return "—";
  const trimmed = value.trim().replace(/\s+/g, " ");
  return trimmed.length > 140 ? `${trimmed.slice(0, 137)}…` : trimmed;
};

const toTitleLabel = (value: string) =>
  value
    .replace(/_/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.replace(/^./, (char) => char.toUpperCase()))
    .join(" ");

const statusTone = (status: string) => {
  if (status === "done") return "bg-emerald-50 text-emerald-700";
  if (status === "running") return "bg-blue-50 text-blue-700";
  if (status === "failed") return "bg-rose-50 text-rose-700";
  if (status === "blocked") return "bg-amber-100 text-amber-700";
  if (status === "paused") return "bg-slate-100 text-slate-700";
  return "bg-slate-100 text-slate-700";
};

const phaseTone = (phase: string) => {
  if (phase === "done") return "bg-emerald-50 text-emerald-700";
  if (phase === "review") return "bg-violet-50 text-violet-700";
  if (phase === "test") return "bg-amber-100 text-amber-700";
  if (phase === "build") return "bg-sky-50 text-sky-700";
  return "bg-slate-100 text-slate-700";
};

const formatActionError = (err: unknown, fallback: string) => {
  if (err instanceof ApiError) {
    if (err.status === 403) {
      return "Read-only access. You do not have permission to create execution runs.";
    }
    return err.message || fallback;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
};

const summaryFields: Array<{
  key: keyof Pick<ExecutionRunRead, "plan_summary" | "build_summary" | "test_summary">;
  label: string;
}> = [
  { key: "plan_summary", label: "Plan" },
  { key: "build_summary", label: "Build" },
  { key: "test_summary", label: "Test" },
];

const STALE_RUN_THRESHOLD_MS = 10 * 60 * 1000;

const formatArtifactState = (artifactState: ExecutionArtifactRead["artifact_state"]) => {
  if (!artifactState) return null;
  try {
    return JSON.stringify(artifactState, null, 2);
  } catch {
    return String(artifactState);
  }
};

const formatHeartbeatAge = (seconds?: number | null) => {
  if (seconds === undefined || seconds === null) return null;
  const totalSeconds = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const hours = Math.floor(minutes / 60);
  if (hours > 0) {
    const remainderMinutes = minutes % 60;
    return remainderMinutes > 0 ? `${hours}h ${remainderMinutes}m ago` : `${hours}h ago`;
  }
  if (minutes > 0) {
    return `${minutes}m ago`;
  }
  return `${totalSeconds}s ago`;
};

const getHeartbeatAgeSeconds = (run: ExecutionRunRead) => {
  if (typeof run.heartbeat_age_seconds === "number") {
    return run.heartbeat_age_seconds;
  }
  if (!run.last_heartbeat_at) {
    return null;
  }
  const heartbeat = parseApiDatetime(run.last_heartbeat_at);
  if (!heartbeat) {
    return null;
  }
  return (Date.now() - heartbeat.getTime()) / 1000;
};

const fallbackRunIsStale = (run: ExecutionRunRead) => {
  if (run.status !== "running" || !run.last_heartbeat_at) {
    return false;
  }
  const heartbeat = parseApiDatetime(run.last_heartbeat_at);
  if (!heartbeat) {
    return false;
  }
  return Date.now() - heartbeat.getTime() >= STALE_RUN_THRESHOLD_MS;
};

export function BoardExecutionRunsPanel({
  boardId,
  taskId = null,
  taskTitle = null,
  canWrite = false,
}: BoardExecutionRunsPanelProps) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [runFilter, setRunFilter] = useState<RunFilter>("all");
  const [sessionFilter, setSessionFilter] = useState<SessionFilter>("all");
  const [selectedSessionKey, setSelectedSessionKey] = useState<string | null>(null);

  const runsQuery = useListExecutionRunsApiV1BoardsBoardIdExecutionRunsGet(boardId, {
    query: {
      enabled: Boolean(boardId),
      staleTime: 15_000,
    },
  });

  const createRunMutation = useCreateExecutionRunApiV1BoardsBoardIdExecutionRunsPost({
    mutation: {
      onError: (err: unknown) => {
        setError(formatActionError(err, "Unable to create execution run."));
      },
    },
  });

  const handleResumeSelectedRun = async () => {
    if (!selectedRun || !boardId || !canWrite) return;
    setError(null);

    try {
      const response = await fetch(
        `/api/v1/boards/${boardId}/execution-runs/${selectedRun.id}/resume`,
        {
          method: "POST",
          headers: {
            Accept: "application/json",
          },
        },
      );
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as
          | { detail?: string }
          | null;
        throw new Error(payload?.detail || "Unable to resume execution run.");
      }
      await runsQuery.refetch();
      await artifactsQuery.refetch();
    } catch (err) {
      setError(formatActionError(err, "Unable to resume execution run."));
    }
  };

  const handleHeartbeatSelectedRun = async () => {
    if (!selectedRun || !boardId || !canWrite) return;
    setError(null);

    try {
      const response = await fetch(
        `/api/v1/boards/${boardId}/execution-runs/${selectedRun.id}/heartbeat`,
        {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            source: "operator",
            message: "Dashboard heartbeat",
          }),
        },
      );
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as
          | { detail?: string }
          | null;
        throw new Error(payload?.detail || "Unable to record heartbeat.");
      }
      await runsQuery.refetch();
      await artifactsQuery.refetch();
    } catch (err) {
      setError(formatActionError(err, "Unable to record heartbeat."));
    }
  };

  const runs = useMemo(() => {
    const items = runsQuery.data?.status === 200 ? runsQuery.data.data : [];
    const scoped = taskId
      ? items.filter(
          (run) => run.task_id === taskId || run.scope === "board" || run.task_id === null,
        )
      : items;
    return scoped.slice(0, 5);
  }, [runsQuery.data, taskId]);

  const filteredRuns = useMemo(() => {
    if (runFilter === "all") {
      return runs;
    }
    return runs.filter((run) => {
      const stale = run.is_stale ?? fallbackRunIsStale(run);
      const healthy = run.status === "done" || (run.status === "running" && !stale);
      const resumable = run.can_resume ?? (stale || run.status === "failed" || run.status === "paused");
      const heartbeatable = run.can_heartbeat ?? (run.status === "running" && !stale);
      switch (runFilter) {
        case "healthy":
          return healthy;
        case "stale":
          return stale;
        case "resumable":
          return resumable;
        case "heartbeatable":
          return heartbeatable;
        default:
          return true;
      }
    });
  }, [runFilter, runs]);

  const effectiveSelectedRunId =
    selectedRunId && filteredRuns.some((run) => run.id === selectedRunId)
      ? selectedRunId
      : filteredRuns[0]?.id ?? runs[0]?.id ?? null;

  const selectedRun = useMemo(
    () => runs.find((run) => run.id === effectiveSelectedRunId) ?? null,
    [runs, effectiveSelectedRunId],
  );

  const artifactsQuery = useListExecutionArtifactsApiV1BoardsBoardIdExecutionRunsRunIdArtifactsGet(
    boardId,
    effectiveSelectedRunId ?? "",
    {
      query: {
        enabled: Boolean(boardId && effectiveSelectedRunId),
        staleTime: 15_000,
      },
    },
  );

  const artifacts = useMemo(
    () => (artifactsQuery.data?.status === 200 ? artifactsQuery.data.data : []),
    [artifactsQuery.data],
  );

  const effectiveSelectedArtifactId =
    selectedArtifactId && artifacts.some((artifact) => artifact.id === selectedArtifactId)
      ? selectedArtifactId
      : artifacts[0]?.id ?? null;

  const selectedArtifact = useMemo(
    () => artifacts.find((artifact) => artifact.id === effectiveSelectedArtifactId) ?? null,
    [artifacts, effectiveSelectedArtifactId],
  );

  const hasRuns = runs.length > 0;
  const canStartRun = canWrite && !createRunMutation.isPending;
  const selectedRunRecovery = selectedRun ?? null;
  const selectedRunIsStale = Boolean(
    selectedRunRecovery?.is_stale ?? (selectedRun ? fallbackRunIsStale(selectedRun) : false),
  );
  const runOverview = useMemo(() => {
    const healthy = runs.filter((run) => {
      if (run.status !== "running") {
        return run.status === "done";
      }
      return !(run.is_stale ?? fallbackRunIsStale(run));
    }).length;
    const stale = runs.filter((run) => run.is_stale ?? fallbackRunIsStale(run)).length;
    const resumable = runs.filter((run) => run.can_resume ?? false).length;
    const heartbeatable = runs.filter((run) => run.can_heartbeat ?? false).length;
    return { healthy, stale, resumable, heartbeatable, total: runs.length };
  }, [runs]);

  const runtimeSessions = useMemo<RuntimeSessionSummary[]>(() => {
    const sessionsByKey = new Map<string, ExecutionRunRead[]>();
    for (const run of runs) {
      const key = run.runtime_session_key;
      if (!key) continue;
      const items = sessionsByKey.get(key) ?? [];
      sessionsByKey.set(key, [...items, run]);
    }

    return [...sessionsByKey.entries()]
      .map(([sessionKey, sessionRuns]) => {
        const sortedRuns = [...sessionRuns].sort(
          (left, right) => right.updated_at.localeCompare(left.updated_at),
        );
        const latestRun = sortedRuns[0];
        const healthyCount = sessionRuns.filter((run) => {
          const stale = run.is_stale ?? fallbackRunIsStale(run);
          return run.status === "done" || (run.status === "running" && !stale);
        }).length;
        const staleCount = sessionRuns.filter((run) => run.is_stale ?? fallbackRunIsStale(run)).length;
        const resumableCount = sessionRuns.filter((run) => run.can_resume ?? false).length;
        const heartbeatableCount = sessionRuns.filter((run) => run.can_heartbeat ?? false).length;
        return {
          sessionKey,
          latestRun,
          runCount: sessionRuns.length,
          healthyCount,
          staleCount,
          resumableCount,
          heartbeatableCount,
        };
      })
      .sort((left, right) => right.latestRun.updated_at.localeCompare(left.latestRun.updated_at));
  }, [runs]);

  const filteredRuntimeSessions = useMemo(() => {
    if (sessionFilter === "all") {
      return runtimeSessions;
    }
    return runtimeSessions.filter((session) => {
      const latestStale = session.latestRun.is_stale ?? fallbackRunIsStale(session.latestRun);
      const latestResumable = session.latestRun.can_resume ?? latestStale;
      switch (sessionFilter) {
        case "live":
          return !latestStale;
        case "stale":
          return latestStale;
        case "resumable":
          return latestResumable;
        default:
          return true;
      }
    });
  }, [runtimeSessions, sessionFilter]);

  const effectiveSelectedSessionKey =
    selectedRun?.runtime_session_key ??
    (selectedSessionKey && runtimeSessions.some((session) => session.sessionKey === selectedSessionKey)
      ? selectedSessionKey
      : runtimeSessions[0]?.sessionKey ?? null);
  const canResumeSelectedRun = Boolean(
    canWrite && (selectedRunRecovery?.can_resume ?? selectedRunIsStale),
  );
  const canHeartbeatSelectedRun = Boolean(
    canWrite &&
      (selectedRunRecovery?.can_heartbeat ?? (selectedRun ? !fallbackRunIsStale(selectedRun) : false)),
  );

  const handleInspectSession = (sessionKey: string) => {
    const session = runtimeSessions.find((item) => item.sessionKey === sessionKey);
    if (!session) return;
    setSelectedSessionKey(sessionKey);
    setSelectedRunId(session.latestRun.id);
    setRunFilter("all");
  };

  const handleRefresh = async () => {
    setError(null);
    await runsQuery.refetch();
    if (effectiveSelectedRunId) {
      await artifactsQuery.refetch();
    }
  };

  const handleStartRun = async () => {
    if (!boardId || !canWrite) return;
    setError(null);

    try {
      await createRunMutation.mutateAsync({
        boardId,
        data: {
          task_id: taskId,
          scope: taskId ? "task" : "board",
          runtime_kind: "opencode",
          status: "pending",
          current_phase: "plan",
          plan_summary: taskTitle ? `Plan for ${taskTitle}` : undefined,
        },
      });
      await queryClient.invalidateQueries({
        queryKey: getListExecutionRunsApiV1BoardsBoardIdExecutionRunsGetQueryKey(boardId),
      });
    } catch (err) {
      setError(formatActionError(err, "Unable to create execution run."));
    }
  };

  const renderEvidenceTimeline = () => {
    if (!selectedRun) {
      return (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
          Select a run to inspect its evidence timeline.
        </div>
      );
    }

    if (artifactsQuery.error) {
      return (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
          Unable to load evidence artifacts.
        </div>
      );
    }

    if (artifactsQuery.isLoading) {
      return <p className="text-sm text-slate-500">Loading evidence artifacts…</p>;
    }

    return (
      <div className="grid gap-3 lg:grid-cols-[220px_minmax(0,1fr)]">
        <div className="space-y-2">
          {artifacts.length > 0 ? (
            artifacts.map((artifact) => {
              const isSelected = artifact.id === selectedArtifact?.id;
              return (
                <button
                  key={artifact.id}
                  type="button"
                  onClick={() => setSelectedArtifactId(artifact.id)}
                  className={cn(
                    "w-full rounded-xl border p-3 text-left transition",
                    isSelected
                      ? "border-violet-300 bg-violet-50"
                      : "border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-white",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-900">{artifact.title}</p>
                      <p className="mt-1 text-[11px] text-slate-500">
                        {artifact.kind} · {formatTimestamp(artifact.created_at)}
                      </p>
                    </div>
                  </div>
                  <p className="mt-2 text-xs text-slate-600">{previewBody(artifact.body)}</p>
                </button>
              );
            })
          ) : (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
              No evidence artifacts yet for this run.
            </div>
          )}
        </div>

        {selectedArtifact ? (
          <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-900">
                  {selectedArtifact.title}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {selectedArtifact.kind} · Created {formatTimestamp(selectedArtifact.created_at)} · Updated {formatTimestamp(selectedArtifact.updated_at)}
                </p>
              </div>
              <span className="rounded-full bg-white px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                Evidence
              </span>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Body</p>
              <pre className="mt-3 whitespace-pre-wrap text-sm text-slate-700">
                {selectedArtifact.body || "—"}
              </pre>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Artifact state
              </p>
              <pre className="mt-3 overflow-auto whitespace-pre-wrap text-xs text-slate-700">
                {formatArtifactState(selectedArtifact.artifact_state) || "—"}
              </pre>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
            Select an artifact to inspect its evidence body and state.
          </div>
        )}
      </div>
    );
  };

  const renderRecoverySummary = () => {
    if (!selectedRun) {
      return null;
    }

    const runRecovery = selectedRun;
    const heartbeatAgeLabel = formatHeartbeatAge(getHeartbeatAgeSeconds(runRecovery));
    const recoveryState = selectedRun.recovery_state ? JSON.stringify(selectedRun.recovery_state) : null;
    const executionState = selectedRun.execution_state
      ? JSON.stringify(selectedRun.execution_state)
      : null;
    const lastDispatchPhase =
      selectedRun.execution_state && typeof selectedRun.execution_state === "object"
        ? (selectedRun.execution_state as Record<string, unknown>).last_dispatched_phase
        : null;
    const lastDispatchRuntimeKind =
      selectedRun.execution_state && typeof selectedRun.execution_state === "object"
        ? (selectedRun.execution_state as Record<string, unknown>).last_dispatched_runtime_kind
        : null;
    const lastHeartbeatSource =
      selectedRun.recovery_state && typeof selectedRun.recovery_state === "object"
        ? (selectedRun.recovery_state as Record<string, unknown>).last_heartbeat_source
        : null;
    const lastHeartbeatMessage =
      selectedRun.recovery_state && typeof selectedRun.recovery_state === "object"
        ? (selectedRun.recovery_state as Record<string, unknown>).last_heartbeat_message
        : null;

    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Recovery
            </p>
            <p className="mt-1 text-sm font-medium text-slate-900">
              {runRecovery.is_stale ? "Stale run" : "Healthy run"}
            </p>
          </div>
          <span className="rounded-full bg-white px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
            {selectedRun.retry_count ?? 0} retries
          </span>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg bg-white px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Resume eligible
            </p>
            <p className="mt-1 text-sm text-slate-700">
              {runRecovery.can_resume ? "Yes" : "No"}
            </p>
          </div>
          <div className="rounded-lg bg-white px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Heartbeat eligible
            </p>
            <p className="mt-1 text-sm text-slate-700">
              {runRecovery.can_heartbeat ? "Yes" : "No"}
            </p>
          </div>
          <div className="rounded-lg bg-white px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Heartbeat age
            </p>
            <p className="mt-1 text-sm text-slate-700">{heartbeatAgeLabel || "—"}</p>
          </div>
          <div className="rounded-lg bg-white px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Last heartbeat
            </p>
            <p className="mt-1 text-sm text-slate-700">
              {formatTimestamp(selectedRun.last_heartbeat_at)}
            </p>
          </div>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div className="rounded-lg bg-white px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Last dispatch
            </p>
            <p className="mt-1 text-sm text-slate-700">
              {lastDispatchPhase ? String(lastDispatchPhase) : "—"}
            </p>
            {lastDispatchRuntimeKind ? (
              <p className="mt-1 text-xs text-slate-500">{String(lastDispatchRuntimeKind)}</p>
            ) : null}
          </div>
          <div className="rounded-lg bg-white px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Last heartbeat source
            </p>
            <p className="mt-1 text-sm text-slate-700">
              {lastHeartbeatSource ? String(lastHeartbeatSource) : "—"}
            </p>
            {lastHeartbeatMessage ? (
              <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                {String(lastHeartbeatMessage)}
              </p>
            ) : null}
          </div>
          <div className="rounded-lg bg-white px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Execution state
            </p>
            <p className="mt-1 line-clamp-3 text-xs text-slate-500">
              {executionState || "—"}
            </p>
          </div>
        </div>

        {recoveryState ? (
          <div className="mt-3 rounded-lg bg-white px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Recovery state
            </p>
            <pre className="mt-1 overflow-auto whitespace-pre-wrap text-xs text-slate-700">
              {recoveryState}
            </pre>
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Execution runs
          </p>
          <p className="text-xs text-slate-400">Plan / build / test / review evidence</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={runsQuery.isFetching}
            className="gap-1.5"
          >
            <RefreshCcw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <Button
            size="sm"
            onClick={handleStartRun}
            disabled={!canStartRun}
            title={canWrite ? "Start execution run" : "Read-only access"}
            className="gap-1.5"
          >
            <Play className="h-3.5 w-3.5" />
            Start run
          </Button>
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
          {error}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
          Total {runOverview.total}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
          Healthy {runOverview.healthy}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
          Stale {runOverview.stale}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
          Resumable {runOverview.resumable}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
          Heartbeatable {runOverview.heartbeatable}
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        {[
          ["all", `All (${runs.length})`],
          ["healthy", `Healthy (${runOverview.healthy})`],
          ["stale", `Stale (${runOverview.stale})`],
          ["resumable", `Resumable (${runOverview.resumable})`],
          ["heartbeatable", `Heartbeatable (${runOverview.heartbeatable})`],
        ].map(([value, label]) => {
          const active = runFilter === value;
          return (
            <button
              key={value}
              type="button"
              onClick={() => setRunFilter(value as RunFilter)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide transition",
                active
                  ? "border-sky-300 bg-sky-50 text-sky-700"
                  : "border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:bg-slate-50",
              )}
            >
              {label}
            </button>
          );
        })}
      </div>

      {runtimeSessions.length > 0 ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-slate-900">Runtime sessions</p>
              <p className="text-xs text-slate-500">
                Grouped by runtime session key. Inspect the latest run in each session.
              </p>
            </div>
            <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
              {filteredRuntimeSessions.length} sessions
            </span>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {[
              ["all", `All (${runtimeSessions.length})`],
              ["live", `Live (${runtimeSessions.filter((session) => !(session.latestRun.is_stale ?? fallbackRunIsStale(session.latestRun))).length})`],
              ["stale", `Stale (${runtimeSessions.filter((session) => session.latestRun.is_stale ?? fallbackRunIsStale(session.latestRun)).length})`],
              ["resumable", `Resumable (${runtimeSessions.filter((session) => session.latestRun.can_resume ?? (session.latestRun.is_stale ?? fallbackRunIsStale(session.latestRun))).length})`],
            ].map(([value, label]) => {
              const active = sessionFilter === value;
              return (
                <button
                  key={value}
                  type="button"
                  onClick={() => setSessionFilter(value as SessionFilter)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide transition",
                    active
                      ? "border-violet-300 bg-violet-50 text-violet-700"
                      : "border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:bg-slate-50",
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
            {filteredRuntimeSessions.map((session) => {
              const latestRunIsSelected = selectedRun?.id === session.latestRun.id;
              const isActive = effectiveSelectedSessionKey === session.sessionKey;
              const latestStale = session.latestRun.is_stale ?? fallbackRunIsStale(session.latestRun);
              const latestHeartbeat = formatHeartbeatAge(getHeartbeatAgeSeconds(session.latestRun));
              return (
                <button
                  key={session.sessionKey}
                  type="button"
                  onClick={() => handleInspectSession(session.sessionKey)}
                  className={cn(
                    "rounded-xl border p-3 text-left transition",
                    isActive
                      ? "border-sky-300 bg-sky-50"
                      : "border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-white",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-900">
                        {session.sessionKey}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-500">
                        Latest {session.latestRun.runtime_kind || "opencode"} · {session.latestRun.current_phase ?? "plan"}
                      </p>
                    </div>
                    <span
                      className={cn(
                        "rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide",
                        latestStale
                          ? "bg-amber-100 text-amber-700"
                          : "bg-emerald-50 text-emerald-700",
                      )}
                    >
                      {latestStale ? "Stale" : "Live"}
                    </span>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500">
                    <div className="rounded-lg bg-white px-2 py-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                        Runs
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-700">{session.runCount}</p>
                    </div>
                    <div className="rounded-lg bg-white px-2 py-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                        Heartbeat
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-700">
                        {latestHeartbeat || "—"}
                      </p>
                    </div>
                    <div className="rounded-lg bg-white px-2 py-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                        Healthy
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-700">
                        {session.healthyCount}
                      </p>
                    </div>
                    <div className="rounded-lg bg-white px-2 py-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                        Resumable
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-700">
                        {session.resumableCount}
                      </p>
                    </div>
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                    <span className="rounded-full bg-white px-2 py-1">
                      Stale {session.staleCount}
                    </span>
                    <span className="rounded-full bg-white px-2 py-1">
                      Heartbeatable {session.heartbeatableCount}
                    </span>
                    <span className="rounded-full bg-white px-2 py-1">
                      {latestRunIsSelected ? "Selected" : "Inspect latest"}
                    </span>
                  </div>
                </button>
              );
            })}
            {filteredRuntimeSessions.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                No runtime sessions match the selected filter.
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {runsQuery.error ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
          Unable to load execution runs.
        </div>
      ) : runsQuery.isLoading ? (
        <p className="text-sm text-slate-500">Loading execution runs…</p>
      ) : hasRuns ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          <div className="space-y-3">
            {filteredRuns.map((run) => {
              const status = run.status ?? "pending";
              const phase = run.current_phase ?? "plan";
              const runRecovery = run;
              const runIsStale = runRecovery.is_stale ?? fallbackRunIsStale(run);
              const heartbeatAgeLabel = formatHeartbeatAge(getHeartbeatAgeSeconds(runRecovery));
              const isSelected = run.id === selectedRun?.id;
              return (
                <button
                  key={run.id}
                  type="button"
                  onClick={() => setSelectedRunId(run.id)}
                  className={cn(
                    "w-full rounded-xl border p-3 text-left transition",
                    isSelected
                      ? "border-blue-300 bg-blue-50"
                      : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50",
                  )}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={cn(
                            "rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide",
                            statusTone(status),
                          )}
                        >
                          {toTitleLabel(status)}
                        </span>
                      <span
                        className={cn(
                          "rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide",
                          phaseTone(phase),
                        )}
                      >
                        {toTitleLabel(phase)}
                      </span>
                      {runIsStale ? (
                        <span className="rounded-full bg-amber-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                          Stale
                        </span>
                      ) : null}
                    </div>
                      <p className="mt-2 text-sm font-medium text-slate-900">
                        {run.runtime_kind || "opencode"}
                        {run.runtime_session_key ? ` · ${run.runtime_session_key}` : ""}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        Updated {formatTimestamp(run.updated_at)}
                      </p>
                      {heartbeatAgeLabel ? (
                        <p className="mt-1 text-xs text-slate-500">
                          {runIsStale ? `Stale for ${heartbeatAgeLabel}` : `Heartbeat ${heartbeatAgeLabel}`}
                        </p>
                      ) : null}
                    </div>
                    <div className="shrink-0 text-right text-xs text-slate-500">
                      <p>{run.retry_count ?? 0} retries</p>
                      <p>{formatTimestamp(run.completed_at ?? run.started_at ?? run.created_at)}</p>
                    </div>
                  </div>

                  <div className="mt-3 space-y-2">
                    {summaryFields.map(({ key, label }) => {
                      const value = run[key];
                      if (!value) return null;
                      return (
                        <div key={`${run.id}-${key}`} className="rounded-lg bg-slate-50 px-3 py-2">
                          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                            {label}
                          </p>
                          <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{value}</p>
                        </div>
                      );
                    })}
                  </div>

                  {run.last_error ? (
                    <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                      {run.last_error}
                    </div>
                  ) : null}

                  <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
                    <span className="inline-flex items-center gap-1">
                      <Activity className="h-3.5 w-3.5" />
                      {run.scope ?? "task"}
                    </span>
                    {run.task_id ? <span>Task {run.task_id}</span> : null}
                    {run.agent_id ? <span>Agent {run.agent_id}</span> : null}
                    {run.last_heartbeat_at ? (
                      <span>Heartbeat {formatTimestamp(run.last_heartbeat_at)}</span>
                    ) : null}
                  </div>
                </button>
              );
            })}
            {filteredRuns.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                No runs match the selected recovery filter.
              </div>
            ) : null}
          </div>

          <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900">Evidence timeline</p>
                <p className="text-xs text-slate-500">
                  {selectedRun
                    ? `Inspect artifacts for ${selectedRun.runtime_kind || "opencode"} · ${selectedRun.status ?? "pending"}`
                    : "Select a run to inspect evidence."}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {selectedRun ? (
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                    {selectedRun.current_phase ?? "plan"}
                  </span>
                ) : null}
                {canHeartbeatSelectedRun ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void handleHeartbeatSelectedRun()}
                    className="gap-1.5"
                  >
                    Heartbeat
                  </Button>
                ) : null}
                {canResumeSelectedRun ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void handleResumeSelectedRun()}
                    className="gap-1.5"
                  >
                    Resume
                  </Button>
                ) : null}
              </div>
            </div>

            {renderRecoverySummary()}
            {renderEvidenceTimeline()}
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
          <div className="flex items-center gap-2 text-slate-700">
            <Activity className="h-4 w-4" />
            <span className="font-medium">No execution runs yet.</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {taskTitle
              ? `Start a run to capture plan, build, and test evidence for ${taskTitle}.`
              : "Start a board-level run to capture plan, build, and test evidence."}
          </p>
        </div>
      )}
    </div>
  );
}

export default BoardExecutionRunsPanel;
