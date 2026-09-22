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
    if is_absolute_program(program) {
        return PathBuf::from(program);
    }
    directory.join(program)
}

/// True when a recorded probe program is absolute on the host it names.
///
/// The recorded channel manifest is read on every platform, so this is deliberately syntactic
/// rather than `Path::is_absolute`: a Windows drive or UNC path is absolute even when the
/// process running the check is not Windows, and a rooted POSIX path is absolute even when it
/// is. The rule mirrors `graph-core`'s `is_absolute_host_path`, which is the canonical host-path
/// predicate of the ecosystem, so a probe path cannot mean two different things in two layers.
fn is_absolute_program(program: &str) -> bool {
    if program.starts_with('/') || program.starts_with(r"\\") || program.starts_with("//") {
        return true;
    }
    let bytes = program.as_bytes();
    bytes.len() >= 3
        && bytes[0].is_ascii_alphabetic()
        && bytes[1] == b':'
        && (bytes[2] == b'\\' || bytes[2] == b'/')
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

    #[test]
    fn every_absolute_program_form_is_recognised_on_every_host() {
        // A Windows drive path, a UNC share and a rooted POSIX path are absolute no matter which
        // process reads the recorded manifest; only a bare relative name is resolved inside the
        // generation. This is the property the host-independent check depends on.
        assert!(is_absolute_program(r"D:/tools/probe.exe"));
        assert!(is_absolute_program(r"D:\tools\probe.exe"));
        assert!(is_absolute_program(r"\\server\share\probe.exe"));
        assert!(is_absolute_program("//server/share/probe.exe"));
        assert!(is_absolute_program("/opt/axiom/probe"));
        assert!(!is_absolute_program("payload/probe.exe"));
        assert!(!is_absolute_program("probe.exe"));
        // A single-letter token without a separator is a relative name, not a drive path.
        assert!(!is_absolute_program("D:probe.exe"));
    }
}
