"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, ChevronRight, Loader2, RefreshCw, ArrowLeft } from "lucide-react";

import {
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { customFetch } from "@/api/mutator";
import type { BoardRead } from "@/api/generated/model";

type ProjectMode =
  | "new_product"
  | "existing_product_evolution"
  | "new_feature"
  | "stabilization"
  | "research_prototype";
type ProjectStage =
  | "idea_only"
  | "spec_exists"
  | "codebase_exists"
  | "active_development"
  | "shipped_product";
type FirstMilestoneType =
  | "mvp"
  | "architecture_plan"
  | "key_feature"
  | "stabilization"
  | "research_prototype"
  | "other";
type DeliveryMode =
  | "quality_first"
  | "balanced"
  | "fast_first_milestone"
  | "aggressive_push";
type DeadlineMode = "none" | "few_days" | "one_two_weeks" | "one_month" | "custom";
type ProvisionMode = "lead_only" | "selected_roles" | "full_team";
type BootstrapMode =
  | "generate_backlog"
  | "empty_board"
  | "lead_only"
  | "draft_only";
type PlannerMode =
  | "spec_to_backlog"
  | "architecture_first"
  | "feature_first"
  | "empty_board";
type QaStrictness = "flexible" | "balanced" | "strict";
type AutomationProfile = "economy" | "normal" | "active" | "aggressive";
type LeadAutonomyLevel = "ask_first" | "balanced" | "autonomous";
type LeadVerbosity = "concise" | "balanced" | "detailed";
type LeadOutputFormat = "bullets" | "mixed" | "narrative";
type LeadUpdateCadence = "asap" | "hourly" | "daily" | "weekly";

interface BoardOnboardingDraftUpdate {
  board_type?: string;
  objective?: string;
  refine_status?: "idle" | "pending" | "questions" | "complete";
  project_info?: {
    project_mode?: ProjectMode;
    project_stage?: ProjectStage;
    first_milestone_type?: FirstMilestoneType;
    first_milestone_text?: string;
    delivery_mode?: DeliveryMode;
    deadline_mode?: DeadlineMode;
    deadline_text?: string;
  };
  context?: {
    description?: string;
    existing_artifacts?: string;
    constraints?: string;
    special_instructions?: string;
    extra_context?: string;
  };
  lead_agent?: {
    name?: string;
    autonomy_level?: LeadAutonomyLevel;
    verbosity?: LeadVerbosity;
    output_format?: LeadOutputFormat;
    update_cadence?: LeadUpdateCadence;
    custom_instructions?: string;
  };
  team_plan?: {
    provision_mode?: ProvisionMode;
    roles?: string[];
  };
  planning_policy?: {
    bootstrap_mode?: BootstrapMode;
    planner_mode?: PlannerMode;
    generate_initial_backlog?: boolean;
  };
  qa_policy?: {
    strictness?: QaStrictness;
  };
  automation_policy?: {
    automation_profile?: AutomationProfile;
  };
}

interface BoardOnboardingConfirm {
  board_type?: string;
  objective?: string;
  success_metrics?: Record<string, unknown>;
}

interface BoardBootstrapResult {
  lead_status: string;
  lead_name?: string;
  team_status: string;
  team_agents_created: number;
  team_created_roles: string[];
  team_skipped_roles: string[];
  team_failed_roles?: string[];
  planner_status: string;
  planner_output_id?: string;
  automation_sync?: {
    status: string;
    agents_updated: number;
  };
  bootstrap_summary?: string;
}

export function computeCurrentStep(
  d: BoardOnboardingDraftUpdate,
  refineStatus?: "idle" | "pending" | "questions" | "complete",
): number {
  if (!d.project_info?.project_mode || !d.project_info?.project_stage) return 1;
  if (!d.project_info?.first_milestone_type) return 2;
  // Step 3 (context) is optional — skip it.
  if (!d.lead_agent?.name) return 4;
  if (!d.team_plan?.provision_mode) return 5;
  if (!d.planning_policy?.bootstrap_mode) return 6;
  if (!d.qa_policy?.strictness) return 7;
  if (!d.automation_policy?.automation_profile) return 8;

  // Steps 1–8 are complete. Determine refine vs review.
  const status = refineStatus ?? d.refine_status;
  if (status === "pending" || status === "questions") return 9;
  return 10;
}

interface _BoardOnboardingRead {
  id: string;
  board_id: string;
  status: string;
  draft_goal?: BoardOnboardingDraftUpdate;
}

const PROJECT_MODE_OPTIONS: { value: ProjectMode; label: string }[] = [
  { value: "new_product", label: "New product" },
  { value: "existing_product_evolution", label: "Existing product evolution" },
  { value: "new_feature", label: "New feature" },
  { value: "stabilization", label: "Stabilization" },
  { value: "research_prototype", label: "Research/prototype" },
];

const PROJECT_STAGE_OPTIONS: { value: ProjectStage; label: string }[] = [
  { value: "idea_only", label: "Idea only" },
  { value: "spec_exists", label: "Spec exists" },
  { value: "codebase_exists", label: "Codebase exists" },
  { value: "active_development", label: "Active development" },
  { value: "shipped_product", label: "Shipped product" },
];

const FIRST_MILESTONE_OPTIONS: { value: FirstMilestoneType; label: string }[] = [
  { value: "mvp", label: "MVP" },
  { value: "architecture_plan", label: "Architecture plan" },
  { value: "key_feature", label: "Key feature" },
  { value: "stabilization", label: "Stabilization" },
  { value: "research_prototype", label: "Research/prototype" },
  { value: "other", label: "Other" },
];

const DELIVERY_MODE_OPTIONS: { value: DeliveryMode; label: string }[] = [
  { value: "quality_first", label: "Quality first" },
  { value: "balanced", label: "Balanced" },
  { value: "fast_first_milestone", label: "Fast first milestone" },
  { value: "aggressive_push", label: "Aggressive push" },
];

const DEADLINE_MODE_OPTIONS: { value: DeadlineMode; label: string }[] = [
  { value: "none", label: "No deadline" },
  { value: "few_days", label: "Few days" },
  { value: "one_two_weeks", label: "1-2 weeks" },
  { value: "one_month", label: "1 month" },
  { value: "custom", label: "Custom" },
];

const AUTONOMY_LEVEL_OPTIONS: { value: LeadAutonomyLevel; label: string }[] = [
  { value: "ask_first", label: "Ask first" },
  { value: "balanced", label: "Balanced" },
  { value: "autonomous", label: "Autonomous" },
];

const VERBOSITY_OPTIONS: { value: LeadVerbosity; label: string }[] = [
  { value: "concise", label: "Concise" },
  { value: "balanced", label: "Balanced" },
  { value: "detailed", label: "Detailed" },
];

const OUTPUT_FORMAT_OPTIONS: { value: LeadOutputFormat; label: string }[] = [
  { value: "bullets", label: "Bullets" },
  { value: "mixed", label: "Mixed" },
  { value: "narrative", label: "Narrative" },
];

const UPDATE_CADENCE_OPTIONS: { value: LeadUpdateCadence; label: string }[] = [
  { value: "asap", label: "ASAP" },
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
];

const PROVISION_MODE_OPTIONS: { value: ProvisionMode; label: string; description: string }[] = [
  { value: "lead_only", label: "Only lead", description: "Just the lead agent" },
  { value: "selected_roles", label: "Lead + selected roles", description: "Choose specific roles" },
  { value: "full_team", label: "Full standard team", description: "All standard roles" },
];

const ROLE_OPTIONS = [
  { value: "board_lead", label: "Board Lead" },
  { value: "developer", label: "Developer" },
  { value: "qa_engineer", label: "QA Engineer" },
  { value: "technical_writer", label: "Technical Writer" },
  { value: "ops_guardian", label: "Ops Guardian" },
];

const BOOTSTRAP_MODE_OPTIONS: { value: BootstrapMode; label: string }[] = [
  { value: "generate_backlog", label: "Generate initial backlog" },
  { value: "empty_board", label: "Start with empty board" },
  { value: "lead_only", label: "Only lead and team" },
  { value: "draft_only", label: "Prepare draft plan without applying" },
];

const PLANNER_MODE_OPTIONS: { value: PlannerMode; label: string }[] = [
  { value: "spec_to_backlog", label: "Spec to backlog" },
  { value: "architecture_first", label: "Architecture first" },
  { value: "feature_first", label: "Feature first" },
  { value: "empty_board", label: "Empty board" },
];

const STRICTNESS_OPTIONS: { value: QaStrictness; label: string; description: string }[] = [
  { value: "flexible", label: "Flexible", description: "Smoke tests, no approval gate" },
  { value: "balanced", label: "Balanced", description: "Standard QA, approval required" },
  { value: "strict", label: "Strict", description: "Rigorous engineering standards" },
];

const AUTOMATION_PROFILE_OPTIONS: { value: AutomationProfile; label: string; preview: string }[] = [
  { value: "economy", label: "Economy", preview: "Online: 10min | Idle: 1hr | Dormant: 6hr" },
  { value: "normal", label: "Normal", preview: "Online: 5min | Idle: 30min | Dormant: 3hr" },
  { value: "active", label: "Active", preview: "Online: 2min | Idle: 15min | Dormant: 1hr" },
  { value: "aggressive", label: "Aggressive", preview: "Online: 30sec | Idle: 5min | Dormant: 30min" },
];

function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(" ");
}

function humanizeProjectMode(mode: ProjectMode | undefined): string {
  const labels: Record<ProjectMode, string> = {
    new_product: "New product",
    existing_product_evolution: "Existing product evolution",
    new_feature: "New feature",
    stabilization: "Stabilization",
    research_prototype: "Research/prototype",
  };
  return mode ? labels[mode] ?? mode : "Not set";
}

function humanizeProjectStage(stage: ProjectStage | undefined): string {
  const labels: Record<ProjectStage, string> = {
    idea_only: "Idea only",
    spec_exists: "Spec exists",
    codebase_exists: "Codebase exists",
    active_development: "Active development",
    shipped_product: "Shipped product",
  };
  return stage ? labels[stage] ?? stage : "Not set";
}

function humanizeMilestoneType(milestone: FirstMilestoneType | undefined): string {
  const labels: Record<FirstMilestoneType, string> = {
    mvp: "MVP",
    architecture_plan: "Architecture plan",
    key_feature: "Key feature",
    stabilization: "Stabilization",
    research_prototype: "Research/prototype",
    other: "Other",
  };
  return milestone ? labels[milestone] ?? milestone : "Not set";
}

function humanizeDeliveryMode(mode: DeliveryMode | undefined): string {
  const labels: Record<DeliveryMode, string> = {
    quality_first: "Quality first",
    balanced: "Balanced",
    fast_first_milestone: "Fast first milestone",
    aggressive_push: "Aggressive push",
  };
  return mode ? labels[mode] ?? mode : "Not set";
}

function humanizeAutonomyLevel(level: LeadAutonomyLevel | undefined): string {
  const labels: Record<LeadAutonomyLevel, string> = {
    ask_first: "Ask first",
    balanced: "Balanced",
    autonomous: "Autonomous",
  };
  return level ? labels[level] ?? level : "Default";
}

function humanizeProvisionMode(mode: ProvisionMode | undefined): string {
  if (mode === "lead_only") return "Lead agent only";
  if (mode === "full_team") return "Full standard team";
  if (mode === "selected_roles") return "Selected roles";
  return "Not set";
}

function humanizeBootstrapMode(mode: BootstrapMode | undefined): string {
  const labels: Record<BootstrapMode, string> = {
    generate_backlog: "Generate initial backlog",
    empty_board: "Start with empty board",
    lead_only: "Lead agent and team only",
    draft_only: "Prepare draft plan",
  };
  return mode ? labels[mode] ?? mode : "Not set";
}

function humanizePlannerMode(mode: PlannerMode | undefined): string {
  const labels: Record<PlannerMode, string> = {
    spec_to_backlog: "Spec to backlog",
    architecture_first: "Architecture first",
    feature_first: "Feature first",
    empty_board: "Empty board",
  };
  return mode ? labels[mode] ?? mode : "Not set";
}

function humanizeStrictness(strictness: QaStrictness | undefined): string {
  const labels: Record<QaStrictness, string> = {
    flexible: "Flexible — smoke tests, no approval gate",
    balanced: "Balanced — standard QA with approval required",
    strict: "Strict — rigorous engineering standards",
  };
  return strictness ? labels[strictness] ?? strictness : "Not set";
}

function humanizeAutomationProfile(profile: AutomationProfile | undefined): string {
  const labels: Record<AutomationProfile, string> = {
    economy: "Economy — slow heartbeat (online: 10min, idle: 1hr)",
    normal: "Normal — balanced heartbeat (online: 5min, idle: 30min)",
    active: "Active — fast heartbeat (online: 2min, idle: 15min)",
    aggressive: "Aggressive — real-time heartbeat (online: 30sec, idle: 5min)",
  };
  return profile ? labels[profile] ?? profile : "Not set";
}

function humanizeLeadStatus(status: string | undefined, name: string | undefined): string {
  if (status === "created") return `Lead '${name || "agent"}' created`;
  if (status === "updated") return `Lead '${name || "agent"}' updated`;
  if (status === "unchanged") return "Lead unchanged";
  return status || "Unknown";
}

function humanizeTeamStatus(
  status: string | undefined,
  created: number,
  createdRoles: string[],
  failedRoles: string[],
): string {
  if (status === "provisioned") {
    const roles = createdRoles.map(r => r.replace(/_/g, " ")).join(", ");
    return `Team provisioned (${created} role${created !== 1 ? "s" : ""}: ${roles})`;
  }
  if (status === "already_provisioned") return "Team already provisioned";
  if (status === "partial_failure") {
    const ok = createdRoles.map(r => r.replace(/_/g, " ")).join(", ");
    const fail = failedRoles.map(r => r.replace(/_/g, " ")).join(", ");
    return `Team partial: ${ok || "none"} created, ${fail || "none"} failed`;
  }
  if (status === "failed") return "Team provisioning failed";
  if (status === "not_requested") return "Team not requested";
  return status || "Unknown";
}

function humanizePlannerStatus(status: string | undefined): string {
  const labels: Record<string, string> = {
    started: "Planner started",
    draft_created: "Planner draft created",
    queued: "Planner queued",
    failed: "Planner bootstrap failed",
    not_requested: "Planner not requested",
  };
  return status ? labels[status] ?? status : "Unknown";
}

function humanizeAutomationSyncStatus(status: string | undefined, updated: number): string {
  if (status === "success") return `Automation synced — ${updated} agent${updated !== 1 ? "s" : ""} updated`;
  if (status === "partial_failure") return `Automation partial sync (${updated} agents updated)`;
  if (status === "failed") return "Automation sync failed";
  if (status === "not_run") return "Automation sync not run";
  return status || "Unknown";
}

interface RadioOptionProps {
  value: string;
  label: string;
  description?: string;
  selected: boolean;
  onSelect: () => void;
  disabled?: boolean;
}

function RadioOption({ value: _value, label, description, selected, onSelect, disabled }: RadioOptionProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={selected}
      className={cn(
        "w-full rounded-xl border-2 px-4 py-3 text-left transition-all",
        selected
          ? "border-[var(--accent)] bg-[var(--accent)]/10"
          : "border-[var(--border)] hover:border-[var(--accent)]/50",
        disabled && "opacity-50 cursor-not-allowed",
      )}
    >
      <div className="flex items-center gap-3">
        <div
          className={cn(
            "flex h-5 w-5 items-center justify-center rounded-full border-2 transition-colors",
            selected
              ? "border-[var(--accent)] bg-[var(--accent)]"
              : "border-[var(--border)]",
          )}
        >
          {selected && <Check className="h-3 w-3 text-white" />}
        </div>
        <div className="flex-1">
          <div className="font-medium text-strong">{label}</div>
          {description && (
            <div className="text-sm text-[var(--text-quiet)]">{description}</div>
          )}
        </div>
      </div>
    </button>
  );
}

interface CheckboxOptionProps {
  value: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

function CheckboxOption({ value: _value, label, checked, onChange, disabled }: CheckboxOptionProps) {
  return (
    <button
      type="button"
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
      className={cn(
        "flex w-full items-center gap-3 rounded-xl border-2 px-4 py-3 transition-all",
        checked
          ? "border-[var(--accent)] bg-[var(--accent)]/10"
          : "border-[var(--border)] hover:border-[var(--accent)]/50",
        disabled && "opacity-50 cursor-not-allowed",
      )}
    >
      <div
        className={cn(
          "flex h-5 w-5 items-center justify-center rounded border-2 transition-colors",
          checked
            ? "border-[var(--accent)] bg-[var(--accent)]"
            : "border-[var(--border)]",
        )}
      >
        {checked && <Check className="h-3 w-3 text-white" />}
      </div>
      <span className="font-medium text-strong">{label}</span>
    </button>
  );
}

interface StepIndicatorProps {
  currentStep: number;
  totalSteps: number;
}

function StepIndicator({ currentStep, totalSteps }: StepIndicatorProps) {
  return (
    <div className="flex items-center gap-2">
      {Array.from({ length: totalSteps }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "h-2 flex-1 rounded-full transition-colors",
            i + 1 <= currentStep
              ? "bg-[var(--accent)]"
              : "bg-[var(--border)]",
          )}
        />
      ))}
    </div>
  );
}

export function BoardOnboardingWizard({
  boardId,
  onConfirmed,
}: {
  boardId: string;
  onConfirmed: (board: BoardRead) => void;
}) {
  const [currentStep, setCurrentStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refined, setRefined] = useState(false);
  const [refining, setRefining] = useState(false);
  const [refineStatus, setRefineStatus] = useState<"idle" | "pending" | "questions" | "complete" | "failed">("idle");
  const [refineQuestions, setRefineQuestions] = useState<{ id: string; question: string; options: { id: string; label: string }[] }[]>([]);
  const [refineSummary, setRefineSummary] = useState<string | null>(null);
  const [refineAnswers, setRefineAnswers] = useState<Record<string, string>>({});
  const [refineTimeout, setRefineTimeout] = useState(false);
  const [bootstrapResult, setBootstrapResult] = useState<BoardBootstrapResult | null>(null);
  const [confirmedBoard, setConfirmedBoard] = useState<BoardRead | null>(null);

  const [draft, setDraft] = useState<BoardOnboardingDraftUpdate>({
    project_info: {},
    context: {},
    lead_agent: {},
    team_plan: {},
    planning_policy: {},
    qa_policy: {},
    automation_policy: {},
  });

  useEffect(() => {
    const loadDraft = async () => {
      try {
        const result = await customFetch<{
          data: { draft_goal?: Record<string, unknown> | null; status?: string; refine_status?: string; refine_questions?: unknown[]; refine_summary?: string | null };
          status: number;
        }>(`/boards/${boardId}/onboarding`, { method: "GET" });

        if (result.status === 200) {
          const { draft_goal, refine_status, refine_questions, refine_summary } = result.data;
          if (refine_status) {
            setRefineStatus(refine_status as typeof refineStatus);
          }
          if (refine_questions) {
            setRefineQuestions(refine_questions as typeof refineQuestions);
          }
          if (refine_summary) {
            setRefineSummary(refine_summary);
          }
          if (draft_goal) {
            const goal = draft_goal as Partial<BoardOnboardingDraftUpdate>;
            if (goal && typeof goal === "object") {
              const restoredDraft: BoardOnboardingDraftUpdate = {
                project_info: (goal.project_info as BoardOnboardingDraftUpdate["project_info"]) ?? {},
                context: (goal.context as BoardOnboardingDraftUpdate["context"]) ?? {},
                lead_agent: (goal.lead_agent as BoardOnboardingDraftUpdate["lead_agent"]) ?? {},
                team_plan: (goal.team_plan as BoardOnboardingDraftUpdate["team_plan"]) ?? {},
                planning_policy: (goal.planning_policy as BoardOnboardingDraftUpdate["planning_policy"]) ?? {},
                qa_policy: (goal.qa_policy as BoardOnboardingDraftUpdate["qa_policy"]) ?? {},
                automation_policy: (goal.automation_policy as BoardOnboardingDraftUpdate["automation_policy"]) ?? {},
              };
              setDraft(restoredDraft);
              const apiRefineStatus = refine_status as typeof refineStatus | undefined;
              const restoredStep = computeCurrentStep(restoredDraft, apiRefineStatus);
              setCurrentStep(restoredStep);
            }
          }
        }
      } catch {
        // No existing onboarding session — start fresh with default empty draft
      }
    };
    void loadDraft();
  }, [boardId]);

  const totalSteps = 11;

  const canProceed = useMemo(() => {
    switch (currentStep) {
      case 1:
        return !!draft.project_info?.project_mode && !!draft.project_info?.project_stage;
      case 2:
        return !!draft.project_info?.first_milestone_type;
      case 3:
        return true;
      case 4:
        return !!draft.lead_agent?.name;
      case 5:
        if (!draft.team_plan?.provision_mode) return false;
        if (draft.team_plan.provision_mode === "selected_roles") {
          return (draft.team_plan.roles?.length ?? 0) > 0;
        }
        return true;
      case 6:
        return !!draft.planning_policy?.bootstrap_mode;
      case 7:
        return !!draft.qa_policy?.strictness;
      case 8:
        return !!draft.automation_policy?.automation_profile;
      case 9:
        return true;
      case 10:
        return true;
      case 11:
        return false;
      default:
        return false;
    }
  }, [currentStep, draft]);

  const _updateDraft = useCallback((updates: Partial<BoardOnboardingDraftUpdate>) => {
    setDraft((prev) => ({ ...prev, ...updates }));
  }, []);

  const updateProjectInfo = useCallback(
    (updates: Partial<BoardOnboardingDraftUpdate["project_info"]>) => {
      setDraft((prev) => ({
        ...prev,
        project_info: { ...prev.project_info, ...updates },
      }));
    },
    [],
  );

  const updateContext = useCallback(
    (updates: Partial<BoardOnboardingDraftUpdate["context"]>) => {
      setDraft((prev) => ({
        ...prev,
        context: { ...prev.context, ...updates },
      }));
    },
    [],
  );

  const updateLeadAgent = useCallback(
    (updates: Partial<BoardOnboardingDraftUpdate["lead_agent"]>) => {
      setDraft((prev) => ({
        ...prev,
        lead_agent: { ...prev.lead_agent, ...updates },
      }));
    },
    [],
  );

  const updateTeamPlan = useCallback(
    (updates: Partial<BoardOnboardingDraftUpdate["team_plan"]>) => {
      setDraft((prev) => ({
        ...prev,
        team_plan: { ...prev.team_plan, ...updates },
      }));
    },
    [],
  );

  const updatePlanningPolicy = useCallback(
    (updates: Partial<BoardOnboardingDraftUpdate["planning_policy"]>) => {
      setDraft((prev) => ({
        ...prev,
        planning_policy: { ...prev.planning_policy, ...updates },
      }));
    },
    [],
  );

  const updateQaPolicy = useCallback(
    (updates: Partial<BoardOnboardingDraftUpdate["qa_policy"]>) => {
      setDraft((prev) => ({
        ...prev,
        qa_policy: { ...prev.qa_policy, ...updates },
      }));
    },
    [],
  );

  const updateAutomationPolicy = useCallback(
    (updates: Partial<BoardOnboardingDraftUpdate["automation_policy"]>) => {
      setDraft((prev) => ({
        ...prev,
        automation_policy: { ...prev.automation_policy, ...updates },
      }));
    },
    [],
  );

  const saveDraft = useCallback(async (): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const result = await customFetch<{ data: unknown; status: number }>(
        `/boards/${boardId}/onboarding/draft`,
        {
          method: "PATCH",
          body: JSON.stringify(draft),
        },
      );
      if (result.status >= 400) throw new Error("Failed to save draft");
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save draft");
      return false;
    } finally {
      setLoading(false);
    }
  }, [boardId, draft]);

  const handleNext = useCallback(async () => {
    const saved = await saveDraft();
    if (saved) {
      setCurrentStep((prev) => Math.min(prev + 1, totalSteps));
    }
  }, [saveDraft, totalSteps]);

  const handleBack = useCallback(() => {
    setCurrentStep((prev) => Math.max(prev - 1, 1));
  }, []);

  const loadRefinedDraft = useCallback(async () => {
    try {
      const result = await customFetch<{
        data: { draft_goal?: Record<string, unknown> | null; status?: string; refine_status?: string; refine_questions?: unknown[]; refine_summary?: string | null };
        status: number;
      }>(`/boards/${boardId}/onboarding`, { method: "GET" });

      if (result.status === 200) {
        const { draft_goal, refine_status, refine_questions, refine_summary } = result.data;
        if (refine_status) {
          setRefineStatus(refine_status as typeof refineStatus);
        }
        if (refine_questions) {
          setRefineQuestions(refine_questions as typeof refineQuestions);
        }
        if (refine_summary) {
          setRefineSummary(refine_summary);
        }
        if (draft_goal) {
          const goal = draft_goal as Partial<BoardOnboardingDraftUpdate>;
          if (goal && typeof goal === "object") {
            setDraft({
              project_info: (goal.project_info as BoardOnboardingDraftUpdate["project_info"]) ?? {},
              context: (goal.context as BoardOnboardingDraftUpdate["context"]) ?? {},
              lead_agent: (goal.lead_agent as BoardOnboardingDraftUpdate["lead_agent"]) ?? {},
              team_plan: (goal.team_plan as BoardOnboardingDraftUpdate["team_plan"]) ?? {},
              planning_policy: (goal.planning_policy as BoardOnboardingDraftUpdate["planning_policy"]) ?? {},
              qa_policy: (goal.qa_policy as BoardOnboardingDraftUpdate["qa_policy"]) ?? {},
              automation_policy: (goal.automation_policy as BoardOnboardingDraftUpdate["automation_policy"]) ?? {},
            });
          }
        }
      }
    } catch {
      // Silently ignore — refine result will still show success state
    }
  }, [boardId]);

  const startRefinePolling = useCallback((startTime: number) => {
    const poll = async () => {
      if (Date.now() - startTime > 60000) {
        setRefineTimeout(true);
        setRefining(false);
        setRefineStatus("failed");
        return;
      }
      try {
        const resp = await customFetch<{
          data: { refine_status?: string; refine_questions?: unknown[]; refine_summary?: string | null };
          status: number;
        }>(`/boards/${boardId}/onboarding`, { method: "GET" });
        if (resp.status === 200) {
          const data = resp.data;
          const status = data.refine_status;
          if (status === "complete") {
            setRefineStatus("complete");
            setRefineSummary(data.refine_summary ?? null);
            await loadRefinedDraft();
            setRefining(false);
            setRefined(true);
          } else if (status === "questions") {
            setRefineStatus("questions");
            setRefineQuestions((data.refine_questions ?? []) as typeof refineQuestions);
            setRefineSummary(data.refine_summary ?? null);
            setRefining(false);
          } else if (status === "failed") {
            setRefineStatus("failed");
            setError("AI refinement failed. Please try again.");
            setRefining(false);
          } else {
            setTimeout(poll, 2000);
          }
        } else {
          setTimeout(poll, 2000);
        }
      } catch {
        setTimeout(poll, 2000);
      }
    };
    setTimeout(poll, 2000);
  }, [boardId, loadRefinedDraft]);

  const handleRefine = useCallback(async () => {
    setRefining(true);
    setRefineTimeout(false);
    setError(null);
    setRefineAnswers({});
    try {
      const result = await customFetch<{ data: unknown; status: number }>(
        `/boards/${boardId}/onboarding/refine`,
        { method: "POST" },
      );
      if (result.status >= 400) throw new Error("Failed to refine");

      setRefineStatus("pending");
      startRefinePolling(Date.now());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refine");
      setRefining(false);
      setRefineStatus("failed");
    }
  }, [boardId, startRefinePolling]);

  const handleSubmitRefineAnswers = useCallback(async () => {
    setError(null);
    setRefining(true);
    setRefineTimeout(false);
    try {
      for (const q of refineQuestions) {
        const answer = refineAnswers[q.id];
        if (answer) {
          await customFetch(`/boards/${boardId}/onboarding/refine-answer`, {
            method: "POST",
            body: JSON.stringify({ question_id: q.id, answer }),
          });
        }
      }
      setRefineStatus("pending");
      setRefineAnswers({});
      setRefineQuestions([]);
      startRefinePolling(Date.now());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit answers");
      setRefining(false);
    }
  }, [boardId, refineQuestions, refineAnswers, startRefinePolling]);

  const handleConfirm = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await customFetch<{ data: { board: BoardRead; bootstrap: BoardBootstrapResult }; status: number }>(
        `/boards/${boardId}/onboarding/confirm`,
        {
          method: "POST",
          body: JSON.stringify({
            objective: draft.context?.description || undefined,
          } as BoardOnboardingConfirm),
        },
      );
      if (result.status >= 400) throw new Error("Failed to confirm");
      setBootstrapResult(result.data.bootstrap);
      setConfirmedBoard(result.data.board);
      setCurrentStep(11);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to confirm");
    } finally {
      setLoading(false);
    }
  }, [boardId, draft]);

  const renderStep = () => {
    switch (currentStep) {
      case 1:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Project mode</label>
              <div className="space-y-2">
                {PROJECT_MODE_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    selected={draft.project_info?.project_mode === opt.value}
                    onSelect={() => updateProjectInfo({ project_mode: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Project stage</label>
              <div className="space-y-2">
                {PROJECT_STAGE_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    selected={draft.project_info?.project_stage === opt.value}
                    onSelect={() => updateProjectInfo({ project_stage: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
          </div>
        );

      case 2:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">First milestone type</label>
              <div className="space-y-2">
                {FIRST_MILESTONE_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    selected={draft.project_info?.first_milestone_type === opt.value}
                    onSelect={() => updateProjectInfo({ first_milestone_type: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
            {draft.project_info?.first_milestone_type === "other" && (
              <div className="space-y-2">
                <label className="text-sm font-medium text-strong">Specify milestone</label>
                <Input
                  placeholder="Describe your milestone"
                  value={draft.project_info?.first_milestone_text ?? ""}
                  onChange={(e) => updateProjectInfo({ first_milestone_text: e.target.value })}
                  disabled={loading}
                />
              </div>
            )}
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Delivery mode</label>
              <div className="space-y-2">
                {DELIVERY_MODE_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    selected={draft.project_info?.delivery_mode === opt.value}
                    onSelect={() => updateProjectInfo({ delivery_mode: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Deadline</label>
              <div className="space-y-2">
                {DEADLINE_MODE_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    selected={draft.project_info?.deadline_mode === opt.value}
                    onSelect={() => updateProjectInfo({ deadline_mode: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
            {draft.project_info?.deadline_mode === "custom" && (
              <div className="space-y-2">
                <label className="text-sm font-medium text-strong">Specify deadline</label>
                <Input
                  placeholder="e.g., End of Q2 2026"
                  value={draft.project_info?.deadline_text ?? ""}
                  onChange={(e) => updateProjectInfo({ deadline_text: e.target.value })}
                  disabled={loading}
                />
              </div>
            )}
          </div>
        );

      case 3:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Project description</label>
              <Textarea
                placeholder="Describe what this project is about"
                value={draft.context?.description ?? ""}
                onChange={(e) => updateContext({ description: e.target.value })}
                disabled={loading}
                className="min-h-[100px]"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Existing artifacts (optional)</label>
              <Textarea
                placeholder="Existing specs, docs, or code"
                value={draft.context?.existing_artifacts ?? ""}
                onChange={(e) => updateContext({ existing_artifacts: e.target.value })}
                disabled={loading}
                className="min-h-[80px]"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Constraints (optional)</label>
              <Textarea
                placeholder="Constraints, requirements, or known blockers"
                value={draft.context?.constraints ?? ""}
                onChange={(e) => updateContext({ constraints: e.target.value })}
                disabled={loading}
                className="min-h-[80px]"
              />
            </div>
          </div>
        );

      case 4:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Lead agent name</label>
              <Input
                placeholder="e.g., Ava"
                value={draft.lead_agent?.name ?? ""}
                onChange={(e) => updateLeadAgent({ name: e.target.value })}
                disabled={loading}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Autonomy level</label>
              <div className="space-y-2">
                {AUTONOMY_LEVEL_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    selected={draft.lead_agent?.autonomy_level === opt.value}
                    onSelect={() => updateLeadAgent({ autonomy_level: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Verbosity</label>
              <div className="space-y-2">
                {VERBOSITY_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    selected={draft.lead_agent?.verbosity === opt.value}
                    onSelect={() => updateLeadAgent({ verbosity: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Output format</label>
              <div className="space-y-2">
                {OUTPUT_FORMAT_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    selected={draft.lead_agent?.output_format === opt.value}
                    onSelect={() => updateLeadAgent({ output_format: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Update cadence</label>
              <div className="space-y-2">
                {UPDATE_CADENCE_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    selected={draft.lead_agent?.update_cadence === opt.value}
                    onSelect={() => updateLeadAgent({ update_cadence: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Custom instructions (optional)</label>
              <Textarea
                placeholder="Any special instructions for the lead agent"
                value={draft.lead_agent?.custom_instructions ?? ""}
                onChange={(e) => updateLeadAgent({ custom_instructions: e.target.value })}
                disabled={loading}
                className="min-h-[80px]"
              />
            </div>
          </div>
        );

      case 5:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Team provisioning</label>
              <div className="space-y-2">
                {PROVISION_MODE_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    description={opt.description}
                    selected={draft.team_plan?.provision_mode === opt.value}
                    onSelect={() => {
                      if (opt.value === "lead_only") {
                        updateTeamPlan({ provision_mode: opt.value, roles: [] });
                      } else if (opt.value === "full_team") {
                        updateTeamPlan({ provision_mode: opt.value, roles: [] });
                      } else {
                        updateTeamPlan({ provision_mode: opt.value, roles: ["developer"] });
                      }
                    }}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
            {draft.team_plan?.provision_mode === "selected_roles" && (
              <div className="space-y-2">
                <label className="text-sm font-semibold text-strong">Select roles</label>
                <div className="space-y-2">
                  {ROLE_OPTIONS.map((opt) => (
                    <CheckboxOption
                      key={opt.value}
                      value={opt.value}
                      label={opt.label}
                      checked={draft.team_plan?.roles?.includes(opt.value) ?? false}
                      onChange={(checked) => {
                        const currentRoles = draft.team_plan?.roles ?? [];
                        if (checked) {
                          updateTeamPlan({ roles: [...currentRoles, opt.value] });
                        } else {
                          updateTeamPlan({
                            roles: currentRoles.filter((r) => r !== opt.value),
                          });
                        }
                      }}
                      disabled={loading}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        );

      case 6:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Bootstrap mode</label>
              <div className="space-y-2">
                {BOOTSTRAP_MODE_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    selected={draft.planning_policy?.bootstrap_mode === opt.value}
                    onSelect={() => {
                      if (opt.value === "lead_only") {
                        updatePlanningPolicy({
                          bootstrap_mode: opt.value,
                          planner_mode: undefined,
                          generate_initial_backlog: false,
                        });
                      } else {
                        updatePlanningPolicy({
                          bootstrap_mode: opt.value,
                          planner_mode: "spec_to_backlog",
                          generate_initial_backlog: opt.value === "generate_backlog",
                        });
                      }
                    }}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
            {draft.planning_policy?.bootstrap_mode &&
              draft.planning_policy.bootstrap_mode !== "lead_only" && (
                <div className="space-y-2">
                  <label className="text-sm font-semibold text-strong">Planner mode</label>
                  <Select
                    value={draft.planning_policy?.planner_mode ?? "spec_to_backlog"}
                    onValueChange={(value: PlannerMode) => updatePlanningPolicy({ planner_mode: value })}
                    disabled={loading}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PLANNER_MODE_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
          </div>
        );

      case 7:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Process strictness</label>
              <div className="space-y-2">
                {STRICTNESS_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    description={opt.description}
                    selected={draft.qa_policy?.strictness === opt.value}
                    onSelect={() => updateQaPolicy({ strictness: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
          </div>
        );

      case 8:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-semibold text-strong">Automation profile</label>
              <div className="space-y-2">
                {AUTOMATION_PROFILE_OPTIONS.map((opt) => (
                  <RadioOption
                    key={opt.value}
                    value={opt.value}
                    label={opt.label}
                    description={opt.preview}
                    selected={draft.automation_policy?.automation_profile === opt.value}
                    onSelect={() => updateAutomationPolicy({ automation_profile: opt.value })}
                    disabled={loading}
                  />
                ))}
              </div>
            </div>
          </div>
        );

      case 9:
        return (
          <div className="space-y-6">
            <div className="rounded-xl border border-[var(--border)] p-4">
              <h3 className="font-semibold text-strong">AI Refinement</h3>
              <p className="mt-1 text-sm text-[var(--text-quiet)]">
                Let AI review and refine your configuration for better results.
              </p>
            </div>

            {refineStatus === "idle" && !refining && (
              <Button onClick={handleRefine} className="w-full">
                <RefreshCw className="mr-2 h-4 w-4" />
                Let AI refine this setup
              </Button>
            )}

            {refining && refineStatus === "pending" && (
              <Button disabled className="w-full">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                AI is reviewing your configuration...
              </Button>
            )}

            {refineTimeout && (
              <div className="space-y-3">
                <div className="rounded-xl border border-red-200 bg-red-50 p-4">
                  <p className="text-sm text-red-700">
                    Refinement timed out after 60 seconds.
                  </p>
                </div>
                <Button onClick={handleRefine} className="w-full">
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Retry refinement
                </Button>
              </div>
            )}

            {refineStatus === "failed" && !refineTimeout && (
              <div className="space-y-3">
                <div className="rounded-xl border border-red-200 bg-red-50 p-4">
                  <p className="text-sm text-red-700">AI refinement failed.</p>
                </div>
                <Button onClick={handleRefine} className="w-full">
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Retry refinement
                </Button>
              </div>
            )}

            {refineStatus === "questions" && refineQuestions.length > 0 && (
              <div className="space-y-4">
                {refineQuestions.map((q) => (
                  <div key={q.id} className="rounded-lg border border-[var(--border)] p-3">
                    <p className="text-sm font-medium text-strong">{q.question}</p>
                    {q.options && q.options.length > 0 ? (
                      <div className="mt-2 space-y-1">
                        {q.options.map((opt) => (
                          <RadioOption
                            key={opt.id}
                            value={opt.id}
                            label={opt.label}
                            selected={refineAnswers[q.id] === opt.id}
                            onSelect={() => setRefineAnswers(prev => ({ ...prev, [q.id]: opt.id }))}
                          />
                        ))}
                      </div>
                    ) : (
                      <Input
                        className="mt-2"
                        placeholder="Your answer"
                        value={refineAnswers[q.id] ?? ""}
                        onChange={(e) => setRefineAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                      />
                    )}
                  </div>
                ))}
                <Button onClick={handleSubmitRefineAnswers} className="w-full">
                  Submit answers
                </Button>
              </div>
            )}

            {refineStatus === "complete" && (
              <div className="rounded-xl border border-green-200 bg-green-50 p-4">
                <div className="flex items-center gap-2 text-green-700">
                  <Check className="h-4 w-4" />
                  <span className="font-medium">Configuration refined</span>
                </div>
                {refineSummary && <p className="mt-1 text-sm text-green-600">{refineSummary}</p>}
              </div>
            )}
          </div>
        );

      case 10:
        return (
          <div className="space-y-4">
            <h3 className="font-semibold text-strong">Review Configuration</h3>
            <div className="space-y-3">
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Project</p>
                <p className="mt-1 text-sm text-strong">
                  {humanizeProjectMode(draft.project_info?.project_mode)} —{" "}
                  {humanizeProjectStage(draft.project_info?.project_stage)}
                </p>
              </div>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Milestone &amp; Delivery</p>
                <p className="mt-1 text-sm text-strong">
                  {humanizeMilestoneType(draft.project_info?.first_milestone_type)}
                  {draft.project_info?.first_milestone_text && ` — ${draft.project_info.first_milestone_text}`}
                  {draft.project_info?.delivery_mode && ` · ${humanizeDeliveryMode(draft.project_info.delivery_mode)}`}
                  {draft.project_info?.deadline_mode && draft.project_info.deadline_mode !== "none" &&
                    ` · Deadline: ${draft.project_info.deadline_mode === "custom" ? (draft.project_info.deadline_text ?? "Custom") : draft.project_info.deadline_mode.replace(/_/g, " ")}`}
                </p>
              </div>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Lead</p>
                <p className="mt-1 text-sm text-strong">
                  {draft.lead_agent?.name || "Default lead"}
                  {draft.lead_agent?.autonomy_level && ` · ${humanizeAutonomyLevel(draft.lead_agent?.autonomy_level)}`}
                  {draft.lead_agent?.verbosity && ` · ${draft.lead_agent.verbosity} verbosity`}
                  {draft.lead_agent?.update_cadence && ` · ${draft.lead_agent.update_cadence} updates`}
                </p>
              </div>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Team</p>
                <p className="mt-1 text-sm text-strong">
                  {humanizeProvisionMode(draft.team_plan?.provision_mode)}
                  {draft.team_plan?.provision_mode === "selected_roles" && draft.team_plan?.roles?.length &&
                    ` — ${draft.team_plan.roles.map(r => r.replace(/_/g, " ")).join(", ")}`}
                </p>
              </div>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Planning</p>
                <p className="mt-1 text-sm text-strong">
                  {humanizeBootstrapMode(draft.planning_policy?.bootstrap_mode)}
                  {draft.planning_policy?.planner_mode && ` · ${humanizePlannerMode(draft.planning_policy?.planner_mode)}`}
                </p>
              </div>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">QA &amp; Process</p>
                <p className="mt-1 text-sm text-strong">
                  {humanizeStrictness(draft.qa_policy?.strictness)}
                </p>
              </div>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Automation</p>
                <p className="mt-1 text-sm text-strong">
                  {humanizeAutomationProfile(draft.automation_policy?.automation_profile)}
                </p>
              </div>
              {draft.context?.description && (
                <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                  <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Context</p>
                  <p className="mt-1 text-sm text-strong">{draft.context.description}</p>
                  {draft.context.constraints && (
                    <p className="mt-1 text-xs text-[var(--text-quiet)]">
                      Constraints: {draft.context.constraints}
                    </p>
                  )}
                </div>
              )}
              {(refined || refineStatus === "complete") && (
                <div className="rounded-lg border border-green-200 bg-green-50 p-3">
                  <p className="text-xs uppercase tracking-wide text-green-600">AI Refinement</p>
                  <p className="mt-1 text-sm text-green-700">Configuration has been refined by AI.</p>
                  {refineSummary && <p className="mt-1 text-xs text-green-600">{refineSummary}</p>}
                </div>
              )}
            </div>
          </div>
        );

      case 11:
        return (
          <div className="space-y-6">
            <div className="text-center">
              <h3 className="text-lg font-semibold text-strong">Bootstrap Complete</h3>
              <p className="mt-1 text-sm text-[var(--text-quiet)]">
                Your project board has been initialized.
              </p>
            </div>
            {bootstrapResult && (
              <div className="space-y-3">
                <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                  <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Lead</p>
                  <p className="mt-1 text-sm text-strong">
                    {humanizeLeadStatus(bootstrapResult.lead_status, bootstrapResult.lead_name)}
                  </p>
                </div>
                <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                  <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Team</p>
                  <p className="mt-1 text-sm text-strong">
                    {humanizeTeamStatus(
                      bootstrapResult.team_status,
                      bootstrapResult.team_agents_created,
                      bootstrapResult.team_created_roles ?? [],
                      bootstrapResult.team_failed_roles ?? [],
                    )}
                  </p>
                </div>
                <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                  <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Planner</p>
                  <p className="mt-1 text-sm text-strong">
                    {humanizePlannerStatus(bootstrapResult.planner_status)}
                  </p>
                </div>
                {bootstrapResult.automation_sync && (
                  <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                    <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Automation</p>
                    <p className="mt-1 text-sm text-strong">
                      {humanizeAutomationSyncStatus(
                        bootstrapResult.automation_sync.status,
                        bootstrapResult.automation_sync.agents_updated,
                      )}
                    </p>
                  </div>
                )}
                {bootstrapResult.bootstrap_summary && (
                  <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
                    <p className="text-xs uppercase tracking-wide text-[var(--text-quiet)]">Summary</p>
                    <p className="mt-1 text-sm text-strong">{bootstrapResult.bootstrap_summary}</p>
                  </div>
                )}
              </div>
            )}
            <Button onClick={() => confirmedBoard && onConfirmed(confirmedBoard)} className="w-full">
              Open project board
            </Button>
          </div>
        );

      default:
        return null;
    }
  };

  const getStepTitle = () => {
    switch (currentStep) {
      case 1:
        return "What are we building?";
      case 2:
        return "First milestone & delivery";
      case 3:
        return "Project context";
      case 4:
        return "Lead agent preferences";
      case 5:
        return "Team on startup";
      case 6:
        return "How do we start work?";
      case 7:
        return "Process strictness";
      case 8:
        return "Agent activity level";
      case 9:
        return "AI refinement";
      case 10:
        return "Review configuration";
      case 11:
        return "Bootstrap complete";
      default:
        return "";
    }
  };

  return (
    <div className="space-y-4">
      <DialogHeader>
        <DialogTitle>{getStepTitle()}</DialogTitle>
      </DialogHeader>

      {currentStep < 11 && <StepIndicator currentStep={currentStep} totalSteps={totalSteps} />}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="max-h-[400px] overflow-y-auto">{renderStep()}</div>

      {currentStep < 11 && (
        <DialogFooter>
          {currentStep > 1 && (
            <Button variant="outline" onClick={handleBack} disabled={loading} type="button">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back
            </Button>
          )}
          {currentStep < 9 && (
            <Button onClick={handleNext} disabled={!canProceed || loading} type="button">
              Next
              <ChevronRight className="ml-2 h-4 w-4" />
            </Button>
          )}
          {currentStep === 9 && (
            <Button onClick={handleNext} disabled={!canProceed || loading} type="button">
              Review
              <ChevronRight className="ml-2 h-4 w-4" />
            </Button>
          )}
          {currentStep === 10 && (
            <Button onClick={handleConfirm} disabled={!canProceed || loading} type="button">
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Bootstrapping...
                </>
              ) : (
                "Confirm & Bootstrap"
              )}
            </Button>
          )}
        </DialogFooter>
      )}
    </div>
  );
}
