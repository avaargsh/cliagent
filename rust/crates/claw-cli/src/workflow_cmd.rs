use std::path::{Path, PathBuf};

use runtime::{
    approve_workflow_gate, initialize_workflow_with_options, load_workflow_config,
    load_workflow_snapshot, return_workflow_gate, WorkflowConfig, WorkflowInitOptions,
    WorkflowInitReport, WorkflowMutationResult, WorkflowPaths, WorkflowSnapshot,
};
use serde::Serialize;
use serde_json::json;

use crate::CliOutputFormat;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum WorkflowCliCommand {
    Init {
        template_path: Option<String>,
        force: bool,
    },
    Status,
    Config,
    GateApprove {
        phase_id: Option<String>,
        note: Option<String>,
    },
    GateReturn {
        phase_id: Option<String>,
        reason: String,
    },
}

pub(crate) fn parse_workflow_args(args: &[String]) -> Result<WorkflowCliCommand, String> {
    let Some(subcommand) = args.first() else {
        return Err("workflow requires a subcommand: init, status, config, or gate".to_string());
    };

    match subcommand.as_str() {
        "init" => parse_workflow_init_args(&args[1..]),
        "status" if args.len() == 1 => Ok(WorkflowCliCommand::Status),
        "status" => Err("workflow status does not accept additional arguments".to_string()),
        "config" if args.len() == 1 => Ok(WorkflowCliCommand::Config),
        "config" => Err("workflow config does not accept additional arguments".to_string()),
        "gate" => parse_workflow_gate_args(&args[1..]),
        other => Err(format!("unknown workflow subcommand: {other}")),
    }
}

pub(crate) fn split_repl_args(input: &str) -> Result<Vec<String>, String> {
    let mut args = Vec::new();
    let mut token = String::new();
    let mut token_started = false;
    let mut quote: Option<char> = None;
    let mut iter = input.chars();

    let flush_token = |token: &mut String, args: &mut Vec<String>, token_started: &mut bool| {
        if *token_started {
            args.push(std::mem::take(token));
            *token_started = false;
        }
        Ok::<(), String>(())
    };

    while let Some(ch) = iter.next() {
        match quote {
            None => match ch {
                '\'' | '"' => {
                    quote = Some(ch);
                    token_started = true;
                }
                '\\' => {
                    let next = iter.next().ok_or_else(|| {
                        "workflow arguments end with dangling backslash".to_string()
                    })?;
                    token.push(next);
                    token_started = true;
                }
                value if value.is_whitespace() => {
                    flush_token(&mut token, &mut args, &mut token_started)?;
                }
                value => {
                    token.push(value);
                    token_started = true;
                }
            },
            Some('\'') => match ch {
                '\'' => {
                    quote = None;
                }
                value => {
                    token.push(value);
                }
            },
            Some('"') => match ch {
                '"' => {
                    quote = None;
                }
                '\\' => {
                    let next = iter.next().ok_or_else(|| {
                        "workflow arguments end with dangling backslash inside quotes".to_string()
                    })?;
                    token.push(match next {
                        '"' | '\\' => next,
                        _ => next,
                    });
                }
                value => {
                    token.push(value);
                }
            },
            Some(_) => unreachable!(),
        }
    }

    if quote.is_some() {
        return Err(format!(
            "workflow arguments contain unmatched {} quote",
            quote.unwrap_or('"')
        ));
    }

    if token_started {
        args.push(token);
    }
    Ok(args)
}

pub(crate) fn run_workflow_command(
    cwd: &Path,
    command: &WorkflowCliCommand,
    output_format: CliOutputFormat,
) -> Result<String, Box<dyn std::error::Error>> {
    match command {
        WorkflowCliCommand::Init {
            template_path,
            force,
        } => {
            let options = WorkflowInitOptions {
                template_path: template_path.as_ref().map(|path| {
                    if Path::new(path).is_absolute() {
                        PathBuf::from(path)
                    } else {
                        cwd.join(path)
                    }
                }),
                force: *force,
            };
            let report = initialize_workflow_with_options(cwd, options)?;
            render_workflow_output(output_format, "workflow init", &report, || {
                render_init_report(cwd, &report)
            })
        }
        WorkflowCliCommand::Status => {
            let snapshot = load_workflow_snapshot(cwd)?;
            render_workflow_output(output_format, "workflow status", &snapshot, || {
                render_snapshot(cwd, &snapshot)
            })
        }
        WorkflowCliCommand::Config => {
            let config = load_workflow_config(cwd)?;
            let config_path = WorkflowPaths::for_workspace(cwd).config_path;
            render_workflow_output(output_format, "workflow config", &config, || {
                render_config(cwd, &config_path, &config)
            })
        }
        WorkflowCliCommand::GateApprove { phase_id, note } => {
            let result = approve_workflow_gate(cwd, phase_id.as_deref(), note.as_deref())?;
            render_workflow_output(output_format, "workflow gate approve", &result, || {
                render_mutation_result(&result)
            })
        }
        WorkflowCliCommand::GateReturn { phase_id, reason } => {
            let result = return_workflow_gate(cwd, phase_id.as_deref(), reason)?;
            render_workflow_output(output_format, "workflow gate return", &result, || {
                render_mutation_result(&result)
            })
        }
    }
}

fn parse_workflow_gate_args(args: &[String]) -> Result<WorkflowCliCommand, String> {
    let Some(action) = args.first() else {
        return Err("workflow gate requires `approve` or `return`".to_string());
    };

    match action.as_str() {
        "approve" => parse_gate_approve_args(&args[1..]),
        "return" => parse_gate_return_args(&args[1..]),
        other => Err(format!("unknown workflow gate action: {other}")),
    }
}

fn parse_workflow_init_args(args: &[String]) -> Result<WorkflowCliCommand, String> {
    let mut template_path = None;
    let mut force = false;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--config" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| "missing value for workflow init --config".to_string())?;
                if value.trim().is_empty() {
                    return Err("workflow init --config requires a non-empty path".to_string());
                }
                template_path = Some(value.clone());
                index += 2;
            }
            option if option.starts_with("--config=") => {
                let value = &option["--config=".len()..];
                if value.trim().is_empty() {
                    return Err("workflow init --config requires a non-empty path".to_string());
                }
                template_path = Some(value.to_string());
                index += 1;
            }
            "--force" => {
                force = true;
                index += 1;
            }
            other => {
                return Err(format!("unknown workflow init option: {other}"));
            }
        }
    }

    Ok(WorkflowCliCommand::Init {
        template_path,
        force,
    })
}

fn parse_gate_approve_args(args: &[String]) -> Result<WorkflowCliCommand, String> {
    let mut phase_id = None;
    let mut note = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--phase" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| "missing value for workflow gate approve --phase".to_string())?;
                phase_id = Some(value.clone());
                index += 2;
            }
            option if option.starts_with("--phase=") => {
                phase_id = Some(option["--phase=".len()..].to_string());
                index += 1;
            }
            "--note" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| "missing value for workflow gate approve --note".to_string())?;
                note = Some(value.clone());
                index += 2;
            }
            option if option.starts_with("--note=") => {
                note = Some(option["--note=".len()..].to_string());
                index += 1;
            }
            value if !value.starts_with("--") && phase_id.is_none() => {
                phase_id = Some(value.to_string());
                index += 1;
            }
            other => return Err(format!("unknown workflow gate approve option: {other}")),
        }
    }

    Ok(WorkflowCliCommand::GateApprove { phase_id, note })
}

fn parse_gate_return_args(args: &[String]) -> Result<WorkflowCliCommand, String> {
    let mut phase_id = None;
    let mut reason = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--phase" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| "missing value for workflow gate return --phase".to_string())?;
                phase_id = Some(value.clone());
                index += 2;
            }
            option if option.starts_with("--phase=") => {
                phase_id = Some(option["--phase=".len()..].to_string());
                index += 1;
            }
            "--reason" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| "missing value for workflow gate return --reason".to_string())?;
                reason = Some(value.clone());
                index += 2;
            }
            option if option.starts_with("--reason=") => {
                reason = Some(option["--reason=".len()..].to_string());
                index += 1;
            }
            value if !value.starts_with("--") && phase_id.is_none() => {
                phase_id = Some(value.to_string());
                index += 1;
            }
            other => return Err(format!("unknown workflow gate return option: {other}")),
        }
    }

    let reason = reason.ok_or_else(|| {
        "workflow gate return requires --reason \"...\" to explain the rollback".to_string()
    })?;
    Ok(WorkflowCliCommand::GateReturn { phase_id, reason })
}

fn render_workflow_output<T: Serialize>(
    output_format: CliOutputFormat,
    command: &str,
    data: &T,
    text_renderer: impl FnOnce() -> String,
) -> Result<String, Box<dyn std::error::Error>> {
    match output_format {
        CliOutputFormat::Text => Ok(text_renderer()),
        CliOutputFormat::Json => Ok(serde_json::to_string_pretty(&json!({
            "schema_version": 1,
            "command": command,
            "ok": true,
            "data": data,
            "error": serde_json::Value::Null,
        }))?),
    }
}

fn render_init_report(cwd: &Path, report: &WorkflowInitReport) -> String {
    let mut lines = vec![
        "Workflow init".to_string(),
        format!(
            "  Config           {} ({})",
            display_path(cwd, &report.config_path),
            report.config_status.as_str()
        ),
        format!(
            "  State            {} ({})",
            display_path(cwd, &report.state_path),
            report.state_status.as_str()
        ),
        format!("  Artifacts        {}", report.artifacts.len()),
    ];
    for artifact in &report.artifacts {
        lines.push(format!(
            "  {:<16} {}",
            display_path(cwd, &artifact.path),
            artifact.status.as_str()
        ));
    }
    lines.push("  Next step        claw workflow status".to_string());
    lines.join("\n")
}

fn render_config(cwd: &Path, config_path: &Path, config: &WorkflowConfig) -> String {
    let mut lines = vec![
        "Workflow config".to_string(),
        format!("  Path             {}", display_path(cwd, config_path)),
        format!("  Version          {}", config.schema_version),
        format!("  Phases           {}", config.phases.len()),
        String::new(),
        "Phases".to_string(),
    ];

    for phase in &config.phases {
        lines.push(format!(
            "  {:<12} {:<26} {:<14} {}",
            phase.id, phase.title, phase.role, phase.artifact_path
        ));
        lines.push(format!("  Summary         {}", phase.summary));
    }

    lines.join("\n")
}

fn render_snapshot(cwd: &Path, snapshot: &WorkflowSnapshot) -> String {
    let current_gate = snapshot.current_phase_id.as_deref().unwrap_or("<complete>");
    let mut lines = vec![
        "Workflow".to_string(),
        format!(
            "  Config           {}",
            display_path(cwd, &snapshot.config_path)
        ),
        format!(
            "  State            {}",
            display_path(cwd, &snapshot.state_path)
        ),
        format!("  Current gate     {current_gate}"),
        format!(
            "  Summary          {} approved / {} total · {} ledger entries",
            snapshot.approved_count, snapshot.total_phases, snapshot.ledger_entries
        ),
        String::new(),
        "Phases".to_string(),
    ];

    for phase in &snapshot.phases {
        lines.push(format!(
            "  {:<12} {:<9} {:<24} {}",
            phase.id,
            phase.status.as_str(),
            phase.title,
            phase.artifact_path
        ));
        if let Some(note) = phase.note.as_deref() {
            lines.push(format!("  Note             {note}"));
        }
    }

    lines.join("\n")
}

fn render_mutation_result(result: &WorkflowMutationResult) -> String {
    let current_gate = result
        .snapshot
        .current_phase_id
        .as_deref()
        .unwrap_or("<complete>");
    let artifact_path = result
        .snapshot
        .phases
        .iter()
        .find(|phase| phase.id == result.phase_id)
        .map(|phase| phase.artifact_path.as_str())
        .unwrap_or("<unknown>");

    let note = result.note.as_deref().unwrap_or("<none>");
    let mut lines = vec![
        "Workflow gate updated".to_string(),
        format!("  Phase            {}", result.phase_id),
        format!("  Decision         {}", result.action.as_str()),
        format!("  Artifact         {artifact_path}"),
        format!("  Note             {note}"),
        format!("  Current gate     {current_gate}"),
        format!(
            "  Summary          {} approved / {} total · {} ledger entries",
            result.snapshot.approved_count,
            result.snapshot.total_phases,
            result.snapshot.ledger_entries
        ),
    ];

    if let Some(path) = result
        .snapshot
        .phases
        .iter()
        .find(|phase| phase.id == current_gate)
        .map(|phase| phase.artifact_path.as_str())
    {
        lines.push(format!("  Next artifact    {path}"));
    }

    lines.join("\n")
}

fn display_path(cwd: &Path, path: &Path) -> String {
    path.strip_prefix(cwd).unwrap_or(path).display().to_string()
}

#[cfg(test)]
mod tests {
    use super::{parse_workflow_args, run_workflow_command, WorkflowCliCommand};
    use crate::CliOutputFormat;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn parses_init_command() {
        assert_eq!(
            parse_workflow_args(&["init".to_string()]).expect("init should parse"),
            WorkflowCliCommand::Init {
                template_path: None,
                force: false
            }
        );
        assert_eq!(
            parse_workflow_args(&[
                "init".to_string(),
                "--config".to_string(),
                "configs/workflow.json".to_string(),
                "--force".to_string(),
            ])
            .expect("init with custom template should parse"),
            WorkflowCliCommand::Init {
                template_path: Some("configs/workflow.json".to_string()),
                force: true
            }
        );
        assert_eq!(
            parse_workflow_args(&[
                "init".to_string(),
                "--config=templates/custom.json".to_string()
            ])
            .expect("init with inline config should parse"),
            WorkflowCliCommand::Init {
                template_path: Some("templates/custom.json".to_string()),
                force: false
            }
        );
        assert_eq!(
            parse_workflow_args(&["init".to_string(), "--config".to_string(), "".to_string()])
                .expect_err("empty --config value should be rejected"),
            "workflow init --config requires a non-empty path".to_string()
        );
        assert_eq!(
            parse_workflow_args(&["init".to_string(), "--config=".to_string()])
                .expect_err("empty --config= value should be rejected"),
            "workflow init --config requires a non-empty path".to_string()
        );
    }

    #[test]
    fn parses_status_command() {
        assert_eq!(
            parse_workflow_args(&["status".to_string()]).expect("status should parse"),
            WorkflowCliCommand::Status
        );
    }

    #[test]
    fn parses_config_command() {
        assert_eq!(
            parse_workflow_args(&["config".to_string()]).expect("config should parse"),
            WorkflowCliCommand::Config
        );
    }

    #[test]
    fn parses_gate_return_with_phase_and_reason() {
        assert_eq!(
            parse_workflow_args(&[
                "gate".to_string(),
                "return".to_string(),
                "plan".to_string(),
                "--reason".to_string(),
                "missing coverage".to_string(),
            ])
            .expect("gate return should parse"),
            WorkflowCliCommand::GateReturn {
                phase_id: Some("plan".to_string()),
                reason: "missing coverage".to_string(),
            }
        );
    }

    fn temp_dir() -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time should move forward")
            .as_nanos();
        let path = std::env::temp_dir().join(format!("claw-workflow-cmd-{nanos}"));
        fs::create_dir_all(&path).expect("temp dir should be created");
        path
    }

    #[test]
    fn runs_init_command_with_json_output() {
        let cwd = temp_dir();
        let output = run_workflow_command(
            &cwd,
            &WorkflowCliCommand::Init {
                template_path: None,
                force: false,
            },
            CliOutputFormat::Json,
        )
        .expect("workflow init should run with json output");
        let value =
            serde_json::from_str::<serde_json::Value>(&output).expect("json output should parse");
        assert_eq!(value["command"], "workflow init");
        assert_eq!(value["ok"], true);
        assert!(value["data"]["artifacts"].is_array());
        assert!(value["data"]["config_status"].is_string());
    }

    #[test]
    fn runs_init_with_relative_config_template_and_force() {
        let cwd = temp_dir();
        fs::create_dir_all(cwd.join(".claw")).expect("template dir should be created");
        fs::write(
            cwd.join(".claw/workflow-template.json"),
            r#"{"schema_version":1,"phases":[{"id":"plan","title":"Plan","role":"Design","summary":"Plan changes","artifact":".claw/workflow/plan.md"}]}"#,
        )
        .expect("template should be written");

        let command = WorkflowCliCommand::Init {
            template_path: Some(".claw/workflow-template.json".to_string()),
            force: true,
        };
        let text = run_workflow_command(&cwd, &command, CliOutputFormat::Text)
            .expect("workflow init should run");
        assert!(text.contains("Workflow init"));
        assert!(text.contains("workflow.json"));
        assert!(text.contains(".claw/workflow/plan.md"));
    }

    #[test]
    fn runs_gate_approve_and_reflects_snapshot() {
        let cwd = temp_dir();
        run_workflow_command(
            &cwd,
            &WorkflowCliCommand::Init {
                template_path: None,
                force: false,
            },
            CliOutputFormat::Text,
        )
        .expect("workflow init should run");

        let text = run_workflow_command(
            &cwd,
            &WorkflowCliCommand::GateApprove {
                phase_id: None,
                note: Some("scope captured".to_string()),
            },
            CliOutputFormat::Text,
        )
        .expect("gate approve should run");
        assert!(text.contains("Workflow gate updated"));
        assert!(text.contains("Phase            scope"));
        assert!(text.contains("Decision         approved"));
        assert!(text.contains("Summary          1 approved / 5 total"));
    }

    #[test]
    fn status_without_initialized_workflow_fails() {
        let cwd = temp_dir();
        let error = run_workflow_command(&cwd, &WorkflowCliCommand::Status, CliOutputFormat::Text)
            .expect_err("status without init should fail");
        let message = error.to_string();
        assert!(message.contains("workflow is not initialized"));
        assert!(message.contains(".claw/workflow.json"));
    }

    #[test]
    fn gate_return_requires_reason() {
        let cwd = temp_dir();
        run_workflow_command(
            &cwd,
            &WorkflowCliCommand::Init {
                template_path: None,
                force: false,
            },
            CliOutputFormat::Text,
        )
        .expect("workflow init should run");

        let command = WorkflowCliCommand::GateReturn {
            phase_id: Some("scope".to_string()),
            reason: String::new(),
        };
        let error = run_workflow_command(&cwd, &command, CliOutputFormat::Text)
            .expect_err("gate return should fail if reason is empty");
        assert!(error
            .to_string()
            .contains("return requires a non-empty reason"));
    }
}
