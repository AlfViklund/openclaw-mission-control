"""Board onboarding gateway messaging service."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import TRACE_LEVEL
from app.models.board_onboarding import BoardOnboardingSession
from app.models.boards import Board
from app.services.openclaw.coordination_service import AbstractGatewayMessagingService
from app.services.openclaw.exceptions import (
    GatewayOperation,
    map_gateway_error_to_http_exception,
)
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.shared import GatewayAgentIdentity


class BoardOnboardingMessagingService(AbstractGatewayMessagingService):
    """Gateway message dispatch helpers for onboarding routes."""

    async def dispatch_start_prompt(
        self,
        *,
        board: Board,
        prompt: str,
        correlation_id: str | None = None,
    ) -> str:
        trace_id = GatewayDispatchService.resolve_trace_id(
            correlation_id, prefix="onboarding.start"
        )
        self.logger.log(
            TRACE_LEVEL,
            "gateway.onboarding.start_dispatch.start trace_id=%s board_id=%s",
            trace_id,
            board.id,
        )
        gateway, config = await GatewayDispatchService(
            self.session
        ).require_gateway_config_for_board(board)
        session_key = GatewayAgentIdentity.session_key(gateway)
        try:
            await self._dispatch_gateway_message(
                session_key=session_key,
                config=config,
                agent_name="Gateway Agent",
                message=prompt,
                deliver=False,
            )
        except (OpenClawGatewayError, TimeoutError) as exc:
            self.logger.error(
                "gateway.onboarding.start_dispatch.failed trace_id=%s board_id=%s error=%s",
                trace_id,
                board.id,
                str(exc),
            )
            raise map_gateway_error_to_http_exception(
                GatewayOperation.ONBOARDING_START_DISPATCH,
                exc,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive guard
            self.logger.critical(
                "gateway.onboarding.start_dispatch.failed_unexpected trace_id=%s board_id=%s "
                "error_type=%s error=%s",
                trace_id,
                board.id,
                exc.__class__.__name__,
                str(exc),
            )
            raise
        self.logger.info(
            "gateway.onboarding.start_dispatch.success trace_id=%s board_id=%s session_key=%s",
            trace_id,
            board.id,
            session_key,
        )
        return session_key

    async def dispatch_answer(
        self,
        *,
        board: Board,
        onboarding: BoardOnboardingSession,
        answer_text: str,
        correlation_id: str | None = None,
    ) -> None:
        trace_id = GatewayDispatchService.resolve_trace_id(
            correlation_id, prefix="onboarding.answer"
        )
        self.logger.log(
            TRACE_LEVEL,
            "gateway.onboarding.answer_dispatch.start trace_id=%s board_id=%s onboarding_id=%s",
            trace_id,
            board.id,
            onboarding.id,
        )
        _gateway, config = await GatewayDispatchService(
            self.session
        ).require_gateway_config_for_board(board)
        try:
            await self._dispatch_gateway_message(
                session_key=onboarding.session_key,
                config=config,
                agent_name="Gateway Agent",
                message=answer_text,
                deliver=False,
            )
        except (OpenClawGatewayError, TimeoutError) as exc:
            self.logger.error(
                "gateway.onboarding.answer_dispatch.failed trace_id=%s board_id=%s "
                "onboarding_id=%s error=%s",
                trace_id,
                board.id,
                onboarding.id,
                str(exc),
            )
            raise map_gateway_error_to_http_exception(
                GatewayOperation.ONBOARDING_ANSWER_DISPATCH,
                exc,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive guard
            self.logger.critical(
                "gateway.onboarding.answer_dispatch.failed_unexpected trace_id=%s board_id=%s "
                "onboarding_id=%s error_type=%s error=%s",
                trace_id,
                board.id,
                onboarding.id,
                exc.__class__.__name__,
                str(exc),
            )
            raise
        self.logger.info(
            "gateway.onboarding.answer_dispatch.success trace_id=%s board_id=%s onboarding_id=%s",
            trace_id,
            board.id,
            onboarding.id,
        )

    async def dispatch_refine_prompt(
        self,
        *,
        board: Board,
        draft: dict[str, Any],
        correlation_id: str | None = None,
        refine_answers: dict[str, dict[str, str]] | None = None,
        refine_questions: list[dict[str, Any]] | None = None,
    ) -> str:
        trace_id = GatewayDispatchService.resolve_trace_id(
            correlation_id, prefix="onboarding.refine"
        )
        self.logger.log(
            TRACE_LEVEL,
            "gateway.onboarding.refine_dispatch.start trace_id=%s board_id=%s",
            trace_id,
            board.id,
        )
        gateway, config = await GatewayDispatchService(
            self.session
        ).require_gateway_config_for_board(board)
        session_key = GatewayAgentIdentity.session_key(gateway)
        base_url = settings.base_url
        prompt = self._build_refine_prompt(board, draft, base_url, refine_answers, refine_questions)
        try:
            await self._dispatch_gateway_message(
                session_key=session_key,
                config=config,
                agent_name="Gateway Agent",
                message=prompt,
                deliver=False,
            )
        except (OpenClawGatewayError, TimeoutError) as exc:
            self.logger.error(
                "gateway.onboarding.refine_dispatch.failed trace_id=%s board_id=%s error=%s",
                trace_id,
                board.id,
                str(exc),
            )
            raise map_gateway_error_to_http_exception(
                GatewayOperation.ONBOARDING_START_DISPATCH,
                exc,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive guard
            self.logger.critical(
                "gateway.onboarding.refine_dispatch.failed_unexpected trace_id=%s board_id=%s "
                "error_type=%s error=%s",
                trace_id,
                board.id,
                exc.__class__.__name__,
                str(exc),
            )
            raise
        self.logger.info(
            "gateway.onboarding.refine_dispatch.success trace_id=%s board_id=%s session_key=%s",
            trace_id,
            board.id,
            session_key,
        )
        return session_key

    def _build_refine_prompt(
        self,
        board: Board,
        draft: dict[str, Any],
        base_url: str,
        refine_answers: dict[str, dict[str, str]] | None = None,
        refine_questions: list[dict[str, Any]] | None = None,
    ) -> str:
        draft_json = __import__("json").dumps(draft, indent=2, default=str)

        context_section = ""
        if refine_questions or refine_answers:
            lines: list[str] = ["\n\nREFINE QUESTIONS ASKED BY AI:"]
            if refine_questions:
                for q in refine_questions:
                    qid = q.get("id", "?")
                    qtext = q.get("question", "")
                    lines.append(f"- {qid}: {qtext}")
                    opts = q.get("options", [])
                    if opts:
                        lines.append("  Options:")
                        for opt in opts:
                            oid = opt.get("id", "?")
                            olabel = opt.get("label", "")
                            lines.append(f"  - {oid}: {olabel}")
            if refine_answers:
                lines.append("\nUSER ANSWERS:")
                for qid, data in refine_answers.items():
                    lines.append(f"- {qid}:")
                    lines.append(f"  selected_option: {data.get('answer', '')}")
                    if data.get("other_text"):
                        lines.append(f"  other_text: {data['other_text']}")
            context_section = "\n".join(lines) + "\n\nUse these answers to refine the draft. The user has provided clarifications that should be incorporated into the configuration."

        return (
            "PROJECT BOOTSTRAP REFINE\n\n"
            f"Board Name: {board.name}\n"
            f"Board Description: {board.description or '(not provided)'}\n\n"
            "CURRENT_DRAFT:\n"
            f"{draft_json}{context_section}\n\n"
            "YOUR TASK:\n"
            "You are the AI refinement assistant for project bootstrap. The user has already "
            "completed a structured wizard. Your role is NOT to redo the onboarding — "
            "it is only to:\n"
            "1. Verify logical consistency of the configuration.\n"
            "2. Suggest improvements to objective wording, lead charter, or team shape.\n"
            "3. If critical information is missing, ask AT MOST 1-2 clarifying questions.\n"
            "4. Otherwise, return status=complete with the refined draft.\n\n"
            "REFINEMENT RULES:\n"
            "- Do NOT ask questions the wizard UI already handles.\n"
            "- Do NOT restart the onboarding questionnaire.\n"
            "- If the draft is complete and consistent, respond with:\n"
            '  {"status":"complete","summary":"Configuration looks good. Ready to bootstrap."}\n'
            "- If you suggest improvements, include them in the updated draft fields.\n"
            "- If you need 1-2 clarifications, respond with:\n"
            '  {"status":"questions","questions":[{"id":"1","question":"...","options":[...]}]}\n'
            "- If you update the draft, respond with:\n"
            '  {"status":"complete","draft":{...updated fields...},"summary":"..."}\n\n'
            "MAPPING REFERENCE:\n"
            "- board_type: goal | general\n"
            "- project_info.project_mode: new_product | existing_product_evolution | new_feature | stabilization | research_prototype\n"
            "- project_info.project_stage: idea_only | spec_exists | codebase_exists | active_development | shipped_product\n"
            "- project_info.first_milestone_type: mvp | architecture_plan | key_feature | stabilization | research_prototype | other\n"
            "- project_info.delivery_mode: quality_first | balanced | fast_first_milestone | aggressive_push\n"
            "- project_info.deadline_mode: none | few_days | one_two_weeks | one_month | custom\n"
            "- lead_agent.autonomy_level: ask_first | balanced | autonomous\n"
            "- lead_agent.verbosity: concise | balanced | detailed\n"
            "- lead_agent.output_format: bullets | mixed | narrative\n"
            "- lead_agent.update_cadence: asap | hourly | daily | weekly\n"
            "- team_plan.provision_mode: lead_only | selected_roles | full_team\n"
            "- team_plan.roles: board_lead | developer | qa_engineer | technical_writer | ops_guardian\n"
            "- planning_policy.bootstrap_mode: generate_backlog | empty_board | lead_only | draft_only\n"
            "- planning_policy.planner_mode: spec_to_backlog | architecture_first | feature_first | empty_board\n"
            "- qa_policy.strictness: flexible | balanced | strict\n"
            "- automation_policy.automation_profile: economy | normal | active | aggressive\n\n"
            "Send your response to Mission Control API:\n"
            f"POST {base_url}/api/v1/agent/boards/{board.id}/onboarding/refine-result\n"
            f'curl -s -X POST "{base_url}/api/v1/agent/boards/{board.id}/onboarding/refine-result" '
            '-H "X-Agent-Token: $AUTH_TOKEN" '
            '-H "Content-Type: application/json" '
            '-d \'{"status":"complete","summary":"...","draft":{...}}\'\n'
            "or\n"
            f'curl -s -X POST "{base_url}/api/v1/agent/boards/{board.id}/onboarding/refine-result" '
            '-H "X-Agent-Token: $AUTH_TOKEN" '
            '-H "Content-Type: application/json" '
            '-d \'{"status":"questions","questions":[{"id":"1","question":"...","options":[{"id":"1","label":"..."}]}]}\'\n'
            "Do NOT respond in OpenClaw chat. All responses MUST be sent via API.\n"
        )
