"""Board onboarding endpoints for user/agent collaboration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlmodel import SQLModel, col

from app.api.deps import (
    ActorContext,
    get_board_for_user_read,
    get_board_for_user_write,
    get_board_or_404,
    require_user_auth,
    require_user_or_agent,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import get_session
from app.models.board_onboarding import BoardOnboardingSession
from app.schemas.board_onboarding import (
    BoardOnboardingAgentComplete,
    BoardOnboardingAgentUpdate,
    BoardOnboardingAnswer,
    BoardOnboardingConfirm,
    BoardOnboardingDraftUpdate,
    BoardOnboardingLeadAgentDraft,
    BoardOnboardingRead,
    BoardOnboardingReadWithRefine,
    BoardOnboardingRefineResult,
    BoardOnboardingRefineQuestion,
    BoardOnboardingStart,
    BoardOnboardingUserProfile,
    BoardOnboardingBootstrapResponse,
    BoardOnboardingTeamPlan,
    BoardOnboardingPlanningPolicy,
    BoardOnboardingQaPolicy,
    BoardOnboardingAutomationPolicy,
)
from app.schemas.boards import BoardRead
from app.services.openclaw.gateway_resolver import get_gateway_for_board
from app.services.openclaw.onboarding_service import BoardOnboardingMessagingService
from app.services.openclaw.policies import OpenClawAuthorizationPolicy
from app.services.openclaw.provisioning_db import (
    LeadAgentOptions,
)
from app.services.board_bootstrap import bootstrap_board_from_onboarding

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext
    from app.models.boards import Board

router = APIRouter(prefix="/boards/{board_id}/onboarding", tags=["board-onboarding"])
logger = get_logger(__name__)
BOARD_USER_READ_DEP = Depends(get_board_for_user_read)
BOARD_USER_WRITE_DEP = Depends(get_board_for_user_write)
BOARD_OR_404_DEP = Depends(get_board_or_404)
SESSION_DEP = Depends(get_session)
ACTOR_DEP = Depends(require_user_or_agent)
USER_AUTH_DEP = Depends(require_user_auth)


def _parse_draft_user_profile(
    draft_goal: object,
) -> BoardOnboardingUserProfile | None:
    if not isinstance(draft_goal, dict):
        return None
    raw_profile = draft_goal.get("user_profile")
    if raw_profile is None:
        return None
    try:
        return BoardOnboardingUserProfile.model_validate(raw_profile)
    except ValidationError:
        return None


def _parse_draft_lead_agent(
    draft_goal: object,
) -> BoardOnboardingLeadAgentDraft | None:
    if not isinstance(draft_goal, dict):
        return None
    raw_lead = draft_goal.get("lead_agent")
    if raw_lead is None:
        return None
    try:
        return BoardOnboardingLeadAgentDraft.model_validate(raw_lead)
    except ValidationError:
        return None


def _parse_draft_team_plan(draft_goal: object) -> BoardOnboardingTeamPlan | None:
    if not isinstance(draft_goal, dict):
        return None
    raw = draft_goal.get("team_plan")
    if raw is None:
        return None
    try:
        return BoardOnboardingTeamPlan.model_validate(raw)
    except ValidationError:
        return None


def _parse_draft_planning_policy(
    draft_goal: object,
) -> BoardOnboardingPlanningPolicy | None:
    if not isinstance(draft_goal, dict):
        return None
    raw = draft_goal.get("planning_policy")
    if raw is None:
        return None
    try:
        return BoardOnboardingPlanningPolicy.model_validate(raw)
    except ValidationError:
        return None


def _parse_draft_qa_policy(draft_goal: object) -> BoardOnboardingQaPolicy | None:
    if not isinstance(draft_goal, dict):
        return None
    raw = draft_goal.get("qa_policy")
    if raw is None:
        return None
    try:
        return BoardOnboardingQaPolicy.model_validate(raw)
    except ValidationError:
        return None


def _parse_draft_automation_policy(
    draft_goal: object,
) -> BoardOnboardingAutomationPolicy | None:
    if not isinstance(draft_goal, dict):
        return None
    raw = draft_goal.get("automation_policy")
    if raw is None:
        return None
    try:
        return BoardOnboardingAutomationPolicy.model_validate(raw)
    except ValidationError:
        return None


def _compute_refine_state(onboarding) -> dict:
    """Derive normalised refine state from onboarding.status + messages."""
    status = onboarding.status
    messages = onboarding.messages or []

    last_refine = None
    for msg in reversed(messages):
        if isinstance(msg, dict) and "refine" in msg:
            last_refine = msg
            break

    if status == "refining" and not last_refine:
        return {
            "refine_status": "pending",
            "refine_questions": [],
            "refine_summary": None,
            "refine_updated_at": None,
        }

    if last_refine:
        refine_type = last_refine.get("refine")
        ts = last_refine.get("timestamp")
        content = last_refine.get("content", "{}")
        try:
            payload = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            payload = {}

        if refine_type == "questions":
            return {
                "refine_status": "questions",
                "refine_questions": payload.get("questions", []),
                "refine_summary": payload.get("summary"),
                "refine_updated_at": ts,
            }
        if refine_type == "complete":
            return {
                "refine_status": "complete",
                "refine_questions": [],
                "refine_summary": payload.get("summary"),
                "refine_updated_at": ts,
            }
        if refine_type == "failed":
            return {
                "refine_status": "failed",
                "refine_questions": [],
                "refine_summary": None,
                "refine_updated_at": ts,
            }
        if refine_type == "refining":
            return {
                "refine_status": "pending",
                "refine_questions": [],
                "refine_summary": None,
                "refine_updated_at": ts,
            }

    return {
        "refine_status": "idle",
        "refine_questions": [],
        "refine_summary": None,
        "refine_updated_at": None,
    }


def _normalize_autonomy_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    return text.replace("_", "-")


def _is_fully_autonomous_choice(value: object) -> bool:
    token = _normalize_autonomy_token(value)
    if token is None:
        return False
    if token in {"autonomous", "fully-autonomous", "full-autonomy"}:
        return True
    return "autonom" in token and "fully" in token


def _require_approval_for_done_from_draft(draft_goal: object) -> bool:
    """Enable done-approval gate unless onboarding selected fully autonomous mode."""
    if not isinstance(draft_goal, dict):
        return True
    raw_lead = draft_goal.get("lead_agent")
    if not isinstance(raw_lead, dict):
        return True
    if _is_fully_autonomous_choice(raw_lead.get("autonomy_level")):
        return False
    raw_identity_profile = raw_lead.get("identity_profile")
    if isinstance(raw_identity_profile, dict):
        for key in ("autonomy_level", "autonomy", "mode"):
            if _is_fully_autonomous_choice(raw_identity_profile.get(key)):
                return False
    return True


def _apply_user_profile(
    auth: AuthContext,
    profile: BoardOnboardingUserProfile | None,
) -> bool:
    if auth.user is None or profile is None:
        return False

    changed = False
    if profile.preferred_name is not None:
        auth.user.preferred_name = profile.preferred_name
        changed = True
    if profile.pronouns is not None:
        auth.user.pronouns = profile.pronouns
        changed = True
    if profile.timezone is not None:
        auth.user.timezone = profile.timezone
        changed = True
    if profile.notes is not None:
        auth.user.notes = profile.notes
        changed = True
    if profile.context is not None:
        auth.user.context = profile.context
        changed = True
    return changed


def _lead_agent_options(
    lead_agent: BoardOnboardingLeadAgentDraft | None,
) -> LeadAgentOptions:
    if lead_agent is None:
        return LeadAgentOptions(action="provision")

    lead_identity_profile: dict[str, str] = {}
    if lead_agent.identity_profile:
        lead_identity_profile.update(lead_agent.identity_profile)
    if lead_agent.autonomy_level:
        lead_identity_profile["autonomy_level"] = lead_agent.autonomy_level
    if lead_agent.verbosity:
        lead_identity_profile["verbosity"] = lead_agent.verbosity
    if lead_agent.output_format:
        lead_identity_profile["output_format"] = lead_agent.output_format
    if lead_agent.update_cadence:
        lead_identity_profile["update_cadence"] = lead_agent.update_cadence
    if lead_agent.custom_instructions:
        lead_identity_profile["custom_instructions"] = lead_agent.custom_instructions

    return LeadAgentOptions(
        agent_name=lead_agent.name,
        identity_profile=lead_identity_profile or None,
        action="provision",
    )


@router.get("", response_model=BoardOnboardingReadWithRefine)
async def get_onboarding(
    board: Board = BOARD_USER_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardOnboardingReadWithRefine:
    """Get the latest onboarding session for a board."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    refine_state = _compute_refine_state(onboarding)
    result = BoardOnboardingReadWithRefine.model_validate(onboarding, from_attributes=True)
    result.refine_status = refine_state["refine_status"]
    result.refine_questions = [
        BoardOnboardingRefineQuestion.model_validate(q)
        for q in refine_state["refine_questions"]
    ]
    result.refine_summary = refine_state["refine_summary"]
    result.refine_updated_at = refine_state["refine_updated_at"]
    return result


@router.post("/start", response_model=BoardOnboardingRead)
async def start_onboarding(
    _payload: BoardOnboardingStart,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardOnboardingSession:
    """Start onboarding and send instructions to the gateway agent."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .filter(col(BoardOnboardingSession.status) == "active")
        .first(session)
    )
    if onboarding:
        last_user_content: str | None = None
        messages = onboarding.messages or []
        if messages:
            last_message = messages[-1]
            if isinstance(last_message, dict):
                last_role = last_message.get("role")
                content = last_message.get("content")
                if last_role == "user" and isinstance(content, str) and content:
                    last_user_content = content

        if last_user_content:
            # Retrigger the agent when the session is waiting on a response.
            dispatcher = BoardOnboardingMessagingService(session)
            await dispatcher.dispatch_answer(
                board=board,
                onboarding=onboarding,
                answer_text=last_user_content,
                correlation_id=f"onboarding.resume:{board.id}:{onboarding.id}",
            )
            onboarding.updated_at = utcnow()
            session.add(onboarding)
            await session.commit()
            await session.refresh(onboarding)
        return onboarding

    dispatcher = BoardOnboardingMessagingService(session)
    base_url = settings.base_url
    prompt = (
        "PROJECT BOOTSTRAP ONBOARDING\n\n"
        f"Board Name: {board.name}\n"
        f"Board Description: {board.description or '(not provided)'}\n"
        "You are the gateway agent helping bootstrap a new project. "
        "Ask the user 8-10 focused questions total to gather everything needed "
        "for a full project setup (board goal, lead agent, team shape, "
        "planning, QA, and automation).\n"
        "QUESTION FLOW:\n"
        "1. Board goal (1-3 questions): what are we building, what does success look like, when?\n"
        "2. Lead agent (1-2 questions): unique name for the board lead, preferred working style.\n"
        "3. Team shape (1 question): lead-only vs. full team now.\n"
        "4. Planning (1 question): generate initial backlog or start with empty board.\n"
        "5. QA & pipeline (1 question): strict validation or flexible/more autonomous.\n"
        "6. Automation (1 question): how active should agents be (heartbeat frequency).\n"
        "7. Final: anything else?\n"
        "- ALWAYS include a final question (and only once): 'Anything else we should know?'\n"
        "  This MUST be the last question.\n"
        "  Provide an option like 'Yes (I\\'ll type it)' so they can enter free-text.\n"
        "- Do NOT ask for additional context on earlier questions.\n"
        "- Only include a free-text option on earlier questions if a typed answer is necessary;\n"
        '  when you do, make the option label include "I\'ll type it" '
        "(e.g., 'Other (I\\'ll type it)').\n"
        '- If the user sends an "Additional context" message later, incorporate '
        "it and resend status=complete to update the draft (until the user confirms).\n"
        "Do NOT respond in OpenClaw chat.\n"
        "All onboarding responses MUST be sent to Mission Control via API.\n"
        f"Mission Control base URL: {base_url}\n"
        "Use the AUTH_TOKEN from USER.md or TOOLS.md and pass it as X-Agent-Token.\n"
        "Onboarding response endpoint:\n"
        f"POST {base_url}/api/v1/agent/boards/{board.id}/onboarding\n"
        "QUESTION example (send JSON body exactly as shown):\n"
        f'curl -s -X POST "{base_url}/api/v1/agent/boards/{board.id}/onboarding" '
        '-H "X-Agent-Token: $AUTH_TOKEN" '
        '-H "Content-Type: application/json" '
        '-d \'{"question":"...","options":[{"id":"1","label":"..."},'
        '{"id":"2","label":"..."}]}\'\n'
        "COMPLETION example (send JSON body exactly as shown):\n"
        f'curl -s -X POST "{base_url}/api/v1/agent/boards/{board.id}/onboarding" '
        '-H "X-Agent-Token: $AUTH_TOKEN" '
        '-H "Content-Type: application/json" '
        '-d \'{"status":"complete","board_type":"goal","objective":"...",'
        '"success_metrics":{"metric":"...","target":"..."},'
        '"target_date":"YYYY-MM-DD",'
        '"user_profile":{"preferred_name":"...","pronouns":"...",'
        '"timezone":"...","notes":"...","context":"..."},'
        '"lead_agent":{"name":"Ava","identity_profile":{"role":"Board Lead",'
        '"communication_style":"structured, decisive, prioritizes quality","emoji":"🎯",'
        '"purpose":"Orchestrate project development, manage backlog, enforce pipeline."},'
        '"autonomy_level":"balanced","verbosity":"concise",'
        '"output_format":"bullets","update_cadence":"daily",'
        '"custom_instructions":"..."},'
        '"team_plan":{"roles":["board_lead","developer","qa_engineer"],'
        '"provision_full_team":true,"optional_roles":["technical_writer","ops_guardian"],'
        '"notes":"..."},'
        '"planning_policy":{"generate_initial_backlog":true,'
        '"planner_mode":"spec_to_backlog","bootstrap_after_confirm":true},'
        '"qa_policy":{"level":"standard","run_smoke_after_build":true,'
        '"require_approval_for_done":true},'
        '"automation_policy":{"online_every_seconds":300,"idle_every_seconds":1800,'
        '"dormant_every_seconds":21600,"wake_on_approvals":true,'
        '"wake_on_review_queue":true,"allow_assist_mode_when_no_tasks":false}}\'\n'
        "ENUMS:\n"
        "- board_type: goal | general\n"
        "- lead_agent.autonomy_level: ask_first | balanced | autonomous\n"
        "- lead_agent.verbosity: concise | balanced | detailed\n"
        "- lead_agent.output_format: bullets | mixed | narrative\n"
        "- lead_agent.update_cadence: asap | hourly | daily | weekly\n"
        "- team_plan.roles: board_lead | developer | qa_engineer | technical_writer | ops_guardian\n"
        "- team_plan.provision_full_team: true | false\n"
        "- planning_policy.generate_initial_backlog: true | false\n"
        "- planning_policy.planner_mode: spec_to_backlog | empty_board\n"
        "- planning_policy.bootstrap_after_confirm: true | false\n"
        "- qa_policy.level: smoke | standard | strict\n"
        "- qa_policy.require_approval_for_done: true | false\n"
        "- automation_policy.online_every_seconds: 60 | 120 | 300 | 600\n"
        "- automation_policy.idle_every_seconds: 600 | 1800 | 3600\n"
        "- automation_policy.dormant_every_seconds: 3600 | 10800 | 21600\n"
        "QUESTION FORMAT (one question per response, no arrays, no markdown, "
        "no extra text):\n"
        '{"question":"...","options":[{"id":"1","label":"..."},{"id":"2","label":"..."}]}\n'
        "Do NOT wrap questions in a list. Do NOT add commentary.\n"
        "When you have enough info, send one final response with status=complete.\n"
        "The completion payload must include board_type. If board_type=goal, "
        "include objective + success_metrics.\n"
        "Include user_profile + lead_agent to configure the board lead's working style.\n"
        "Include team_plan, planning_policy, qa_policy, and automation_policy "
        "to configure the project operating model.\n"
        "All policy sections are optional; defaults will be used if omitted.\n"
    )

    session_key = await dispatcher.dispatch_start_prompt(
        board=board,
        prompt=prompt,
        correlation_id=f"onboarding.start:{board.id}",
    )

    onboarding = BoardOnboardingSession(
        board_id=board.id,
        session_key=session_key,
        status="active",
        messages=[
            {"role": "user", "content": prompt, "timestamp": utcnow().isoformat()},
        ],
    )
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)
    return onboarding


@router.post("/answer", response_model=BoardOnboardingRead)
async def answer_onboarding(
    payload: BoardOnboardingAnswer,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardOnboardingSession:
    """Send a user onboarding answer to the gateway agent."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    dispatcher = BoardOnboardingMessagingService(session)
    answer_text = payload.answer
    if payload.other_text:
        answer_text = f"{payload.answer}: {payload.other_text}"

    messages = list(onboarding.messages or [])
    messages.append(
        {"role": "user", "content": answer_text, "timestamp": utcnow().isoformat()},
    )

    await dispatcher.dispatch_answer(
        board=board,
        onboarding=onboarding,
        answer_text=answer_text,
        correlation_id=f"onboarding.answer:{board.id}:{onboarding.id}",
    )

    onboarding.messages = messages
    onboarding.updated_at = utcnow()
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)
    return onboarding


@router.post("/agent", response_model=BoardOnboardingRead)
async def agent_onboarding_update(
    payload: BoardOnboardingAgentUpdate,
    board: Board = BOARD_OR_404_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> BoardOnboardingSession:
    """Store onboarding updates submitted by the gateway agent."""
    if actor.actor_type != "agent" or actor.agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    agent = actor.agent
    OpenClawAuthorizationPolicy.require_gateway_scoped_actor(actor_agent=agent)

    gateway = await get_gateway_for_board(session, board)
    if gateway is not None:
        OpenClawAuthorizationPolicy.require_gateway_main_actor_binding(
            actor_agent=agent,
            gateway=gateway,
        )

    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if onboarding.status == "confirmed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)

    messages = list(onboarding.messages or [])
    now = utcnow().isoformat()
    payload_text = payload.model_dump_json(exclude_none=True)
    payload_data = payload.model_dump(mode="json", exclude_none=True)
    logger.info(
        "onboarding.agent.update board_id=%s agent_id=%s payload=%s",
        board.id,
        agent.id,
        payload_text,
    )
    if isinstance(payload, BoardOnboardingAgentComplete):
        onboarding.draft_goal = payload_data
        onboarding.status = "completed"
        messages.append(
            {"role": "assistant", "content": payload_text, "timestamp": now},
        )
    else:
        messages.append(
            {"role": "assistant", "content": payload_text, "timestamp": now},
        )

    onboarding.messages = messages
    onboarding.updated_at = utcnow()
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)
    logger.info(
        "onboarding.agent.update stored board_id=%s messages_count=%s status=%s",
        board.id,
        len(onboarding.messages or []),
        onboarding.status,
    )
    return onboarding


@router.patch("/draft", response_model=BoardOnboardingRead)
async def update_draft(
    payload: BoardOnboardingDraftUpdate,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardOnboardingSession:
    """Save structured wizard draft incrementally without calling gateway."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        onboarding = BoardOnboardingSession(
            board_id=board.id,
            session_key=f"wizard-draft:{board.id}",
            status="active",
            messages=[],
        )
        session.add(onboarding)
        await session.flush()
    elif onboarding.status == "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update draft on a confirmed onboarding.",
        )

    existing_draft: dict[str, object] = dict(onboarding.draft_goal or {})

    if payload.board_type is not None:
        existing_draft["board_type"] = payload.board_type
    if payload.objective is not None:
        existing_draft["objective"] = payload.objective
    if payload.success_metrics is not None:
        existing_draft["success_metrics"] = payload.success_metrics
    if payload.target_date is not None:
        existing_draft["target_date"] = payload.target_date.isoformat()
    if payload.user_profile is not None:
        existing_draft["user_profile"] = payload.user_profile.model_dump(
            mode="json", exclude_none=True
        )
    if payload.project_info is not None:
        existing_draft["project_info"] = payload.project_info.model_dump(
            mode="json", exclude_none=True
        )
    if payload.context is not None:
        existing_draft["context"] = payload.context.model_dump(
            mode="json", exclude_none=True
        )
    if payload.lead_agent is not None:
        existing_draft["lead_agent"] = payload.lead_agent.model_dump(
            mode="json", exclude_none=True
        )
    if payload.team_plan is not None:
        existing_draft["team_plan"] = payload.team_plan.model_dump(
            mode="json", exclude_none=True
        )
    if payload.planning_policy is not None:
        existing_draft["planning_policy"] = payload.planning_policy.model_dump(
            mode="json", exclude_none=True
        )
    if payload.qa_policy is not None:
        existing_draft["qa_policy"] = payload.qa_policy.model_dump(
            mode="json", exclude_none=True
        )
    if payload.automation_policy is not None:
        existing_draft["automation_policy"] = payload.automation_policy.model_dump(
            mode="json", exclude_none=True
        )

    onboarding.draft_goal = existing_draft
    onboarding.updated_at = utcnow()
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)
    return onboarding


@router.post("/refine", response_model=BoardOnboardingReadWithRefine)
async def refine_onboarding(
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardOnboardingReadWithRefine:
    """Trigger AI refinement of the current structured draft."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if onboarding.status == "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot refine a confirmed onboarding.",
        )

    if not onboarding.draft_goal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No draft to refine. Complete wizard steps first.",
        )

    dispatcher = BoardOnboardingMessagingService(session)
    await dispatcher.dispatch_refine_prompt(
        board=board,
        draft=onboarding.draft_goal,
        correlation_id=f"onboarding.refine:{board.id}:{onboarding.id}",
    )

    messages = list(onboarding.messages or [])
    messages.append(
        {
            "role": "user",
            "content": "[Wizard] Requested AI refinement",
            "timestamp": utcnow().isoformat(),
        }
    )

    onboarding.status = "refining"
    onboarding.messages = messages
    onboarding.updated_at = utcnow()
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)

    refine_state = _compute_refine_state(onboarding)
    result = BoardOnboardingReadWithRefine.model_validate(onboarding, from_attributes=True)
    result.refine_status = refine_state["refine_status"]
    result.refine_questions = [
        BoardOnboardingRefineQuestion.model_validate(q)
        for q in refine_state["refine_questions"]
    ]
    result.refine_summary = refine_state["refine_summary"]
    result.refine_updated_at = refine_state["refine_updated_at"]
    return result


@router.post("/agent/refine-result", response_model=BoardOnboardingReadWithRefine)
async def agent_refine_result(
    payload: BoardOnboardingRefineResult,
    board: Board = BOARD_OR_404_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> BoardOnboardingReadWithRefine:
    """Store AI refinement result submitted by the gateway agent."""
    if actor.actor_type != "agent" or actor.agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    agent = actor.agent
    OpenClawAuthorizationPolicy.require_gateway_scoped_actor(actor_agent=agent)

    gateway = await get_gateway_for_board(session, board)
    if gateway is not None:
        OpenClawAuthorizationPolicy.require_gateway_main_actor_binding(
            actor_agent=agent,
            gateway=gateway,
        )

    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if onboarding.status == "confirmed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)

    messages = list(onboarding.messages or [])
    payload_text = payload.model_dump_json(exclude_none=True)
    now = utcnow().isoformat()

    if payload.status == "complete" and payload.draft is not None:
        if onboarding.draft_goal is None:
            onboarding.draft_goal = {}
        existing = dict(onboarding.draft_goal)
        updated = payload.draft.model_dump(exclude_none=True)
        existing.update(updated)
        onboarding.draft_goal = existing
        onboarding.status = "completed"
        messages.append(
            {
                "role": "assistant",
                "content": payload_text,
                "timestamp": now,
                "refine": "complete",
            }
        )
    elif payload.status == "questions":
        messages.append(
            {
                "role": "assistant",
                "content": payload_text,
                "timestamp": now,
                "refine": "questions",
            }
        )
        if onboarding.status == "refining":
            onboarding.status = "active"
    else:
        messages.append(
            {
                "role": "assistant",
                "content": payload_text,
                "timestamp": now,
                "refine": "failed",
            }
        )
        if onboarding.status == "refining":
            onboarding.status = "active"

    onboarding.messages = messages
    onboarding.updated_at = utcnow()
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)

    refine_state = _compute_refine_state(onboarding)
    result = BoardOnboardingReadWithRefine.model_validate(onboarding, from_attributes=True)
    result.refine_status = refine_state["refine_status"]
    result.refine_questions = [
        BoardOnboardingRefineQuestion.model_validate(q)
        for q in refine_state["refine_questions"]
    ]
    result.refine_summary = refine_state["refine_summary"]
    result.refine_updated_at = refine_state["refine_updated_at"]
    return result


class BoardOnboardingRefineAnswer(SQLModel):
    """User answer to a single refine clarification question."""

    question_id: str
    answer: str
    other_text: str | None = None


def _extract_current_refine_questions(messages: list) -> list[dict]:
    """Return the list of refine questions from the last refine:questions message."""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("refine") == "questions":
            content = msg.get("content", "{}")
            try:
                payload = json.loads(content) if isinstance(content, str) else content
            except (json.JSONDecodeError, TypeError):
                payload = {}
            return payload.get("questions", [])
    return []


def _extract_refine_answers(messages: list) -> dict[str, dict[str, str]]:
    """Collect refine answers from messages.

    Priority order:
    1. Structured dict — current format with question_id/answer/other_text.
    2. Legacy flat fields — refine_answer_value + refine_answer_other_text.
    3. Legacy content parsing — backward-compat fallback for old sessions.
    """
    answers: dict[str, dict[str, str]] = {}

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        raw = msg.get("refine_answer")

        # 1. Structured format (current)
        if isinstance(raw, dict):
            question_id = str(raw.get("question_id", "")).strip()
            if question_id:
                answers[question_id] = {
                    "answer": str(raw.get("answer", "")).strip(),
                    "other_text": str(raw.get("other_text", "")).strip(),
                }
            continue

        # 2. Legacy flat fields
        if isinstance(raw, str) and raw:
            flat_answer = str(msg.get("refine_answer_value", "")).strip()
            flat_other = str(msg.get("refine_answer_other_text", "")).strip()
            if flat_answer or flat_other:
                answers[raw] = {
                    "answer": flat_answer,
                    "other_text": flat_other,
                }
                continue

        # 3. Legacy content parsing fallback
        content = msg.get("content", "")
        if isinstance(raw, str) and raw and isinstance(content, str):
            prefix = f"[Wizard] Refine answer to {raw}: "
            if content.startswith(prefix):
                rest = content[len(prefix):]
                answer_text = rest
                other_text = ""
                marker = " (other: "
                if marker in rest:
                    idx = rest.index(marker)
                    answer_text = rest[:idx]
                    tail = rest[idx + len(marker):]
                    other_text = tail[:-1] if tail.endswith(")") else tail
                answers[raw] = {
                    "answer": answer_text.strip(),
                    "other_text": other_text.strip(),
                }

    return answers


def _is_other_like_option(option: dict[str, object]) -> bool:
    """Check if an option represents an 'other/custom/free_text' choice by id or label."""
    opt_id = str(option.get("id", "")).strip().lower()
    label = str(option.get("label", "")).strip().lower()
    return (
        opt_id in {"other", "custom", "free_text"}
        or "other" in label
        or "i'll type it" in label
        or "free text" in label
        or "custom" in label
    )


def _validate_refine_answer(
    questions: list[dict],
    question_id: str,
    answer: str,
    other_text: str | None = None,
) -> None:
    """Validate refine answer: question exists, option valid, other_text required when needed."""
    target = None
    for q in questions:
        if isinstance(q, dict) and q.get("id") == question_id:
            target = q
            break

    if target is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown refine question: {question_id}",
        )

    options = target.get("options", [])
    if isinstance(options, list) and len(options) > 0:
        valid_ids = {
            str(opt.get("id"))
            for opt in options
            if isinstance(opt, dict) and "id" in opt
        }
        if answer not in valid_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Answer '{answer}' is not a valid option for question {question_id}",
            )
        selected_option = next(
            (opt for opt in options if str(opt.get("id")) == answer),
            None,
        )
        if selected_option is not None and _is_other_like_option(selected_option):
            if not (other_text or "").strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Question '{question_id}' requires additional text when '{answer}' is selected",
                )
    elif not answer.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Question '{question_id}' requires a non-empty answer",
        )


@router.post("/refine-answer", response_model=BoardOnboardingReadWithRefine)
async def answer_refine_question(
    payload: BoardOnboardingRefineAnswer,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> BoardOnboardingReadWithRefine:
    """Submit an answer to a refine clarification question and resume AI refinement."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if onboarding.status == "confirmed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)

    messages = list(onboarding.messages or [])
    current_questions = _extract_current_refine_questions(messages)
    _validate_refine_answer(current_questions, payload.question_id, payload.answer, payload.other_text)

    messages.append(
        {
            "role": "user",
            "content": f"[Wizard] Refine answer to {payload.question_id}: {payload.answer}"
                       + (f" (other: {payload.other_text})" if payload.other_text else ""),
            "timestamp": utcnow().isoformat(),
            "refine_answer": {
                "question_id": payload.question_id,
                "answer": payload.answer,
                "other_text": payload.other_text or "",
            },
        }
    )

    onboarding.messages = messages
    onboarding.status = "refining"
    onboarding.updated_at = utcnow()
    session.add(onboarding)
    await session.commit()
    await session.refresh(onboarding)

    if not onboarding.draft_goal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No draft to refine. Complete wizard steps first.",
        )

    dispatcher = BoardOnboardingMessagingService(session)
    refine_answers = _extract_refine_answers(messages)
    await dispatcher.dispatch_refine_prompt(
        board=board,
        draft=cast(dict[str, Any], onboarding.draft_goal),
        correlation_id=f"onboarding.refine-answer:{board.id}:{onboarding.id}",
        refine_answers=refine_answers if refine_answers else None,
        refine_questions=current_questions if current_questions else None,
    )

    refine_state = _compute_refine_state(onboarding)
    result = BoardOnboardingReadWithRefine.model_validate(onboarding, from_attributes=True)
    result.refine_status = refine_state["refine_status"]
    result.refine_questions = [
        BoardOnboardingRefineQuestion.model_validate(q)
        for q in refine_state["refine_questions"]
    ]
    result.refine_summary = refine_state["refine_summary"]
    result.refine_updated_at = refine_state["refine_updated_at"]
    return result


@router.post("/confirm", response_model=BoardOnboardingBootstrapResponse)
async def confirm_onboarding(
    payload: BoardOnboardingConfirm,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = USER_AUTH_DEP,
) -> BoardOnboardingBootstrapResponse:
    """Confirm onboarding and bootstrap the board (lead + optional team + planner + automation)."""
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    user_profile = _parse_draft_user_profile(onboarding.draft_goal)
    if _apply_user_profile(auth, user_profile) and auth.user is not None:
        session.add(auth.user)

    draft: BoardOnboardingAgentComplete | None = None
    if onboarding.draft_goal is not None:
        try:
            draft = BoardOnboardingAgentComplete.model_validate(onboarding.draft_goal)
        except ValidationError:
            pass

    project_info = getattr(draft, "project_info", None) if draft else None
    context = getattr(draft, "context", None) if draft else None

    human_readable_objective = None
    if context and context.description:
        human_readable_objective = context.description
    elif payload.objective:
        human_readable_objective = payload.objective
    if human_readable_objective:
        board.objective = human_readable_objective

    if (
        project_info
        and project_info.deadline_mode
        and project_info.deadline_mode != "none"
    ):
        board.target_date = payload.target_date
    elif payload.target_date:
        board.target_date = payload.target_date
    if payload.board_type is not None:
        board.board_type = payload.board_type
    if payload.success_metrics is not None:
        board.success_metrics = payload.success_metrics
    board.goal_confirmed = True
    board.goal_source = "lead_agent_onboarding"

    onboarding.status = "confirmed"
    onboarding.updated_at = utcnow()

    bootstrap_result = await bootstrap_board_from_onboarding(
        session=session,
        board=board,
        draft=draft,
        user=auth.user,
    )

    session.add(board)
    session.add(onboarding)
    await session.commit()
    await session.refresh(board)

    return BoardOnboardingBootstrapResponse(
        board=BoardRead.model_validate(board, from_attributes=True),
        bootstrap=bootstrap_result,
    )
