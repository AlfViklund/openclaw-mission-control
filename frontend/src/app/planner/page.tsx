"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/auth/clerk";
import { getLocalAuthToken } from "@/auth/localAuth";
import {
  Loader2,
  FileText,
  GitBranch,
  Play,
  Trash2,
  AlertTriangle,
  CheckCircle,
  Clock,
  XCircle,
  RefreshCw,
  Layers,
} from "lucide-react";
import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  MarkerType,
  Position,
  Handle,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { buttonVariants } from "@/components/ui/button";
import { ConfirmActionDialog } from "@/components/ui/confirm-action-dialog";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

interface Artifact {
  id: string;
  board_id?: string;
  filename: string;
  type: string;
}

interface Board {
  id: string;
  name: string;
}

interface PlannerTask {
  id: string;
  epic_id?: string;
  title: string;
  description?: string;
  acceptance_criteria?: string[];
  depends_on?: string[];
  tags?: string[];
  estimate?: string;
  suggested_agent_role?: string;
}

interface PlannerEpicState {
  epic_id: string;
  status: string;
  coverage_summary?: string | null;
  remaining_work_summary?: string | null;
  materialized_tasks: number;
  done_tasks: number;
  open_acceptance_items: string[];
  next_focus_roles: string[];
}

interface PlannerExpansionRun {
  id: string;
  planner_output_id: string;
  board_id: string;
  round_number: number;
  status: string;
  trigger: string;
  source_epic_ids: string[];
  created_task_ids: string[];
  summary?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

interface PlannerOutput {
  id: string;
  board_id: string;
  artifact_id: string;
  status: string;
  pipeline_phase: string;
  json_schema_version: number;
  epics: { id: string; title: string; description?: string }[];
  tasks: PlannerTask[];
  documents: {
    key: string;
    title: string;
    preferred_role?: string | null;
    resolved_agent_name?: string | null;
    resolved_agent_role?: string | null;
    artifact_id?: string | null;
    filename?: string | null;
    content?: string | null;
    status?: string;
  }[];
  phase_statuses: {
    key: string;
    label: string;
    status: string;
    detail?: string | null;
  }[];
  epic_states: PlannerEpicState[];
  expansion_policy: Record<string, unknown>;
  parallelism_groups: { level: number; task_ids: string[] }[];
  materialized_task_count: number;
  remaining_scope_count: number | null;
  error_message: string | null;
  created_at: string;
  created_by: string | null;
  applied_at: string | null;
  latest_expansion_at: string | null;
}

const ROLE_COLORS: Record<string, string> = {
  dev: "bg-blue-100 text-blue-700",
  qa: "bg-green-100 text-green-700",
  docs: "bg-amber-100 text-amber-700",
  ops: "bg-purple-100 text-purple-700",
};

const STATUS_CONFIG: Record<string, { icon: typeof CheckCircle; color: string; label: string }> = {
  generating: { icon: Loader2, color: "text-blue-500", label: "Generating" },
  draft: { icon: Clock, color: "text-amber-500", label: "Draft" },
  applied: { icon: CheckCircle, color: "text-green-500", label: "Applied" },
  rejected: { icon: XCircle, color: "text-red-500", label: "Rejected" },
  failed: { icon: AlertTriangle, color: "text-red-500", label: "Failed" },
};

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

function getAuthToken(): string {
  return getLocalAuthToken() || "";
}

async function fetchSpecArtifacts(boardId?: string): Promise<Artifact[]> {
  const token = getAuthToken();
  const params = new URLSearchParams({ artifact_type: "spec" });
  if (boardId) params.set("board_id", boardId);
  const res = await fetch(`${BASE_URL}/api/v1/artifacts?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch specs");
  const data = await res.json();
  return data.items || [];
}

async function fetchBoards(): Promise<Board[]> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/boards`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch boards");
  const data = await res.json();
  return data.items || [];
}

async function generateBacklog(artifactId: string): Promise<PlannerOutput> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/planner/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ artifact_id: artifactId, max_tasks: 50 }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Generation failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function regenerateBacklog(artifactId: string): Promise<PlannerOutput> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/planner/generate?force=true`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ artifact_id: artifactId, max_tasks: 50 }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Generation failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function fetchPlannerOutputs(boardId?: string): Promise<PlannerOutput[]> {
  const token = getAuthToken();
  const params = new URLSearchParams();
  if (boardId) params.set("board_id", boardId);
  const res = await fetch(`${BASE_URL}/api/v1/planner?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch planner outputs");
  const data = await res.json();
  return data.items || [];
}

async function applyPlannerOutput(id: string): Promise<PlannerOutput> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/planner/${id}/apply`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Apply failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function expandPlannerOutput(id: string): Promise<PlannerOutput> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/planner/${id}/expand`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ trigger: "manual" }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Expand failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function updatePlannerExpansionPolicy(
  id: string,
  expansionPolicy: Record<string, unknown>,
): Promise<PlannerOutput> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/planner/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ expansion_policy: expansionPolicy }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Policy update failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function fetchPlannerExpansionRuns(id: string): Promise<PlannerExpansionRun[]> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/planner/${id}/expansions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch expansion history");
  return res.json();
}

async function deletePlannerOutput(id: string): Promise<void> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/planner/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Delete failed");
}

function TaskNode({ data }: { data: { task: PlannerTask; epicTitle?: string } }) {
  const task = data.task;
  return (
    <div className="bg-white border-2 border-slate-200 rounded-lg shadow-sm px-3 py-2 min-w-[180px] max-w-[240px] hover:border-blue-400 transition-colors">
      <Handle type="target" position={Position.Top} className="!w-2 !h-2 !bg-slate-400" />
      <div className="text-xs font-semibold text-slate-800 truncate">{task.title}</div>
      {task.suggested_agent_role && (
        <span className={cn("inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-medium mt-1", ROLE_COLORS[task.suggested_agent_role] || "bg-slate-100 text-slate-600")}>
          {task.suggested_agent_role}
        </span>
      )}
      {task.estimate && (
        <span className="ml-1 text-[9px] text-slate-400">{task.estimate}</span>
      )}
      {data.epicTitle && (
        <div className="text-[9px] text-slate-400 mt-1 truncate">{data.epicTitle}</div>
      )}
      <Handle type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-slate-400" />
    </div>
  );
}

const nodeTypes = { taskNode: TaskNode };

function PhaseTimeline({
  phaseStatuses,
  pipelinePhase,
}: {
  phaseStatuses: PlannerOutput["phase_statuses"];
  pipelinePhase: string;
}) {
  if (!phaseStatuses.length) return null;
  return (
    <div className="grid gap-2 md:grid-cols-5">
      {phaseStatuses.map((phase) => {
        const isRunning = phase.status === "running";
        const isCompleted = phase.status === "completed";
        const isFailed = phase.status === "failed";
        return (
          <div
            key={phase.key}
            className={cn(
              "rounded-xl border p-3 transition-colors",
              isCompleted && "border-green-200 bg-green-50",
              isRunning && "border-blue-200 bg-blue-50",
              isFailed && "border-red-200 bg-red-50",
              !isCompleted && !isRunning && !isFailed && "border-slate-200 bg-slate-50",
            )}
          >
            <div className="flex items-center gap-2">
              {isRunning ? (
                <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
              ) : isCompleted ? (
                <CheckCircle className="h-4 w-4 text-green-500" />
              ) : isFailed ? (
                <AlertTriangle className="h-4 w-4 text-red-500" />
              ) : (
                <Clock className="h-4 w-4 text-slate-400" />
              )}
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                {phase.key === pipelinePhase ? "Current" : phase.status}
              </p>
            </div>
            <p className="mt-2 text-sm font-medium text-slate-800">{phase.label}</p>
            {phase.detail && (
              <p className="mt-1 text-xs text-slate-600">{phase.detail}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function PlannerDocumentCard({
  document,
}: {
  document: PlannerOutput["documents"][number];
}) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      <div className="border-b border-slate-100 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold text-slate-800">{document.title}</h4>
            <p className="mt-1 text-xs text-slate-500">
              Preferred owner: {document.preferred_role || "lead"}
              {document.resolved_agent_name
                ? ` · Generated by ${document.resolved_agent_name}`
                : ""}
            </p>
            {(document.filename || document.artifact_id) && (
              <p className="mt-1 text-[11px] text-slate-400">
                {document.filename || "Generated artifact"}
                {document.artifact_id ? ` · ${document.artifact_id}` : ""}
              </p>
            )}
          </div>
          {document.preferred_role && (
            <span
              className={cn(
                "rounded-full px-2 py-1 text-[10px] font-medium",
                ROLE_COLORS[document.preferred_role] || "bg-slate-100 text-slate-600",
              )}
            >
              {document.preferred_role}
            </span>
          )}
        </div>
      </div>
      <div className="px-4 py-4 prose prose-slate max-w-none prose-p:my-2 prose-headings:mb-2 prose-headings:mt-4">
        <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
          {document.content || "_No content_"}
        </ReactMarkdown>
      </div>
    </article>
  );
}

type FlowNode = {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: { task: PlannerTask; epicTitle?: string };
};

type FlowEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  animated?: boolean;
  markerEnd?: { type: MarkerType; width?: number; height?: number; color?: string };
  style?: { stroke?: string; strokeWidth?: number };
};

function buildFlowElements(tasks: PlannerTask[], epics: { id: string; title: string }[]) {
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];

  const epicMap = new Map(epics.map(e => [e.id, e.title]));

  const rootTasks = tasks.filter(t => !t.depends_on || t.depends_on.length === 0);
  const dependentTasks = tasks.filter(t => t.depends_on && t.depends_on.length > 0);

  const ySpacing = 100;
  const xSpacing = 260;

  rootTasks.forEach((task, i) => {
    nodes.push({
      id: task.id,
      type: "taskNode",
      position: { x: i * xSpacing, y: 0 },
      data: { task, epicTitle: task.epic_id ? epicMap.get(task.epic_id) : undefined },
    });
  });

  const placed = new Set(rootTasks.map(t => t.id));
  let level = 1;
  let remaining = [...dependentTasks];

  while (remaining.length > 0) {
    const placeable = remaining.filter(t => t.depends_on!.every(d => placed.has(d)));
    if (placeable.length === 0) {
      remaining.forEach(t => {
        nodes.push({
          id: t.id,
          type: "taskNode",
          position: { x: Math.random() * 600, y: level * ySpacing },
          data: { task: t, epicTitle: t.epic_id ? epicMap.get(t.epic_id) : undefined },
        });
        placed.add(t.id);
      });
      break;
    }

    placeable.forEach((task, i) => {
      const parentX = task.depends_on![0];
      const parentNode = nodes.find(n => n.id === parentX);
      const x = parentNode ? parentNode.position.x + (i % 2 === 0 ? -xSpacing / 2 : xSpacing / 2) : i * xSpacing;
      nodes.push({
        id: task.id,
        type: "taskNode",
        position: { x, y: level * ySpacing },
        data: { task, epicTitle: task.epic_id ? epicMap.get(task.epic_id) : undefined },
      });
      placed.add(task.id);

      task.depends_on!.forEach(depId => {
        edges.push({
          id: `${depId}-${task.id}`,
          source: depId,
          target: task.id,
          type: "smoothstep",
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#94a3b8" },
          style: { stroke: "#94a3b8", strokeWidth: 1.5 },
        });
      });
    });

    remaining = remaining.filter(t => !placed.has(t.id));
    level++;
  }

  return { nodes, edges };
}

export default function PlannerPage() {
  const { isSignedIn } = useAuth();
  const searchParams = useSearchParams();
  const boardIdFromUrl = searchParams.get("boardId") ?? "";
  const [boards, setBoards] = useState<Board[]>([]);
  const [selectedBoardId, setSelectedBoardId] = useState("");
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [plannerOutputs, setPlannerOutputs] = useState<PlannerOutput[]>([]);
  const [selectedOutput, setSelectedOutput] = useState<PlannerOutput | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showGenerateDialog, setShowGenerateDialog] = useState(false);
  const [selectedArtifact, setSelectedArtifact] = useState<string>("");
  const [deleteTarget, setDeleteTarget] = useState<PlannerOutput | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [isExpanding, setIsExpanding] = useState(false);
  const [isUpdatingPolicy, setIsUpdatingPolicy] = useState(false);
  const [expansionRuns, setExpansionRuns] = useState<PlannerExpansionRun[]>([]);
  const [showPreviewDialog, setShowPreviewDialog] = useState(false);
  const [previewSection, setPreviewSection] = useState<"docs" | "epics" | "tasks">("docs");
  const selectedOutputId = selectedOutput?.id ?? null;
  const hasGeneratingOutputs = useMemo(
    () => plannerOutputs.some((output) => output.status === "generating"),
    [plannerOutputs],
  );

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const nextBoards = await fetchBoards();
      setBoards(nextBoards);

      const boardId =
        boardIdFromUrl ||
        selectedBoardId ||
        localStorage.getItem("clawdev_active_board_id") ||
        nextBoards[0]?.id ||
        "";
      if (boardId && boardId !== selectedBoardId) {
        setSelectedBoardId(boardId);
      }

      const [specs, outputs] = await Promise.all([
        fetchSpecArtifacts(boardId || undefined),
        fetchPlannerOutputs(boardId || undefined),
      ]);
      setArtifacts(specs);
      setPlannerOutputs(outputs);
      if (boardId) {
        localStorage.setItem("clawdev_active_board_id", boardId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setIsLoading(false);
    }
  }, [boardIdFromUrl, selectedBoardId]);

  useEffect(() => {
    if (isSignedIn) loadData();
  }, [isSignedIn, loadData]);

  useEffect(() => {
    if (!isSignedIn) return;
    const intervalId = window.setInterval(() => {
      void loadData();
    }, hasGeneratingOutputs ? 5000 : 30000);
    return () => window.clearInterval(intervalId);
  }, [hasGeneratingOutputs, isSignedIn, loadData]);

  useEffect(() => {
    if (plannerOutputs.length === 0) {
      if (selectedOutputId !== null) {
        setSelectedOutput(null);
      }
      return;
    }

    if (selectedOutputId === null) {
      setSelectedOutput(plannerOutputs[0]);
      return;
    }

    const refreshed = plannerOutputs.find((output) => output.id === selectedOutputId);
    if (refreshed) {
      setSelectedOutput(refreshed);
      return;
    }

    setSelectedOutput(plannerOutputs[0]);
  }, [plannerOutputs, selectedOutputId]);

  useEffect(() => {
    if (!isSignedIn || !selectedOutputId) {
      setExpansionRuns([]);
      return;
    }
    void fetchPlannerExpansionRuns(selectedOutputId)
      .then(setExpansionRuns)
      .catch(() => setExpansionRuns([]));
  }, [isSignedIn, selectedOutputId, plannerOutputs]);

  const handleGenerate = async (force = false) => {
    if (!selectedArtifact) return;
    setIsGenerating(true);
    setError(null);
    try {
      const output = force
        ? await regenerateBacklog(selectedArtifact)
        : await generateBacklog(selectedArtifact);
      setShowGenerateDialog(false);
      setSelectedArtifact("");
      setSelectedOutput(output);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleRegenerateSelected = async () => {
    if (!selectedOutput) return;
    setIsGenerating(true);
    setError(null);
    try {
      const output = await regenerateBacklog(selectedOutput.artifact_id);
      setSelectedOutput(output);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Regeneration failed");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleApply = async (output: PlannerOutput) => {
    setIsApplying(true);
    setError(null);
    try {
      const updated = await applyPlannerOutput(output.id);
      setSelectedOutput(updated);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Apply failed");
    } finally {
      setIsApplying(false);
    }
  };

  const handleExpand = async (output: PlannerOutput) => {
    setIsExpanding(true);
    setError(null);
    try {
      const updated = await expandPlannerOutput(output.id);
      setSelectedOutput(updated);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Expand failed");
    } finally {
      setIsExpanding(false);
    }
  };

  const handleToggleAutoExpand = async (output: PlannerOutput, enabled: boolean) => {
    setIsUpdatingPolicy(true);
    setError(null);
    try {
      const updated = await updatePlannerExpansionPolicy(output.id, {
        ...(output.expansion_policy || {}),
        auto_expand_enabled: enabled,
      });
      setSelectedOutput(updated);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Policy update failed");
    } finally {
      setIsUpdatingPolicy(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      await deletePlannerOutput(deleteTarget.id);
      setDeleteTarget(null);
      if (selectedOutput?.id === deleteTarget.id) setSelectedOutput(null);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setIsDeleting(false);
    }
  };

  const flowElements = useMemo(() => {
    if (!selectedOutput || !selectedOutput.tasks.length) return { nodes: [], edges: [] };
    return buildFlowElements(selectedOutput.tasks, selectedOutput.epics);
  }, [selectedOutput]);

  const selectedStatusConfig = selectedOutput
    ? STATUS_CONFIG[selectedOutput.status] || STATUS_CONFIG.draft
    : null;
  const selectedSpec = selectedOutput
    ? artifacts.find((artifact) => artifact.id === selectedOutput.artifact_id)
    : null;
  const autoExpandEnabled = Boolean(
    selectedOutput?.expansion_policy?.auto_expand_enabled ?? false,
  );
  const latestExpansionRun = expansionRuns[0] ?? null;

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to use the planner.",
          forceRedirectUrl: "/planner",
          signUpForceRedirectUrl: "/planner",
        }}
        title="Backlog Planner"
        description="Turn specifications into approved execution packages with progressive task materialization."
        headerActions={
          <div className="flex items-center gap-2">
            <select
              value={selectedBoardId}
              onChange={(e) => setSelectedBoardId(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Select project</option>
              {boards.map((board) => (
                <option key={board.id} value={board.id}>{board.name}</option>
              ))}
            </select>
            <button
              onClick={() => setShowGenerateDialog(true)}
              className={buttonVariants({ size: "md", variant: "primary" })}
              disabled={artifacts.length === 0 || !selectedBoardId || isGenerating}
            >
              <GitBranch className="mr-2 h-4 w-4" />
              Generate Planner Package
            </button>
            {selectedOutput &&
              selectedOutput.status !== "applied" &&
              selectedOutput.status !== "generating" && (
              <button
                onClick={handleRegenerateSelected}
                className={buttonVariants({ size: "md", variant: "outline" })}
                disabled={isGenerating}
              >
                <RefreshCw className="mr-2 h-4 w-4" />
                Regenerate
              </button>
            )}
          </div>
        }
        stickyHeader
      >
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Left: Planner outputs list */}
          <div className="lg:col-span-1 space-y-3">
            <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
              <Layers className="h-4 w-4" />
              Planner Outputs
            </h2>
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
              </div>
            ) : plannerOutputs.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center">
                <GitBranch className="mx-auto h-8 w-8 text-slate-400" />
                <p className="mt-2 text-sm text-slate-500">No planner outputs yet</p>
                <p className="text-xs text-slate-400">Generate an execution package from a spec to get started</p>
              </div>
            ) : (
              plannerOutputs.map(output => {
                const StatusIcon = STATUS_CONFIG[output.status]?.icon || Clock;
                const statusColor = STATUS_CONFIG[output.status]?.color || "text-slate-500";
                const spec = artifacts.find(a => a.id === output.artifact_id);
                return (
                  <button
                    key={output.id}
                    onClick={() => {
                      setSelectedOutput(output);
                      setPreviewSection("docs");
                      setShowPreviewDialog(true);
                    }}
                    className={cn(
                      "w-full text-left rounded-xl border bg-white p-3 shadow-sm hover:shadow-md transition-all",
                      selectedOutput?.id === output.id ? "border-blue-400 ring-1 ring-blue-200" : "border-slate-200",
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <StatusIcon
                          className={cn(
                            "h-4 w-4",
                            statusColor,
                            output.status === "generating" && "animate-spin",
                          )}
                        />
                        <span className="text-sm font-medium text-slate-800 truncate">
                          {spec?.filename || "Unknown spec"}
                        </span>
                      </div>
                      <span className={cn("text-xs font-medium", statusColor)}>
                        {STATUS_CONFIG[output.status]?.label || output.status}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-3 text-[10px] text-slate-400">
                        <span>{output.tasks.length} seed tasks</span>
                        <span>{output.epics.length} epics</span>
                        <span>{new Date(output.created_at).toLocaleDateString()}</span>
                      </div>
                      {output.status === "generating" && (
                        <p className="mt-2 text-[11px] text-slate-500">
                          Lead agent is drafting the execution package. The page refreshes automatically.
                        </p>
                      )}
                    </button>
                );
              })
            )}
          </div>

          {/* Right: DAG visualization or empty state */}
          <div className="lg:col-span-2">
            {selectedOutput ? (
              <div className="space-y-4">
                <PhaseTimeline
                  phaseStatuses={selectedOutput.phase_statuses || []}
                  pipelinePhase={selectedOutput.pipeline_phase}
                />
                <div className="grid gap-3 md:grid-cols-4">
                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                      Seed Tasks
                    </p>
                    <p className="mt-2 text-2xl font-semibold text-slate-900">
                      {selectedOutput.tasks.length}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Initial work package generated from the dossier.
                    </p>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                      Materialized
                    </p>
                    <p className="mt-2 text-2xl font-semibold text-slate-900">
                      {selectedOutput.materialized_task_count}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Tasks already created on the board.
                    </p>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                      Remaining Scope
                    </p>
                    <p className="mt-2 text-2xl font-semibold text-slate-900">
                      {selectedOutput.remaining_scope_count ?? "—"}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Outstanding acceptance/work items still to materialize.
                    </p>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                      Auto-Expand
                    </p>
                    <p className="mt-2 text-sm font-semibold text-slate-900">
                      {autoExpandEnabled ? "Buffered auto" : "Paused"}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {latestExpansionRun
                        ? `Latest round ${latestExpansionRun.round_number}: ${latestExpansionRun.status}`
                        : "No expansion rounds yet."}
                    </p>
                  </div>
                </div>
                {selectedOutput.status === "generating" ? (
              <div className="rounded-xl border border-blue-200 bg-gradient-to-br from-blue-50 via-white to-cyan-50 p-8 shadow-sm h-full flex flex-col justify-center">
                <div className="flex items-center gap-3">
                  <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                  <div>
                    <h3 className="text-lg font-semibold text-slate-800">
                      Generating delivery backlog
                    </h3>
                    <p className="mt-1 text-sm text-slate-600">
                      {selectedSpec?.filename || "Selected spec"} is being analyzed by the lead
                      agent. You can stay on this page or switch tabs; the result will appear
                      automatically.
                    </p>
                  </div>
                </div>
                <div className="mt-6 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-blue-100 bg-white/80 p-4">
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-blue-600">
                      Step 1
                    </p>
                    <p className="mt-2 text-sm text-slate-700">
                      Parse the specification into epics and delivery streams.
                    </p>
                  </div>
                  <div className="rounded-xl border border-blue-100 bg-white/80 p-4">
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-blue-600">
                      Step 2
                    </p>
                    <p className="mt-2 text-sm text-slate-700">
                      Build concrete tasks for engineering, QA, docs, and ops.
                    </p>
                  </div>
                  <div className="rounded-xl border border-blue-100 bg-white/80 p-4">
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-blue-600">
                      Step 3
                    </p>
                    <p className="mt-2 text-sm text-slate-700">
                      Return a board-ready backlog with dependencies and assignee hints.
                    </p>
                  </div>
                </div>
              </div>
                ) : selectedOutput.status === "failed" ? (
              <div className="rounded-xl border border-red-200 bg-red-50/60 p-8 shadow-sm h-full flex flex-col justify-center">
                <div className="flex items-center gap-3">
                  <AlertTriangle className="h-8 w-8 text-red-500" />
                  <div>
                    <h3 className="text-lg font-semibold text-slate-800">
                      Generation failed
                    </h3>
                    <p className="mt-1 text-sm text-slate-600">
                      The planner started, but one of the pipeline steps did not complete.
                      Review the phase timeline and error details, then retry after fixing the
                      underlying runtime issue.
                    </p>
                  </div>
                </div>
                {selectedOutput.error_message && (
                  <div className="mt-4 rounded-xl border border-red-200 bg-white p-4">
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-red-600">
                      Error
                    </p>
                    <p className="mt-2 text-sm text-slate-700">{selectedOutput.error_message}</p>
                  </div>
                )}
              </div>
                ) : (
              <>
                {selectedOutput.documents.length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700">Planner Dossier</h3>
                        <p className="text-xs text-slate-500">
                          Readable documents generated from the specification before backlog expansion.
                        </p>
                      </div>
                      <span className="text-[10px] bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">
                        {selectedOutput.documents.length} docs
                      </span>
                    </div>
                    <div className="space-y-3">
                      {selectedOutput.documents.map((document) => (
                        <PlannerDocumentCard key={document.key} document={document} />
                      ))}
                    </div>
                  </div>
                )}

                {selectedOutput.epics.length > 0 && (
                  <div className="rounded-xl border border-slate-200 bg-white shadow-sm p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700">Epic Plan</h3>
                        <p className="text-xs text-slate-500">
                          Delivery epics synthesized from the planner dossier.
                        </p>
                      </div>
                      <span className="text-[10px] bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">
                        {selectedOutput.epics.length} epics
                      </span>
                    </div>
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      {selectedOutput.epics.map((epic) => (
                        <div key={epic.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                          <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-slate-500">
                            {epic.id}
                          </p>
                          <h4 className="mt-2 text-sm font-semibold text-slate-800">{epic.title}</h4>
                          {epic.description && (
                            <p className="mt-2 text-sm text-slate-600">{epic.description}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {selectedOutput.epic_states.length > 0 && (
                  <div className="rounded-xl border border-slate-200 bg-white shadow-sm p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700">Execution Coverage</h3>
                        <p className="text-xs text-slate-500">
                          What is already materialized on the board and what still remains in approved scope.
                        </p>
                      </div>
                      <span className="text-[10px] bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">
                        {selectedOutput.epic_states.length} epic states
                      </span>
                    </div>
                    <div className="mt-4 space-y-3">
                      {selectedOutput.epic_states.map((state) => (
                        <div key={state.epic_id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <p className="text-sm font-semibold text-slate-900">{state.epic_id}</p>
                              <p className="mt-1 text-xs text-slate-500">
                                {state.materialized_tasks} materialized · {state.done_tasks} done · {state.status}
                              </p>
                            </div>
                            {state.next_focus_roles.length > 0 && (
                              <div className="flex flex-wrap gap-1">
                                {state.next_focus_roles.map((role) => (
                                  <span
                                    key={`${state.epic_id}-${role}`}
                                    className={cn(
                                      "rounded-full px-2 py-1 text-[10px] font-medium",
                                      ROLE_COLORS[role] || "bg-slate-100 text-slate-600",
                                    )}
                                  >
                                    {role}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                          {state.coverage_summary && (
                            <p className="mt-3 text-sm text-slate-700">{state.coverage_summary}</p>
                          )}
                          {state.remaining_work_summary && (
                            <p className="mt-2 text-xs text-slate-600">
                              Remaining: {state.remaining_work_summary}
                            </p>
                          )}
                          {state.open_acceptance_items.length > 0 && (
                            <ul className="mt-2 list-disc pl-5 text-xs text-slate-500">
                              {state.open_acceptance_items.slice(0, 4).map((item) => (
                                <li key={`${state.epic_id}-${item}`}>{item}</li>
                              ))}
                            </ul>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {expansionRuns.length > 0 && (
                  <div className="rounded-xl border border-slate-200 bg-white shadow-sm p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700">Expansion History</h3>
                        <p className="text-xs text-slate-500">
                          Progressive materialization rounds after the initial work package.
                        </p>
                      </div>
                      <span className="text-[10px] bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">
                        {expansionRuns.length} runs
                      </span>
                    </div>
                    <div className="mt-4 space-y-3">
                      {expansionRuns.map((run) => (
                        <div key={run.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <p className="text-sm font-semibold text-slate-900">
                                Round {run.round_number} · {run.status}
                              </p>
                              <p className="mt-1 text-xs text-slate-500">
                                Trigger: {run.trigger}
                                {run.source_epic_ids.length > 0 ? ` · ${run.source_epic_ids.join(", ")}` : ""}
                              </p>
                            </div>
                            <p className="text-[11px] text-slate-400">
                              {new Date(run.updated_at).toLocaleString()}
                            </p>
                          </div>
                          {run.summary && <p className="mt-2 text-sm text-slate-700">{run.summary}</p>}
                          {run.error_message && (
                            <p className="mt-2 text-xs text-red-600">{run.error_message}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {selectedOutput.tasks.length > 0 && (
                  <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <h3 className="text-sm font-semibold text-slate-700">Seed Task Graph</h3>
                    {selectedOutput.parallelism_groups.length > 0 && (
                      <span className="text-[10px] bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">
                        {selectedOutput.parallelism_groups.length} parallel levels
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {selectedOutput.status === "draft" && !selectedOutput.error_message && (
                      <button
                        onClick={() => handleApply(selectedOutput)}
                        disabled={isApplying}
                        className={cn(buttonVariants({ size: "sm", variant: "primary" }))}
                      >
                        {isApplying ? (
                          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                        ) : (
                          <Play className="mr-1 h-3 w-3" />
                        )}
                        Create Initial Work Package
                      </button>
                    )}
                    {selectedOutput.status === "draft" && (
                      <button
                        onClick={() => setDeleteTarget(selectedOutput)}
                        className={cn(buttonVariants({ size: "sm", variant: "outline" }))}
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                    {selectedOutput.status === "applied" && (
                      <>
                        <button
                          onClick={() => handleExpand(selectedOutput)}
                          disabled={isExpanding}
                          className={cn(buttonVariants({ size: "sm", variant: "outline" }))}
                        >
                          {isExpanding ? (
                            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                          ) : (
                            <RefreshCw className="mr-1 h-3 w-3" />
                          )}
                          Expand Next Batch
                        </button>
                        <button
                          onClick={() => handleToggleAutoExpand(selectedOutput, !autoExpandEnabled)}
                          disabled={isUpdatingPolicy}
                          className={cn(buttonVariants({ size: "sm", variant: "outline" }))}
                        >
                          {isUpdatingPolicy ? (
                            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                          ) : null}
                          {autoExpandEnabled ? "Pause Auto-Expand" : "Resume Auto-Expand"}
                        </button>
                        <span className="text-xs text-green-600 flex items-center gap-1">
                          <CheckCircle className="h-3 w-3" />
                          Applied {selectedOutput.applied_at && new Date(selectedOutput.applied_at).toLocaleDateString()}
                        </span>
                      </>
                    )}
                  </div>
                </div>
                {selectedOutput.error_message && (
                  <div className="px-4 py-3 bg-amber-50 border-b border-amber-200 flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0" />
                    <p className="text-xs text-amber-700">{selectedOutput.error_message}</p>
                  </div>
                )}
                <div className="h-[500px]">
                  <ReactFlow
                    nodes={flowElements.nodes}
                    edges={flowElements.edges}
                    nodeTypes={nodeTypes}
                    fitView
                    fitViewOptions={{ padding: 0.2 }}
                    minZoom={0.2}
                    maxZoom={1.5}
                  >
                    <Controls showInteractive={false} />
                    <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
                  </ReactFlow>
                </div>
              </div>
                )}
              </>
                )}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center h-full flex flex-col items-center justify-center">
                <GitBranch className="h-12 w-12 text-slate-300" />
                <h3 className="mt-4 text-lg font-medium text-slate-600">No DAG to display</h3>
                <p className="mt-2 text-sm text-slate-400">
                  Select a planner output from the list or generate a new planner package
                </p>
              </div>
            )}
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-lg bg-red-50 border border-red-200 p-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-500 flex-shrink-0" />
            <p className="text-sm text-red-600">{error}</p>
          </div>
        )}
      </DashboardPageLayout>

      {/* Generate Dialog */}
      <Dialog open={showGenerateDialog} onOpenChange={setShowGenerateDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Generate Planner Package</DialogTitle>
            <DialogDescription>
              Select a specification artifact to start a background planner generation.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {artifacts.length === 0 ? (
              <div className="text-center py-4">
                <FileText className="mx-auto h-8 w-8 text-slate-400" />
                <p className="mt-2 text-sm text-slate-500">No spec artifacts found</p>
                <p className="text-xs text-slate-400">Upload a spec first in the Artifacts page</p>
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Specification</label>
                  <div className="space-y-2 max-h-60 overflow-auto">
                    {artifacts.map(artifact => (
                      <button
                        key={artifact.id}
                        onClick={() => setSelectedArtifact(artifact.id)}
                        className={cn(
                          "w-full text-left rounded-lg border p-3 transition-all",
                          selectedArtifact === artifact.id
                            ? "border-blue-400 bg-blue-50 ring-1 ring-blue-200"
                            : "border-slate-200 hover:border-slate-300",
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4 text-slate-500" />
                          <span className="text-sm font-medium text-slate-800 truncate">{artifact.filename}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex justify-end gap-2">
                  <button
                    onClick={() => { setShowGenerateDialog(false); setSelectedArtifact(""); }}
                    className={buttonVariants({ size: "md", variant: "outline" })}
                    disabled={isGenerating}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => void handleGenerate()}
                    disabled={!selectedArtifact || isGenerating}
                    className={buttonVariants({ size: "md", variant: "primary" })}
                  >
                    {isGenerating ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Starting...
                      </>
                    ) : (
                      <>
                        <GitBranch className="mr-2 h-4 w-4" />
                        Start Generation
                      </>
                    )}
                  </button>
                </div>
                <p className="text-xs text-slate-500">
                  Generation runs in the background. You do not need to keep this dialog open.
                </p>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Preview Dialog */}
      <Dialog open={showPreviewDialog} onOpenChange={setShowPreviewDialog}>
        <DialogContent className="sm:max-w-3xl max-h-[85vh]">
          <DialogHeader>
            <DialogTitle>
              {selectedSpec?.filename || "Planner Output"}
            </DialogTitle>
            <DialogDescription>
              {selectedOutput && (
                <div className="flex items-center gap-3 mt-1">
                  {selectedStatusConfig && (
                    <span className={cn("flex items-center gap-1 text-xs", selectedStatusConfig.color)}>
                      <selectedStatusConfig.icon
                        className={cn(
                          "h-3 w-3",
                          selectedOutput.status === "generating" && "animate-spin",
                        )}
                      />
                      {selectedStatusConfig.label}
                    </span>
                  )}
                  <span className="text-xs text-slate-400">
                    {selectedOutput.tasks.length} seed tasks · {selectedOutput.epics.length} epics
                  </span>
                </div>
              )}
            </DialogDescription>
          </DialogHeader>
          {selectedOutput && (
            <div className="flex gap-2 border-b pb-3">
              {[
                { key: "docs", label: "Documents" },
                { key: "epics", label: "Epics" },
                { key: "tasks", label: "Tasks" },
              ].map((section) => (
                <button
                  key={section.key}
                  onClick={() => setPreviewSection(section.key as "docs" | "epics" | "tasks")}
                  className={cn(
                    "rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                    previewSection === section.key
                      ? "bg-slate-900 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                  )}
                >
                  {section.label}
                </button>
              ))}
            </div>
          )}
          <div className="overflow-auto max-h-[65vh]">
            {selectedOutput?.status === "generating" && (
              <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4 flex items-start gap-3">
                <Loader2 className="h-4 w-4 animate-spin text-blue-500 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-slate-800">Generation in progress</p>
                  <p className="mt-1 text-xs text-slate-600">
                    The lead agent is still preparing the backlog. This dialog will show the
                    resulting tasks after the next automatic refresh.
                  </p>
                </div>
              </div>
            )}
            {selectedOutput?.error_message && (
              <div className="mb-4 rounded-lg bg-amber-50 border border-amber-200 p-3 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0" />
                <p className="text-xs text-amber-700">{selectedOutput.error_message}</p>
              </div>
            )}
            {selectedOutput && previewSection === "docs" && selectedOutput.documents.length > 0 && (
              <div className="space-y-4">
                {selectedOutput.documents.map((document) => (
                  <PlannerDocumentCard key={document.key} document={document} />
                ))}
              </div>
            )}
            {selectedOutput && previewSection === "epics" && selectedOutput.epics.map((epic) => {
              const epicTasks = selectedOutput.tasks.filter((task) => task.epic_id === epic.id);
              return (
                <div key={epic.id} className="mb-4 rounded-xl border border-slate-200 bg-white p-4">
                  <h4 className="text-sm font-semibold text-slate-800">{epic.title}</h4>
                  {epic.description && (
                    <p className="mt-2 text-xs text-slate-500">{epic.description}</p>
                  )}
                  <p className="mt-2 text-[11px] text-slate-400">{epicTasks.length} tasks</p>
                </div>
              );
            })}
            {selectedOutput && previewSection === "tasks" && selectedOutput.tasks.map((task) => (
              <div key={task.id} className="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-800">{task.title}</span>
                  <div className="flex items-center gap-2">
                    {task.suggested_agent_role && (
                      <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium", ROLE_COLORS[task.suggested_agent_role] || "bg-slate-100 text-slate-600")}>
                        {task.suggested_agent_role}
                      </span>
                    )}
                    {task.estimate && (
                      <span className="text-[10px] text-slate-400">{task.estimate}</span>
                    )}
                  </div>
                </div>
                {task.description && (
                  <p className="text-xs text-slate-500 mt-1">{task.description}</p>
                )}
                {task.depends_on && task.depends_on.length > 0 && (
                  <p className="text-[10px] text-slate-400 mt-1">
                    Depends on: {task.depends_on.join(", ")}
                  </p>
                )}
                {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
                  <div className="mt-2">
                    <p className="text-[10px] font-medium text-slate-500 mb-1">Acceptance Criteria:</p>
                    <ul className="text-[10px] text-slate-500 list-disc list-inside">
                      {task.acceptance_criteria.map((criterion, index) => (
                        <li key={index}>{criterion}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))}
            {selectedOutput &&
              previewSection === "docs" &&
              selectedOutput.documents.length === 0 &&
              selectedOutput.status !== "generating" && (
              <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center">
                <p className="text-sm text-slate-500">No planner documents are available for this output yet.</p>
              </div>
            )}
            {selectedOutput &&
              previewSection !== "docs" &&
              selectedOutput.epics.length === 0 &&
              selectedOutput.status !== "generating" && (
              <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center">
                <p className="text-sm text-slate-500">No backlog content is available for this output yet.</p>
              </div>
            )}
          </div>
          {selectedOutput?.status === "draft" && !selectedOutput.error_message && (
            <div className="flex justify-end gap-2 pt-3 border-t">
              <button
                onClick={() => setShowPreviewDialog(false)}
                className={buttonVariants({ size: "md", variant: "outline" })}
              >
                Close
              </button>
              <button
                onClick={() => { handleApply(selectedOutput); setShowPreviewDialog(false); }}
                disabled={isApplying}
                className={buttonVariants({ size: "md", variant: "primary" })}
              >
                {isApplying ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Play className="mr-2 h-4 w-4" />
                )}
                Create Initial Work Package
              </button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <ConfirmActionDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        ariaLabel="Delete planner output"
        title="Delete planner output"
        description="This will remove the generated backlog. This action cannot be undone."
        errorMessage={error}
        onConfirm={handleDelete}
        isConfirming={isDeleting}
      />
    </>
  );
}
