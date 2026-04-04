"use client";

import { useMemo, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { Sparkles, Plus, FileText } from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  getListSpecArtifactsApiV1BoardsBoardIdSpecArtifactsGetQueryKey,
  useApplySpecArtifactApiV1BoardsBoardIdSpecArtifactsSpecArtifactIdApplyPost,
  useCreateSpecArtifactApiV1BoardsBoardIdSpecArtifactsPost,
  useDraftSpecArtifactApiV1BoardsBoardIdSpecArtifactsSpecArtifactIdDraftPost,
  useListSpecArtifactsApiV1BoardsBoardIdSpecArtifactsGet,
} from "@/api/generated/planner/planner";
import type { PlannerDraftRead, SpecArtifactRead } from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { parseApiDatetime } from "@/lib/datetime";
import { cn } from "@/lib/utils";

type BoardSpecArtifactsPanelProps = {
  boardId: string;
  canWrite?: boolean;
  onBoardRefresh?: () => Promise<void> | void;
};

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

const previewBody = (value: string) => {
  const trimmed = value.trim().replace(/\s+/g, " ");
  return trimmed.length > 120 ? `${trimmed.slice(0, 117)}…` : trimmed;
};

const formatActionError = (err: unknown, fallback: string) => {
  if (err instanceof ApiError) {
    if (err.status === 403) {
      return "Read-only access. You do not have permission to change spec artifacts.";
    }
    return err.message || fallback;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
};

export function BoardSpecArtifactsPanel({
  boardId,
  canWrite = false,
  onBoardRefresh,
}: BoardSpecArtifactsPanelProps) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draftsById, setDraftsById] = useState<Record<string, PlannerDraftRead>>({});
  const [appliedCountsById, setAppliedCountsById] = useState<Record<string, number>>({});

  const listQuery = useListSpecArtifactsApiV1BoardsBoardIdSpecArtifactsGet(boardId, {
    query: {
      enabled: Boolean(boardId),
      staleTime: 15_000,
    },
  });

  const createMutation = useCreateSpecArtifactApiV1BoardsBoardIdSpecArtifactsPost({
    mutation: {
      onError: (err: unknown) => {
        setError(formatActionError(err, "Unable to save spec artifact."));
      },
    },
  });

  const draftMutation = useDraftSpecArtifactApiV1BoardsBoardIdSpecArtifactsSpecArtifactIdDraftPost({
    mutation: {
      onError: (err: unknown) => {
        setError(formatActionError(err, "Unable to generate a planner draft."));
      },
    },
  });

  const applyMutation = useApplySpecArtifactApiV1BoardsBoardIdSpecArtifactsSpecArtifactIdApplyPost({
    mutation: {
      onError: (err: unknown) => {
        setError(formatActionError(err, "Unable to apply the spec artifact."));
      },
    },
  });

  const artifacts = useMemo(
    () =>
      listQuery.data?.status === 200
        ? [...listQuery.data.data].sort((left, right) => right.created_at.localeCompare(left.created_at))
        : [],
    [listQuery.data],
  );

  const handleCreate = async () => {
    if (!boardId || !title.trim() || !body.trim()) return;
    setError(null);
    setMessage(null);
    try {
      await createMutation.mutateAsync({
        boardId,
        data: {
          title: title.trim(),
          body: body.trim(),
          source: "markdown",
        },
      });
      setTitle("");
      setBody("");
      await queryClient.invalidateQueries({
        queryKey: getListSpecArtifactsApiV1BoardsBoardIdSpecArtifactsGetQueryKey(boardId),
      });
      setMessage("Spec artifact saved.");
    } catch {
      // handled by mutation callback
    }
  };

  const handleDraft = async (artifact: SpecArtifactRead) => {
    setError(null);
    setMessage(null);
    try {
      const response = await draftMutation.mutateAsync({
        boardId,
        specArtifactId: artifact.id,
      });
      if (response.status === 200) {
        setDraftsById((current) => ({
          ...current,
          [artifact.id]: response.data,
        }));
        setMessage(`Drafted ${response.data.node_count} tasks from ${artifact.title}.`);
      }
    } catch {
      // handled by mutation callback
    }
  };

  const handleApply = async (artifact: SpecArtifactRead) => {
    setError(null);
    setMessage(null);
    try {
      const response = await applyMutation.mutateAsync({
        boardId,
        specArtifactId: artifact.id,
      });
      if (response.status === 200) {
        setAppliedCountsById((current) => ({
          ...current,
          [artifact.id]: response.data.length,
        }));
        await onBoardRefresh?.();
        await queryClient.invalidateQueries({
          queryKey: getListSpecArtifactsApiV1BoardsBoardIdSpecArtifactsGetQueryKey(boardId),
        });
        setMessage(`Applied ${response.data.length} tasks from ${artifact.title}.`);
      }
    } catch {
      // handled by mutation callback
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Spec artifacts
          </p>
          <p className="text-xs text-slate-400">Seed and draft the backlog from a markdown spec</p>
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
          {error}
        </div>
      ) : null}
      {message ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
          {message}
        </div>
      ) : null}

      <div className="space-y-2 rounded-xl border border-slate-200 bg-white p-3">
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Spec title"
          disabled={!canWrite || createMutation.isPending}
        />
        <Textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          placeholder="Write a markdown spec with headings and bullet points."
          rows={5}
          disabled={!canWrite || createMutation.isPending}
        />
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-slate-500">
            {canWrite
              ? "Headings and bullets become a deterministic DAG draft."
              : "Read-only access. Spec creation is disabled."}
          </p>
          <Button
            size="sm"
            onClick={handleCreate}
            disabled={!canWrite || createMutation.isPending || !title.trim() || !body.trim()}
            className="gap-1.5"
          >
            <Plus className="h-3.5 w-3.5" />
            Save spec
          </Button>
        </div>
      </div>

      {listQuery.error ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
          Unable to load spec artifacts.
        </div>
      ) : listQuery.isLoading ? (
        <p className="text-sm text-slate-500">Loading spec artifacts…</p>
      ) : artifacts.length > 0 ? (
        <div className="space-y-2">
          {artifacts.map((artifact) => {
            const draft = draftsById[artifact.id];
            const appliedCount = appliedCountsById[artifact.id];
            return (
              <div key={artifact.id} className="rounded-xl border border-slate-200 bg-white p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-900">{artifact.title}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {artifact.source} · {formatTimestamp(artifact.created_at)}
                    </p>
                    <p className="mt-2 text-xs text-slate-600">{previewBody(artifact.body)}</p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleDraft(artifact)}
                      disabled={!canWrite || draftMutation.isPending || applyMutation.isPending}
                      className="gap-1.5"
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      Draft
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => handleApply(artifact)}
                      disabled={!canWrite || draftMutation.isPending || applyMutation.isPending}
                      className="gap-1.5"
                    >
                      <FileText className="h-3.5 w-3.5" />
                      Apply
                    </Button>
                  </div>
                </div>

                {draft ? (
                  <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                    <p className="font-semibold text-slate-900">
                      Draft: {draft.node_count} tasks
                    </p>
                    <ul className="mt-1 space-y-1">
                      {draft.nodes.slice(0, 3).map((node) => (
                        <li key={node.key} className="truncate">
                          {node.title}
                          {(node.depends_on_keys ?? []).length > 0
                            ? ` ← ${(node.depends_on_keys ?? []).join(", ")}`
                            : ""}
                        </li>
                      ))}
                    </ul>
                    {draft.nodes.length > 3 ? (
                      <p className="mt-1 text-[11px] text-slate-500">
                        +{draft.nodes.length - 3} more tasks
                      </p>
                    ) : null}
                  </div>
                ) : null}

                {typeof appliedCount === "number" ? (
                  <p className="mt-2 text-xs text-emerald-700">
                    Applied {appliedCount} tasks to the board.
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div className={cn("rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500")}>
          No spec artifacts yet.
        </div>
      )}
    </div>
  );
}

export default BoardSpecArtifactsPanel;
