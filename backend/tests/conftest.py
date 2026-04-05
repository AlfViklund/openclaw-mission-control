"""Backend test shims for optional third-party auth packages."""

from __future__ import annotations

import sys
import types

import os


os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("LOCAL_AUTH_TOKEN", "test-token-" + "x" * 60)
os.environ.setdefault("BASE_URL", "http://localhost:8000")
os.environ.setdefault("AGENT_AUTH_SECRET", "test-agent-auth-secret-" + "y" * 40)


def _install_clerk_backend_api_stubs() -> None:
    if "clerk_backend_api" in sys.modules:
        return

    clerk_backend_api = types.ModuleType("clerk_backend_api")
    clerk_backend_api.Clerk = type("Clerk", (), {})

    models = types.ModuleType("clerk_backend_api.models")
    clerkerrors = types.ModuleType("clerk_backend_api.models.clerkerrors")
    clerkerrors.ClerkErrors = type("ClerkErrors", (), {})
    sdkerror = types.ModuleType("clerk_backend_api.models.sdkerror")
    sdkerror.SDKError = type("SDKError", (), {})

    security = types.ModuleType("clerk_backend_api.security")
    security_types = types.ModuleType("clerk_backend_api.security.types")
    security_types.AuthenticateRequestOptions = type("AuthenticateRequestOptions", (), {})
    security_types.AuthStatus = type("AuthStatus", (), {})
    security_types.RequestState = type("RequestState", (), {})

    sys.modules["clerk_backend_api"] = clerk_backend_api
    sys.modules["clerk_backend_api.models"] = models
    sys.modules["clerk_backend_api.models.clerkerrors"] = clerkerrors
    sys.modules["clerk_backend_api.models.sdkerror"] = sdkerror
    sys.modules["clerk_backend_api.security"] = security
    sys.modules["clerk_backend_api.security.types"] = security_types


_install_clerk_backend_api_stubs()
