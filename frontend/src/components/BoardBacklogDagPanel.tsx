"use client";

import { useCallback, useMemo, useState, type ReactElement } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FileText, RefreshCcw, Sparkles, Workflow } from "lucide-react";

import { ApiError } from "@/api/mutator";
import {
  getListSpecArtifactsApiV1BoardsBoardIdSpecArtifactsGetQueryKey,
  useApplySpecArtifactApiV1BoardsBoardIdSpecArtifactsSpecArtifactIdApplyPost,
  useDraftSpecArtifactApiV1BoardsBoardIdSpecArtifactsSpecArtifactIdDraftPost,
  useListSpecArtifactsApiV1BoardsBoardIdSpecArtifactsGet,
} from "@/api/generated/planner/planner";
import type {
  PlannerDraftNodeRead,
  PlannerDraftRead,
  SpecArtifactRead,
} from "@/api/generated/model";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/atoms/Markdown";
import { parseApiDatetime } from "@/lib/datetime";
import { cn } from "@/lib/utils";

type PlannerTaskLike = {
  id: string;
  title: string;
  status: string;
  priority?: string | null;
  description?: string | null;
  created_at: string;
  updated_at: string;
  depends_on_task_ids?: string[];
  blocked_by_task_ids?: string[];
  is_blocked?: boolean;
  assigned_agent_id?: string | null;
  assignee?: string | null;
};

type BoardBacklogDagPanelProps = {
  boardId: string;
  tasks: PlannerTaskLike[];
  canWrite?: boolean;
  onTaskSelect?: (task: { id: string }) => void;
  onBoardRefresh?: () => Promise<void> | void;
};

type TaskTreeNode = {
  task: PlannerTaskLike;
  children: TaskTreeNode[];
  dependencyCount: number;
  extraDependencyCount: number;
};

type DraftTreeNode = PlannerDraftNodeRead & { children: DraftTreeNode[] };

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

const toTitleLabel = (value: string) =>
  value
    .replace(/_/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.replace(/^./, (char) => char.toUpperCase()))
    .join(" ");

const statusTone = (status: string) => {
  if (status === "done") return "bg-emerald-50 text-emerald-700";
  if (status === "review") return "bg-violet-50 text-violet-700";
  if (status === "in_progress") return "bg-sky-50 text-sky-700";
  if (status === "blocked") return "bg-amber-100 text-amber-700";
  return "bg-slate-100 text-slate-700";
};

const priorityTone = (priority: string) => {
  if (priority === "high") return "bg-rose-50 text-rose-700";
  if (priority === "medium") return "bg-amber-50 text-amber-700";
  if (priority === "low") return "bg-emerald-50 text-emerald-700";
  return "bg-slate-100 text-slate-700";
};

const formatActionError = (err: unknown, fallback: string) => {
  if (err instanceof ApiError) {
    if (err.status === 403) {
      return "Read-only access. You do not have permission to update spec artifacts.";
    }
    return err.message || fallback;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
};

const sortByTimestampThenTitle = <T extends { created_at: string; title: string }>(
  left: T,
  right: T,
) =>
  right.created_at.localeCompare(left.created_at) ||
  left.title.localeCompare(right.title);

const buildTaskTree = (tasks: PlannerTaskLike[]): TaskTreeNode[] => {
  const orderedTasks = [...tasks].sort(sortByTimestampThenTitle);
  const taskById = new Map(orderedTasks.map((task) => [task.id, task] as const));
  const childIdsByParent = new Map<string, string[]>();
  const rootIds: string[] = [];

  for (const task of orderedTasks) {
    const dependencyIds = (task.depends_on_task_ids ?? []).filter((dependencyId) =>
      taskById.has(dependencyId),
    );
    const primaryParentId = dependencyIds[0];
    if (primaryParentId) {
      const siblings = childIdsByParent.get(primaryParentId) ?? [];
      siblings.push(task.id);
      childIdsByParent.set(primaryParentId, siblings);
      continue;
    }
    rootIds.push(task.id);
  }

  const seen = new Set<string>();
  const buildNode = (taskId: string): TaskTreeNode | null => {
    if (seen.has(taskId)) return null;
    const task = taskById.get(taskId);
    if (!task) return null;
    seen.add(taskId);

    const dependencyIds = (task.depends_on_task_ids ?? []).filter((dependencyId) =>
      taskById.has(dependencyId),
    );
    const directChildren = (childIdsByParent.get(taskId) ?? [])
      .map((childTaskId) => buildNode(childTaskId))
      .filter(Boolean) as TaskTreeNode[];

    return {
      task,
      children: directChildren,
      dependencyCount: dependencyIds.length,
      extraDependencyCount: Math.max(0, dependencyIds.length - 1),
    };
  };

  const tree = rootIds.map((taskId) => buildNode(taskId)).filter(Boolean) as TaskTreeNode[];
  for (const task of orderedTasks) {
    if (!seen.has(task.id)) {
      const node = buildNode(task.id);
      if (node) tree.push(node);
    }
  }
  return tree;
};

const buildDraftTree = (nodes: PlannerDraftNodeRead[]): DraftTreeNode[] => {
  const orderedNodes = [...nodes].sort((left, right) => {
    return left.source_line - right.source_line || left.title.localeCompare(right.title);
  });
  const nodesByKey = new Map(orderedNodes.map((node) => [node.key, node] as const));
  const childKeysByParent = new Map<string, string[]>();
  const rootKeys: string[] = [];

  for (const node of orderedNodes) {
    const parentKey = node.parent_key ?? null;
    if (parentKey && nodesByKey.has(parentKey)) {
      const siblings = childKeysByParent.get(parentKey) ?? [];
      siblings.push(node.key);
      childKeysByParent.set(parentKey, siblings);
    } else {
      rootKeys.push(node.key);
    }
  }

  const buildNode = (nodeKey: string): DraftTreeNode | null => {
    const node = nodesByKey.get(nodeKey);
    if (!node) return null;
    return {
      ...node,
      children: (childKeysByParent.get(nodeKey) ?? [])
        .map((childKey) => buildNode(childKey))
        .filter(Boolean) as DraftTreeNode[],
    };
  };

  return rootKeys.map((nodeKey) => buildNode(nodeKey)).filter(Boolean) as DraftTreeNode[];
};

const renderDraftNode = (node: DraftTreeNode, depth = 0): ReactElement => {
  const dependencyKeys = node.depends_on_keys ?? [];

  return (
  <div key={node.key} className={cn(depth > 0 && "ml-4 border-l border-slate-200 pl-3") }>
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="truncate text-sm font-medium text-slate-900">{node.title}</p>
        <span className="text-[11px] text-slate-500">line {node.source_line}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-slate-500">
        <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-700">
          {node.key}
        </span>
        {dependencyKeys.length > 0 ? (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-700">
            depends on {dependencyKeys.join(", ")}
          </span>
        ) : null}
      </div>
    </div>
    {node.children.length > 0 ? (
      <div className="mt-2 space-y-2">
        {node.children.map((child) => renderDraftNode(child, depth + 1))}
      </div>
    ) : null}
  </div>
  );
};

const renderTaskNode = (
  node: TaskTreeNode,
  onTaskSelect?: (task: { id: string }) => void,
  depth = 0,
): ReactElement => {
  const priority = node.task.priority ?? "unknown";
  const status = node.task.status ?? "unknown";
  const blockedCount = node.task.blocked_by_task_ids?.length ?? 0;
  const dependencyIds = node.task.depends_on_task_ids ?? [];
  const extraDependencies = dependencyIds.slice(1, 3);

  return (
    <div key={node.task.id} className={cn(depth > 0 && "ml-4 border-l border-slate-200 pl-3")}>
      <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm transition hover:border-slate-300 hover:bg-slate-50">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <button
              type="button"
              onClick={() => onTaskSelect?.({ id: node.task.id })}
              className="block text-left text-sm font-medium text-slate-900 transition hover:text-sky-700"
            >
              {node.task.title}
            </button>
            {node.task.description ? (
              <p className="mt-1 text-xs text-slate-500">
                {previewBody(node.task.description)}
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-wide">
            <span className={cn("rounded-full px-2 py-1", statusTone(status))}>
              {toTitleLabel(status)}
            </span>
            <span className={cn("rounded-full px-2 py-1", priorityTone(priority))}>
              {priority}
            </span>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
          <span>{dependencyIds.length} dependencies</span>
          {extraDependencies.length > 0 ? (
            <span>+{extraDependencies.length} more deps</span>
          ) : null}
          {blockedCount > 0 ? (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 font-semibold text-amber-700">
              blocked by {blockedCount}
            </span>
          ) : null}
          <span>{formatTimestamp(node.task.updated_at)}</span>
        </div>
      </div>
      {node.children.length > 0 ? (
        <div className="mt-2 space-y-2">
          {node.children.map((child) => renderTaskNode(child, onTaskSelect, depth + 1))}
        </div>
      ) : null}
    </div>
  );
};

export function BoardBacklogDagPanel({
  boardId,
  tasks,
  canWrite = false,
  onTaskSelect,
  onBoardRefresh,
}: BoardBacklogDagPanelProps) {
  const queryClient = useQueryClient();
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [draftsById, setDraftsById] = useState<Record<string, PlannerDraftRead>>({});
  const [appliedCountsById, setAppliedCountsById] = useState<Record<string, number>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const listQuery = useListSpecArtifactsApiV1BoardsBoardIdSpecArtifactsGet(boardId, {
    query: {
      enabled: Boolean(boardId),
      staleTime: 15_000,
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

  const taskTree = useMemo(() => buildTaskTree(tasks), [tasks]);
  const effectiveSelectedArtifactId =
    selectedArtifactId && artifacts.some((artifact) => artifact.id === selectedArtifactId)
      ? selectedArtifactId
      : artifacts[0]?.id ?? null;

  const selectedArtifact = useMemo(
    () => artifacts.find((artifact) => artifact.id === effectiveSelectedArtifactId) ?? null,
    [artifacts, effectiveSelectedArtifactId],
  );
  const selectedDraft = selectedArtifact ? draftsById[selectedArtifact.id] ?? null : null;
  const selectedDraftTree = useMemo(
    () => (selectedDraft ? buildDraftTree(selectedDraft.nodes) : []),
    [selectedDraft],
  );

  const handleRefresh = useCallback(async () => {
    setError(null);
    await listQuery.refetch();
    await onBoardRefresh?.();
  }, [listQuery, onBoardRefresh]);

  const handleDraft = useCallback(
    async (artifact: SpecArtifactRead) => {
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
    },
    [boardId, draftMutation],
  );

  const handleApply = useCallback(
    async (artifact: SpecArtifactRead) => {
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
    },
    [applyMutation, boardId, onBoardRefresh, queryClient],
  );

  const blockedTaskCount = tasks.filter((task) => task.is_blocked).length;
  const rootTaskCount = taskTree.length;

  return (
    <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50/80 p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Backlog / DAG
          </p>
          <p className="mt-1 text-sm text-slate-600">
            Task tree on the left, spec detail and planner draft on the right.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void handleRefresh()} className="gap-1.5">
            <RefreshCcw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
          Tasks {tasks.length}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
          Roots {rootTaskCount}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
          Blocked {blockedTaskCount}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-2 py-1">
          Specs {artifacts.length}
        </span>
      </div>

      {error ? (
        <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-500">
          {error}
        </div>
      ) : null}
      {message ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
          {message}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-slate-900">Task tree</p>
              <p className="text-xs text-slate-500">Dependencies are rendered from parent to child.</p>
            </div>
            <Workflow className="h-4 w-4 text-slate-400" />
          </div>

          {taskTree.length > 0 ? (
            <div className="space-y-3">
              {taskTree.map((node) => renderTaskNode(node, onTaskSelect))}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
              No tasks yet. Apply a spec artifact to generate a backlog tree.
            </div>
          )}
        </section>

        <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-slate-900">Spec detail</p>
              <p className="text-xs text-slate-500">Select a spec to inspect the generated DAG draft.</p>
            </div>
            <FileText className="h-4 w-4 text-slate-400" />
          </div>

          {artifacts.length > 0 ? (
            <div className="grid gap-3 lg:grid-cols-[220px_minmax(0,1fr)]">
              <div className="space-y-2">
                {artifacts.map((artifact) => {
                  const isSelected = artifact.id === selectedArtifact?.id;
                  return (
                    <button
                      key={artifact.id}
                      type="button"
                      onClick={() => setSelectedArtifactId(artifact.id)}
                      className={cn(
                        "w-full rounded-xl border p-3 text-left transition",
                        isSelected
                          ? "border-sky-300 bg-sky-50"
                          : "border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-white",
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-slate-900">{artifact.title}</p>
                          <p className="mt-1 text-[11px] text-slate-500">
                            {artifact.source ?? "markdown"} · {formatTimestamp(artifact.created_at)}
                          </p>
                        </div>
                        <ChevronRight className={cn("h-4 w-4 shrink-0", isSelected ? "text-sky-600" : "text-slate-300")} />
                      </div>
                      <p className="mt-2 text-xs text-slate-600">
                        {previewBody(artifact.body)}
                      </p>
                    </button>
                  );
                })}
              </div>

              {selectedArtifact ? (
                <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {selectedArtifact.title}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {selectedArtifact.source ?? "markdown"} · Created {formatTimestamp(selectedArtifact.created_at)} · Updated {formatTimestamp(selectedArtifact.updated_at)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => void handleDraft(selectedArtifact)}
                        disabled={!canWrite || draftMutation.isPending || applyMutation.isPending}
                        className="gap-1.5"
                      >
                        <Sparkles className="h-3.5 w-3.5" />
                        Draft
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => void handleApply(selectedArtifact)}
                        disabled={!canWrite || draftMutation.isPending || applyMutation.isPending}
                        className="gap-1.5"
                      >
                        <FileText className="h-3.5 w-3.5" />
                        Apply
                      </Button>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-200 bg-white p-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Spec body
                    </p>
                    <div className="prose prose-sm mt-3 max-w-none text-slate-700">
                      <Markdown content={selectedArtifact.body} variant="description" />
                    </div>
                  </div>

                  {selectedDraft ? (
                    <div className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                            Planner draft
                          </p>
                          <p className="mt-1 text-sm text-slate-700">
                            {selectedDraft.node_count} nodes drafted from the spec.
                          </p>
                        </div>
                        <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                          {selectedDraft.spec_title}
                        </span>
                      </div>
                      <div className="mt-3 space-y-2">
                        {selectedDraftTree.map((node) => renderDraftNode(node))}
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-xl border border-dashed border-slate-200 bg-white p-4 text-sm text-slate-500">
                      Draft the spec to inspect the generated task DAG.
                    </div>
                  )}

                  {typeof appliedCountsById[selectedArtifact.id] === "number" ? (
                    <p className="text-xs font-medium text-emerald-700">
                      Applied {appliedCountsById[selectedArtifact.id]} tasks from this spec.
                    </p>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                  No spec artifact selected.
                </div>
              )}
            </div>
          ) : listQuery.isLoading ? (
            <p className="text-sm text-slate-500">Loading spec artifacts…</p>
          ) : listQuery.error ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
              Unable to load spec artifacts.
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
              No spec artifacts yet. Use the sidebar to seed a spec and then come back here to inspect
              the resulting backlog.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export default BoardBacklogDagPanel;
