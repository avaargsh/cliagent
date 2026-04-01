"""Configuration loading."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from digital_employee.infra.config.models import (
    APIConfig,
    CLIConfig,
    EmployeeConfig,
    LoadedConfig,
    ObservabilityConfig,
    ProviderConfig,
    RuntimeConfig,
    SystemConfig,
)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return payload


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def load_app_config(
    root_path: Path,
    profile: str | None = None,
    tenant: str | None = None,
    base_url_override: str | None = None,
    timeout_override: int | None = None,
    output_json: bool = False,
    no_input: bool = False,
) -> LoadedConfig:
    config_dir = root_path / "configs"
    system_payload = _read_yaml(config_dir / "system.yaml")

    runtime_payload = system_payload.get("runtime") or {}
    api_payload = system_payload.get("api") or {}
    cli_payload = system_payload.get("cli") or {}
    observability_payload = system_payload.get("observability") or {}

    runtime = RuntimeConfig(
        default_timeout_seconds=int(timeout_override or runtime_payload.get("default_timeout_seconds", 30)),
        max_retry_count=int(runtime_payload.get("max_retry_count", 3)),
        default_budget_tokens=int(runtime_payload.get("default_budget_tokens", 12000)),
        max_context_tokens=int(runtime_payload.get("max_context_tokens", 2000)),
        recent_message_window=int(runtime_payload.get("recent_message_window", 6)),
        compaction_target_tokens=int(runtime_payload.get("compaction_target_tokens", 400)),
        background_task_timeout_seconds=int(runtime_payload.get("background_task_timeout_seconds", 900)),
    )
    api = APIConfig(
        base_url=base_url_override or os.getenv("DE_BASE_URL") or api_payload.get("base_url", "http://localhost:8000"),
        request_timeout_seconds=int(
            timeout_override
            or os.getenv("DE_TIMEOUT", api_payload.get("request_timeout_seconds", 30))
        ),
    )
    cli = CLIConfig(
        default_output="json" if output_json else os.getenv("DE_OUTPUT", cli_payload.get("default_output", "human")),
        no_input=no_input or _bool_env("DE_NO_INPUT", bool(cli_payload.get("no_input", False))),
    )
    observability = ObservabilityConfig(
        enable_tracing=bool(observability_payload.get("enable_tracing", True)),
        redact_secrets=bool(observability_payload.get("redact_secrets", True)),
    )

    providers: dict[str, ProviderConfig] = {}
    for path in sorted((config_dir / "providers").glob("*.yaml")):
        payload = _read_yaml(path).get("provider", {})
        if not payload:
            continue
        providers[payload["name"]] = ProviderConfig(
            name=payload["name"],
            model=payload["model"],
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            max_output_tokens=int(payload.get("max_output_tokens", 1024)),
            api_key_env=payload.get("api_key_env", ""),
        )

    employees: dict[str, EmployeeConfig] = {}
    for path in sorted((config_dir / "agents").glob("*.yaml")):
        payload = _read_yaml(path).get("employee", {})
        if not payload:
            continue
        employees[payload["id"]] = EmployeeConfig(
            id=payload["id"],
            display_name=payload["display_name"],
            default_provider=payload["default_provider"],
            skill_packs=list(payload.get("skill_packs", [])),
            allowed_tools=list(payload.get("allowed_tools", [])),
            knowledge_scopes=list(payload.get("knowledge_scopes", [])),
            approval_policy=payload.get("approval_policy", "manual"),
        )

    policies: dict[str, dict] = {}
    for path in sorted((config_dir / "policies").glob("*.yaml")):
        payload = _read_yaml(path)
        policies[path.stem] = payload

    selected_profile = profile or os.getenv("DE_PROFILE")
    selected_tenant = tenant or os.getenv("DE_TENANT")
    return LoadedConfig(
        system=SystemConfig(runtime=runtime, api=api, cli=cli, observability=observability),
        providers=providers,
        employees=employees,
        policies=policies,
        profile=selected_profile,
        tenant=selected_tenant,
    )
