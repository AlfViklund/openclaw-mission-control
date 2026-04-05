"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/auth/clerk";
import { getLocalAuthToken } from "@/auth/localAuth";
import {
  FileText,
  Upload,
  Download,
  Trash2,
  FileCode,
  FileSpreadsheet,
  File,
  Eye,
  Loader2,
  Filter,
  X,
} from "lucide-react";

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

type ArtifactType = "spec" | "plan" | "diff" | "test_report" | "release_note" | "other";

interface Artifact {
  id: string;
  board_id: string;
  task_id: string | null;
  type: ArtifactType;
  source: string;
  filename: string;
  mime_type: string | null;
  size_bytes: number;
  storage_path: string;
  checksum: string | null;
  version: number;
  created_at: string;
  created_by: string | null;
}

interface Board {
  id: string;
  name: string;
}

interface TaskOption {
  id: string;
  title: string;
}

interface ListResponse {
  items: Artifact[];
  total: number;
  limit: number;
  offset: number;
}

const ARTIFACT_TYPE_LABELS: Record<ArtifactType, string> = {
  spec: "Specification",
  plan: "Plan",
  diff: "Diff",
  test_report: "Test Report",
  release_note: "Release Note",
  other: "Other",
};

const ARTIFACT_TYPE_COLORS: Record<ArtifactType, string> = {
  spec: "bg-blue-100 text-blue-700",
  plan: "bg-amber-100 text-amber-700",
  diff: "bg-purple-100 text-purple-700",
  test_report: "bg-green-100 text-green-700",
  release_note: "bg-cyan-100 text-cyan-700",
  other: "bg-slate-100 text-slate-700",
};

function getFileIcon(mimeType: string | null, filename: string) {
  if (mimeType?.startsWith("image/")) return FileSpreadsheet;
  if (mimeType?.includes("json") || mimeType?.includes("yaml") || mimeType?.includes("text")) return FileCode;
  if (/\.(md|txt|pdf|doc)/i.test(filename)) return FileText;
  return File;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function resolveAuthToken(): string {
  return getLocalAuthToken() || "";
}

async function fetchArtifacts(
  baseUrl: string,
  token: string,
  filters?: { board_id?: string; task_id?: string; type?: string },
): Promise<ListResponse> {
  const params = new URLSearchParams();
  if (filters?.board_id) params.set("board_id", filters.board_id);
  if (filters?.task_id) params.set("task_id", filters.task_id);
  if (filters?.type) params.set("artifact_type", filters.type);

  const res = await fetch(`${baseUrl}/api/v1/artifacts?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Failed to fetch artifacts: ${res.status}`);
  const data = await res.json();
  return {
    items: data.items ?? [],
    total: data.total ?? 0,
    limit: data.limit ?? 50,
    offset: data.offset ?? 0,
  };
}

async function fetchBoards(baseUrl: string, token: string): Promise<Board[]> {
  const res = await fetch(`${baseUrl}/api/v1/boards`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Failed to fetch boards: ${res.status}`);
  const data = await res.json();
  return data.items ?? [];
}

async function fetchBoardTasks(baseUrl: string, token: string, boardId: string): Promise<TaskOption[]> {
  const res = await fetch(`${baseUrl}/api/v1/boards/${boardId}/tasks`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Failed to fetch tasks: ${res.status}`);
  const data = await res.json();
  return data.items ?? [];
}

async function uploadArtifact(
  baseUrl: string,
  token: string,
  file: File,
  boardId: string,
  artifactType: string,
  taskId?: string,
): Promise<Artifact> {
  const formData = new FormData();
  formData.append("file", file);

  const params = new URLSearchParams({ board_id: boardId });
  if (taskId) params.set("task_id", taskId);
  params.set("artifact_type", artifactType);

  const res = await fetch(`${baseUrl}/api/v1/artifacts?${params}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Upload failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function deleteArtifact(baseUrl: string, token: string, artifactId: string): Promise<void> {
  const res = await fetch(`${baseUrl}/api/v1/artifacts/${artifactId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
}

async function fetchPreview(baseUrl: string, token: string, artifactId: string): Promise<{ preview: string | null; reason?: string }> {
  const res = await fetch(`${baseUrl}/api/v1/artifacts/${artifactId}/preview`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return { preview: null, reason: "Preview unavailable" };
  return res.json();
}

export default function ArtifactsPage() {
  const { isSignedIn } = useAuth();
  const searchParams = useSearchParams();
  const boardIdFromUrl = searchParams.get("board_id") ?? "";
  const [boards, setBoards] = useState<Board[]>([]);
  const [boardTasks, setBoardTasks] = useState<TaskOption[]>([]);
  const [selectedBoardId, setSelectedBoardId] = useState(boardIdFromUrl);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Artifact | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [previewArtifact, setPreviewArtifact] = useState<Artifact | null>(null);
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [showUploadDialog, setShowUploadDialog] = useState(false);

  // Filters
  const [filterType, setFilterType] = useState<string>("");
  const [filterBoardId, setFilterBoardId] = useState<string>(boardIdFromUrl);
  const [showFilters, setShowFilters] = useState(false);

  // Upload form state
  const [uploadBoardId, setUploadBoardId] = useState("");
  const [uploadTaskId, setUploadTaskId] = useState("");
  const [uploadType, setUploadType] = useState<ArtifactType>("spec");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const refreshBoardTasks = useCallback(async (boardId: string) => {
    if (!boardId) {
      setBoardTasks([]);
      return;
    }
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || "";
      const token = resolveAuthToken();
      const tasks = await fetchBoardTasks(baseUrl, token, boardId);
      setBoardTasks(tasks);
    } catch {
      setBoardTasks([]);
    }
  }, []);

  const loadArtifacts = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || "";
      const token = resolveAuthToken();
      if (!token) {
        setError("Authentication required. Please sign in.");
        setIsLoading(false);
        return;
      }
      const nextBoards = await fetchBoards(baseUrl, token);
      setBoards(nextBoards);

      const boardId = boardIdFromUrl || selectedBoardId || localStorage.getItem("clawdev_active_board_id") || nextBoards[0]?.id || "";
      if (boardId && boardId !== selectedBoardId) {
        setSelectedBoardId(boardId);
      }

      const filters: Record<string, string> = {};
      if (boardId) filters.board_id = boardId;
      if (filterType) filters.type = filterType;
      const data = await fetchArtifacts(baseUrl, token, filters);
      setArtifacts(data.items);
      setFilterBoardId(boardId);
      if (boardId) {
        localStorage.setItem("clawdev_active_board_id", boardId);
        await refreshBoardTasks(boardId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load artifacts");
    } finally {
      setIsLoading(false);
    }
  }, [filterType, refreshBoardTasks, selectedBoardId]);

  useEffect(() => {
    if (isSignedIn) loadArtifacts();
  }, [isSignedIn, loadArtifacts]);

  useEffect(() => {
    if (!isSignedIn) return;
    const intervalId = window.setInterval(() => {
      void loadArtifacts();
    }, 30000);
    return () => window.clearInterval(intervalId);
  }, [isSignedIn, loadArtifacts]);

  useEffect(() => {
    if (showUploadDialog && selectedBoardId) {
      setUploadBoardId(selectedBoardId);
    }
  }, [selectedBoardId, showUploadDialog]);

  const handleUpload = async () => {
    if (!selectedFile || !uploadBoardId) return;
    setIsUploading(true);
    setUploadError(null);
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || "";
      const token = resolveAuthToken();
      await uploadArtifact(baseUrl, token, selectedFile, uploadBoardId, uploadType, uploadTaskId || undefined);
      setShowUploadDialog(false);
      setSelectedFile(null);
      setUploadBoardId("");
      setUploadTaskId("");
      setUploadType("spec");
      await loadArtifacts();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || "";
      const token = resolveAuthToken();
      await deleteArtifact(baseUrl, token, deleteTarget.id);
      setDeleteTarget(null);
      await loadArtifacts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setIsDeleting(false);
    }
  };

  const handlePreview = async (artifact: Artifact) => {
    setPreviewArtifact(artifact);
    setPreviewContent(null);
    setPreviewLoading(true);
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || "";
      const token = resolveAuthToken();
      const data = await fetchPreview(baseUrl, token, artifact.id);
      setPreviewContent(data.preview);
    } catch {
      setPreviewContent(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleDownload = (artifact: Artifact) => {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || "";
    const url = `${baseUrl}/api/v1/artifacts/${artifact.id}/download`;
    const a = document.createElement("a");
    a.href = url;
    a.download = artifact.filename;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleFileDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) setSelectedFile(file);
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
  }, []);

  const activeFilters = useMemo(() => {
    const count = (filterType ? 1 : 0) + (filterBoardId ? 1 : 0);
    return count;
  }, [filterType, filterBoardId]);

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to view artifacts.",
          forceRedirectUrl: boardIdFromUrl ? `/artifacts?board_id=${encodeURIComponent(boardIdFromUrl)}` : "/artifacts",
          signUpForceRedirectUrl: boardIdFromUrl ? `/artifacts?board_id=${encodeURIComponent(boardIdFromUrl)}` : "/artifacts",
        }}
        title="Spec & Artifact Hub"
        description={`${artifacts.length} artifact${artifacts.length === 1 ? "" : "s"} stored. Upload specifications, plans, diffs, and reports.`}
        headerActions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={cn(
                buttonVariants({ size: "md", variant: "outline" }),
                activeFilters > 0 && "border-blue-500 text-blue-700",
              )}
            >
              <Filter className="h-4 w-4" />
              {activeFilters > 0 && (
                <span className="ml-1 h-4 w-4 rounded-full bg-blue-600 text-[10px] text-white flex items-center justify-center">
                  {activeFilters}
                </span>
              )}
            </button>
            <button
              onClick={() => setShowUploadDialog(true)}
              className={buttonVariants({ size: "md", variant: "primary" })}
            >
              <Upload className="mr-2 h-4 w-4" />
              Upload
            </button>
          </div>
        }
        stickyHeader
      >
        {showFilters && (
          <div className="mb-4 rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-slate-700">Filters</h3>
              {activeFilters > 0 && (
                <button
                  onClick={() => { setFilterType(""); setFilterBoardId(""); }}
                  className="text-xs text-blue-600 hover:text-blue-800"
                >
                  Clear all
                </button>
              )}
            </div>
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="flex-1">
                <label className="block text-xs font-medium text-slate-500 mb-1">Type</label>
                <select
                  value={filterType}
                  onChange={(e) => setFilterType(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">All types</option>
                  {Object.entries(ARTIFACT_TYPE_LABELS).map(([key, label]) => (
                    <option key={key} value={key}>{label}</option>
                  ))}
                </select>
              </div>
              <div className="flex-1">
                <label className="block text-xs font-medium text-slate-500 mb-1">Project</label>
                <select
                  value={selectedBoardId}
                  onChange={(e) => {
                    setSelectedBoardId(e.target.value);
                    setFilterBoardId(e.target.value);
                  }}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">All projects</option>
                  {boards.map((board) => (
                    <option key={board.id} value={board.id}>{board.name}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-end">
                <button
                  onClick={loadArtifacts}
                  className={buttonVariants({ size: "md", variant: "primary" })}
                >
                  Apply
                </button>
              </div>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
          </div>
        ) : artifacts.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
            <FileText className="mx-auto h-12 w-12 text-slate-400" />
            <h3 className="mt-4 text-lg font-medium text-slate-700">No artifacts yet</h3>
            <p className="mt-2 text-sm text-slate-500">
              Upload a specification document or other artifacts to get started.
            </p>
            <button
              onClick={() => setShowUploadDialog(true)}
              className={cn(buttonVariants({ size: "md", variant: "primary" }), "mt-4")}
            >
              <Upload className="mr-2 h-4 w-4" />
              Upload your first artifact
            </button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {artifacts.map((artifact) => {
              const FileIcon = getFileIcon(artifact.mime_type, artifact.filename);
              return (
                <div
                  key={artifact.id}
                  className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow"
                >
                  <div className="flex items-start gap-3">
                    <div className="rounded-lg bg-slate-100 p-2">
                      <FileIcon className="h-5 w-5 text-slate-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-medium text-slate-900 truncate" title={artifact.filename}>
                        {artifact.filename}
                      </h4>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-medium", ARTIFACT_TYPE_COLORS[artifact.type])}>
                          {ARTIFACT_TYPE_LABELS[artifact.type]}
                        </span>
                        <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                          v{artifact.version}
                        </span>
                        <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                          {formatBytes(artifact.size_bytes)}
                        </span>
                      </div>
                      {artifact.task_id && (
                        <p className="mt-1 text-[10px] text-slate-500 truncate">
                          Task: {artifact.task_id}
                        </p>
                      )}
                      <p className="mt-1 text-[10px] text-slate-400">
                        {formatDate(artifact.created_at)}
                      </p>
                    </div>
                  </div>
                  <div className="mt-3 flex items-center gap-2 pt-3 border-t border-slate-100">
                    {_isTextType(artifact.mime_type) && (
                      <button
                        onClick={() => handlePreview(artifact)}
                        className="flex items-center gap-1 text-xs text-slate-600 hover:text-blue-600 transition-colors"
                      >
                        <Eye className="h-3.5 w-3.5" />
                        Preview
                      </button>
                    )}
                    <button
                      onClick={() => handleDownload(artifact)}
                      className="flex items-center gap-1 text-xs text-slate-600 hover:text-blue-600 transition-colors ml-auto"
                    >
                      <Download className="h-3.5 w-3.5" />
                      Download
                    </button>
                    <button
                      onClick={() => setDeleteTarget(artifact)}
                      className="flex items-center gap-1 text-xs text-slate-600 hover:text-red-600 transition-colors"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {error && (
          <p className="mt-4 text-sm text-red-500">{error}</p>
        )}
      </DashboardPageLayout>

      {/* Upload Dialog */}
      <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Upload Artifact</DialogTitle>
            <DialogDescription>
              Upload a specification, plan, diff, or other document.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Project *</label>
              <select
                value={uploadBoardId}
                onChange={(e) => {
                  setUploadBoardId(e.target.value);
                  void refreshBoardTasks(e.target.value);
                }}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select project</option>
                {boards.map((board) => (
                  <option key={board.id} value={board.id}>{board.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Task (optional)</label>
              <select
                value={uploadTaskId}
                onChange={(e) => setUploadTaskId(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">No linked task</option>
                {boardTasks.map((task) => (
                  <option key={task.id} value={task.id}>{task.title}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Type</label>
              <select
                value={uploadType}
                onChange={(e) => setUploadType(e.target.value as ArtifactType)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {Object.entries(ARTIFACT_TYPE_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </div>
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleFileDrop}
              className="rounded-lg border-2 border-dashed border-slate-300 p-6 text-center hover:border-blue-400 transition-colors cursor-pointer"
              onClick={() => document.getElementById("file-input")?.click()}
            >
              <Upload className="mx-auto h-8 w-8 text-slate-400" />
              {selectedFile ? (
                <p className="mt-2 text-sm font-medium text-slate-700">{selectedFile.name}</p>
              ) : (
                <p className="mt-2 text-sm text-slate-500">Drag & drop or click to select</p>
              )}
              <input
                id="file-input"
                type="file"
                onChange={handleFileSelect}
                className="hidden"
              />
            </div>
            {uploadError && (
              <p className="text-sm text-red-500">{uploadError}</p>
            )}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setShowUploadDialog(false); setSelectedFile(null); setUploadError(null); }}
                className={buttonVariants({ size: "md", variant: "outline" })}
                disabled={isUploading}
              >
                Cancel
              </button>
              <button
                onClick={handleUpload}
                disabled={!selectedFile || !uploadBoardId || isUploading}
                className={buttonVariants({ size: "md", variant: "primary" })}
              >
                {isUploading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Uploading...
                  </>
                ) : (
                  <>
                    <Upload className="mr-2 h-4 w-4" />
                    Upload
                  </>
                )}
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Preview Dialog */}
      <Dialog open={!!previewArtifact} onOpenChange={() => { setPreviewArtifact(null); setPreviewContent(null); }}>
        <DialogContent className="sm:max-w-2xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle>{previewArtifact?.filename}</DialogTitle>
            <DialogDescription>
              {previewArtifact && (
                <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-medium", ARTIFACT_TYPE_COLORS[previewArtifact.type])}>
                  {ARTIFACT_TYPE_LABELS[previewArtifact.type]}
                </span>
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="overflow-auto max-h-[60vh]">
            {previewLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
              </div>
            ) : previewContent ? (
              <pre className="text-xs text-slate-800 whitespace-pre-wrap font-mono bg-slate-50 p-4 rounded-lg">
                {previewContent}
              </pre>
            ) : (
              <p className="text-sm text-slate-500 text-center py-8">Preview not available for this file type.</p>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <ConfirmActionDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        ariaLabel="Delete artifact"
        title="Delete artifact"
        description={
          <>
            This will remove <strong>{deleteTarget?.filename}</strong>. This action cannot be undone.
          </>
        }
        errorMessage={error}
        onConfirm={handleDelete}
        isConfirming={isDeleting}
      />
    </>
  );
}

function _isTextType(mimeType: string | null): boolean {
  if (!mimeType) return false;
  return mimeType.startsWith("text/") ||
    mimeType.includes("json") ||
    mimeType.includes("yaml") ||
    mimeType.includes("xml") ||
    mimeType.includes("markdown");
}
