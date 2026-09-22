//! Pins the frozen `axiom-cli` argv surface (task J-003).
//!
//! Every assertion runs the real built binary through `CARGO_BIN_EXE_axiom-cli`, so the
//! test observes the same argv -> exit code -> stdout/stderr behavior a user gets.
//!
//! The documented verb list is written here independently of `src/cli.rs` on purpose. If
//! the usage text and the dispatcher were generated from one table, removing a verb from
//! one of them could not be detected; keeping the expectation independent makes the
//! drift guard real.

use std::process::Command;

/// The five verbs the distribution contract declares (section 2).
const DOCUMENTED_VERBS: [&str; 5] = ["install", "update", "doctor", "version", "uninstall"];

/// Canonical exit vocabulary owned by `axiom-specs/docs/16-CLI-AND-CONTROL-API.md` 6.
const SUCCESS: i32 = 0;
const VALIDATION: i32 = 2;
const NOT_READY: i32 = 4;
const CANONICAL_EXIT_CODES: [i32; 11] = [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20];

struct Outcome {
    code: i32,
    stdout: String,
    stderr: String,
}

fn run(args: &[&str]) -> Outcome {
    let output = Command::new(env!("CARGO_BIN_EXE_axiom-cli"))
        .args(args)
        .output()
        .expect("the built axiom-cli binary must be runnable");
    Outcome {
        code: output
            .status
            .code()
            .expect("axiom-cli must exit with a code, not a signal"),
        stdout: String::from_utf8(output.stdout).expect("stdout must be UTF-8"),
        stderr: String::from_utf8(output.stderr).expect("stderr must be UTF-8"),
    }
}

/// Smallest argv that is structurally valid for a verb.
fn minimal_argv(verb: &str) -> Vec<&str> {
    match verb {
        "update" => vec!["update", "check"],
        // `install` and `uninstall` require an explicit transaction mode, so the minimal
        // invocation a documented verb must be reachable through names that mode. A bare verb is a
        // validation error by design, and `validation_defects_exit_two` locks that separately.
        "install" | "uninstall" => vec![verb, "--dry-run"],
        other => vec![other],
    }
}

/// Extract the verbs listed by the `VERBS:` block of `--help`.
fn help_verbs(help: &str) -> Vec<String> {
    let mut verbs = Vec::new();
    let mut inside = false;
    for line in help.lines() {
        if line.trim_end() == "VERBS:" {
            inside = true;
            continue;
        }
        if !inside {
            continue;
        }
        if line.trim().is_empty() || line.starts_with(|c: char| c.is_ascii_uppercase()) {
            break;
        }
        if !line.starts_with("    ") {
            break;
        }
        if let Some(name) = line.split_whitespace().next() {
            verbs.push(name.to_string());
        }
    }
    verbs
}

/// Assert `text` is exactly one JSON object and nothing else.
fn assert_single_json_object(text: &str) {
    let trimmed = text.trim();
    assert!(
        trimmed.starts_with('{'),
        "stdout must start with a JSON object, got: {text:?}"
    );
    assert!(
        trimmed.ends_with('}'),
        "stdout must end with a JSON object, got: {text:?}"
    );
    let mut depth = 0i32;
    let mut top_level = 0usize;
    let mut in_string = false;
    let mut escaped = false;
    for character in trimmed.chars() {
        if in_string {
            if escaped {
                escaped = false;
            } else if character == '\\' {
                escaped = true;
            } else if character == '"' {
                in_string = false;
            }
            continue;
        }
        match character {
            '"' => in_string = true,
            '{' => {
                if depth == 0 {
                    top_level += 1;
                }
                depth += 1;
            }
            '}' => {
                depth -= 1;
                assert!(depth >= 0, "unbalanced braces in: {text:?}");
            }
            _ => {}
        }
    }
    assert_eq!(depth, 0, "unbalanced braces in: {text:?}");
    assert_eq!(
        top_level, 1,
        "expected exactly one JSON object, got {top_level}"
    );
}

/// Minimal JSON string-field reader: enough to inspect the frozen envelope keys.
fn json_string_field(json: &str, key: &str) -> Option<String> {
    let needle = format!("\"{key}\":\"");
    let start = json.find(&needle)? + needle.len();
    let mut out = String::new();
    let mut chars = json[start..].chars();
    while let Some(character) = chars.next() {
        match character {
            '"' => return Some(out),
            '\\' => match chars.next() {
                Some('n') => out.push('\n'),
                Some('r') => out.push('\r'),
                Some('t') => out.push('\t'),
                Some('"') => out.push('"'),
                Some('\\') => out.push('\\'),
                Some(other) => out.push(other),
                None => return None,
            },
            other => out.push(other),
        }
    }
    None
}

fn json_number_field(json: &str, key: &str) -> Option<i64> {
    let needle = format!("\"{key}\":");
    let start = json.find(&needle)? + needle.len();
    let digits: String = json[start..]
        .chars()
        .take_while(|character| character.is_ascii_digit() || *character == '-')
        .collect();
    digits.parse().ok()
}

#[test]
fn help_lists_exactly_the_documented_verbs() {
    let help = run(&["--help"]);
    assert_eq!(help.code, SUCCESS, "`--help` must exit 0");
    let listed = help_verbs(&help.stdout);
    assert_eq!(
        listed, DOCUMENTED_VERBS,
        "the usage text must list exactly the five documented verbs, in contract order"
    );
}

#[test]
fn every_documented_verb_is_reachable_from_argv() {
    for verb in DOCUMENTED_VERBS {
        let argv = minimal_argv(verb);
        let outcome = run(&argv);
        assert_ne!(
            outcome.code, VALIDATION,
            "`{verb}` is documented, so argv must not reject it as validation; stderr={}",
            outcome.stderr
        );
        assert!(
            CANONICAL_EXIT_CODES.contains(&outcome.code),
            "`{verb}` must answer a canonical exit code, got {}; stderr={}",
            outcome.code,
            outcome.stderr
        );
        // A verb that cannot complete states why in plain mode, on stderr rather than stdout.
        if outcome.code == NOT_READY {
            assert!(
                outcome.stderr.contains("NotReady") && outcome.stderr.len() > 40,
                "`{verb}` must state a NotReady reason on stderr; stderr={}",
                outcome.stderr
            );
        }
    }
}

#[test]
fn usage_text_and_dispatcher_cannot_drift() {
    let help = run(&["--help"]);
    let listed = help_verbs(&help.stdout);

    // Direction 1: everything the usage text lists must be dispatchable.
    for verb in &listed {
        let argv = minimal_argv(verb);
        let outcome = run(&argv);
        assert_ne!(
            outcome.code, VALIDATION,
            "the usage text lists `{verb}` but the dispatcher rejects it: removing a verb \
             from the dispatcher while leaving it in the usage text is a defect"
        );
    }

    // Direction 2: everything the dispatcher accepts must be listed in the usage text.
    for verb in DOCUMENTED_VERBS {
        assert!(
            listed.iter().any(|item| item == verb),
            "the dispatcher accepts `{verb}` but the usage text does not list it: removing a \
             verb from the usage text while leaving it in the dispatcher is a defect"
        );
    }

    // Direction 3: no undocumented verb may be advertised.
    assert_eq!(
        listed, DOCUMENTED_VERBS,
        "the usage text must not advertise a verb outside the distribution contract"
    );
}

#[test]
fn every_verb_reports_a_real_result_and_never_an_empty_success() {
    // The old stub contract ("every verb is unbuilt, so every verb answers 4") is gone. What
    // survives is the rule the distribution contract keeps: a verb answers a canonical code, and a
    // success is never an empty envelope. `details.engine_owner` proves a report was rendered from
    // the real result path rather than from a placeholder.
    for verb in DOCUMENTED_VERBS {
        let mut argv = vec!["--json"];
        argv.extend(minimal_argv(verb));
        let outcome = run(&argv);
        assert_single_json_object(&outcome.stdout);
        assert!(
            CANONICAL_EXIT_CODES.contains(&outcome.code),
            "`{verb}` must answer a canonical exit code, got {}; stdout={}",
            outcome.code,
            outcome.stdout
        );
        assert_eq!(
            json_number_field(&outcome.stdout, "code"),
            Some(i64::from(outcome.code)),
            "the envelope code must equal the process exit code for `{verb}`"
        );
        assert!(
            !json_string_field(&outcome.stdout, "message")
                .unwrap_or_default()
                .is_empty(),
            "`{verb}` must carry a message; stdout={}",
            outcome.stdout
        );
        assert_eq!(
            json_string_field(&outcome.stdout, "engine_owner").as_deref(),
            Some("axiom-graphd"),
            "`{verb}` must name the engine owner this layer wraps"
        );
        assert!(
            !outcome.stdout.contains("\"details\":{}"),
            "an empty details object is an empty success envelope; argv={argv:?}"
        );
    }
}
#[test]
fn json_mode_writes_exactly_one_object_on_every_path() {
    let paths: Vec<Vec<&str>> = vec![
        vec!["--json", "install"],
        vec!["doctor", "--json"],
        vec!["--json", "update", "check"],
        vec!["--json", "bogus"],
        vec!["--json", "install", "--plan"],
        vec!["--json", "--help"],
    ];
    for argv in paths {
        let outcome = run(&argv);
        assert_single_json_object(&outcome.stdout);
        assert!(
            outcome.stderr.is_empty(),
            "JSON mode must not write diagnostics to stdout/stderr by default; argv={argv:?} stderr={}",
            outcome.stderr
        );
    }
}

#[test]
fn validation_defects_exit_two() {
    let cases: Vec<(&str, Vec<&str>)> = vec![
        ("unknown verb", vec!["frobnicate"]),
        ("no verb", vec![]),
        ("missing option value", vec!["install", "--approve-digest"]),
        (
            "missing option value in plan",
            vec!["update", "plan", "--to"],
        ),
        (
            "missing option value in rollback",
            vec!["update", "rollback", "--transaction"],
        ),
        ("apply without approval", vec!["install", "--apply"]),
        (
            "mutually exclusive modes",
            vec!["install", "--dry-run", "--apply"],
        ),
        (
            "uninstall purge without apply",
            vec!["uninstall", "--purge-data"],
        ),
        ("flag not valid for verb", vec!["version", "--dry-run"]),
        ("unknown option", vec!["install", "--bogus"]),
        ("update without subcommand", vec!["update"]),
        ("unknown update subcommand", vec!["update", "frobnicate"]),
        (
            "update apply without digest",
            vec!["update", "apply", "--plan", "plan.json"],
        ),
        ("unexpected positional", vec!["doctor", "extra"]),
        ("install without a mode", vec!["install"]),
        ("uninstall without a mode", vec!["uninstall"]),
        (
            "install without a mode but with a flag",
            vec!["install", "--from", "/does/not/exist"],
        ),
        (
            "malformed digest",
            vec!["install", "--apply", "--approve-digest", "deadbeef"],
        ),
    ];
    for (name, argv) in cases {
        let outcome = run(&argv);
        assert_eq!(
            outcome.code, VALIDATION,
            "case `{name}` must exit 2; stdout={} stderr={}",
            outcome.stdout, outcome.stderr
        );
        assert!(
            outcome.stdout.is_empty(),
            "plain mode must keep stdout clean for `{name}`; stdout={}",
            outcome.stdout
        );
        assert!(
            !outcome.stderr.is_empty(),
            "plain mode must explain `{name}` on stderr"
        );
    }
}

#[test]
fn validation_in_json_mode_carries_the_canonical_envelope() {
    let paths: Vec<Vec<&str>> = vec![
        vec!["--json", "frobnicate"],
        vec!["--json", "install", "--apply"],
        vec!["--json", "install", "--approve-digest"],
        // A bare mutating verb is the newest validation path, so it must carry the same canonical
        // envelope as the older ones: `status:"validation_error"`, `code` equal to the exit, and a
        // message that teaches the missing mode rather than a bare "invalid".
        vec!["--json", "install"],
        vec!["--json", "uninstall"],
        vec!["--json", "install", "--from", "/does/not/exist"],
    ];
    for argv in paths {
        let outcome = run(&argv);
        assert_eq!(outcome.code, VALIDATION, "argv={argv:?}");
        assert_single_json_object(&outcome.stdout);
        assert_eq!(json_number_field(&outcome.stdout, "code"), Some(2));
        assert_eq!(
            json_string_field(&outcome.stdout, "status").as_deref(),
            Some("validation_error")
        );
        assert!(
            !json_string_field(&outcome.stdout, "message")
                .unwrap_or_default()
                .is_empty(),
            "the validation envelope must carry a message"
        );
    }
}

#[test]
fn approve_digest_boundary_is_enforced() {
    let digest = "a".repeat(64);
    let upper = "A1".repeat(32);
    let short = "a".repeat(63);
    let long = "a".repeat(65);
    let non_hex = format!("{}g", "a".repeat(63));

    let accepted = run(&["install", "--apply", "--approve-digest", digest.as_str()]);
    assert_ne!(
        accepted.code, VALIDATION,
        "a 64-character hex digest is a valid approval, so it must not be rejected as validation; stderr={}",
        accepted.stderr
    );
    assert!(
        CANONICAL_EXIT_CODES.contains(&accepted.code),
        "a valid approval must answer a canonical exit code, got {}",
        accepted.code
    );
    let accepted_upper = run(&["install", "--apply", "--approve-digest", upper.as_str()]);
    assert_ne!(accepted_upper.code, VALIDATION);

    let rejected: Vec<(&str, &str)> = vec![
        ("63 characters", short.as_str()),
        ("65 characters", long.as_str()),
        ("non-hex characters", non_hex.as_str()),
    ];
    for (name, candidate) in rejected {
        let outcome = run(&["install", "--apply", "--approve-digest", candidate]);
        assert_eq!(
            outcome.code, VALIDATION,
            "`{name}` must be rejected as validation; stderr={}",
            outcome.stderr
        );
    }
}

#[test]
fn help_exits_zero_and_is_available_per_verb() {
    assert_eq!(run(&["--help"]).code, SUCCESS);
    assert_eq!(run(&["-h"]).code, SUCCESS);

    let json_help = run(&["--help", "--json"]);
    assert_eq!(json_help.code, SUCCESS);
    assert_single_json_object(&json_help.stdout);
    assert_eq!(json_number_field(&json_help.stdout, "code"), Some(0));

    for verb in DOCUMENTED_VERBS {
        let outcome = run(&[verb, "--help"]);
        assert_eq!(outcome.code, SUCCESS, "`{verb} --help` must exit 0");
        assert!(
            outcome.stdout.contains(verb),
            "`{verb} --help` must name the verb"
        );
    }
}

#[test]
fn help_freezes_the_canonical_exit_vocabulary() {
    let help = run(&["--help"]).stdout;
    let section = help
        .split("EXIT CODES:")
        .nth(1)
        .expect("global help must document EXIT CODES");
    let body = section.split("NOTES:").next().unwrap_or(section);
    for code in CANONICAL_EXIT_CODES {
        assert!(
            body.contains(&format!("\n    {code} ")),
            "global help must document exit code {code}"
        );
    }
    for verb in DOCUMENTED_VERBS {
        let verb_help = run(&[verb, "--help"]).stdout;
        for code in CANONICAL_EXIT_CODES {
            assert!(
                verb_help.contains(&format!("\n    {code} ")),
                "`{verb} --help` must document exit code {code}"
            );
        }
    }
}

#[test]
fn json_flag_is_accepted_before_and_after_the_verb() {
    for argv in [vec!["--json", "doctor"], vec!["doctor", "--json"]] {
        let outcome = run(&argv);
        assert!(
            CANONICAL_EXIT_CODES.contains(&outcome.code),
            "`--json` must be accepted on either side of the verb; argv={argv:?}",
        );
        assert_single_json_object(&outcome.stdout);
    }
}

#[test]
fn help_option_blocks_are_indented_and_name_the_required_mode() {
    // Regression guard for a `\`-continued literal, which silently swallowed the leading
    // indentation of the first option line of every verb, so `OPTIONS:` was followed by a
    // flush-left line while the rest of the block was indented. `concat!` fixed it; this keeps
    // it fixed without anyone having to look at the rendered help by eye.
    for verb in DOCUMENTED_VERBS {
        let help = run(&[verb, "--help"]);
        assert_eq!(
            help.code, SUCCESS,
            "`{verb} --help` must exit 0; stderr={}",
            help.stderr
        );
        let mut inside = false;
        let mut option_lines = 0usize;
        for line in help.stdout.lines() {
            if line.trim_end() == "OPTIONS:" {
                inside = true;
                continue;
            }
            if !inside {
                continue;
            }
            if line.trim().is_empty() {
                break;
            }
            assert!(
                line.starts_with("    "),
                "an option line must keep its four-space indent; verb={verb} line={line:?}"
            );
            option_lines += 1;
        }
        assert!(
            option_lines > 0,
            "`{verb} --help` must document at least one option; stdout={}",
            help.stdout
        );
    }

    // The two verbs that require a mode must document both, because the requirement is the
    // single most likely thing an operator gets wrong and exit 2 alone does not teach it.
    for verb in ["install", "uninstall"] {
        let help = run(&[verb, "--help"]);
        for flag in ["--dry-run", "--apply"] {
            assert!(
                help.stdout.contains(flag),
                "`{verb} --help` must name {flag}; stdout={}",
                help.stdout
            );
        }
    }
}

#[test]
fn a_bare_mutating_verb_teaches_the_mode_it_requires() {
    // Exit 2 alone does not teach anyone what to type next. The validation envelope for a bare
    // `install`/`uninstall` must name both modes, because the missing mode is the whole defect.
    for verb in ["install", "uninstall"] {
        let outcome = run(&["--json", verb]);
        assert_eq!(outcome.code, VALIDATION, "verb={verb}");
        assert_single_json_object(&outcome.stdout);
        let message = json_string_field(&outcome.stdout, "message").unwrap_or_default();
        for flag in ["--dry-run", "--apply"] {
            assert!(
                message.contains(flag),
                "`{verb}` must name {flag} in its refusal; message={message}"
            );
        }
        assert!(
            !outcome.stdout.contains("\"details\":{}"),
            "a validation envelope must not be empty; verb={verb} stdout={}",
            outcome.stdout
        );
    }
}

#[test]
fn the_machine_readable_contract_does_not_depend_on_flag_order() {
    // The distribution contract says `--json` puts exactly one JSON object on stdout and sends
    // diagnostics to stderr. That is a property of the invocation, not of where the flag sits.
    // Before this was pinned, `axiom-cli <unknown-verb> --json` answered prose on stderr with an
    // empty stdout, while `axiom-cli --json <unknown-verb>` answered the envelope: the same
    // request answered in two different shapes. A caller that appends `--json` to its argv must
    // not silently lose the machine-readable answer, so both orders are asserted here.
    for argv in [vec!["--json", "frobnicate"], vec!["frobnicate", "--json"]] {
        let outcome = run(&argv);
        assert_eq!(outcome.code, VALIDATION, "argv={argv:?}");
        assert_single_json_object(&outcome.stdout);
        assert!(
            outcome.stderr.is_empty(),
            "a refused invocation that names --json owes stdout one JSON object and no stderr; argv={argv:?} stderr={}",
            outcome.stderr
        );
    }

    // An unknown global option can be refused before any verb is resolved. A trailing `--json`
    // must still be latched, because the caller's intent to read machine output is already known.
    let outcome = run(&["--bogus", "--json"]);
    assert_eq!(outcome.code, VALIDATION);
    assert_single_json_object(&outcome.stdout);
}
