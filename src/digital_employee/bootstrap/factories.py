"""Composition-root factory helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import partial
import hashlib
import json
from pathlib import Path

from digital_employee.agents.registry import EmployeeRegistry
from digital_employee.domain.errors import NotFoundError
from digital_employee.contracts.repositories import ApprovalRepository
from digital_employee.domain.employee_profile import EmployeeProfile
from digital_employee.infra.config.models import LoadedConfig
from digital_employee.infra.repositories.events import FileEventLedgerRepository
from digital_employee.infra.repositories.approvals import FileApprovalRepository
from digital_employee.infra.repositories.projections import FileSessionProjectionRepository
from digital_employee.infra.repositories.sessions import FileSessionRepository
from digital_employee.infra.repositories.work_orders import FileWorkOrderRepository
from digital_employee.memory.context_compactor import ContextCompactor
from digital_employee.observability.ledger import EventLedger
from digital_employee.observability.projections import ProjectionStore
from digital_employee.policy.engine import PolicyEngine
from digital_employee.providers.catalog import ProviderCatalog
from digital_employee.providers.factory import ProviderFactory
from digital_employee.providers.router import ProviderRouter, build_provider
from digital_employee.runtime.cell import RuntimeCell, RuntimeCellKey
from digital_employee.runtime.hooks import HookDispatcher
from digital_employee.runtime.manager import RuntimeManager
from digital_employee.runtime.task_supervisor import TaskSupervisor
from digital_employee.runtime.turn_engine import TurnEngine
from digital_employee.tools.exposure import ToolExposurePlanner
from digital_employee.tools.executor import ToolExecutor
from digital_employee.tools.registry import ToolRegistry, build_tool_registry


@dataclass(slots=True)
class RepositoryBundle:
    work_order_repo: FileWorkOrderRepository
    session_repo: FileSessionRepository
    approval_repo: FileApprovalRepository
    event_repo: FileEventLedgerRepository
    session_projection_repo: FileSessionProjectionRepository


@dataclass(slots=True)
class ObservabilityBundle:
    event_ledger: EventLedger
    projection_store: ProjectionStore


@dataclass(slots=True)
class RuntimeBundle:
    provider_catalog: ProviderCatalog
    provider_factory: ProviderFactory
    provider_router: ProviderRouter
    hook_dispatcher: HookDispatcher
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    context_compactor: ContextCompactor
    tool_exposure_planner: ToolExposurePlanner
    policy_engine: PolicyEngine
    task_supervisor: TaskSupervisor
    turn_engine: TurnEngine


def build_config_version(config: LoadedConfig) -> str:
    payload = json.dumps(asdict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_repositories(root_path: Path, tenant: str | None) -> RepositoryBundle:
    return RepositoryBundle(
        work_order_repo=FileWorkOrderRepository(root_path=root_path, tenant=tenant),
        session_repo=FileSessionRepository(root_path=root_path, tenant=tenant),
        approval_repo=FileApprovalRepository(root_path=root_path, tenant=tenant),
        event_repo=FileEventLedgerRepository(root_path=root_path, tenant=tenant),
        session_projection_repo=FileSessionProjectionRepository(root_path=root_path, tenant=tenant),
    )


def build_observability_bundle(repositories: RepositoryBundle, tenant: str | None) -> ObservabilityBundle:
    return ObservabilityBundle(
        event_ledger=EventLedger(repositories.event_repo, tenant=tenant),
        projection_store=ProjectionStore(repositories.session_projection_repo),
    )


def build_provider_router(config: LoadedConfig) -> ProviderRouter:
    builders = {
        name: partial(
            build_provider,
            provider_name=provider.name,
            model=provider.model,
            timeout_seconds=provider.timeout_seconds,
            max_output_tokens=provider.max_output_tokens,
            api_key_env=provider.api_key_env,
        )
        for name, provider in config.providers.items()
    }
    catalog = ProviderCatalog.from_config(config)
    provider_factory = ProviderFactory(catalog, builders=builders)
    return ProviderRouter(catalog=catalog, provider_factory=provider_factory)


def build_tool_names(config: LoadedConfig) -> list[str]:
    tool_names: set[str] = set()
    for employee in config.employees.values():
        tool_names.update(employee.allowed_tools)
    return sorted(tool_names)


def build_runtime_bundle(config: LoadedConfig, approval_repo: ApprovalRepository) -> RuntimeBundle:
    provider_catalog = ProviderCatalog.from_config(config)
    provider_factory = ProviderFactory(
        provider_catalog,
        builders={
            name: partial(
                build_provider,
                provider_name=provider.name,
                model=provider.model,
                timeout_seconds=provider.timeout_seconds,
                max_output_tokens=provider.max_output_tokens,
                api_key_env=provider.api_key_env,
            )
            for name, provider in config.providers.items()
        },
    )
    provider_router = ProviderRouter(catalog=provider_catalog, provider_factory=provider_factory)
    hook_dispatcher = HookDispatcher()
    tool_registry = build_tool_registry(build_tool_names(config))
    tool_executor = ToolExecutor()
    context_compactor = ContextCompactor(
        max_context_tokens=config.system.runtime.max_context_tokens,
        recent_message_window=config.system.runtime.recent_message_window,
        compaction_target_tokens=config.system.runtime.compaction_target_tokens,
    )
    tool_exposure_planner = ToolExposurePlanner()
    policy_engine = PolicyEngine()
    task_supervisor = TaskSupervisor(
        default_timeout_seconds=config.system.runtime.background_task_timeout_seconds,
    )
    turn_engine = TurnEngine(
        provider_router=provider_router,
        tool_registry=tool_registry,
        hook_dispatcher=hook_dispatcher,
        approval_repo=approval_repo,
        policy_engine=policy_engine,
        tool_executor=tool_executor,
        default_budget_tokens=config.system.runtime.default_budget_tokens,
        context_compactor=context_compactor,
        tool_exposure_planner=tool_exposure_planner,
    )
    return RuntimeBundle(
        provider_catalog=provider_catalog,
        provider_factory=provider_factory,
        provider_router=provider_router,
        hook_dispatcher=hook_dispatcher,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        context_compactor=context_compactor,
        tool_exposure_planner=tool_exposure_planner,
        policy_engine=policy_engine,
        task_supervisor=task_supervisor,
        turn_engine=turn_engine,
    )


def build_runtime_cell(
    *,
    key: RuntimeCellKey,
    config: LoadedConfig,
    profile: EmployeeProfile,
    approval_repo: ApprovalRepository,
) -> RuntimeCell:
    provider_catalog = ProviderCatalog.from_config(config)
    provider_factory = ProviderFactory(
        provider_catalog,
        builders={
            name: partial(
                build_provider,
                provider_name=provider.name,
                model=provider.model,
                timeout_seconds=provider.timeout_seconds,
                max_output_tokens=provider.max_output_tokens,
                api_key_env=provider.api_key_env,
            )
            for name, provider in config.providers.items()
        },
    )
    provider_router = ProviderRouter(catalog=provider_catalog, provider_factory=provider_factory)
    hook_dispatcher = HookDispatcher()
    tool_registry = build_tool_registry(sorted(profile.allowed_tools))
    tool_executor = ToolExecutor()
    context_compactor = ContextCompactor(
        max_context_tokens=config.system.runtime.max_context_tokens,
        recent_message_window=config.system.runtime.recent_message_window,
        compaction_target_tokens=config.system.runtime.compaction_target_tokens,
    )
    tool_exposure_planner = ToolExposurePlanner()
    policy_engine = PolicyEngine()
    task_supervisor = TaskSupervisor(
        default_timeout_seconds=config.system.runtime.background_task_timeout_seconds,
    )
    turn_engine = TurnEngine(
        provider_router=provider_router,
        tool_registry=tool_registry,
        hook_dispatcher=hook_dispatcher,
        approval_repo=approval_repo,
        policy_engine=policy_engine,
        tool_executor=tool_executor,
        default_budget_tokens=config.system.runtime.default_budget_tokens,
        context_compactor=context_compactor,
        tool_exposure_planner=tool_exposure_planner,
    )
    return RuntimeCell(
        key=key,
        provider_catalog=provider_catalog,
        provider_factory=provider_factory,
        provider_router=provider_router,
        hook_dispatcher=hook_dispatcher,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        context_compactor=context_compactor,
        tool_exposure_planner=tool_exposure_planner,
        policy_engine=policy_engine,
        task_supervisor=task_supervisor,
        turn_engine=turn_engine,
    )


def build_runtime_manager(
    config: LoadedConfig,
    employee_registry: EmployeeRegistry,
    approval_repo: ApprovalRepository,
) -> RuntimeManager:
    config_version = build_config_version(config)

    def _factory(key: RuntimeCellKey) -> RuntimeCell:
        profile = employee_registry.get_profile(key.employee_id)
        if profile is None:
            raise NotFoundError("employee", key.employee_id)
        return build_runtime_cell(
            key=key,
            config=config,
            profile=profile,
            approval_repo=approval_repo,
        )

    return RuntimeManager(
        tenant=config.tenant,
        config_version=config_version,
        factory=_factory,
    )
