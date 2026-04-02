"""Board bootstrap orchestration: wires onboarding confirm to lead/team/planner/automation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from app.models.agents import Agent
from app.models.boards import Board
from app.models.planner_outputs import PlannerOutput
from app.schemas.board_onboarding import (
    AUTOMATION_PROFILE_DEFAULTS,
    QA_STRICTNESS_DEFAULTS,
    BoardAutomationSyncResultData,
    BoardBootstrapResult,
    BoardOnboardingAgentComplete,
    BoardOnboardingAutomationPolicy,
    BoardOnboardingPlanningPolicy,
    BoardOnboardingQaPolicy,
)
from app.services.agent_provisioning import (
    AgentProvisioningService,
    TeamProvisionResult,
)
from app.services.board_automation import (
    BoardAutomationSyncResult,
    sync_board_automation_policy,
)
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.provisioning_db import (
    LeadAgentOptions,
    LeadAgentRequest,
    OpenClawProvisioningService,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.users import User


def _automation_config_from_policy(
    policy: BoardOnboardingAutomationPolicy | None,
) -> dict[str, Any] | None:
    if policy is None:
        return None
    result: dict[str, Any] = {}
    if (
        policy.automation_profile
        and policy.automation_profile in AUTOMATION_PROFILE_DEFAULTS
    ):
        result.update(AUTOMATION_PROFILE_DEFAULTS[policy.automation_profile])
    if policy.online_every_seconds is not None:
        result["online_every_seconds"] = policy.online_every_seconds
    if policy.idle_every_seconds is not None:
        result["idle_every_seconds"] = policy.idle_every_seconds
    if policy.dormant_every_seconds is not None:
        result["dormant_every_seconds"] = policy.dormant_every_seconds
    if policy.wake_on_approvals is not None:
        result["wake_on_approvals"] = policy.wake_on_approvals
    if policy.wake_on_review_queue is not None:
        result["wake_on_review_queue"] = policy.wake_on_review_queue
    if policy.allow_assist_mode_when_no_tasks is not None:
        result["allow_assist_mode"] = policy.allow_assist_mode_when_no_tasks
    return result or None


def _apply_qa_strictness(
    qa_policy: BoardOnboardingQaPolicy | None,
) -> BoardOnboardingQaPolicy:
    if qa_policy is None:
        return BoardOnboardingQaPolicy()
    if qa_policy.strictness and qa_policy.strictness in QA_STRICTNESS_DEFAULTS:
        defaults = QA_STRICTNESS_DEFAULTS[qa_policy.strictness]
        result = BoardOnboardingQaPolicy(
            strictness=qa_policy.strictness,
            level=qa_policy.level or str(defaults.get("level", "standard")),
            run_smoke_after_build=qa_policy.run_smoke_after_build,
            require_approval_for_done=qa_policy.require_approval_for_done
            if qa_policy.require_approval_for_done is not None
            else bool(defaults.get("require_approval_for_done", True)),
        )
        return result
    return qa_policy


def _lead_options_from_draft(
    draft: BoardOnboardingAgentComplete | None,
) -> LeadAgentOptions:
    if draft is None or draft.lead_agent is None:
        return LeadAgentOptions(action="provision")
    lead = draft.lead_agent
    identity_profile: dict[str, str] = {}
    if lead.identity_profile:
        identity_profile.update(lead.identity_profile)
    if lead.autonomy_level:
        identity_profile["autonomy_level"] = lead.autonomy_level
    if lead.verbosity:
        identity_profile["verbosity"] = lead.verbosity
    if lead.output_format:
        identity_profile["output_format"] = lead.output_format
    if lead.update_cadence:
        identity_profile["update_cadence"] = lead.update_cadence

    heartbeat_config: dict[str, Any] | None = None
    if draft.automation_policy is not None:
        ap = draft.automation_policy
        hb: dict[str, Any] = {}
        if ap.online_every_seconds is not None:
            hb["online_every_seconds"] = ap.online_every_seconds
        if ap.idle_every_seconds is not None:
            hb["idle_every_seconds"] = ap.idle_every_seconds
        if ap.dormant_every_seconds is not None:
            hb["dormant_every_seconds"] = ap.dormant_every_seconds
        if hb:
            heartbeat_config = hb

    return LeadAgentOptions(
        agent_name=lead.name,
        identity_profile=identity_profile or None,
        heartbeat_config=heartbeat_config,
        action="provision",
    )


def _require_approval_for_done_from_qa(
    qa_policy: BoardOnboardingQaPolicy | None,
) -> bool:
    if qa_policy is None:
        return True
    if qa_policy.require_approval_for_done is not None:
        return qa_policy.require_approval_for_done
    return True


async def _start_planner_bootstrap(
    session: AsyncSession,
    board: Board,
    planning_policy: BoardOnboardingPlanningPolicy | None,
) -> PlannerOutput | None:
    if planning_policy is None:
        return None
    if (
        not planning_policy.generate_initial_backlog
        and not planning_policy.bootstrap_after_confirm
    ):
        return None
    output = PlannerOutput(
        board_id=board.id,
        artifact_id=None,
        status="draft",
        epics=[],
        tasks=[],
        parallelism_groups=[],
    )
    session.add(output)
    await session.flush()
    return output


def _sync_result_to_data(
    result: BoardAutomationSyncResult,
) -> BoardAutomationSyncResultData:
    return BoardAutomationSyncResultData(
        status=result.status,
        agents_updated=result.agents_updated,
        gateway_syncs_succeeded=result.gateway_syncs_succeeded,
        gateway_syncs_failed=result.gateway_syncs_failed,
        failed_agent_ids=list(result.failed_agent_ids),
    )


async def bootstrap_board_from_onboarding(
    session: AsyncSession,
    board: Board,
    draft: BoardOnboardingAgentComplete | None,
    user: User | None,
) -> BoardBootstrapResult:
    """Bootstrap a board from an onboarding draft.

    Orchestrates: lead creation/update, optional team provision,
    optional planner bootstrap, and automation policy sync.
    """
    result = BoardBootstrapResult()

    automation_policy = getattr(draft, "automation_policy", None) if draft else None
    team_plan = getattr(draft, "team_plan", None) if draft else None
    planning_policy = getattr(draft, "planning_policy", None) if draft else None
    raw_qa_policy = getattr(draft, "qa_policy", None) if draft else None
    qa_policy = _apply_qa_strictness(raw_qa_policy)

    if board.automation_config is None and automation_policy is not None:
        config = _automation_config_from_policy(automation_policy)
        if config:
            board.automation_config = config

    board.require_approval_for_done = _require_approval_for_done_from_qa(qa_policy)

    gateway_dispatch = GatewayDispatchService(session)
    gateway = None
    gateway_config: GatewayClientConfig | None = None
    try:
        (
            gateway,
            gateway_config,
        ) = await gateway_dispatch.require_gateway_config_for_board(board)
    except Exception:
        gateway = None

    if gateway is not None:
        provisioning = OpenClawProvisioningService(session)
        lead_options = _lead_options_from_draft(draft)
        existing_lead = (
            await session.exec(
                select(Agent)
                .where(Agent.board_id == board.id)
                .where(col(Agent.is_board_lead).is_(True)),
            )
        ).first()

        if existing_lead:
            result.lead_status = "updated"
        else:
            result.lead_status = "created"

        if gateway_config is not None:
            req = LeadAgentRequest(
                board=board,
                gateway=gateway,
                config=gateway_config,
                user=user,
                options=lead_options,
            )
            agent, _created = await provisioning.ensure_board_lead_agent(request=req)
            result.lead_agent_id = agent.id
            result.lead_name = agent.name

    _should_provision = (
        team_plan is not None
        and team_plan.provision_mode in ("selected_roles", "full_team")
        and gateway is not None
    )
    if _should_provision:
        roles = team_plan.roles or None
        provision_service = AgentProvisioningService(session)
        team_result: TeamProvisionResult = await provision_service.provision_full_team(
            board_id=board.id,
            gateway_id=gateway.id,
            roles=roles,
        )
        result.team_agents_created = team_result.created
        result.team_created_roles = list(team_result.created_roles)
        result.team_skipped_roles = list(team_result.skipped_roles)
        result.team_failed_roles = [str(e.get("role", "")) for e in team_result.errors]

        if team_result.created > 0 and not team_result.errors:
            result.team_status = "provisioned"
        elif (
            team_result.created == 0
            and not team_result.errors
            and team_result.skipped_roles
        ):
            result.team_status = "already_provisioned"
        elif team_result.created > 0 and team_result.errors:
            result.team_status = "partial_failure"
        else:
            result.team_status = "failed"
    elif team_plan is not None and team_plan.provision_mode == "lead_only":
        result.team_status = "not_requested"
    else:
        result.team_status = "not_requested"

    if planning_policy is not None and (
        planning_policy.generate_initial_backlog
        or planning_policy.bootstrap_after_confirm
    ):
        output = await _start_planner_bootstrap(session, board, planning_policy)
        result.planner_status = "queued"
        if output is not None:
            result.planner_output_id = output.id
    else:
        result.planner_status = "not_requested"

    if board.automation_config:
        sync_result = await sync_board_automation_policy(session, board)
        result.automation_sync = _sync_result_to_data(sync_result)
    else:
        result.automation_sync = BoardAutomationSyncResultData(status="not_run")

    return result
