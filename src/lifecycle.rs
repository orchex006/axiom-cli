//! `axiom-cli install` and `axiom-cli uninstall` - the distribution transaction.
//!
//! The distribution contract makes this repository the owner of *what is distributed and how it
//! is delivered, verified and updated*, while the installation engine, the bootstrap rules, the
//! service lifecycle and the per-component update transaction stay in `axiom-graphd`. This
//! module implements exactly the distribution half and delegates the engine half through the
//! engine's published argv surface:
//!
//! 1. resolve the delivery target and refuse to act on a target the contract does not declare;
//! 2. resolve the release set - a local release set named by `--from`, else the channel manifest
//!    the installed release records, and never a branch tip, a tag alias or a network `latest`;
//! 3. verify every artifact for this host by byte length and sha256 *before* it is used;
//! 4. build the canonical plan and its digest, and require `--approve-digest` to name that exact
//!    digest before anything mutating runs (supplying `--plan` or `--from` is not approval);
//! 5. delegate the engine-owned placement/removal to the engine binary, and report a precise
//!    *not found* when the engine is absent rather than pretending the work happened.
//!
//! `--dry-run` performs steps 1-4 and changes nothing. `--apply` performs all five. Neither
//! form touches user data, the graph output root or portable workspace state.

use std::path::{Path, PathBuf};

use crate::bundle;
use crate::engine::{self, Located};
use crate::target;
use crate::update::channel::Manifest;
use crate::update::error::{Class, Refusal};
use crate::update::json::Json;
use crate::update::report::Report;
use crate::update::{fetch, plan as plan_contract, state, time::Stamp};

/// The two mutating modes of the distribution transaction.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Mode {
    /// `--dry-run`: report the plan without changing the host.
    DryRun,
    /// `--apply`: run the transaction; requires an approval digest bound to the plan digest.
    Apply,
}

impl Mode {
    /// Canonical mode token.
    pub fn name(self) -> &'static str {
        match self {
            Mode::DryRun => "dry-run",
            Mode::Apply => "apply",
        }
    }
}

/// A parsed `install` request.
#[derive(Clone, Debug)]
pub struct InstallRequest {
    /// `--dry-run` or `--apply`.
    pub mode: Mode,
    /// `--from <path>`: a local release set instead of the channel.
    pub from: Option<String>,
    /// `--approve-digest <sha256>`.
    pub approve_digest: Option<String>,
}

/// A parsed `uninstall` request.
#[derive(Clone, Debug)]
pub struct UninstallRequest {
    /// `--dry-run` or `--apply`.
    pub mode: Mode,
    /// `--approve-digest <sha256>`.
    pub approve_digest: Option<String>,
    /// `--purge-data`: additionally delete workspace data, which needs the engine.
    pub purge_data: bool,
}

/// Run `install`.
pub fn run_install(request: InstallRequest, json: bool, verbose: bool) -> i32 {
    match install(request) {
        Ok(report) => report.emit(json, verbose),
        Err(refusal) => refusal_report("install", &refusal).emit(json, verbose),
    }
}

/// Run `uninstall`.
pub fn run_uninstall(request: UninstallRequest, json: bool, verbose: bool) -> i32 {
    match uninstall(request) {
        Ok(report) => report.emit(json, verbose),
        Err(refusal) => refusal_report("uninstall", &refusal).emit(json, verbose),
    }
}

fn refusal_report(subject: &'static str, refusal: &Refusal) -> Report {
    let mut report = match refusal.class {
        Class::NotReady => Report::not_ready(refusal.message.clone()),
        Class::Validation => Report::refused(refusal.message.clone()),
        other => Report::new(other.exit_code(), other.status(), refusal.message.clone()),
    }
    .subject(subject);
    report.detail("reason", Json::text(&refusal.message));
    report.detail("reason_code", Json::text(&refusal.reason));
    if refusal.class.retryable() {
        report = report.retryable();
    }
    report
}

/// The resolved release set and the canonical plan built from it.
struct ReleaseSet {
    manifest: Manifest,
    manifest_sha256: String,
    manifest_source: String,
    /// Directory that local artifact bytes are resolved from, when the set is local.
    local_root: Option<PathBuf>,
    /// Digest of the canonical plan body.
    plan: Json,
    plan_digest: String,
}

fn install(request: InstallRequest) -> Result<Report, Refusal> {
    let set = resolve_release_set(request.from.as_deref())?;

    if request.mode == Mode::Apply {
        let approval = plan_contract::approval_reasons(
            &set.plan,
            request.approve_digest.as_deref().unwrap_or(""),
        );
        if !approval.is_empty() {
            return Err(Refusal::conflict(
                "approval_required",
                format!(
                    "the install plan digest is {}; {}",
                    set.plan_digest,
                    plan_contract::describe(&approval)
                ),
            ));
        }
    }

    // Verify every artifact this host would receive, before anything is used.
    let verified = verify_artifacts(&set)?;

    // A plan this host would install nothing from is not a plan, and that is a property of the
    // release set rather than of the mode: `--dry-run` and `--apply` answer the same way, so an
    // operator who approves a digest is never approving a no-op. The message states the fact
    // rather than the mode.
    if verified.is_empty() {
        return Err(nothing_to_install(&set));
    }

    let mut report = if request.mode == Mode::Apply {
        apply_install(&set, &verified)?
    } else {
        Report::ok("ok", "install plan reported; nothing was changed").subject("install")
    };
    report.detail("mode", Json::text(request.mode.name()));
    report.detail("generated_at", Json::text(&Stamp::now().format()));
    report.detail(
        "target",
        Json::text(set.plan.get("host").and_then(Json::as_text).unwrap_or("")),
    );
    report.detail(
        "install_root",
        set.plan.get("install_root").cloned().unwrap_or(Json::Null),
    );
    report.detail("channel", Json::text(&set.manifest.channel));
    report.detail("manifest_source", Json::text(&set.manifest_source));
    report.detail("manifest_sha256", Json::text(&set.manifest_sha256));
    report.detail("published", Json::bool(set.manifest.published));
    report.detail("plan", set.plan.clone());
    report.detail("plan_digest", Json::text(&set.plan_digest));
    report.detail("verified_artifacts", Json::array(verified));
    for line in plan_lines(&set) {
        report.line(line);
    }
    Ok(report)
}

/// Build the plan, and - for `--apply` - hand the engine-owned placement to the engine.
///
/// The ownership boundary is explicit here, because getting it wrong is how a distribution layer
/// reports an install that never happened. `axiom-cli` resolves and verifies the release set; the
/// placement of verified bytes is owned by `axiom-graphd`. The engine publishes that placement as
/// `install plan --bundle <dir>` followed by `install apply --plan <file>` over its own ecosystem
/// plan document, built from a verified local bundle. This layer therefore
///
/// * refuses with `not_found` when no engine binary is present, naming every place it looked;
/// * refuses with `not_ready` when verified bytes exist but the engine bundle they belong to
///   cannot be assembled (`bundle::assemble` states exactly which input is missing) - never
///   handing the engine a distribution plan document it cannot validate; and
/// * otherwise assembles the bundle from bytes it already verified and invokes the engine, then
///   reports the engine's own status and exit code with its raw stdout and stderr as evidence.
///
/// Every refusal states that nothing was placed, and none is a bare "unbuilt verb": the
/// verification work above really ran.
/// The refusal for a release set that declares nothing this host could receive.
fn nothing_to_install(set: &ReleaseSet) -> Refusal {
    Refusal::not_ready(
        "nothing_to_install",
        format!(
            "the install plan digest is {}; the release set from {} declares no artifact for host \
             {} (channel `{}` published={}); there is nothing to download or place, so nothing was \
             installed or repaired",
            set.plan_digest,
            set.manifest_source,
            set.plan.get("host").and_then(Json::as_text).unwrap_or("?"),
            set.manifest.channel,
            set.manifest.published
        ),
    )
}

fn apply_install(set: &ReleaseSet, verified: &[Json]) -> Result<Report, Refusal> {
    if verified.is_empty() {
        // The install flow refuses this before the mode branch, so the guard cannot be reached
        // from the verb. It is kept because `apply_install` owns the placement contract and a
        // future caller must not be able to reach the engine with nothing to place.
        return Err(nothing_to_install(set));
    }
    let engine = match engine::locate() {
        Located::Found(found) => found,
        Located::Missing(searched) => return Err(engine::missing_refusal(&searched)),
    };
    let root = state::default_root().ok_or_else(|| {
        Refusal::not_ready(
            "no_install_root",
            "this host offers no per-user install root, so the assembled bundle has nowhere to \
             live and the engine has no `AXIOM_HOME`",
        )
    })?;
    let staging_root = root.join("staging").join("engine-bundle");
    let plan_components = set
        .plan
        .get("components")
        .and_then(Json::as_array)
        .unwrap_or(&[]);
    let request = bundle::Request {
        staging_root: staging_root.clone(),
        install_root: root,
        host: set
            .plan
            .get("host")
            .and_then(Json::as_text)
            .unwrap_or("")
            .to_string(),
        channel: set.manifest.channel.clone(),
        created_at: set.manifest.updated_at.format(),
        release_root: set.local_root.clone(),
        verified,
        plan_components,
    };
    // A refusal from the assembly or the engine is *this* layer's answer, so it names the plan
    // the operator approved: the engine's refusal alone would leave `--apply --approve-digest`'s
    // subject unstated. The class and reason token are the ones the boundary chose.
    let mut report = bundle::apply(&engine, &request).map_err(|refusal| {
        Refusal::new(
            refusal.class,
            refusal.reason,
            format!(
                "the install plan digest is {}; {}",
                set.plan_digest, refusal.message
            ),
        )
    })?;
    report.detail(
        "staging_root",
        Json::text(&staging_root.display().to_string()),
    );
    report.detail(
        "engine_program",
        Json::text(&engine.program().display().to_string()),
    );
    report.detail("engine_source", Json::text(engine.source()));
    Ok(report)
}

/// Run `uninstall`.
fn uninstall(request: UninstallRequest) -> Result<Report, Refusal> {
    if request.purge_data {
        return Err(Refusal::validation(
            "purge_data_unsupported",
            "uninstall preserves user data; this distribution wrapper does not expose purge-data",
        ));
    }
    let root = state::default_root().ok_or_else(|| {
        Refusal::not_ready(
            "no_install_root",
            "this host offers no per-user install root, so there is nothing this layer owns to remove",
        )
    })?;
    let st = state::State::new(root.clone());

    let mut plan = uninstall_plan(&st, request.purge_data)?;
    if st.has_installed() || engine_current_exists(&root) {
        plan.set("installed", Json::bool(true))
            .map_err(|e| Refusal::validation("installed", e))?;
        plan.set("engine_plan", engine_uninstall_plan(&root)?)
            .map_err(|e| Refusal::validation("engine_plan", e))?;
        if st.has_installed() {
            let bytes = std::fs::read(st.installed_path()).map_err(|e| {
                Refusal::io(
                    "installed_marker_read",
                    &st.installed_path().display().to_string(),
                    &e,
                )
            })?;
            plan.set(
                "installed_marker_sha256",
                Json::text(&crate::update::sha256::hex(&crate::update::sha256::digest(
                    &bytes,
                ))),
            )
            .map_err(|e| Refusal::validation("installed_marker", e))?;
        }
    }
    let digest = plan_contract::digest(&plan).ok_or_else(|| {
        Refusal::validation(
            "plan_unbuildable",
            "the uninstall plan could not be digested",
        )
    })?;
    seal(&mut plan, &digest)?;

    if request.mode == Mode::Apply {
        let reasons =
            plan_contract::approval_reasons(&plan, request.approve_digest.as_deref().unwrap_or(""));
        if !reasons.is_empty() {
            return Err(Refusal::conflict(
                "approval_required",
                format!(
                    "the uninstall plan digest is {digest}; {}",
                    plan_contract::describe(&reasons)
                ),
            ));
        }
    }

    let mut report = if request.mode == Mode::Apply {
        apply_uninstall(&plan, &digest, request.purge_data)?
    } else {
        Report::ok("ok", "uninstall plan reported; nothing was removed").subject("uninstall")
    };
    report.detail("mode", Json::text(request.mode.name()));
    report.detail("generated_at", Json::text(&Stamp::now().format()));
    report.detail("purge_data", Json::bool(request.purge_data));
    report.detail("install_root", Json::text(&root.display().to_string()));
    report.detail("plan", plan);
    report.detail("plan_digest", Json::text(&digest));
    Ok(report)
}

fn engine_current_exists(root: &std::path::Path) -> bool {
    root.join("installs/ecosystem/current").is_file()
}

fn apply_uninstall(plan: &Json, digest: &str, _purge_data: bool) -> Result<Report, Refusal> {
    let installed = plan
        .get("installed")
        .and_then(Json::as_bool)
        .unwrap_or(false);
    if !installed {
        return Err(Refusal::new(
            Class::NotFound,
            "nothing_installed",
            "no installed release is recorded, so there is nothing for this layer to remove",
        ));
    }
    let engine = match engine::locate() {
        Located::Found(found) => found,
        Located::Missing(searched) => return Err(engine::missing_refusal(&searched)),
    };
    let root = plan
        .get("install_root")
        .and_then(Json::as_text)
        .unwrap_or_default();
    let embedded = plan.get("engine_plan").ok_or_else(|| {
        Refusal::validation(
            "engine_plan_missing",
            "outer uninstall plan has no engine plan",
        )
    })?;
    let engine_digest = embedded
        .get("plan_digest")
        .and_then(Json::as_text)
        .map(str::to_owned)
        .ok_or_else(|| {
            Refusal::validation(
                "engine_uninstall_plan_digest",
                "engine uninstall plan has no digest",
            )
        })?;
    let plan_path = std::path::Path::new(root).join("state/engine-uninstall-approved.json");
    std::fs::write(&plan_path, crate::update::json::canonical_bytes(embedded)).map_err(|e| {
        Refusal::io(
            "engine_uninstall_plan_write",
            &plan_path.display().to_string(),
            &e,
        )
    })?;
    let applied = engine.invoke_with_env(
        &[
            "uninstall".into(),
            "apply".into(),
            "--plan".into(),
            plan_path.display().to_string(),
            "--approve-digest".into(),
            engine_digest,
        ],
        &[("AXIOM_HOME", root.to_owned())],
    )?;
    if applied.exit_code() != 0 {
        return Err(Refusal::not_ready(
            "engine_uninstall_apply_failed",
            applied.stderr,
        ));
    }
    clear_installed_marker(
        std::path::Path::new(root),
        plan.get("installed_marker_sha256").and_then(Json::as_text),
    )?;
    Ok(Report::ok(
        "ok",
        format!(
            "engine-owned uninstall completed; distribution approval {digest} bound the request"
        ),
    )
    .subject("uninstall"))
}

fn clear_installed_marker(root: &std::path::Path, expected: Option<&str>) -> Result<(), Refusal> {
    let Some(expected) = expected else {
        return Ok(());
    };
    let path = root.join("installed.json");
    if !path.exists() {
        return Ok(());
    }
    let bytes = std::fs::read(&path)
        .map_err(|e| Refusal::io("installed_marker_read", &path.display().to_string(), &e))?;
    if crate::update::sha256::hex(&crate::update::sha256::digest(&bytes)) != expected {
        return Err(Refusal::conflict(
            "installed_marker_changed",
            "installed marker changed after approval and was preserved",
        ));
    }
    std::fs::remove_file(path)
        .map_err(|e| Refusal::io("installed_marker_remove", "installed.json", &e))
}

fn engine_uninstall_plan(root: &std::path::Path) -> Result<Json, Refusal> {
    let engine = match engine::locate() {
        Located::Found(found) => found,
        Located::Missing(searched) => return Err(engine::missing_refusal(&searched)),
    };
    let path = root.join("state/engine-uninstall-preview.json");
    let outcome = engine.invoke_with_env(
        &[
            "uninstall".into(),
            "plan".into(),
            "--out".into(),
            path.display().to_string(),
        ],
        &[("AXIOM_HOME", root.display().to_string())],
    )?;
    if outcome.exit_code() != 0 {
        return Err(Refusal::not_ready(
            "engine_uninstall_plan_failed",
            outcome.stderr,
        ));
    }
    crate::update::json::parse(&std::fs::read_to_string(&path).map_err(|e| {
        Refusal::io(
            "engine_uninstall_plan_missing",
            &path.display().to_string(),
            &e,
        )
    })?)
    .map_err(|e| Refusal::validation("engine_uninstall_plan_invalid", e))
}

fn uninstall_plan(st: &state::State, purge_data: bool) -> Result<Json, Refusal> {
    let installed = st.has_installed();
    let mut pairs = vec![
        ("plan_version", Json::int(1)),
        ("verb", Json::text("uninstall")),
        (
            "host",
            match target::host_id() {
                Some(value) => Json::text(value),
                None => Json::null(),
            },
        ),
        ("install_root", Json::text(&st.root().display().to_string())),
        ("installed", Json::bool(installed)),
        ("purge_data", Json::bool(purge_data)),
        ("approval", approval_block()),
    ];
    if installed {
        let record = st.read_installed()?;
        pairs.push(("channel", Json::text(&record.channel)));
        pairs.push(("generation", Json::text(&record.current_generation)));
    }
    Ok(Json::from_pairs(pairs))
}

/// Resolve the release set: an explicit local set, else the recorded channel manifest.
fn resolve_release_set(from: Option<&str>) -> Result<ReleaseSet, Refusal> {
    let host = target::host_id().ok_or_else(|| {
        Refusal::new(
            Class::Incompatible,
            "undeclared_target",
            format!(
                "this host ({}) is not a delivery platform the distribution contract declares, so \
                 the distribution refuses to install on it",
                target::host_description()
            ),
        )
    })?;

    let (loaded, local_root) = match from {
        Some(path) => {
            let path = Path::new(path);
            let manifest_path = if path.is_dir() {
                local_manifest_in(path).ok_or_else(|| {
                    Refusal::new(
                        Class::NotFound,
                        "release_set_manifest_missing",
                        format!(
                            "the release set {} has no channel manifest (expected channel.json or \
                             stable.json in that directory)",
                            path.display()
                        ),
                    )
                })?
            } else {
                path.to_path_buf()
            };
            let loaded = state::State::load_manifest_file(&manifest_path)?;
            let root = manifest_path.parent().map(Path::to_path_buf);
            (loaded, root)
        }
        None => {
            let root = state::default_root().ok_or_else(|| {
                Refusal::not_ready(
                    "no_install_root",
                    "this host offers no per-user install root, so no recorded channel manifest can be read",
                )
            })?;
            let st = state::State::new(root);
            if st.has_installed() {
                let record = st.read_installed()?;
                (st.load_recorded_manifest(&record)?, None)
            } else if let Ok(candidate) = std::env::var(state::CHANNEL_MANIFEST_ENV) {
                if candidate.trim().is_empty() {
                    return Err(no_release_set());
                }
                let loaded = state::State::load_manifest_file(Path::new(&candidate))?;
                let root = Path::new(&candidate).parent().map(Path::to_path_buf);
                (loaded, root)
            } else {
                return Err(no_release_set());
            }
        }
    };

    let mut plan = build_plan(host, &loaded.manifest, &loaded.path, &loaded.sha256)?;
    let digest = plan_contract::digest(&plan).ok_or_else(|| {
        Refusal::validation("plan_unbuildable", "the install plan could not be digested")
    })?;
    seal(&mut plan, &digest)?;
    Ok(ReleaseSet {
        manifest: loaded.manifest,
        manifest_sha256: loaded.sha256,
        manifest_source: loaded.path.display().to_string(),
        local_root,
        plan,
        plan_digest: digest,
    })
}

fn no_release_set() -> Refusal {
    Refusal::not_ready(
        "no_release_set",
        "no release set is available: nothing is installed, no local release set was named with \
         `--from`, and no candidate channel manifest was named. The distribution resolves from a \
         recorded or explicit manifest only and never invents one",
    )
}

fn local_manifest_in(directory: &Path) -> Option<PathBuf> {
    for name in ["channel.json", "stable.json", "manifest.json"] {
        let candidate = directory.join(name);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// Build the canonical install plan for one host.
fn build_plan(
    host: &str,
    manifest: &Manifest,
    manifest_path: &Path,
    manifest_sha256: &str,
) -> Result<Json, Refusal> {
    let root = state::default_root();
    let mut components: Vec<Json> = Vec::new();
    for component in &manifest.components {
        let artifact = component.artifact(
            host,
            target::platform(host)
                .map(|p| p.artifact_class)
                .unwrap_or(""),
        );
        components.push(Json::from_pairs(vec![
            ("component", Json::text(&component.component)),
            (
                "version",
                match &component.version {
                    Some(value) => Json::text(value),
                    None => Json::null(),
                },
            ),
            (
                "revision",
                match &component.revision {
                    Some(value) => Json::text(value),
                    None => Json::null(),
                },
            ),
            ("declared", Json::bool(component.declared)),
            ("needs_restart", Json::bool(component.needs_restart)),
            (
                "artifact",
                match artifact {
                    Some(artifact) => Json::from_pairs(vec![
                        ("platform", Json::text(&artifact.platform)),
                        ("class", Json::text(&artifact.class)),
                        ("url", Json::text(&artifact.url)),
                        ("sha256", Json::text(&artifact.sha256)),
                        ("size_bytes", Json::int(artifact.size_bytes)),
                    ]),
                    None => Json::null(),
                },
            ),
        ]));
    }
    Ok(Json::from_pairs(vec![
        ("plan_version", Json::int(1)),
        ("verb", Json::text("install")),
        ("host", Json::text(host)),
        (
            "install_root",
            match &root {
                Some(path) => Json::text(&path.display().to_string()),
                None => Json::null(),
            },
        ),
        ("channel", Json::text(&manifest.channel)),
        ("manifest", Json::text(&manifest_path.display().to_string())),
        ("manifest_sha256", Json::text(manifest_sha256)),
        ("published", Json::bool(manifest.published)),
        ("components", Json::array(components)),
        ("approval", approval_block()),
    ]))
}

fn approval_block() -> Json {
    Json::from_pairs(vec![
        ("state", Json::text("unapproved")),
        ("approve_digest", Json::null()),
    ])
}

/// Record a plan's own digest inside the plan document.
///
/// `plan_contract::approval_reasons` mirrors the canonical planner: it accepts an approval only
/// when the plan computes to the approved digest **and** the plan carries that digest in its own
/// `plan_digest` member. A plan this layer digests but never seals can therefore never be
/// approved - `--apply` would refuse every request, including a correct one, as
/// `plan_digest_not_approved`. Sealing is safe because `plan_digest` is excluded from the digest
/// body, so writing it does not change the digest it records.
fn seal(plan: &mut Json, digest: &str) -> Result<(), Refusal> {
    plan.set("plan_digest", Json::text(digest))
        .map_err(|error| {
            Refusal::validation(
                "plan_unbuildable",
                format!("the plan digest could not be recorded in the plan: {error}"),
            )
        })
}

/// Verify every artifact this host would receive.
///
/// A local release set resolves bytes from its own directory; otherwise the local artifact cache
/// is used. An artifact that is not available locally is a refusal, never a silent skip: an
/// unverified artifact must not be mistaken for a verified one.
fn verify_artifacts(set: &ReleaseSet) -> Result<Vec<Json>, Refusal> {
    let host = set.plan.get("host").and_then(Json::as_text).unwrap_or("");
    let Some(components) = set.plan.get("components").and_then(Json::as_array) else {
        return Ok(Vec::new());
    };
    let mut verified: Vec<Json> = Vec::new();
    for entry in components {
        let Some(object) = entry.as_object() else {
            continue;
        };
        let Some(artifact) = object.get("artifact").and_then(Json::as_object) else {
            continue;
        };
        let url = artifact.get("url").and_then(Json::as_text).unwrap_or("");
        let digest = artifact.get("sha256").and_then(Json::as_text).unwrap_or("");
        let size = artifact
            .get("size_bytes")
            .and_then(Json::as_int)
            .unwrap_or(0);
        let component = object
            .get("component")
            .and_then(Json::as_text)
            .unwrap_or("?");
        let path = resolve_local(set.local_root.as_deref(), url).ok_or_else(|| {
            Refusal::not_ready(
                "artifact_unreachable",
                format!(
                    "artifact for `{component}` ({url}) is not available locally for host {host}; \
                     this wave resolves artifacts from a local release set or the local artifact \
                     cache and never fetches from the network"
                ),
            )
        })?;
        fetch::verify_file(&path, digest, size).map_err(|refusal| {
            Refusal::validation(
                format!("artifact_unverified:{component}"),
                format!(
                    "artifact for `{component}` at {} failed verification: {}",
                    path.display(),
                    refusal.message
                ),
            )
        })?;
        verified.push(Json::from_pairs(vec![
            ("component", Json::text(component)),
            ("url", Json::text(url)),
            ("sha256", Json::text(digest)),
            ("size_bytes", Json::int(size)),
            ("resolved", Json::text(&path.display().to_string())),
            ("verified", Json::bool(true)),
        ]));
    }
    Ok(verified)
}

/// Resolve one artifact URL to a local file: the release-set directory first, then the cache.
fn resolve_local(local_root: Option<&Path>, url: &str) -> Option<PathBuf> {
    let name = fetch::url_basename(url)?;
    if let Some(root) = local_root {
        let candidate = root.join(&name);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    let cache = fetch::cache_dir()?;
    let candidate = cache.join(&name);
    if candidate.is_file() {
        return Some(candidate);
    }
    None
}

fn plan_lines(set: &ReleaseSet) -> Vec<String> {
    let mut lines = Vec::new();
    let host = set.plan.get("host").and_then(Json::as_text).unwrap_or("?");
    lines.push(format!(
        "target: {host} (evidence target {})",
        target::evidence_target_for(host)
    ));
    lines.push(format!(
        "release set: {} (sha256 {})",
        set.manifest_source, set.manifest_sha256
    ));
    lines.push(format!(
        "channel: {} published={}",
        set.manifest.channel, set.manifest.published
    ));
    if let Some(components) = set.plan.get("components").and_then(Json::as_array) {
        for entry in components {
            let Some(object) = entry.as_object() else {
                continue;
            };
            let component = object
                .get("component")
                .and_then(Json::as_text)
                .unwrap_or("?");
            let version = object
                .get("version")
                .and_then(Json::as_text)
                .unwrap_or("undeclared");
            let artifact = object
                .get("artifact")
                .and_then(Json::as_object)
                .map(|_| "artifact declared")
                .unwrap_or("no artifact for this host");
            lines.push(format!("  {component} {version} - {artifact}"));
        }
    }
    lines.push(format!("plan digest: {}", set.plan_digest));
    lines
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::update::json::Json;

    /// A minimal plan body shaped like the distribution plan, without a digest member.
    fn plan_body() -> Json {
        Json::from_pairs(vec![
            ("plan_version", Json::int(1)),
            ("verb", Json::text("install")),
            ("host", Json::text("macos-x64")),
            ("install_root", Json::text("/fixture/root")),
        ])
    }

    #[test]
    fn sealing_records_the_digest_without_changing_it() {
        let mut plan = plan_body();
        let before = plan_contract::digest(&plan).expect("the plan must digest");
        seal(&mut plan, &before).expect("sealing must succeed");
        assert_eq!(
            plan.get("plan_digest").and_then(Json::as_text),
            Some(before.as_str())
        );
        assert_eq!(
            plan_contract::digest(&plan).expect("the sealed plan must digest"),
            before,
            "`plan_digest` is excluded from the digest body, so sealing must not change the digest"
        );
    }

    #[test]
    fn an_unsealed_plan_can_never_be_approved() {
        // This is the regression guard for the defect this module fixed: the canonical approval
        // boundary requires the plan to carry its own digest, so a plan that is digested but not
        // sealed is refused even when the caller passes the exactly-correct digest.
        let plan = plan_body();
        let digest = plan_contract::digest(&plan).expect("the plan must digest");
        assert_eq!(
            plan_contract::approval_reasons(&plan, &digest),
            vec!["plan_digest_not_approved".to_string()]
        );
    }

    #[test]
    fn a_sealed_plan_is_approved_by_its_own_digest() {
        let mut plan = plan_body();
        let digest = plan_contract::digest(&plan).expect("the plan must digest");
        seal(&mut plan, &digest).expect("sealing must succeed");
        assert!(
            plan_contract::approval_reasons(&plan, &digest).is_empty(),
            "a sealed plan must be accepted by the approval boundary"
        );
    }

    #[test]
    fn a_sealed_plan_still_refuses_a_wrong_digest() {
        let mut plan = plan_body();
        let digest = plan_contract::digest(&plan).expect("the plan must digest");
        seal(&mut plan, &digest).expect("sealing must succeed");
        let wrong = "b".repeat(64);
        let reasons = plan_contract::approval_reasons(&plan, &wrong);
        assert!(
            reasons.contains(&"approval_stale".to_string()),
            "a wrong approval must stay stale: {reasons:?}"
        );
    }

    #[test]
    fn the_uninstall_plan_carries_no_volatile_timestamp() {
        // A plan whose digest body contains the observation time can never be re-derived on a
        // later `--apply`, so it could never be approved. The plan must be a pure function of its
        // decision inputs; the observation time belongs on the report, not in the plan.
        let state = state::State::new(PathBuf::from("/fixture/root"));
        let plan = uninstall_plan(&state, false).expect("the plan must build");
        assert!(
            plan.get("generated_at").is_none(),
            "the plan body must not carry a volatile timestamp: {plan:?}"
        );
        assert!(plan.get("created_at").is_none());
    }

    #[test]
    fn embedded_engine_plan_changes_outer_digest() {
        let mut first = plan_body();
        first
            .set(
                "engine_plan",
                Json::from_pairs(vec![
                    ("plan_digest", Json::text(&"a".repeat(64))),
                    ("owned", Json::text("one")),
                ]),
            )
            .unwrap();
        let mut second = first.clone();
        second
            .set(
                "engine_plan",
                Json::from_pairs(vec![
                    ("plan_digest", Json::text(&"b".repeat(64))),
                    ("owned", Json::text("two")),
                ]),
            )
            .unwrap();
        assert_ne!(
            plan_contract::digest(&first),
            plan_contract::digest(&second)
        );
    }

    #[test]
    fn marker_cleanup_only_removes_approved_bytes() {
        let temp = std::env::temp_dir().join(format!("axiom-cli-marker-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&temp);
        std::fs::create_dir_all(&temp).unwrap();
        let path = temp.join("installed.json");
        std::fs::write(&path, b"owned").unwrap();
        let digest = crate::update::sha256::hex(&crate::update::sha256::digest(b"owned"));
        clear_installed_marker(&temp, Some(&digest)).unwrap();
        assert!(!path.exists());
        std::fs::write(&path, b"edited").unwrap();
        assert!(clear_installed_marker(&temp, Some(&digest)).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"edited");
        std::fs::remove_file(&path).unwrap();
        clear_installed_marker(&temp, None).unwrap();
        std::fs::remove_dir_all(temp).unwrap();
    }
}
