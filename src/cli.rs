//! The `axiom-cli` argv surface.
//!
//! `axiom-cli` is the canonical Axiom ecosystem *distribution* entrypoint. It owns the
//! distributed executable, the argv surface, the exit vocabulary and the `NotReady`
//! contract. It does **not** own the installation engine, the bootstrap rules, the
//! service lifecycle or the per-component update transaction: those stay in
//! `axiom-graphd` and are invoked through their published argv surface.
//!
//! Frozen by task `J-003`. Contract references (canonical in the pinned `axiom-specs`):
//!
//! - `contracts/axiom-cli-distribution-contract.md` sections 2, 6 and 7
//! - `docs/16-CLI-AND-CONTROL-API.md` sections 1, 6 and 7
//!
//! The usage text is written out by hand and is pinned against the dispatcher by
//! `tests/argv_surface.rs`: removing a verb from the dispatcher while leaving it in the
//! usage text - or the reverse - fails that test.

use std::ffi::OsString;

/// Canonical CLI exit vocabulary.
///
/// Owned by `axiom-specs/docs/16-CLI-AND-CONTROL-API.md` section 6. The distribution
/// contract references that owner and MUST NOT define a private exit-code space.
///
/// The complete canonical set is frozen here even while this slice only produces the
/// success and validation codes: the contract owns the vocabulary, not the
/// implementation, so a code must not disappear because nothing emits it yet.
#[allow(dead_code)]
pub mod exit {
    /// `0` success.
    pub const SUCCESS: i32 = 0;
    /// `2` validation.
    pub const VALIDATION: i32 = 2;
    /// `3` not found.
    pub const NOT_FOUND: i32 = 3;
    /// `4` not-ready / stale.
    pub const NOT_READY: i32 = 4;
    /// `5` authorization.
    pub const AUTHORIZATION: i32 = 5;
    /// `6` conflict.
    pub const CONFLICT: i32 = 6;
    /// `7` timeout / busy.
    pub const TIMEOUT_BUSY: i32 = 7;
    /// `8` I/O or internal.
    pub const IO_INTERNAL: i32 = 8;
    /// `9` incompatible.
    pub const INCOMPATIBLE: i32 = 9;
    /// `10` lock unavailable.
    pub const LOCK_UNAVAILABLE: i32 = 10;
    /// `20` partial multi-repository operation.
    pub const PARTIAL: i32 = 20;
}

/// The distributed program name (`axiom-cli.exe` on Windows).
pub const PROGRAM: &str = "axiom-cli";
/// The repository that owns the installation engine this layer wraps.
pub const ENGINE_OWNER: &str = "axiom-graphd";
/// Distribution version, taken from `Cargo.toml` and kept in step with `VERSION`.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// The five verbs of the distribution contract, section 2 "Entrypoint and verbs".
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Verb {
    /// `install` - install or repair this platform's pinned component set.
    Install,
    /// `update` - `check`, `plan`, `apply`, `rollback` through the update channel.
    Update,
    /// `doctor` - report prerequisites, installed versions, digests and target state.
    Doctor,
    /// `version` - report installed and available versions per component and target.
    Version,
    /// `uninstall` - remove binaries and service registration; preserve user data.
    Uninstall,
}

impl Verb {
    /// Resolve a verb from its argv token.
    pub fn from_name(name: &str) -> Option<Verb> {
        match name {
            "install" => Some(Verb::Install),
            "update" => Some(Verb::Update),
            "doctor" => Some(Verb::Doctor),
            "version" => Some(Verb::Version),
            "uninstall" => Some(Verb::Uninstall),
            _ => None,
        }
    }

    /// Canonical argv token for this verb.
    pub fn name(self) -> &'static str {
        match self {
            Verb::Install => "install",
            Verb::Update => "update",
            Verb::Doctor => "doctor",
            Verb::Version => "version",
            Verb::Uninstall => "uninstall",
        }
    }

    /// One-line contract summary shown by `--help`.
    pub fn summary(self) -> &'static str {
        match self {
            Verb::Install => "Install or repair this platform's pinned component set",
            Verb::Update => "check | plan | apply | rollback through the update channel",
            Verb::Doctor => "Report prerequisites, installed versions, digests and target state",
            Verb::Version => "Report installed and available versions per component and per target",
            Verb::Uninstall => "Remove binaries and service registration; preserve user data",
        }
    }
}

/// Verb block of the global usage text.
///
/// Written by hand on purpose: it is an independent statement of the documented surface,
/// so a drift between it and [`Verb::from_name`] is detectable instead of impossible.
const USAGE_VERBS: &str = "\
VERBS:
    install      Install or repair this platform's pinned component set
    update       check | plan | apply | rollback through the update channel
    doctor       Report prerequisites, installed versions, digests and target state
    version      Report installed and available versions per component and per target
    uninstall    Remove binaries and service registration; preserve user data
";

/// Canonical exit vocabulary as printed by `--help`.
///
/// Written with explicit `\n` separators: a `\`-continued literal would swallow the
/// leading indentation of its first line and print the first code unindented.
const USAGE_EXIT_CODES: &str = concat!(
    "    0   success\n",
    "    2   validation\n",
    "    3   not found\n",
    "    4   not ready / stale\n",
    "    5   authorization\n",
    "    6   conflict\n",
    "    7   timeout / busy\n",
    "    8   I/O internal\n",
    "    9   incompatible\n",
    "    10  lock unavailable\n",
    "    20  partial multi-repository operation\n",
);

/// Global usage text, printed by `axiom-cli --help`.
pub fn usage() -> String {
    format!(
        "\
{PROGRAM} {VERSION} - Axiom ecosystem distribution entrypoint

USAGE:
    {PROGRAM} [GLOBAL OPTIONS] <verb> [verb options]

{USAGE_VERBS}
GLOBAL OPTIONS:
    -h, --help    Print this help and exit 0
    --json        Machine-readable mode: exactly one JSON object on stdout
    --verbose     Emit diagnostics on stderr

VERB OPTIONS:
    install      --dry-run | --apply, --approve-digest <sha256>, --from <path>
    update       check [--all] | plan --to <version> [--out <file>] |
                 apply --plan <file> --approve-digest <sha256> |
                 rollback --transaction <id> [--approve-digest <sha256>]
    doctor       [--all]
    version      [--all]
    uninstall    --dry-run | --apply, --approve-digest <sha256>, [--purge-data]

EXIT CODES:
{USAGE_EXIT_CODES}
NOTES:
    A verb the distribution contract declares but whose production behaviour is not
    built answers NotReady with exit code 4 and a stated reason. It never returns 0
    and never emits an empty success envelope.
    A destructive install/update/uninstall transaction needs its approval bound to the
    canonical plan digest through --approve-digest <sha256>; supplying --plan is not
    approval.
    The installation engine stays owned by {ENGINE_OWNER}; this layer wraps it.
"
    )
}

/// Verb-specific help text, printed by `axiom-cli <verb> --help`.
pub fn verb_help(verb: Verb) -> String {
    let options = match verb {
        Verb::Install => "\
    --dry-run                  Validate and report the plan without changing the host
    --apply                    Apply the transaction; requires --approve-digest
    --approve-digest <sha256>  Approval bound to the canonical plan digest
    --from <path>              Read the release set from a local path instead of the channel
",
        Verb::Update => "\
    update check [--all]                                  Report available transitions
    update plan --to <version> [--out <file>]             Write the canonical plan
    update apply --plan <file> --approve-digest <sha256>  Apply the approved plan
    update rollback --transaction <id>                    Restore the previous generation
",
        Verb::Doctor => "\
    --all  Probe every declared component, not only the pinned set
",
        Verb::Version => "\
    --all  Report core, MCP, skills and pinned spec provenance
",
        Verb::Uninstall => "\
    --dry-run                  Report what would be removed without removing it
    --apply                    Remove owned binaries and startup entries; requires --approve-digest
    --approve-digest <sha256>  Approval bound to the canonical plan digest
    --purge-data               Also delete workspace data; needs --apply and separate approval
",
    };
    format!(
        "\
{PROGRAM} {verb_name} - {summary}

USAGE:
    {PROGRAM} {verb_name} [options]

OPTIONS:
{options}
GLOBAL OPTIONS:
    -h, --help    Print this help and exit 0
    --json        Machine-readable mode: exactly one JSON object on stdout
    --verbose     Emit diagnostics on stderr

EXIT CODES:
{USAGE_EXIT_CODES}
NOTES:
    The production behaviour of this verb is not built in this slice. It answers
    NotReady with exit code 4 and a stated reason; it never returns 0.
",
        verb_name = verb.name(),
        summary = verb.summary(),
    )
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum OptKind {
    DryRun,
    Apply,
    ApproveDigest,
    From,
    Plan,
    To,
    Out,
    Transaction,
    All,
    PurgeData,
}

impl OptKind {
    fn flag(self) -> &'static str {
        match self {
            OptKind::DryRun => "--dry-run",
            OptKind::Apply => "--apply",
            OptKind::ApproveDigest => "--approve-digest",
            OptKind::From => "--from",
            OptKind::Plan => "--plan",
            OptKind::To => "--to",
            OptKind::Out => "--out",
            OptKind::Transaction => "--transaction",
            OptKind::All => "--all",
            OptKind::PurgeData => "--purge-data",
        }
    }
}

struct Invocation {
    verb: Verb,
    detail: String,
}

/// Parse the program argv and return the process exit code.
///
/// The first element of `args` is the program name; it is skipped.
pub fn run<I>(args: I) -> i32
where
    I: IntoIterator<Item = OsString>,
{
    let mut tokens: Vec<String> = Vec::new();
    for (index, arg) in args.into_iter().enumerate() {
        if index == 0 {
            continue;
        }
        match arg.to_str() {
            Some(text) => tokens.push(text.to_string()),
            None => {
                return fail(
                    false,
                    false,
                    None,
                    "argument is not valid UTF-8; argv is passed as a program and argument list",
                )
            }
        }
    }

    let mut json = false;
    let mut verbose = false;
    let mut help = false;
    let mut verb: Option<Verb> = None;
    let mut rest: Vec<String> = Vec::new();

    for token in tokens {
        if token == "-h" || token == "--help" {
            help = true;
            continue;
        }
        if verb.is_none() {
            if token == "--json" {
                json = true;
            } else if token == "--verbose" {
                verbose = true;
            } else if token.starts_with('-') {
                return fail(
                    json,
                    verbose,
                    None,
                    &format!("unknown global option `{token}`"),
                );
            } else {
                match Verb::from_name(&token) {
                    Some(found) => verb = Some(found),
                    None => {
                        return fail(json, verbose, None, &format!("unknown verb `{token}`"))
                    }
                }
            }
        } else if token == "--json" {
            json = true;
        } else if token == "--verbose" {
            verbose = true;
        } else {
            rest.push(token);
        }
    }

    if help {
        let body = match verb {
            Some(found) => verb_help(found),
            None => usage(),
        };
        if json {
            println!(
                "{}",
                envelope(
                    exit::SUCCESS,
                    "ok",
                    "help",
                    false,
                    &[("usage", body.as_str())],
                )
            );
        } else {
            print!("{body}");
        }
        return exit::SUCCESS;
    }

    let Some(verb) = verb else {
        return fail(
            json,
            verbose,
            None,
            "no verb supplied; expected one of install, update, doctor, version, uninstall",
        );
    };

    let invocation = match parse_invocation(verb, &rest) {
        Ok(invocation) => invocation,
        Err(message) => return fail(json, verbose, Some(verb.name()), &message),
    };

    not_ready(json, verbose, invocation)
}

fn parse_invocation(verb: Verb, rest: &[String]) -> Result<Invocation, String> {
    let mut flags: Vec<OptKind> = Vec::new();
    let mut values: Vec<(OptKind, String)> = Vec::new();
    let mut positionals: Vec<String> = Vec::new();

    let mut index = 0usize;
    while index < rest.len() {
        let token = rest[index].as_str();
        if token.starts_with('-') {
            let Some((kind, needs_value)) = option_spec(verb, token) else {
                return Err(format!(
                    "unknown option `{token}` for verb `{}`",
                    verb.name()
                ));
            };
            if needs_value {
                match rest.get(index + 1) {
                    Some(next) if !next.starts_with('-') => {
                        values.push((kind, next.clone()));
                        index += 2;
                    }
                    _ => return Err(format!("option `{token}` requires a value")),
                }
            } else {
                flags.push(kind);
                index += 1;
            }
        } else {
            positionals.push(rest[index].clone());
            index += 1;
        }
    }

    match verb {
        Verb::Update => parse_update(&flags, &values, &positionals),
        Verb::Install => {
            reject_positionals(verb, &positionals)?;
            if has(&flags, OptKind::DryRun) && has(&flags, OptKind::Apply) {
                return Err("`--dry-run` and `--apply` are mutually exclusive on `install`".into());
            }
            if has(&flags, OptKind::Apply) && value(&values, OptKind::ApproveDigest).is_none() {
                return Err(
                    "`install --apply` requires `--approve-digest <sha256>`; approval is bound to the canonical plan digest"
                        .into(),
                );
            }
            if let Some(digest) = value(&values, OptKind::ApproveDigest) {
                check_digest(&digest)?;
            }
            let mode = if has(&flags, OptKind::Apply) {
                "apply"
            } else if has(&flags, OptKind::DryRun) {
                "dry-run"
            } else {
                "unspecified"
            };
            let from = value(&values, OptKind::From).unwrap_or_else(|| "-".to_string());
            Ok(Invocation {
                verb,
                detail: format!("install mode={mode} from={from}"),
            })
        }
        Verb::Uninstall => {
            reject_positionals(verb, &positionals)?;
            if has(&flags, OptKind::DryRun) && has(&flags, OptKind::Apply) {
                return Err(
                    "`--dry-run` and `--apply` are mutually exclusive on `uninstall`".into(),
                );
            }
            let apply = has(&flags, OptKind::Apply);
            let purge = has(&flags, OptKind::PurgeData);
            if purge && !apply {
                return Err(
                    "`--purge-data` requires `uninstall --apply --approve-digest <sha256>`; deleting workspace data needs a separate explicit approval"
                        .into(),
                );
            }
            if apply && value(&values, OptKind::ApproveDigest).is_none() {
                return Err("`uninstall --apply` requires `--approve-digest <sha256>`".into());
            }
            if let Some(digest) = value(&values, OptKind::ApproveDigest) {
                check_digest(&digest)?;
            }
            let mode = if apply {
                "apply"
            } else if has(&flags, OptKind::DryRun) {
                "dry-run"
            } else {
                "unspecified"
            };
            Ok(Invocation {
                verb,
                detail: format!("uninstall mode={mode} purge_data={purge}"),
            })
        }
        Verb::Doctor => {
            reject_positionals(verb, &positionals)?;
            Ok(Invocation {
                verb,
                detail: format!("doctor all={}", has(&flags, OptKind::All)),
            })
        }
        Verb::Version => {
            reject_positionals(verb, &positionals)?;
            Ok(Invocation {
                verb,
                detail: format!("version all={}", has(&flags, OptKind::All)),
            })
        }
    }
}

fn parse_update(
    flags: &[OptKind],
    values: &[(OptKind, String)],
    positionals: &[String],
) -> Result<Invocation, String> {
    let subcommand = match positionals.len() {
        0 => {
            return Err(
                "`update` requires a subcommand: one of check, plan, apply or rollback".into(),
            )
        }
        1 => positionals[0].as_str(),
        count => {
            return Err(format!(
                "`update` accepts exactly one subcommand, got {count} positional arguments"
            ))
        }
    };

    match subcommand {
        "check" => {
            for flag in flags {
                if *flag != OptKind::All {
                    return Err(format!(
                        "option `{}` is not valid for `update check`",
                        flag.flag()
                    ));
                }
            }
            if let Some((kind, _)) = values.first() {
                return Err(format!(
                    "option `{}` is not valid for `update check`",
                    kind.flag()
                ));
            }
            Ok(Invocation {
                verb: Verb::Update,
                detail: format!("update check all={}", has(flags, OptKind::All)),
            })
        }
        "plan" => {
            reject_update_flags(flags, subcommand)?;
            for (kind, _) in values {
                if !matches!(kind, OptKind::To | OptKind::Out) {
                    return Err(format!(
                        "option `{}` is not valid for `update plan`",
                        kind.flag()
                    ));
                }
            }
            let to = value(values, OptKind::To)
                .ok_or_else(|| "`update plan` requires `--to <version>`".to_string())?;
            let out = value(values, OptKind::Out).unwrap_or_else(|| "-".to_string());
            Ok(Invocation {
                verb: Verb::Update,
                detail: format!("update plan to={to} out={out}"),
            })
        }
        "apply" => {
            reject_update_flags(flags, subcommand)?;
            for (kind, _) in values {
                if !matches!(kind, OptKind::Plan | OptKind::ApproveDigest) {
                    return Err(format!(
                        "option `{}` is not valid for `update apply`",
                        kind.flag()
                    ));
                }
            }
            let plan = value(values, OptKind::Plan)
                .ok_or_else(|| "`update apply` requires `--plan <file>`".to_string())?;
            let digest = value(values, OptKind::ApproveDigest).ok_or_else(|| {
                "`update apply` requires `--approve-digest <sha256>`; supplying `--plan` alone is not approval"
                    .to_string()
            })?;
            check_digest(&digest)?;
            Ok(Invocation {
                verb: Verb::Update,
                detail: format!("update apply plan={plan}"),
            })
        }
        "rollback" => {
            reject_update_flags(flags, subcommand)?;
            for (kind, _) in values {
                if !matches!(kind, OptKind::Transaction | OptKind::ApproveDigest) {
                    return Err(format!(
                        "option `{}` is not valid for `update rollback`",
                        kind.flag()
                    ));
                }
            }
            let transaction = value(values, OptKind::Transaction)
                .ok_or_else(|| "`update rollback` requires `--transaction <id>`".to_string())?;
            if let Some(digest) = value(values, OptKind::ApproveDigest) {
                check_digest(&digest)?;
            }
            Ok(Invocation {
                verb: Verb::Update,
                detail: format!("update rollback transaction={transaction}"),
            })
        }
        other => Err(format!(
            "unknown update subcommand `{other}`; expected check, plan, apply or rollback"
        )),
    }
}

fn reject_update_flags(flags: &[OptKind], subcommand: &str) -> Result<(), String> {
    if let Some(flag) = flags.first() {
        return Err(format!(
            "option `{}` is not valid for `update {subcommand}`",
            flag.flag()
        ));
    }
    Ok(())
}

fn option_spec(verb: Verb, token: &str) -> Option<(OptKind, bool)> {
    let (kind, needs_value) = match token {
        "--dry-run" => (OptKind::DryRun, false),
        "--apply" => (OptKind::Apply, false),
        "--approve-digest" => (OptKind::ApproveDigest, true),
        "--from" => (OptKind::From, true),
        "--plan" => (OptKind::Plan, true),
        "--to" => (OptKind::To, true),
        "--out" => (OptKind::Out, true),
        "--transaction" => (OptKind::Transaction, true),
        "--all" => (OptKind::All, false),
        "--purge-data" => (OptKind::PurgeData, false),
        _ => return None,
    };
    let allowed = match kind {
        OptKind::DryRun | OptKind::Apply => matches!(verb, Verb::Install | Verb::Uninstall),
        OptKind::ApproveDigest => matches!(verb, Verb::Install | Verb::Update | Verb::Uninstall),
        OptKind::From => matches!(verb, Verb::Install),
        OptKind::Plan | OptKind::To | OptKind::Out | OptKind::Transaction => {
            matches!(verb, Verb::Update)
        }
        OptKind::All => matches!(verb, Verb::Update | Verb::Doctor | Verb::Version),
        OptKind::PurgeData => matches!(verb, Verb::Uninstall),
    };
    if allowed {
        Some((kind, needs_value))
    } else {
        None
    }
}

fn has(flags: &[OptKind], kind: OptKind) -> bool {
    flags.contains(&kind)
}

fn value(values: &[(OptKind, String)], kind: OptKind) -> Option<String> {
    values
        .iter()
        .find(|(candidate, _)| *candidate == kind)
        .map(|(_, text)| text.clone())
}

fn reject_positionals(verb: Verb, positionals: &[String]) -> Result<(), String> {
    match positionals.first() {
        Some(extra) => Err(format!(
            "unexpected positional argument `{extra}` for verb `{}`",
            verb.name()
        )),
        None => Ok(()),
    }
}

fn check_digest(digest: &str) -> Result<(), String> {
    if digest.len() == 64 && digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        Ok(())
    } else {
        Err(format!(
            "`--approve-digest` must be a 64-character hex sha256 digest, got {} characters",
            digest.len()
        ))
    }
}

/// Why a declared verb cannot answer yet.
///
/// These reasons are stated on purpose: an unbuilt slice must never look like a success.
fn reason_for(verb: Verb) -> &'static str {
    match verb {
        Verb::Install => {
            "install is declared by the distribution contract, but the transactional installer \
             and the axiom-graphd engine delegation are not built in this slice: J-003 delivers \
             the argv surface only, and the engine handoff awaits I-003/I-004. Nothing was \
             installed, repaired or downloaded."
        }
        Verb::Update => {
            "the update transaction and its pinned channel manifest (channels/stable.json, \
             J-007) are not built, so no mutating update was started and no version was \
             resolved. Nothing was swapped, rolled back or pushed."
        }
        Verb::Doctor => {
            "doctor needs the installed-component and prerequisite probe owned by axiom-graphd \
             (I-003/I-004); this slice exposes argv only and did not probe the host."
        }
        Verb::Version => {
            "component version resolution needs the pinned update-channel manifest \
             (channels/stable.json, J-007); no installed or available version was resolved or \
             invented."
        }
        Verb::Uninstall => {
            "ownership-scoped removal is not built in this slice, so nothing was removed. \
             Deleting workspace data would additionally need an explicit approval digest."
        }
    }
}

fn not_ready(json: bool, verbose: bool, invocation: Invocation) -> i32 {
    let verb = invocation.verb;
    let reason = reason_for(verb);
    if json {
        let message = format!("`{}` is not ready: {reason}", verb.name());
        println!(
            "{}",
            envelope(
                exit::NOT_READY,
                "not_ready",
                &message,
                false,
                &[
                    ("verb", verb.name()),
                    ("engine_owner", ENGINE_OWNER),
                    ("reason", reason),
                    ("parsed", invocation.detail.as_str()),
                ],
            )
        );
    } else {
        eprintln!("{PROGRAM}: {}: NotReady: {reason}", verb.name());
        if verbose {
            eprintln!(
                "{PROGRAM}: diagnostic: parsed invocation: {}",
                invocation.detail
            );
        }
    }
    exit::NOT_READY
}

fn fail(json: bool, verbose: bool, verb: Option<&str>, message: &str) -> i32 {
    if json {
        let mut details: Vec<(&str, &str)> = Vec::new();
        if let Some(name) = verb {
            details.push(("verb", name));
        }
        println!(
            "{}",
            envelope(
                exit::VALIDATION,
                "validation_error",
                message,
                false,
                &details
            )
        );
    } else {
        eprintln!("{PROGRAM}: error: {message}");
        eprintln!("{PROGRAM}: try `{PROGRAM} --help`");
        if verbose {
            eprintln!("{PROGRAM}: diagnostic: exit code {}", exit::VALIDATION);
        }
    }
    exit::VALIDATION
}

fn envelope(
    code: i32,
    status: &str,
    message: &str,
    retryable: bool,
    details: &[(&str, &str)],
) -> String {
    let mut out = String::new();
    out.push('{');
    out.push_str(&format!("\"code\":{code},"));
    out.push_str(&format!("\"status\":\"{}\",", escape(status)));
    out.push_str(&format!("\"message\":\"{}\",", escape(message)));
    out.push_str(&format!("\"retryable\":{retryable},"));
    out.push_str("\"details\":{");
    for (index, (key, item)) in details.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        out.push_str(&format!("\"{}\":\"{}\"", escape(key), escape(item)));
    }
    out.push_str("},\"request_id\":\"");
    out.push_str(&escape(&request_id()));
    out.push_str("\"}");
    out
}

fn request_id() -> String {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_nanos())
        .unwrap_or(0);
    format!("{PROGRAM}-{:x}-{:x}", std::process::id(), nanos)
}

fn escape(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for character in text.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            control if (control as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", control as u32))
            }
            other => out.push(other),
        }
    }
    out
}
