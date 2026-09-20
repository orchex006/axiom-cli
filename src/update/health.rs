//! Post-swap health checking.
//!
//! Two things are checked, and neither of them is a convention invented here:
//!
//! 1. every payload the generation records still digests to the value it was verified against,
//!    so the bytes that are active are the bytes that were accepted; and
//! 2. every owner-declared probe of the recorded channel manifest exits with the code the owner
//!    requires, executed as a program plus argv.
//!
//! A failure is not reported as a successful update. `apply` turns a failure here into a
//! rollback, and the caller is told that the new generation did not become healthy.

use std::path::{Path, PathBuf};
use std::process::Command;

use super::error::{Class, Refusal};
use super::generation::Generation;
use super::state::State;

/// Where a probe program is resolved from: an absolute path stands alone, a relative one is
/// resolved inside the generation directory so a probe can ship beside its payload.
fn resolve_program(directory: &Path, program: &str) -> PathBuf {
    let candidate = Path::new(program);
    if candidate.is_absolute() {
        return candidate.to_path_buf();
    }
    directory.join(candidate)
}

/// Run the health check for a generation that is already the active generation.
pub fn check(state: &State, generation: &Generation) -> Result<(), Refusal> {
    let directory = state.generation_dir(&generation.generation_id);
    generation.verify(&directory).map_err(|error| {
        Refusal::new(
            Class::Conflict,
            error.reason,
            format!("the health check failed: {}", error.message),
        )
    })?;
    for entry in &generation.entries {
        let Some(probe) = &entry.probe else {
            continue;
        };
        let program = resolve_program(&directory, &probe.program);
        let outcome = Command::new(&program).args(&probe.args).output();
        let output = match outcome {
            Ok(output) => output,
            Err(error) => {
                return Err(Refusal::new(
                    Class::Conflict,
                    format!("health_probe_unavailable:{}", entry.component),
                    format!(
                        "the health probe for `{}` could not be executed as {} with args {:?}: \
                         {error}",
                        entry.component,
                        program.display(),
                        probe.args
                    ),
                ))
            }
        };
        let observed = output.status.code();
        if observed != Some(probe.expect_exit as i32) {
            return Err(Refusal::new(
                Class::Conflict,
                format!("health_check_failed:{}", entry.component),
                format!(
                    "the post-swap health probe for `{}` exited with {} but the recorded channel \
                     manifest requires {}: {} with args {:?}",
                    entry.component,
                    observed
                        .map(|code| code.to_string())
                        .unwrap_or_else(|| "no exit code".to_string()),
                    probe.expect_exit,
                    program.display(),
                    probe.args
                ),
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_absolute_probe_program_is_used_as_written() {
        let resolved = resolve_program(
            Path::new("D:/fixture/generations/g-1"),
            "D:/tools/probe.exe",
        );
        assert_eq!(resolved, PathBuf::from("D:/tools/probe.exe"));
    }

    #[test]
    fn a_relative_probe_program_is_resolved_inside_the_generation() {
        let resolved =
            resolve_program(Path::new("D:/fixture/generations/g-1"), "payload/probe.exe");
        let expected = Path::new("D:/fixture/generations/g-1").join("payload/probe.exe");
        assert_eq!(resolved, expected);
    }
}
