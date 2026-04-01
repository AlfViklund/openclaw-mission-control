"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/auth/clerk";
import {
  Loader2,
  FileText,
  GitBranch,
  Play,
  Trash2,
  Eye,
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

interface Artifact {
  id: string;
  filename: string;
  type: string;
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

interface PlannerOutput {
  id: string;
  board_id: string;
  artifact_id: string;
  status: string;
  json_schema_version: number;
  epics: { id: string; title: string; description?: string }[];
  tasks: PlannerTask[];
  parallelism_groups: { level: number; task_ids: string[] }[];
  error_message: string | null;
  created_at: string;
  created_by: string | null;
  applied_at: string | null;
}

const ROLE_COLORS: Record<string, string> = {
  dev: "bg-blue-100 text-blue-700",
  qa: "bg-green-100 text-green-700",
  docs: "bg-amber-100 text-amber-700",
  ops: "bg-purple-100 text-purple-700",
};

const STATUS_CONFIG: Record<string, { icon: typeof CheckCircle; color: string; label: string }> = {
  draft: { icon: Clock, color: "text-amber-500", label: "Draft" },
  applied: { icon: CheckCircle, color: "text-green-500", label: "Applied" },
  rejected: { icon: XCircle, color: "text-red-500", label: "Rejected" },
};

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

function getAuthToken(): string {
  return localStorage.getItem("mc_auth_token") || "";
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

async function fetchPlannerOutput(id: string): Promise<PlannerOutput> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/planner/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch planner output");
  return res.json();
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

function buildFlowElements(tasks: PlannerTask[], epics: { id: string; title: string }[]) {
  const nodes: any[] = [];
  const edges: any[] = [];

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
  const [showPreviewDialog, setShowPreviewDialog] = useState(false);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [specs, outputs] = await Promise.all([
        fetchSpecArtifacts(),
        fetchPlannerOutputs(),
      ]);
      setArtifacts(specs);
      setPlannerOutputs(outputs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isSignedIn) loadData();
  }, [isSignedIn, loadData]);

  const handleGenerate = async () => {
    if (!selectedArtifact) return;
    setIsGenerating(true);
    setError(null);
    try {
      const output = await generateBacklog(selectedArtifact);
      setShowGenerateDialog(false);
      setSelectedArtifact("");
      await loadData();
      setSelectedOutput(output);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
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

  const selectedStatusConfig = selectedOutput ? STATUS_CONFIG[selectedOutput.status] || STATUS_CONFIG.draft : null;

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to use the planner.",
          forceRedirectUrl: "/planner",
          signUpForceRedirectUrl: "/planner",
        }}
        title="Backlog Planner"
        description="Generate structured backlogs from specifications with dependency graphs."
        headerActions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowGenerateDialog(true)}
              className={buttonVariants({ size: "md", variant: "primary" })}
              disabled={artifacts.length === 0}
            >
              <GitBranch className="mr-2 h-4 w-4" />
              Generate Backlog
            </button>
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
                <p className="text-xs text-slate-400">Generate a backlog from a spec to get started</p>
              </div>
            ) : (
              plannerOutputs.map(output => {
                const StatusIcon = STATUS_CONFIG[output.status]?.icon || Clock;
                const statusColor = STATUS_CONFIG[output.status]?.color || "text-slate-500";
                const spec = artifacts.find(a => a.id === output.artifact_id);
                return (
                  <button
                    key={output.id}
                    onClick={() => { setSelectedOutput(output); setShowPreviewDialog(true); }}
                    className={cn(
                      "w-full text-left rounded-xl border bg-white p-3 shadow-sm hover:shadow-md transition-all",
                      selectedOutput?.id === output.id ? "border-blue-400 ring-1 ring-blue-200" : "border-slate-200",
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <StatusIcon className={cn("h-4 w-4", statusColor)} />
                        <span className="text-sm font-medium text-slate-800 truncate">
                          {spec?.filename || "Unknown spec"}
                        </span>
                      </div>
                      <span className={cn("text-xs font-medium", statusColor)}>
                        {STATUS_CONFIG[output.status]?.label || output.status}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-3 text-[10px] text-slate-400">
                      <span>{output.tasks.length} tasks</span>
                      <span>{output.epics.length} epics</span>
                      <span>{new Date(output.created_at).toLocaleDateString()}</span>
                    </div>
                  </button>
                );
              })
            )}
          </div>

          {/* Right: DAG visualization or empty state */}
          <div className="lg:col-span-2">
            {selectedOutput && selectedOutput.tasks.length > 0 ? (
              <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <h3 className="text-sm font-semibold text-slate-700">Dependency Graph</h3>
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
                        Apply to Board
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
                      <span className="text-xs text-green-600 flex items-center gap-1">
                        <CheckCircle className="h-3 w-3" />
                        Applied {selectedOutput.applied_at && new Date(selectedOutput.applied_at).toLocaleDateString()}
                      </span>
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
                    <Background variant="dots" gap={16} size={1} />
                  </ReactFlow>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center h-full flex flex-col items-center justify-center">
                <GitBranch className="h-12 w-12 text-slate-300" />
                <h3 className="mt-4 text-lg font-medium text-slate-600">No DAG to display</h3>
                <p className="mt-2 text-sm text-slate-400">
                  Select a planner output from the list or generate a new backlog
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
            <DialogTitle>Generate Backlog</DialogTitle>
            <DialogDescription>
              Select a specification artifact to generate a structured backlog.
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
                    onClick={handleGenerate}
                    disabled={!selectedArtifact || isGenerating}
                    className={buttonVariants({ size: "md", variant: "primary" })}
                  >
                    {isGenerating ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Generating...
                      </>
                    ) : (
                      <>
                        <GitBranch className="mr-2 h-4 w-4" />
                        Generate
                      </>
                    )}
                  </button>
                </div>
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
              {selectedOutput ? (() => {
                const spec = artifacts.find(a => a.id === selectedOutput.artifact_id);
                return spec?.filename || "Planner Output";
              })() : "Planner Output"}
            </DialogTitle>
            <DialogDescription>
              {selectedOutput && (
                <div className="flex items-center gap-3 mt-1">
                  {selectedStatusConfig && (
                    <span className={cn("flex items-center gap-1 text-xs", selectedStatusConfig.color)}>
                      <selectedStatusConfig.icon className="h-3 w-3" />
                      {selectedStatusConfig.label}
                    </span>
                  )}
                  <span className="text-xs text-slate-400">
                    {selectedOutput.tasks.length} tasks · {selectedOutput.epics.length} epics
                  </span>
                </div>
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="overflow-auto max-h-[65vh]">
            {selectedOutput?.error_message && (
              <div className="mb-4 rounded-lg bg-amber-50 border border-amber-200 p-3 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0" />
                <p className="text-xs text-amber-700">{selectedOutput.error_message}</p>
              </div>
            )}
            {selectedOutput?.epics.map(epic => {
              const epicTasks = selectedOutput.tasks.filter(t => t.epic_id === epic.id);
              return (
                <div key={epic.id} className="mb-4">
                  <h4 className="text-sm font-semibold text-slate-800 mb-2">{epic.title}</h4>
                  <div className="space-y-2">
                    {epicTasks.map(task => (
                      <div key={task.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
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
                              {task.acceptance_criteria.map((c, i) => (
                                <li key={i}>{c}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
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
                Apply to Board
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
