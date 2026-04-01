"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/auth/clerk";
import {
  Loader2,
  Activity,
  AlertTriangle,
  RefreshCw,
  RotateCw,
  Power,
  FileSync,
  CheckCircle,
  XCircle,
  Clock,
  Shield,
} from "lucide-react";

import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useActiveBoard } from "@/lib/active-project";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

interface BoardOption {
  id: string;
  name: string;
}

function getAuthToken(): string {
  return localStorage.getItem("mc_auth_token") || "";
}

async function runHealthCheck(): Promise<any> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/watchdog/health-check`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}

async function getEscalations(): Promise<any> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/watchdog/escalations`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch escalations");
  return res.json();
}

async function opsCommand(agentId: string, command: string): Promise<any> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/watchdog/agents/${agentId}/${command}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${command} failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function fetchAgents(): Promise<any[]> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/agents`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch agents");
  const data = await res.json();
  return data.items || [];
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

export default function WatchdogPage() {
  const { isSignedIn } = useAuth();
  const [activeBoardId, setActiveBoardId] = useActiveBoard();
  const [boards, setBoards] = useState<BoardOption[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [escalations, setEscalations] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isChecking, setIsChecking] = useState(false);
  const [lastCheck, setLastCheck] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [runningCommand, setRunningCommand] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [boardsData, agentsData, escData] = await Promise.all([
        fetchBoards(),
        fetchAgents(),
        getEscalations(),
      ]);
      setBoards(boardsData);
      const boardId = activeBoardId || boardsData[0]?.id || "";
      if (boardId && boardId !== activeBoardId) {
        setActiveBoardId(boardId);
      }
      setAgents(boardId ? agentsData.filter((agent) => agent.board_id === boardId) : agentsData);
      setEscalations(escData.escalations || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }, [activeBoardId, setActiveBoardId]);

  useEffect(() => {
    if (isSignedIn) loadData();
  }, [isSignedIn, loadData]);

  useEffect(() => {
    if (!isSignedIn) return;
    const intervalId = window.setInterval(() => {
      void loadData();
    }, 30000);
    return () => window.clearInterval(intervalId);
  }, [isSignedIn, loadData]);

  const handleHealthCheck = async () => {
    setIsChecking(true);
    setError(null);
    try {
      const result = await runHealthCheck();
      setLastCheck(result);
      await loadData();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsChecking(false);
    }
  };

  const handleCommand = async (agentId: string, command: string) => {
    setRunningCommand(`${agentId}-${command}`);
    try {
      await opsCommand(agentId, command);
      await loadData();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRunningCommand(null);
    }
  };

  const offlineCount = agents.filter((a) => a.status === "offline").length;
  const onlineCount = agents.filter((a) => a.status === "online").length;
  const idleCount = agents.filter((a) => a.status === "idle").length;
  const dormantCount = agents.filter((a) => a.status === "dormant").length;

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to view watchdog.",
          forceRedirectUrl: "/watchdog",
          signUpForceRedirectUrl: "/watchdog",
        }}
        title="Watchdog"
        description={`Monitoring ${agents.length} agents. ${onlineCount} online, ${idleCount} idle, ${dormantCount} dormant, ${offlineCount} offline.`}
        headerActions={
          <div className="flex items-center gap-2">
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
            <button
              onClick={handleHealthCheck}
              disabled={isChecking}
              className={buttonVariants({ size: "md", variant: "primary" })}
            >
              {isChecking ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Activity className="mr-2 h-4 w-4" />
              )}
              Run Health Check
            </button>
          </div>
        }
        stickyHeader
      >
        {/* Summary cards */}
        <div className="grid gap-4 sm:grid-cols-5 mb-6">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-blue-500" />
              <div>
                <p className="text-2xl font-bold text-slate-800">{agents.length}</p>
                <p className="text-xs text-slate-500">Total Agents</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-green-200 bg-green-50 p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <CheckCircle className="h-5 w-5 text-green-500" />
              <div>
                <p className="text-2xl font-bold text-green-600">{onlineCount}</p>
                <p className="text-xs text-slate-500">Online</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <Clock className="h-5 w-5 text-blue-500" />
              <div>
                <p className="text-2xl font-bold text-blue-600">{idleCount}</p>
                <p className="text-xs text-slate-500">Idle</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-slate-300 bg-slate-50 p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-slate-500" />
              <div>
                <p className="text-2xl font-bold text-slate-700">{dormantCount}</p>
                <p className="text-xs text-slate-500">Dormant</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <XCircle className="h-5 w-5 text-red-500" />
              <div>
                <p className="text-2xl font-bold text-red-600">{offlineCount}</p>
                <p className="text-xs text-slate-500">Offline</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
              <div>
                <p className="text-2xl font-bold text-amber-600">{escalations.length}</p>
                <p className="text-xs text-slate-500">Escalations</p>
              </div>
            </div>
          </div>
        </div>

        {/* Escalations */}
        {escalations.length > 0 && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 mb-6">
            <h2 className="text-sm font-semibold text-amber-800 mb-3 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              Active Escalations
            </h2>
            <div className="space-y-2">
              {escalations.map((esc, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 rounded-lg bg-white border border-amber-200 p-3"
                >
                  <AlertTriangle
                    className={cn(
                      "h-4 w-4 flex-shrink-0",
                      esc.severity === "high" ? "text-red-500" : "text-amber-500"
                    )}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800 capitalize">
                      {esc.type.replace(/_/g, " ")}
                    </p>
                    <p className="text-xs text-slate-500 truncate">
                      {esc.agent_name || esc.task_id || esc.run_id}
                      {esc.duration_minutes && ` · ${Math.round(esc.duration_minutes)}m`}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "text-[10px] px-2 py-0.5 rounded font-medium",
                      esc.severity === "high"
                        ? "bg-red-100 text-red-700"
                        : "bg-amber-100 text-amber-700"
                    )}
                  >
                    {esc.severity}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Last health check results */}
        {lastCheck && (
          <div className="rounded-xl border border-slate-200 bg-white p-4 mb-6">
            <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Last Health Check Results
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="text-center p-3 rounded-lg bg-slate-50">
                <p className="text-lg font-bold text-slate-800">{lastCheck.heartbeats?.count || 0}</p>
                <p className="text-[10px] text-slate-500">Offline Transitions</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-slate-50">
                <p className="text-lg font-bold text-slate-800">{lastCheck.retries?.count || 0}</p>
                <p className="text-[10px] text-slate-500">Retried Runs</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-slate-50">
                <p className="text-lg font-bold text-slate-800">{lastCheck.reassignments?.count || 0}</p>
                <p className="text-[10px] text-slate-500">Reassigned Tasks</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-slate-50">
                <p className="text-lg font-bold text-slate-800">{lastCheck.escalations?.count || 0}</p>
                <p className="text-[10px] text-slate-500">Escalations</p>
              </div>
            </div>
          </div>
        )}

        {/* Agents list */}
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="px-4 py-3 border-b border-slate-100">
            <h2 className="text-sm font-semibold text-slate-700">Agent Health Status</h2>
          </div>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
            </div>
          ) : agents.length === 0 ? (
            <p className="text-sm text-slate-400 text-center py-8">No agents found.</p>
          ) : (
            <div className="divide-y divide-slate-100">
              {agents.map((agent) => (
                <div key={agent.id} className="px-4 py-3 flex items-center gap-4">
                  <span
                    className={cn(
                      "h-3 w-3 rounded-full flex-shrink-0",
                      agent.status === "online"
                        ? "bg-green-500"
                        : agent.status === "idle"
                        ? "bg-blue-500"
                        : agent.status === "dormant"
                        ? "bg-slate-500"
                        : agent.status === "offline"
                        ? "bg-red-500"
                        : "bg-amber-500"
                    )}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800 truncate">{agent.name}</p>
                    <p className="text-[10px] text-slate-400">
                      {agent.identity_profile?.role || "Unknown"}
                      {agent.last_seen_at && ` · Last seen: ${new Date(agent.last_seen_at).toLocaleString()}`}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "text-[10px] px-2 py-0.5 rounded font-medium",
                      agent.status === "online"
                        ? "bg-green-100 text-green-700"
                        : agent.status === "idle"
                        ? "bg-blue-100 text-blue-700"
                        : agent.status === "dormant"
                        ? "bg-slate-100 text-slate-700"
                        : agent.status === "offline"
                        ? "bg-red-100 text-red-700"
                        : "bg-amber-100 text-amber-700"
                    )}
                  >
                    {agent.status}
                  </span>
                  <div className="flex items-center gap-1">
                    {[
                      { cmd: "template-sync", icon: FileSync, label: "Sync" },
                      { cmd: "rotate-tokens", icon: RotateCw, label: "Rotate" },
                      { cmd: "reset-session", icon: RefreshCw, label: "Reset" },
                      { cmd: "wake", icon: Power, label: "Wake" },
                    ].map(({ cmd, icon: Icon, label }) => (
                      <button
                        key={cmd}
                        onClick={() => handleCommand(agent.id, cmd)}
                        disabled={runningCommand === `${agent.id}-${cmd}`}
                        className="p-1.5 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                        title={label}
                      >
                        {runningCommand === `${agent.id}-${cmd}` ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Icon className="h-3.5 w-3.5" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {error && (
          <p className="mt-4 text-sm text-red-500">{error}</p>
        )}
      </DashboardPageLayout>
    </>
  );
}
