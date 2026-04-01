"use client";

import { cn } from "@/lib/utils";

const ROLES = [
  {
    id: "board_lead",
    label: "Board Lead",
    emoji: "🎯",
    description: "Orchestrates project development, manages backlog, enforces pipeline discipline.",
    heartbeat: "5m",
    color: "border-blue-400 bg-blue-50",
    textColor: "text-blue-700",
  },
  {
    id: "developer",
    label: "Developer",
    emoji: "🔧",
    description: "Implements tasks according to approved plans, maintains code quality.",
    heartbeat: "10m",
    color: "border-purple-400 bg-purple-50",
    textColor: "text-purple-700",
  },
  {
    id: "qa_engineer",
    label: "QA Engineer",
    emoji: "🧪",
    description: "Tests implementations, finds bugs, runs Playwright e2e tests.",
    heartbeat: "10m",
    color: "border-green-400 bg-green-50",
    textColor: "text-green-700",
  },
  {
    id: "technical_writer",
    label: "Technical Writer",
    emoji: "📝",
    description: "Maintains documentation, ADRs, changelogs, and knowledge base.",
    heartbeat: "15m",
    color: "border-amber-400 bg-amber-50",
    textColor: "text-amber-700",
  },
  {
    id: "ops_guardian",
    label: "Ops Guardian",
    emoji: "🛡️",
    description: "Monitors system health, recovers from failures, maintains security.",
    heartbeat: "3m",
    color: "border-red-400 bg-red-50",
    textColor: "text-red-700",
  },
];

export function RoleSelector({
  selected,
  onChange,
}: {
  selected: string;
  onChange: (role: string) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {ROLES.map((role) => (
        <button
          key={role.id}
          onClick={() => onChange(role.id)}
          className={cn(
            "rounded-xl border-2 p-4 text-left transition-all hover:shadow-md",
            selected === role.id
              ? cn("ring-2 ring-offset-1", role.color, role.textColor)
              : "border-slate-200 bg-white hover:border-slate-300"
          )}
        >
          <div className="flex items-center gap-2 mb-2">
            <span className="text-2xl">{role.emoji}</span>
            <span className="font-semibold text-sm">{role.label}</span>
          </div>
          <p className="text-xs text-slate-500 mb-2">{role.description}</p>
          <span className="text-[10px] text-slate-400">Heartbeat: {role.heartbeat}</span>
        </button>
      ))}
    </div>
  );
}

export { ROLES };
