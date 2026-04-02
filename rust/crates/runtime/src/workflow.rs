use std::collections::BTreeSet;
use std::fmt::{Display, Formatter};
use std::fs;
use std::io;
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};

pub const DEFAULT_WORKFLOW_CONFIG_RELATIVE_PATH: &str = ".claw/workflow.json";
pub const DEFAULT_WORKFLOW_STATE_RELATIVE_PATH: &str = ".claw/workflow-state.json";

const WORKFLOW_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkflowPaths {
    pub config_path: PathBuf,
    pub state_path: PathBuf,
}

impl WorkflowPaths {
    #[must_use]
    pub fn for_workspace(cwd: &Path) -> Self {
        Self {
            config_path: cwd.join(DEFAULT_WORKFLOW_CONFIG_RELATIVE_PATH),
            state_path: cwd.join(DEFAULT_WORKFLOW_STATE_RELATIVE_PATH),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowConfig {
    pub schema_version: u32,
    pub phases: Vec<WorkflowPhaseDefinition>,
}

impl WorkflowConfig {
    #[must_use]
    pub fn claw_default() -> Self {
        Self {
            schema_version: WORKFLOW_SCHEMA_VERSION,
            phases: vec![
                WorkflowPhaseDefinition {
                    id: "scope".to_string(),
                    title: "Scope & constraints".to_string(),
                    role: "Discovery".to_string(),
                    summary: "Clarify the task, constraints, assumptions, and success criteria before coding."
                        .to_string(),
                    artifact_path: ".claw/workflow/scope.md".to_string(),
                },
                WorkflowPhaseDefinition {
                    id: "plan".to_string(),
                    title: "Plan & interface changes".to_string(),
                    role: "Design".to_string(),
                    summary: "Describe the implementation plan, touched files, and verification strategy."
                        .to_string(),
                    artifact_path: ".claw/workflow/plan.md".to_string(),
                },
                WorkflowPhaseDefinition {
                    id: "implement".to_string(),
                    title: "Implementation log".to_string(),
                    role: "Build".to_string(),
                    summary: "Capture the shipped change set, key decisions, and follow-up items."
                        .to_string(),
                    artifact_path: ".claw/workflow/implement.md".to_string(),
                },
                WorkflowPhaseDefinition {
                    id: "review".to_string(),
                    title: "Review findings".to_string(),
                    role: "Review".to_string(),
                    summary: "Record behavioral risks, review findings, and fixes before sign-off."
                        .to_string(),
                    artifact_path: ".claw/workflow/review.md".to_string(),
                },
                WorkflowPhaseDefinition {
                    id: "verify".to_string(),
                    title: "Verification & handoff".to_string(),
                    role: "QA".to_string(),
                    summary: "Track tests run, observed results, and handoff notes for the next operator."
                        .to_string(),
                    artifact_path: ".claw/workflow/verify.md".to_string(),
                },
            ],
        }
    }

    fn validate(&self) -> Result<(), WorkflowError> {
        if self.schema_version != WORKFLOW_SCHEMA_VERSION {
            return Err(WorkflowError::InvalidConfig(format!(
                "unsupported workflow schema_version {}",
                self.schema_version
            )));
        }
        if self.phases.is_empty() {
            return Err(WorkflowError::InvalidConfig(
                "workflow config must define at least one phase".to_string(),
            ));
        }

        let mut seen_ids = BTreeSet::new();
        for phase in &self.phases {
            validate_phase_id(&phase.id)?;
            validate_non_empty_field("phase title", &phase.title)?;
            validate_non_empty_field("phase role", &phase.role)?;
            validate_non_empty_field("phase summary", &phase.summary)?;
            validate_artifact_path(&phase.artifact_path)?;
            if !seen_ids.insert(phase.id.clone()) {
                return Err(WorkflowError::InvalidConfig(format!(
                    "workflow phase ids must be unique: {}",
                    phase.id
                )));
            }
        }

        Ok(())
    }

    fn phase_index(&self, phase_id: &str) -> Option<usize> {
        self.phases.iter().position(|phase| phase.id == phase_id)
    }
}

impl Default for WorkflowConfig {
    fn default() -> Self {
        Self::claw_default()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowPhaseDefinition {
    pub id: String,
    pub title: String,
    pub role: String,
    pub summary: String,
    #[serde(rename = "artifact")]
    pub artifact_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowState {
    pub schema_version: u32,
    pub phases: Vec<WorkflowPhaseState>,
    #[serde(default)]
    pub ledger: Vec<WorkflowLedgerEntry>,
}

impl WorkflowState {
    #[must_use]
    pub fn pending_for(config: &WorkflowConfig) -> Self {
        Self {
            schema_version: WORKFLOW_SCHEMA_VERSION,
            phases: config
                .phases
                .iter()
                .map(|phase| WorkflowPhaseState::pending(&phase.id))
                .collect(),
            ledger: Vec::new(),
        }
    }

    fn validate(&self, config: &WorkflowConfig) -> Result<(), WorkflowError> {
        if self.schema_version != WORKFLOW_SCHEMA_VERSION {
            return Err(WorkflowError::InvalidState(format!(
                "unsupported workflow state schema_version {}",
                self.schema_version
            )));
        }
        if self.phases.len() != config.phases.len() {
            return Err(WorkflowError::InvalidState(format!(
                "workflow state has {} phases but config has {}",
                self.phases.len(),
                config.phases.len()
            )));
        }

        for (index, (phase_state, phase_config)) in
            self.phases.iter().zip(&config.phases).enumerate()
        {
            if phase_state.phase_id != phase_config.id {
                return Err(WorkflowError::InvalidState(format!(
                    "workflow state phase {} expected {} but found {}",
                    index + 1,
                    phase_config.id,
                    phase_state.phase_id
                )));
            }
        }

        Ok(())
    }

    fn current_phase_index(&self) -> Option<usize> {
        self.phases
            .iter()
            .position(|phase| phase.gate != WorkflowStoredGateStatus::Approved)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowPhaseState {
    pub phase_id: String,
    pub gate: WorkflowStoredGateStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub updated_at_unix_s: Option<u64>,
}

impl WorkflowPhaseState {
    fn pending(phase_id: &str) -> Self {
        Self {
            phase_id: phase_id.to_string(),
            gate: WorkflowStoredGateStatus::Pending,
            note: None,
            updated_at_unix_s: None,
        }
    }

    fn reset_to_pending(&mut self) {
        self.gate = WorkflowStoredGateStatus::Pending;
        self.note = None;
        self.updated_at_unix_s = None;
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowStoredGateStatus {
    Pending,
    Approved,
    Returned,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowLedgerEntry {
    pub sequence: u64,
    pub phase_id: String,
    pub action: WorkflowLedgerAction,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    pub created_at_unix_s: u64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowLedgerAction {
    Approved,
    Returned,
}

impl WorkflowLedgerAction {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Approved => "approved",
            Self::Returned => "returned",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowDisplayStatus {
    Approved,
    Current,
    Returned,
    Blocked,
}

impl WorkflowDisplayStatus {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Approved => "approved",
            Self::Current => "current",
            Self::Returned => "returned",
            Self::Blocked => "blocked",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowPhaseSnapshot {
    pub id: String,
    pub title: String,
    pub role: String,
    pub summary: String,
    pub artifact_path: String,
    pub status: WorkflowDisplayStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub updated_at_unix_s: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowSnapshot {
    pub schema_version: u32,
    pub config_path: PathBuf,
    pub state_path: PathBuf,
    pub total_phases: usize,
    pub approved_count: usize,
    pub ledger_entries: usize,
    pub is_complete: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub current_phase_id: Option<String>,
    pub phases: Vec<WorkflowPhaseSnapshot>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowMutationResult {
    pub phase_id: String,
    pub action: WorkflowLedgerAction,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    pub snapshot: WorkflowSnapshot,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowInitReport {
    pub config_path: PathBuf,
    pub state_path: PathBuf,
    pub config_status: WorkflowFileStatus,
    pub state_status: WorkflowFileStatus,
    pub artifacts: Vec<WorkflowArtifactStatus>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowArtifactStatus {
    pub path: PathBuf,
    pub status: WorkflowFileStatus,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowFileStatus {
    Created,
    Skipped,
}

impl WorkflowFileStatus {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Created => "created",
            Self::Skipped => "skipped",
        }
    }
}

#[derive(Debug)]
pub enum WorkflowError {
    NotConfigured(PathBuf),
    Io(io::Error),
    Json(serde_json::Error),
    InvalidConfig(String),
    InvalidState(String),
    Gate(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkflowInitOptions {
    pub template_path: Option<PathBuf>,
    pub force: bool,
}

impl Default for WorkflowInitOptions {
    fn default() -> Self {
        Self {
            template_path: None,
            force: false,
        }
    }
}

impl Display for WorkflowError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotConfigured(path) => write!(
                f,
                "workflow is not initialized (expected {}). Run `claw workflow init` first.",
                path.display()
            ),
            Self::Io(error) => write!(f, "{error}"),
            Self::Json(error) => write!(f, "{error}"),
            Self::InvalidConfig(error) => write!(f, "{error}"),
            Self::InvalidState(error) => write!(f, "{error}"),
            Self::Gate(error) => write!(f, "{error}"),
        }
    }
}

impl std::error::Error for WorkflowError {}

impl From<io::Error> for WorkflowError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<serde_json::Error> for WorkflowError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value)
    }
}

pub fn initialize_workflow(cwd: &Path) -> Result<WorkflowInitReport, WorkflowError> {
    initialize_workflow_with_options(cwd, WorkflowInitOptions::default())
}

pub fn initialize_workflow_with_options(
    cwd: &Path,
    options: WorkflowInitOptions,
) -> Result<WorkflowInitReport, WorkflowError> {
    let paths = WorkflowPaths::for_workspace(cwd);
    let mut config_status = WorkflowFileStatus::Skipped;
    let config = if let Some(template_path) = options.template_path {
        if paths.config_path.exists() && !options.force {
            return Err(WorkflowError::InvalidConfig(format!(
                "workflow config already exists at {}. Use --force to replace it.",
                paths.config_path.display()
            )));
        }

        let template = read_template_config(cwd, &template_path)?;
        write_json_file(&paths.config_path, &template)?;
        config_status = WorkflowFileStatus::Created;
        template
    } else {
        if paths.config_path.exists() {
            read_json_file::<WorkflowConfig>(&paths.config_path)?
        } else {
            let config = WorkflowConfig::claw_default();
            write_json_file(&paths.config_path, &config)?;
            config_status = WorkflowFileStatus::Created;
            config
        }
    };

    config.validate()?;

    let state_status = if paths.state_path.exists() {
        match read_json_file::<WorkflowState>(&paths.state_path).and_then(|state| {
            state
                .validate(&config)
                .map(|()| (WorkflowFileStatus::Skipped, state))
                .map_err(WorkflowError::from)
        }) {
            Ok((_status, _state)) => WorkflowFileStatus::Skipped,
            Err(_) if options.force => {
                let state = WorkflowState::pending_for(&config);
                write_json_file(&paths.state_path, &state)?;
                WorkflowFileStatus::Created
            }
            Err(error) => return Err(error),
        }
    } else {
        let state = WorkflowState::pending_for(&config);
        write_json_file(&paths.state_path, &state)?;
        WorkflowFileStatus::Created
    };

    let artifacts = config
        .phases
        .iter()
        .map(|phase| ensure_artifact_file(cwd, phase))
        .collect::<Result<Vec<_>, _>>()?;

    Ok(WorkflowInitReport {
        config_path: paths.config_path,
        state_path: paths.state_path,
        config_status,
        state_status,
        artifacts,
    })
}

pub fn load_workflow_snapshot(cwd: &Path) -> Result<WorkflowSnapshot, WorkflowError> {
    let store = WorkflowStore::load(cwd)?;
    Ok(store.snapshot())
}

pub fn load_workflow_config(cwd: &Path) -> Result<WorkflowConfig, WorkflowError> {
    let paths = WorkflowPaths::for_workspace(cwd);
    if !paths.config_path.exists() {
        return Err(WorkflowError::NotConfigured(paths.config_path));
    }

    let config = read_json_file::<WorkflowConfig>(&paths.config_path)?;
    config.validate()?;
    Ok(config)
}

pub fn approve_workflow_gate(
    cwd: &Path,
    phase_id: Option<&str>,
    note: Option<&str>,
) -> Result<WorkflowMutationResult, WorkflowError> {
    let mut store = WorkflowStore::load(cwd)?;
    let current_index = store
        .state
        .current_phase_index()
        .ok_or_else(|| WorkflowError::Gate("workflow is already fully approved".to_string()))?;
    let expected_phase = store.config.phases[current_index].id.clone();
    if let Some(requested_phase) = phase_id {
        if requested_phase != expected_phase.as_str() {
            return Err(WorkflowError::Gate(format!(
                "phase {requested_phase} is not the current gate; current gate is {expected_phase}"
            )));
        }
    }

    let timestamp = unix_timestamp_now()?;
    let normalized_note = normalize_optional_text(note);
    let phase_state = &mut store.state.phases[current_index];
    phase_state.gate = WorkflowStoredGateStatus::Approved;
    phase_state.note = normalized_note.clone();
    phase_state.updated_at_unix_s = Some(timestamp);
    store.state.ledger.push(WorkflowLedgerEntry {
        sequence: next_ledger_sequence(&store.state),
        phase_id: expected_phase.clone(),
        action: WorkflowLedgerAction::Approved,
        note: normalized_note.clone(),
        created_at_unix_s: timestamp,
    });
    write_json_file(&store.paths.state_path, &store.state)?;

    Ok(WorkflowMutationResult {
        phase_id: expected_phase,
        action: WorkflowLedgerAction::Approved,
        note: normalized_note,
        snapshot: store.snapshot(),
    })
}

pub fn return_workflow_gate(
    cwd: &Path,
    phase_id: Option<&str>,
    reason: &str,
) -> Result<WorkflowMutationResult, WorkflowError> {
    let mut store = WorkflowStore::load(cwd)?;
    let timestamp = unix_timestamp_now()?;
    let normalized_reason = normalize_optional_text(Some(reason))
        .ok_or_else(|| WorkflowError::Gate("return requires a non-empty reason".to_string()))?;

    let target_index = match phase_id {
        Some(requested_phase) => resolve_return_index(&store, requested_phase)?,
        None => store.state.current_phase_index().ok_or_else(|| {
            WorkflowError::Gate(
                "workflow is already fully approved; specify a phase id to reopen it".to_string(),
            )
        })?,
    };

    let target_phase = store.config.phases[target_index].id.clone();
    let target_state = &mut store.state.phases[target_index];
    target_state.gate = WorkflowStoredGateStatus::Returned;
    target_state.note = Some(normalized_reason.clone());
    target_state.updated_at_unix_s = Some(timestamp);

    for later_phase in store.state.phases.iter_mut().skip(target_index + 1) {
        later_phase.reset_to_pending();
    }

    store.state.ledger.push(WorkflowLedgerEntry {
        sequence: next_ledger_sequence(&store.state),
        phase_id: target_phase.clone(),
        action: WorkflowLedgerAction::Returned,
        note: Some(normalized_reason.clone()),
        created_at_unix_s: timestamp,
    });
    write_json_file(&store.paths.state_path, &store.state)?;

    Ok(WorkflowMutationResult {
        phase_id: target_phase,
        action: WorkflowLedgerAction::Returned,
        note: Some(normalized_reason),
        snapshot: store.snapshot(),
    })
}

#[derive(Debug)]
struct WorkflowStore {
    paths: WorkflowPaths,
    config: WorkflowConfig,
    state: WorkflowState,
}

impl WorkflowStore {
    fn load(cwd: &Path) -> Result<Self, WorkflowError> {
        let paths = WorkflowPaths::for_workspace(cwd);
        let config = load_config_or_error(&paths)?;
        let state = if paths.state_path.exists() {
            let state = read_json_file::<WorkflowState>(&paths.state_path)?;
            state.validate(&config)?;
            state
        } else {
            WorkflowState::pending_for(&config)
        };

        Ok(Self {
            paths,
            config,
            state,
        })
    }

    fn snapshot(&self) -> WorkflowSnapshot {
        let current_phase_index = self.state.current_phase_index();
        let approved_count = self
            .state
            .phases
            .iter()
            .filter(|phase| phase.gate == WorkflowStoredGateStatus::Approved)
            .count();

        let phases = self
            .config
            .phases
            .iter()
            .zip(&self.state.phases)
            .enumerate()
            .map(|(index, (definition, state))| WorkflowPhaseSnapshot {
                id: definition.id.clone(),
                title: definition.title.clone(),
                role: definition.role.clone(),
                summary: definition.summary.clone(),
                artifact_path: definition.artifact_path.clone(),
                status: phase_display_status(index, current_phase_index, state.gate),
                note: state.note.clone(),
                updated_at_unix_s: state.updated_at_unix_s,
            })
            .collect();

        WorkflowSnapshot {
            schema_version: WORKFLOW_SCHEMA_VERSION,
            config_path: self.paths.config_path.clone(),
            state_path: self.paths.state_path.clone(),
            total_phases: self.config.phases.len(),
            approved_count,
            ledger_entries: self.state.ledger.len(),
            is_complete: current_phase_index.is_none(),
            current_phase_id: current_phase_index.map(|index| self.config.phases[index].id.clone()),
            phases,
        }
    }
}

fn phase_display_status(
    index: usize,
    current_phase_index: Option<usize>,
    gate: WorkflowStoredGateStatus,
) -> WorkflowDisplayStatus {
    match gate {
        WorkflowStoredGateStatus::Approved => WorkflowDisplayStatus::Approved,
        WorkflowStoredGateStatus::Returned if current_phase_index == Some(index) => {
            WorkflowDisplayStatus::Returned
        }
        WorkflowStoredGateStatus::Returned | WorkflowStoredGateStatus::Pending
            if current_phase_index == Some(index) =>
        {
            WorkflowDisplayStatus::Current
        }
        WorkflowStoredGateStatus::Pending | WorkflowStoredGateStatus::Returned => {
            WorkflowDisplayStatus::Blocked
        }
    }
}

fn resolve_return_index(store: &WorkflowStore, phase_id: &str) -> Result<usize, WorkflowError> {
    let index = store
        .config
        .phase_index(phase_id)
        .ok_or_else(|| WorkflowError::Gate(format!("unknown workflow phase: {phase_id}")))?;

    if let Some(blocking_phase) = store
        .state
        .phases
        .iter()
        .zip(&store.config.phases)
        .take(index)
        .find(|(phase_state, _)| phase_state.gate != WorkflowStoredGateStatus::Approved)
        .map(|(_, phase_config)| phase_config.id.as_str())
    {
        return Err(WorkflowError::Gate(format!(
            "phase {phase_id} is blocked by {blocking_phase}; approve or return earlier gates first"
        )));
    }

    Ok(index)
}

fn ensure_artifact_file(
    cwd: &Path,
    phase: &WorkflowPhaseDefinition,
) -> Result<WorkflowArtifactStatus, WorkflowError> {
    let artifact_path = cwd.join(&phase.artifact_path);
    if artifact_path.exists() {
        return Ok(WorkflowArtifactStatus {
            path: artifact_path,
            status: WorkflowFileStatus::Skipped,
        });
    }

    if let Some(parent) = artifact_path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&artifact_path, render_artifact_stub(phase))?;
    Ok(WorkflowArtifactStatus {
        path: artifact_path,
        status: WorkflowFileStatus::Created,
    })
}

fn render_artifact_stub(phase: &WorkflowPhaseDefinition) -> String {
    format!(
        "# {title}\n\nRole: {role}\n\nSummary: {summary}\n\n## Notes\n\n- Context:\n- Decisions:\n- Risks / follow-up:\n\n## Gate checklist\n\n- [ ] Artifact updated\n- [ ] Decisions recorded\n- [ ] Risks or open questions captured\n",
        title = phase.title,
        role = phase.role,
        summary = phase.summary
    )
}

fn read_json_file<T: DeserializeOwned>(path: &Path) -> Result<T, WorkflowError> {
    let contents = fs::read_to_string(path)?;
    Ok(serde_json::from_str(&contents)?)
}

fn read_template_config(
    cwd: &Path,
    template_path: &PathBuf,
) -> Result<WorkflowConfig, WorkflowError> {
    let resolved_path = if template_path.is_absolute() {
        template_path.clone()
    } else {
        cwd.join(template_path)
    };
    let config: WorkflowConfig = read_json_file(&resolved_path)?;
    config.validate()?;
    Ok(config)
}

fn write_json_file<T: Serialize>(path: &Path, value: &T) -> Result<(), WorkflowError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let rendered = serde_json::to_string_pretty(value)?;
    let temp_path = path.with_extension("json.tmp");
    fs::write(&temp_path, format!("{rendered}\n"))?;
    fs::rename(temp_path, path)?;
    Ok(())
}

fn next_ledger_sequence(state: &WorkflowState) -> u64 {
    u64::try_from(state.ledger.len()).unwrap_or(u64::MAX.saturating_sub(1)) + 1
}

fn normalize_optional_text(value: Option<&str>) -> Option<String> {
    value
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .map(str::to_string)
}

fn validate_non_empty_field(name: &str, value: &str) -> Result<(), WorkflowError> {
    if value.trim().is_empty() {
        return Err(WorkflowError::InvalidConfig(format!(
            "{name} cannot be empty"
        )));
    }
    Ok(())
}

fn validate_phase_id(value: &str) -> Result<(), WorkflowError> {
    if value.is_empty() {
        return Err(WorkflowError::InvalidConfig(
            "workflow phase ids cannot be empty".to_string(),
        ));
    }
    if !value
        .chars()
        .all(|character| character.is_ascii_alphanumeric() || character == '-' || character == '_')
    {
        return Err(WorkflowError::InvalidConfig(format!(
            "workflow phase id must use [A-Za-z0-9_-]: {value}"
        )));
    }
    Ok(())
}

fn validate_artifact_path(path: &str) -> Result<(), WorkflowError> {
    validate_non_empty_field("artifact path", path)?;
    let artifact_path = Path::new(path);
    if artifact_path.is_absolute() {
        return Err(WorkflowError::InvalidConfig(format!(
            "artifact path must be repo-relative: {path}"
        )));
    }
    if artifact_path
        .components()
        .any(|component| matches!(component, Component::ParentDir))
    {
        return Err(WorkflowError::InvalidConfig(format!(
            "artifact path cannot escape the workspace: {path}"
        )));
    }
    Ok(())
}

fn unix_timestamp_now() -> Result<u64, WorkflowError> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| WorkflowError::Gate(error.to_string()))?
        .as_secs())
}

fn load_config_or_error(paths: &WorkflowPaths) -> Result<WorkflowConfig, WorkflowError> {
    if !paths.config_path.exists() {
        return Err(WorkflowError::NotConfigured(paths.config_path.clone()));
    }
    let config = read_json_file::<WorkflowConfig>(&paths.config_path)?;
    config.validate()?;
    Ok(config)
}

#[cfg(test)]
mod tests {
    use super::{
        approve_workflow_gate, initialize_workflow, initialize_workflow_with_options,
        load_workflow_snapshot, read_json_file, return_workflow_gate, WorkflowDisplayStatus,
        WorkflowError, WorkflowFileStatus, WorkflowInitOptions, WorkflowState,
        DEFAULT_WORKFLOW_CONFIG_RELATIVE_PATH, DEFAULT_WORKFLOW_STATE_RELATIVE_PATH,
    };
    use serde_json::json;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_dir() -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time should move forward")
            .as_nanos();
        let path = std::env::temp_dir().join(format!("claw-workflow-{nanos}"));
        fs::create_dir_all(&path).expect("temp dir should be created");
        path
    }

    #[test]
    fn initialize_workflow_creates_default_files_and_snapshot() {
        let root = temp_dir();
        let report = initialize_workflow(&root).expect("workflow init should succeed");

        assert!(report
            .config_path
            .ends_with(DEFAULT_WORKFLOW_CONFIG_RELATIVE_PATH));
        assert!(report
            .state_path
            .ends_with(DEFAULT_WORKFLOW_STATE_RELATIVE_PATH));
        assert_eq!(report.artifacts.len(), 5);
        assert!(root.join(".claw/workflow/scope.md").is_file());

        let snapshot = load_workflow_snapshot(&root).expect("snapshot should load");
        assert_eq!(snapshot.current_phase_id.as_deref(), Some("scope"));
        assert_eq!(snapshot.approved_count, 0);
        assert_eq!(snapshot.phases[0].status, WorkflowDisplayStatus::Current);
        assert_eq!(snapshot.phases[1].status, WorkflowDisplayStatus::Blocked);
    }

    #[test]
    fn initialize_workflow_with_template_and_force_overwrites_existing_config() {
        let root = temp_dir();
        let template = root.join(".claw/workflow-template.json");
        fs::create_dir_all(root.join(".claw")).expect("template directory should be created");
        fs::write(
            &template,
            serde_json::to_string_pretty(&json!({
                "schema_version": 1u32,
                "phases": [{
                    "id": "discover",
                    "title": "Discovery",
                    "role": "Plan",
                    "summary": "Collect requirements and constraints.",
                    "artifact": ".claw/workflow/discovery.md"
                }]
            }))
            .expect("template should serialize"),
        )
        .expect("template write should succeed");

        initialize_workflow_with_options(
            &root,
            WorkflowInitOptions {
                template_path: Some(template.clone()),
                force: true,
            },
        )
        .expect("workflow init with template should succeed");

        let report = initialize_workflow_with_options(
            &root,
            WorkflowInitOptions {
                template_path: Some(template),
                force: true,
            },
        )
        .expect("workflow init should overwrite with force");

        assert_eq!(report.config_status, WorkflowFileStatus::Created);
        assert_eq!(report.state_status, WorkflowFileStatus::Skipped);
        assert_eq!(report.artifacts.len(), 1);
        assert!(root.join(".claw/workflow/discovery.md").is_file());
    }

    #[test]
    fn initialize_workflow_with_force_regenerates_invalid_state() {
        let root = temp_dir();
        initialize_workflow(&root).expect("workflow init should succeed");
        fs::write(
            root.join(DEFAULT_WORKFLOW_STATE_RELATIVE_PATH),
            "invalid json",
        )
        .expect("state clobber should succeed");

        let report = initialize_workflow_with_options(
            &root,
            WorkflowInitOptions {
                template_path: None,
                force: true,
            },
        )
        .expect("workflow init with force should recover invalid state");

        assert_eq!(report.state_status, WorkflowFileStatus::Created);
        let state: WorkflowState =
            read_json_file(&root.join(DEFAULT_WORKFLOW_STATE_RELATIVE_PATH)).expect("state loads");
        assert!(state.phases.len() > 0);
    }

    #[test]
    fn initialize_workflow_with_relative_template_path() {
        let root = temp_dir();
        let template_dir = root.join(".claw");
        fs::create_dir_all(&template_dir).expect("template dir should be created");
        let template_path = PathBuf::from(".claw/workflow-template.json");
        fs::write(
            root.join(&template_path),
            serde_json::to_string_pretty(&json!({
                "schema_version": 1u32,
                "phases": [{
                    "id": "plan",
                    "title": "Plan",
                    "role": "Design",
                    "summary": "Create a concrete implementation plan.",
                    "artifact": ".claw/workflow/plan.md"
                }]
            }))
            .expect("template should serialize"),
        )
        .expect("template write should succeed");

        let report = initialize_workflow_with_options(
            &root,
            WorkflowInitOptions {
                template_path: Some(template_path),
                force: false,
            },
        )
        .expect("relative template path should work");

        assert_eq!(report.config_status, WorkflowFileStatus::Created);
        assert_eq!(
            report.config_path,
            root.join(DEFAULT_WORKFLOW_CONFIG_RELATIVE_PATH)
        );
    }

    #[test]
    fn initialize_workflow_with_missing_template_is_io_error() {
        let root = temp_dir();
        let error = initialize_workflow_with_options(
            &root,
            WorkflowInitOptions {
                template_path: Some(PathBuf::from(".claw/missing-workflow-template.json")),
                force: true,
            },
        )
        .expect_err("missing template should error");

        assert!(matches!(error, WorkflowError::Io(_)));
    }

    #[test]
    fn initialize_workflow_with_invalid_template_is_invalid_config() {
        let root = temp_dir();
        fs::create_dir_all(root.join(".claw")).expect("template dir should be created");
        let template_path = root.join(".claw/workflow-template.json");
        fs::write(&template_path, r#"{"schema_version":1,"phases":[]}"#)
            .expect("template should write");

        let error = initialize_workflow_with_options(
            &root,
            WorkflowInitOptions {
                template_path: Some(template_path),
                force: true,
            },
        )
        .expect_err("invalid template should reject");

        assert!(matches!(error, WorkflowError::InvalidConfig(_)));
    }

    #[test]
    fn approve_advances_to_the_next_gate() {
        let root = temp_dir();
        initialize_workflow(&root).expect("workflow init should succeed");

        let result = approve_workflow_gate(&root, None, Some("scope captured"))
            .expect("approve should succeed");
        assert_eq!(result.phase_id, "scope");
        assert_eq!(result.snapshot.current_phase_id.as_deref(), Some("plan"));
        assert_eq!(result.snapshot.approved_count, 1);
        assert_eq!(
            result.snapshot.phases[0].status,
            WorkflowDisplayStatus::Approved
        );
        assert_eq!(
            result.snapshot.phases[1].status,
            WorkflowDisplayStatus::Current
        );
    }

    #[test]
    fn returning_an_earlier_phase_reopens_it_and_resets_later_state() {
        let root = temp_dir();
        initialize_workflow(&root).expect("workflow init should succeed");
        approve_workflow_gate(&root, Some("scope"), None).expect("scope should approve");
        approve_workflow_gate(&root, Some("plan"), None).expect("plan should approve");

        let result = return_workflow_gate(&root, Some("scope"), "need tighter constraints")
            .expect("return should succeed");
        assert_eq!(result.phase_id, "scope");
        assert_eq!(result.snapshot.current_phase_id.as_deref(), Some("scope"));
        assert_eq!(
            result.snapshot.phases[0].status,
            WorkflowDisplayStatus::Returned
        );
        assert_eq!(
            result.snapshot.phases[1].status,
            WorkflowDisplayStatus::Blocked
        );
        assert_eq!(result.snapshot.approved_count, 0);

        let state: WorkflowState =
            read_json_file(&root.join(DEFAULT_WORKFLOW_STATE_RELATIVE_PATH)).expect("state loads");
        assert_eq!(
            state.phases[0].gate,
            super::WorkflowStoredGateStatus::Returned
        );
        assert_eq!(
            state.phases[1].gate,
            super::WorkflowStoredGateStatus::Pending
        );
    }

    #[test]
    fn return_requires_reachable_phase() {
        let root = temp_dir();
        initialize_workflow(&root).expect("workflow init should succeed");

        let error = return_workflow_gate(&root, Some("plan"), "too early")
            .expect_err("blocked phase should be rejected");
        assert!(error.to_string().contains("blocked by scope"));
    }
}
