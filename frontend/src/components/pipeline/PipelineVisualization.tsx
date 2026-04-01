"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle, XCircle, Loader2, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { buttonVariants } from "@/components/ui/button";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
const STAGES = ["plan", "build", "test"];

function getAuthToken(): string {
  return localStorage.getItem("mc_auth_token") || "";
}

async function fetchTaskRuns(taskId: string) {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/runs/tasks/${taskId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return [];
  const data = await res.json();
  return data.items || [];
}

async function validateStage(taskId: string, stage: string) {
  const token = getAuthToken();
  const res = await fetch(
    `${BASE_URL}/api/v1/pipeline/tasks/${taskId}/validate?stage=${stage}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) return { warnings: [] };
  return res.json();
}

async function executeStage(taskId: string, stage: string) {
  const token = getAuthToken();
  const res = await fetch(
    `${BASE_URL}/api/v1/pipeline/tasks/${taskId}/execute?stage=${stage}&runtime=acp`,
    { method: "POST", headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Execute failed: ${res.status} ${text}`);
  }
  return res.json();
}

export function PipelineVisualization({ taskId }: { taskId: string }) {
  const [stages, setStages] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [executing, setExecuting] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<any[]>([]);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const runs = await fetchTaskRuns(taskId);
      const mapped = STAGES.map((stage) => {
        const stageRuns = runs.filter((r: any) => r.stage === stage);
        const latest = stageRuns[0] || null;
        let status = "pending";
        if (latest) {
          if (latest.status === "succeeded") status = "succeeded";
          else if (latest.status === "running") status = "running";
          else if (latest.status === "failed") status = "failed";
        }
        return { name: stage, status, run: latest };
      });
      setStages(mapped);
    } catch {
      setStages(STAGES.map((s) => ({ name: s, status: "pending", run: null })));
    } finally {
      setIsLoading(false);
    }
  }, [taskId]);

  useEffect(() => { load(); }, [load]);

  const handleExecute = async (stage: string) => {
    const result = await validateStage(taskId, stage);
    if (result.warnings?.length > 0) {
      setWarnings(result.warnings);
    }
    setExecuting(stage);
    try {
      await executeStage(taskId, stage);
      await load();
    } catch (err: any) {
      console.error(err);
    } finally {
      setExecuting(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center gap-2">
        {stages.map((stage) => {
          const Icon =
            stage.status === "succeeded"
              ? CheckCircle
              : stage.status === "running"
              ? Loader2
              : stage.status === "failed"
              ? XCircle
              : Clock;
          const color =
            stage.status === "succeeded"
              ? "text-green-500"
              : stage.status === "running"
              ? "text-blue-500"
              : stage.status === "failed"
              ? "text-red-500"
              : "text-slate-400";
          const bg =
            stage.status === "succeeded"
              ? "bg-green-50 border-green-200"
              : stage.status === "running"
              ? "bg-blue-50 border-blue-200"
              : stage.status === "failed"
              ? "bg-red-50 border-red-200"
              : "bg-white border-slate-200";

          return (
            <div key={stage.name} className="flex items-center">
              <button
                onClick={() => handleExecute(stage.name)}
                disabled={executing !== null}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-all",
                  bg,
                  color
                )}
              >
                <Icon
                  className={cn(
                    "h-3.5 w-3.5",
                    stage.status === "running" && "animate-spin"
                  )}
                />
                <span className="capitalize">{stage.name}</span>
              </button>
              {stage.name !== "test" && (
                <ArrowRight className="h-3 w-3 text-slate-300 mx-1" />
              )}
            </div>
          );
        })}
      </div>

      <Dialog
        open={warnings.length > 0}
        onOpenChange={() => setWarnings([])}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Pipeline Warnings</DialogTitle>
            <DialogDescription>
              These warnings indicate the pipeline order is not being followed.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {warnings.map((w: any, i: number) => (
              <div
                key={i}
                className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-700"
              >
                {w.message}
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ArrowRight({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <path d="M5 12h14" />
      <path d="m12 5 7 7-7 7" />
    </svg>
  );
}
