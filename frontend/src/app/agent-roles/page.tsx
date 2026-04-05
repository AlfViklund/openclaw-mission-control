"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/auth/clerk";
import { getLocalAuthToken } from "@/auth/localAuth";
import {
  Loader2,
  Users,
  Shield,
  Wrench,
  FlaskConical,
  PenTool,
  Target,
  Clock,
  Plus,
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
import { ROLES } from "@/components/agents/RoleSelector";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

interface BoardOption {
  id: string;
  name: string;
}

interface GatewayOption {
  id: string;
  name: string;
}

function getAuthToken(): string {
  return getLocalAuthToken() || "";
}

async function fetchPresets(): Promise<any[]> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/agents/presets`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch presets");
  const data = await res.json();
  return Object.values(data.presets || {});
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

async function fetchGateways(): Promise<GatewayOption[]> {
  const token = getAuthToken();
  const res = await fetch(`${BASE_URL}/api/v1/gateways`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch gateways");
  const data = await res.json();
  return data.items || [];
}

async function provisionTeam(boardId: string, gatewayId: string, roles: string[]): Promise<any> {
  const token = getAuthToken();
  const params = new URLSearchParams();
  roles.forEach((r) => params.append("roles", r));
  params.set("gateway_id", gatewayId);
  const res = await fetch(
    `${BASE_URL}/api/v1/agents/boards/${boardId}/team/provision?${params}`,
    { method: "POST", headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Provision failed: ${res.status} ${text}`);
  }
  return res.json();
}

const ROLE_ICONS: Record<string, typeof Target> = {
  "Board Lead": Target,
  Developer: Wrench,
  "QA Engineer": FlaskConical,
  "Technical Writer": PenTool,
  "Ops Guardian": Shield,
};

export default function AgentRolesPage() {
  const { isSignedIn } = useAuth();
  const [boards, setBoards] = useState<BoardOption[]>([]);
  const [gateways, setGateways] = useState<GatewayOption[]>([]);
  const [selectedBoardId, setSelectedBoardId] = useState("");
  const [agents, setAgents] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showProvisionDialog, setShowProvisionDialog] = useState(false);
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [boardId, setBoardId] = useState("");
  const [gatewayId, setGatewayId] = useState("");
  const [isProvisioning, setIsProvisioning] = useState(false);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [agentsData, boardsData, gatewaysData] = await Promise.all([
        fetchAgents(),
        fetchBoards(),
        fetchGateways(),
      ]);
      setBoards(boardsData);
      setGateways(gatewaysData);
      const boardId = selectedBoardId || localStorage.getItem("clawdev_active_board_id") || boardsData[0]?.id || "";
      if (boardId && boardId !== selectedBoardId) {
        setSelectedBoardId(boardId);
      }
      setAgents(boardId ? agentsData.filter((agent) => agent.board_id === boardId) : agentsData);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }, [selectedBoardId]);

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

  const handleProvision = async () => {
    if (!boardId || !gatewayId || selectedRoles.length === 0) return;
    setIsProvisioning(true);
    setError(null);
    try {
      await provisionTeam(boardId, gatewayId, selectedRoles);
      setShowProvisionDialog(false);
      setSelectedRoles([]);
      setBoardId("");
      setGatewayId("");
      await loadData();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsProvisioning(false);
    }
  };

  const agentsByRole: Record<string, any[]> = {};
  agents.forEach((a) => {
    const role = a.identity_profile?.role || "Unknown";
    if (!agentsByRole[role]) agentsByRole[role] = [];
    agentsByRole[role].push(a);
  });

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to view agent roles.",
          forceRedirectUrl: "/agent-roles",
          signUpForceRedirectUrl: "/agent-roles",
        }}
        title="Agent Roles"
        description="Manage agent roles, view team composition, and provision new agents."
        headerActions={
          <div className="flex items-center gap-2">
            <select
              value={selectedBoardId}
              onChange={(e) => {
                setSelectedBoardId(e.target.value);
                localStorage.setItem("clawdev_active_board_id", e.target.value);
              }}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">All projects</option>
              {boards.map((board) => (
                <option key={board.id} value={board.id}>{board.name}</option>
              ))}
            </select>
            <button
              onClick={() => setShowProvisionDialog(true)}
              className={buttonVariants({ size: "md", variant: "primary" })}
            >
              <Plus className="mr-2 h-4 w-4" />
              Provision Team
            </button>
          </div>
        }
        stickyHeader
      >
        {/* Role overview cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-8">
          {ROLES.map((role) => {
            const Icon = ROLE_ICONS[role.label] || Users;
            const roleAgents = agentsByRole[role.label] || [];
            const online = roleAgents.filter((a) => a.status === "online").length;
            return (
              <div
                key={role.id}
                className={cn(
                  "rounded-xl border p-4 bg-white shadow-sm",
                  roleAgents.length > 0 ? "border-slate-200" : "border-dashed border-slate-300"
                )}
              >
                <div className="flex items-center gap-3 mb-3">
                  <div className={cn("rounded-lg p-2", role.color.replace("border-", "bg-").replace("-400", "-100"))}>
                    <Icon className={cn("h-5 w-5", role.textColor)} />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-slate-800">{role.label}</h3>
                    <p className="text-[10px] text-slate-400">Heartbeat: {role.heartbeat}</p>
                  </div>
                </div>
                <p className="text-xs text-slate-500 mb-3">{role.description}</p>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">
                    {roleAgents.length} agent{roleAgents.length !== 1 ? "s" : ""}
                  </span>
                  {roleAgents.length > 0 && (
                    <span className="flex items-center gap-1 text-green-600">
                      <Clock className="h-3 w-3" />
                      {online} online
                    </span>
                  )}
                </div>
                {roleAgents.length > 0 && (
                  <div className="mt-3 space-y-1">
                    {roleAgents.map((agent) => (
                      <div
                        key={agent.id}
                        className="flex items-center justify-between text-xs py-1 px-2 rounded bg-slate-50"
                      >
                        <span className="truncate text-slate-700">{agent.name}</span>
                        <span
                          className={cn(
                            "h-2 w-2 rounded-full flex-shrink-0 ml-2",
                            agent.status === "online"
                              ? "bg-green-500"
                              : agent.status === "offline"
                              ? "bg-red-500"
                              : "bg-amber-500"
                          )}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Team composition visualization */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-2">
            <Users className="h-4 w-4" />
            Team Composition
          </h2>
          {agents.length === 0 ? (
            <p className="text-sm text-slate-400 text-center py-8">
              No agents provisioned yet. Use "Provision Team" to create your agent team.
            </p>
          ) : (
            <div className="flex flex-wrap gap-3">
              {agents.map((agent) => {
                const role = agent.identity_profile?.role || "Unknown";
                const roleConfig = ROLES.find(
                  (r) => r.label === role
                );
                const emoji = roleConfig?.emoji || "⚙️";
                return (
                  <div
                    key={agent.id}
                    className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
                  >
                    <span className="text-lg">{emoji}</span>
                    <div>
                      <p className="text-xs font-medium text-slate-700">{agent.name}</p>
                      <p className="text-[10px] text-slate-400">{role}</p>
                    </div>
                    <span
                      className={cn(
                        "h-2 w-2 rounded-full ml-2",
                        agent.status === "online"
                          ? "bg-green-500"
                          : agent.status === "offline"
                          ? "bg-red-500"
                          : "bg-amber-500"
                      )}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {error && (
          <p className="mt-4 text-sm text-red-500">{error}</p>
        )}
      </DashboardPageLayout>

      {/* Provision Dialog */}
      <Dialog open={showProvisionDialog} onOpenChange={setShowProvisionDialog}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Provision Team</DialogTitle>
            <DialogDescription>
              Create a team of agents with role-based presets for a board.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Project *</label>
              <select
                value={boardId}
                onChange={(e) => setBoardId(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select project</option>
                {boards.map((board) => (
                  <option key={board.id} value={board.id}>{board.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Gateway *</label>
              <select
                value={gatewayId}
                onChange={(e) => setGatewayId(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select gateway</option>
                {gateways.map((gateway) => (
                  <option key={gateway.id} value={gateway.id}>{gateway.name}</option>
                ))}
              </select>
            </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-2">
                Select Roles ({selectedRoles.length} selected)
              </label>
              <div className="grid grid-cols-2 gap-2">
                {ROLES.map((role) => {
                  const isSelected = selectedRoles.includes(role.id);
                  return (
                    <button
                      key={role.id}
                      onClick={() =>
                        setSelectedRoles((prev) =>
                          prev.includes(role.id)
                            ? prev.filter((r) => r !== role.id)
                            : [...prev, role.id]
                        )
                      }
                      className={cn(
                        "flex items-center gap-2 rounded-lg border p-2 text-xs transition-all",
                        isSelected
                          ? cn("border-blue-400 bg-blue-50", role.textColor)
                          : "border-slate-200 hover:border-slate-300"
                      )}
                    >
                      <span className="text-base">{role.emoji}</span>
                      <span>{role.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowProvisionDialog(false);
                  setSelectedRoles([]);
                  setBoardId("");
                  setGatewayId("");
                }}
                className={buttonVariants({ size: "md", variant: "outline" })}
                disabled={isProvisioning}
              >
                Cancel
              </button>
              <button
                onClick={handleProvision}
                disabled={!boardId || !gatewayId || selectedRoles.length === 0 || isProvisioning}
                className={buttonVariants({ size: "md", variant: "primary" })}
              >
                {isProvisioning ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="mr-2 h-4 w-4" />
                )}
                Provision {selectedRoles.length} Agent{selectedRoles.length !== 1 ? "s" : ""}
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
