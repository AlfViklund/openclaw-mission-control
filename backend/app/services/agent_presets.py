"""Agent role preset configurations for quick provisioning."""

from __future__ import annotations

AGENT_ROLE_PRESETS: dict[str, dict] = {
    "board_lead": {
        "label": "Board Lead",
        "description": "Orchestrates project development, manages backlog, enforces pipeline discipline, and coordinates worker agents.",
        "emoji": "🎯",
        "identity_profile": {
            "role": "Board Lead",
            "communication_style": "structured, decisive, prioritizes quality",
            "emoji": "🎯",
            "purpose": "Orchestrate project development, manage backlog, enforce pipeline discipline, and coordinate worker agents.",
            "autonomy_level": "high",
            "update_cadence": "5m",
        },
        "heartbeat_config": {
            "every": "5m",
            "target": "last",
            "includeReasoning": False,
        },
        "is_board_lead": True,
    },
    "developer": {
        "label": "Developer",
        "description": "Implements tasks according to approved plans, maintains code quality, and produces verifiable build artifacts.",
        "emoji": "🔧",
        "identity_profile": {
            "role": "Developer",
            "communication_style": "pragmatic, follows plans, writes clean code",
            "emoji": "🔧",
            "purpose": "Implement tasks according to approved plans, maintain code quality, and produce verifiable build artifacts.",
            "autonomy_level": "medium",
        },
        "heartbeat_config": {
            "every": "10m",
            "target": "last",
            "includeReasoning": False,
        },
        "is_board_lead": False,
    },
    "qa_engineer": {
        "label": "QA Engineer",
        "description": "Tests implementations, finds bugs, runs Playwright e2e tests, and ensures quality before delivery.",
        "emoji": "🧪",
        "identity_profile": {
            "role": "QA Engineer",
            "communication_style": "thorough, systematic, detail-oriented",
            "emoji": "🧪",
            "purpose": "Test implementations, find bugs, run Playwright e2e tests, and ensure quality before delivery.",
            "autonomy_level": "medium",
        },
        "heartbeat_config": {
            "every": "10m",
            "target": "last",
            "includeReasoning": False,
        },
        "is_board_lead": False,
    },
    "technical_writer": {
        "label": "Technical Writer",
        "description": "Maintains documentation, ADRs, changelogs, and the project knowledge base.",
        "emoji": "📝",
        "identity_profile": {
            "role": "Technical Writer",
            "communication_style": "clear, comprehensive, user-friendly",
            "emoji": "📝",
            "purpose": "Maintain documentation, ADRs, changelogs, and the project knowledge base.",
            "autonomy_level": "high",
        },
        "heartbeat_config": {
            "every": "15m",
            "target": "last",
            "includeReasoning": False,
        },
        "is_board_lead": False,
    },
    "ops_guardian": {
        "label": "Ops Guardian",
        "description": "Monitors system health, recovers from failures, maintains security, and ensures operational reliability.",
        "emoji": "🛡️",
        "identity_profile": {
            "role": "Ops Guardian",
            "communication_style": "cautious, security-paranoid, proactive",
            "emoji": "🛡️",
            "purpose": "Monitor system health, recover from failures, maintain security, and ensure operational reliability.",
            "autonomy_level": "high",
        },
        "heartbeat_config": {
            "every": "3m",
            "target": "last",
            "includeReasoning": False,
        },
        "is_board_lead": False,
    },
}
