//! Install-root state: the installed release and the channel manifest it came from.
//!
//! The distribution contract freezes one rule above all others: the installed release records
//! the channel manifest it came from, and versions resolve **only** from that recorded
//! manifest. This module owns the on-disk record that makes that rule enforceable - the exact
//! manifest bytes and their digest - plus the generation bookkeeping the swap and rollback
//! need.
//!
//! ## Layout decision (task J-007)
//!
//! `src/update/` did not exist in this repository before J-007, so its path and the install
//! root layout below are decisions made here and recorded in `docs/50-UPDATE-CHANNEL.md`:
//!
//! ```text
//! <install-root>/
//!   installed.json                 active generation + recorded channel manifest digest
//!   recorded-manifest.json         the exact channel manifest bytes this release came from
//!   update.lock                    coordinator lock, one update transaction at a time
//!   generations/<id>/generation.json
//!   generations/<id>/payload/**    the verified artifact bytes of that generation
//!   staging/<transaction>/         staging area, renamed into place once verified
//!   journal/<transaction>.json     recovery journal for an interrupted transaction
//! ```
//!
//! Every path that reaches a contract document is written with forward slashes relative to the
//! install root, because the plan schema and the recovery journal are read on every platform.
//!
//! Nothing here touches user data, the graph output root or portable workspace state: the whole
//! update transaction lives inside the install root, which is why the root is a single explicit
//! value rather than a scatter of paths.

use std::path::{Path, PathBuf};

use super::channel::{self, Loaded, Manifest};
use super::error::Refusal;
use super::json;
use super::json::{canonical_text, Json};
use super::rules;
use super::sha256;
use super::time::Stamp;

/// Schema version of `installed.json`.
pub const STATE_SCHEMA_VERSION: i64 = 1;

/// Record of the active generation.
pub const INSTALLED_FILE: &str = "installed.json";
/// The exact channel manifest bytes the installed release came from.
pub const RECORDED_MANIFEST_FILE: &str = "recorded-manifest.json";
/// Directory holding every retained generation.
pub const GENERATIONS_DIR: &str = "generations";
/// Directory holding in-flight staging trees.
pub const STAGING_DIR: &str = "staging";
/// Directory holding recovery journals.
pub const JOURNAL_DIR: &str = "journal";
/// The single coordinator lock file.
pub const LOCK_FILE: &str = "update.lock";
/// Per-generation record file name.
pub const GENERATION_FILE: &str = "generation.json";
/// Per-generation verified payload directory name.
pub const PAYLOAD_DIR: &str = "payload";

/// Environment override for the install root. Documented so a fixture can be driven end to end.
pub const INSTALL_ROOT_ENV: &str = "AXIOM_CLI_INSTALL_ROOT";
/// Environment override naming a channel manifest to use while nothing is installed yet.
pub const CHANNEL_MANIFEST_ENV: &str = "AXIOM_CLI_CHANNEL_MANIFEST";
/// Environment override naming the local artifact cache used for offline acquisition.
pub const ARTIFACT_CACHE_ENV: &str = "AXIOM_CLI_ARTIFACT_CACHE";

/// The install root this process should use, if the host offers one.
///
/// The override wins so a test or a portable install can name its root explicitly; otherwise the
/// per-user data directory is used. No machine-wide location and no elevation: a distribution
/// layer that needs administrator rights to update itself is not per-user.
pub fn default_root() -> Option<PathBuf> {
    if let Ok(value) = std::env::var(INSTALL_ROOT_ENV) {
        if !value.trim().is_empty() {
            return Some(PathBuf::from(value));
        }
    }
    if cfg!(windows) {
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            if !local.trim().is_empty() {
                return Some(Path::new(&local).join("Axiom"));
            }
        }
    }
    if let Ok(data) = std::env::var("XDG_DATA_HOME") {
        if !data.trim().is_empty() {
            return Some(Path::new(&data).join("axiom"));
        }
    }
    let home = std::env::var("HOME")
        .ok()
        .or_else(|| std::env::var("USERPROFILE").ok())?;
    if home.trim().is_empty() {
        return None;
    }
    Some(Path::new(&home).join(".local").join("share").join("axiom"))
}

/// A generation id is a single safe path segment.
pub fn generation_id_ok(id: &str) -> bool {
    rules::is_plan_id(id)
}

/// The record of the active generation.
#[derive(Clone, Debug)]
pub struct Installed {
    /// Schema version.
    pub schema_version: i64,
    /// Channel the active release came from.
    pub channel: String,
    /// sha256 of the recorded channel manifest bytes.
    pub channel_manifest_sha256: String,
    /// The active generation id.
    pub current_generation: String,
    /// The generation the active one replaced, retained until the next swap.
    pub previous_generation: Option<String>,
    /// When the active generation was recorded.
    pub installed_at: Stamp,
}

impl Installed {
    /// Parse and validate an `installed.json` document.
    pub fn parse(text: &str) -> Result<Installed, Refusal> {
        let value = json::parse(text).map_err(|error| {
            Refusal::validation(
                "installed_not_json",
                format!("installed.json is not valid JSON: {error}"),
            )
        })?;
        let object = value.as_object().ok_or_else(|| {
            Refusal::validation("installed_not_object", "installed.json must be an object")
        })?;
        let schema_version = object.get("schema_version").and_then(Json::as_int);
        if schema_version != Some(STATE_SCHEMA_VERSION) {
            return Err(Refusal::validation(
                "unsupported_installed_schema_version",
                format!(
                    "installed.json schema_version {schema_version:?} is not supported; \
                     this CLI reads version {STATE_SCHEMA_VERSION}"
                ),
            ));
        }
        let channel = object
            .get("channel")
            .and_then(Json::as_text)
            .ok_or_else(|| {
                Refusal::validation(
                    "invalid_installed_record:channel",
                    "installed.json requires string `channel`",
                )
            })?;
        if !channel::CHANNEL_NAMES.contains(&channel) {
            return Err(Refusal::validation(
                "unsupported_installed_channel",
                format!(
                    "installed.json channel `{channel}` is not one of {:?}",
                    channel::CHANNEL_NAMES
                ),
            ));
        }
        let digest = object
            .get("channel_manifest_sha256")
            .and_then(Json::as_text)
            .unwrap_or("");
        if !rules::is_digest64(digest) {
            return Err(Refusal::validation(
                "invalid_installed_record:channel_manifest_sha256",
                "installed.json requires a 64-hex `channel_manifest_sha256`",
            ));
        }
        let current = object
            .get("current_generation")
            .and_then(Json::as_text)
            .unwrap_or("");
        if !generation_id_ok(current) {
            return Err(Refusal::validation(
                "invalid_installed_record:current_generation",
                "installed.json requires a single-segment `current_generation` id",
            ));
        }
        let previous = match object.get("previous_generation") {
            None | Some(Json::Null) => None,
            Some(value) => {
                let text = value.as_text().unwrap_or("");
                if !generation_id_ok(text) {
                    return Err(Refusal::validation(
                        "invalid_installed_record:previous_generation",
                        "`previous_generation` must be null or a single-segment generation id",
                    ));
                }
                Some(text.to_string())
            }
        };
        let installed_at = object
            .get("installed_at")
            .and_then(Json::as_text)
            .map(Stamp::parse)
            .transpose()
            .map_err(|error| {
                Refusal::validation(
                    "invalid_installed_record:installed_at",
                    format!("installed.json `installed_at` is not a UTC timestamp: {error}"),
                )
            })?
            .ok_or_else(|| {
                Refusal::validation(
                    "invalid_installed_record:installed_at",
                    "installed.json requires string `installed_at`",
                )
            })?;
        Ok(Installed {
            schema_version: STATE_SCHEMA_VERSION,
            channel: channel.to_string(),
            channel_manifest_sha256: digest.to_string(),
            current_generation: current.to_string(),
            previous_generation: previous,
            installed_at,
        })
    }

    /// Render the record as a JSON object.
    pub fn to_json(&self) -> Json {
        let mut object = Json::Object(Default::default());
        let _ = object.set("schema_version", Json::int(self.schema_version));
        let _ = object.set("channel", Json::text(&self.channel));
        let _ = object.set(
            "channel_manifest_sha256",
            Json::text(&self.channel_manifest_sha256),
        );
        let _ = object.set("current_generation", Json::text(&self.current_generation));
        let _ = object.set(
            "previous_generation",
            match &self.previous_generation {
                Some(id) => Json::text(id),
                None => Json::null(),
            },
        );
        let _ = object.set("installed_at", Json::text(&self.installed_at.format()));
        object
    }

    /// Canonical text form, so the record is byte-stable across a rewrite.
    pub fn to_text(&self) -> String {
        canonical_text(&self.to_json())
    }
}

/// The install root and the paths derived from it.
#[derive(Clone, Debug)]
pub struct State {
    root: PathBuf,
}

impl State {
    /// Wrap an install root. Nothing is created until a caller asks for a write.
    pub fn new(root: impl Into<PathBuf>) -> State {
        State { root: root.into() }
    }

    /// The install root.
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// `installed.json`.
    pub fn installed_path(&self) -> PathBuf {
        self.root.join(INSTALLED_FILE)
    }

    /// `recorded-manifest.json`.
    pub fn recorded_manifest_path(&self) -> PathBuf {
        self.root.join(RECORDED_MANIFEST_FILE)
    }

    /// `generations/`.
    pub fn generations_dir(&self) -> PathBuf {
        self.root.join(GENERATIONS_DIR)
    }

    /// `staging/`.
    pub fn staging_dir(&self) -> PathBuf {
        self.root.join(STAGING_DIR)
    }

    /// `journal/`.
    pub fn journal_dir(&self) -> PathBuf {
        self.root.join(JOURNAL_DIR)
    }

    /// `update.lock`.
    pub fn lock_path(&self) -> PathBuf {
        self.root.join(LOCK_FILE)
    }

    /// One generation directory.
    pub fn generation_dir(&self, id: &str) -> PathBuf {
        self.generations_dir().join(id)
    }

    /// One generation record.
    pub fn generation_record_path(&self, id: &str) -> PathBuf {
        self.generation_dir(id).join(GENERATION_FILE)
    }

    /// One staging tree.
    pub fn staging_tree(&self, transaction: &str) -> PathBuf {
        self.staging_dir().join(transaction)
    }

    /// One journal file.
    pub fn journal_path(&self, transaction: &str) -> PathBuf {
        self.journal_dir().join(format!("{transaction}.json"))
    }

    /// Whether an installed release is recorded.
    pub fn has_installed(&self) -> bool {
        self.installed_path().is_file()
    }

    /// Read the active generation record.
    pub fn read_installed(&self) -> Result<Installed, Refusal> {
        let path = self.installed_path();
        if !path.is_file() {
            return Err(Refusal::not_ready(
                "no_installed_release",
                format!(
                    "no installed release is recorded at {}/{}: the update channel resolves \
                     versions only from the manifest the installed release came from, and nothing \
                     is installed under {}",
                    self.root.display(),
                    INSTALLED_FILE,
                    self.root.display()
                ),
            ));
        }
        let text = std::fs::read_to_string(&path).map_err(|error| {
            Refusal::io("installed_unreadable", &path.display().to_string(), &error)
        })?;
        Installed::parse(&text)
    }

    /// Replace the active generation record atomically.
    ///
    /// The replacement is one `rename` over the destination, which Windows implements as
    /// `MoveFileEx` with replace-existing semantics and POSIX as `rename(2)`: a reader either
    /// sees the whole previous record or the whole new one, never a partial write.
    pub fn write_installed(&self, installed: &Installed) -> Result<(), Refusal> {
        let path = self.installed_path();
        let temporary = path.with_extension("json.tmp");
        std::fs::create_dir_all(&self.root).map_err(|error| {
            Refusal::io(
                "install_root_unwritable",
                &self.root.display().to_string(),
                &error,
            )
        })?;
        write_atomic(&temporary, &path, installed.to_text().as_bytes())
    }

    /// Persist the exact channel manifest bytes the installed release came from.
    pub fn record_manifest_bytes(&self, bytes: &[u8]) -> Result<(), Refusal> {
        let path = self.recorded_manifest_path();
        let temporary = path.with_extension("json.tmp");
        write_atomic(&temporary, &path, bytes)
    }

    /// Load the recorded channel manifest, verifying its digest against the installed record.
    ///
    /// The digest check is the point of the record: a manifest that changed on disk after it was
    /// recorded is no longer the manifest this release came from, so it is refused rather than
    /// silently used.
    pub fn load_recorded_manifest(&self, installed: &Installed) -> Result<Loaded, Refusal> {
        let path = self.recorded_manifest_path();
        if !path.is_file() {
            return Err(Refusal::not_ready(
                "no_recorded_channel_manifest",
                format!(
                    "the installed release does not record a channel manifest ({} is absent), so \
                     no version can be resolved",
                    path.display()
                ),
            ));
        }
        let loaded: Loaded = Manifest::load(&path).map_err(Refusal::from)?;
        if loaded.sha256 != installed.channel_manifest_sha256 {
            return Err(Refusal::validation(
                "recorded_manifest_digest_mismatch",
                format!(
                    "the recorded channel manifest {} now digests to {} but the installed record \
                     declares {}: the recorded manifest was changed after it was recorded",
                    path.display(),
                    loaded.sha256,
                    installed.channel_manifest_sha256
                ),
            ));
        }
        Ok(loaded)
    }

    /// Read a candidate channel manifest without touching the installed record.
    pub fn load_manifest_file(path: &Path) -> Result<Loaded, Refusal> {
        Manifest::load(path).map_err(Refusal::from)
    }
}

/// Bytes of a file, with an I/O refusal on failure.
pub fn read_bytes(path: &Path, reason: &str) -> Result<Vec<u8>, Refusal> {
    std::fs::read(path).map_err(|error| Refusal::io(reason, &path.display().to_string(), &error))
}

/// sha256 of a file, with an I/O refusal on failure.
pub fn digest_file(path: &Path, reason: &str) -> Result<String, Refusal> {
    sha256::file_hex(path).map_err(|error| Refusal::io(reason, &path.display().to_string(), &error))
}

/// Write bytes to `temporary`, then rename it over `destination`.
pub fn write_atomic(temporary: &Path, destination: &Path, bytes: &[u8]) -> Result<(), Refusal> {
    if let Some(parent) = destination.parent() {
        std::fs::create_dir_all(parent).map_err(|error| {
            Refusal::io(
                "directory_unwritable",
                &parent.display().to_string(),
                &error,
            )
        })?;
    }
    std::fs::write(temporary, bytes).map_err(|error| {
        Refusal::io(
            "temporary_write_failed",
            &temporary.display().to_string(),
            &error,
        )
    })?;
    if let Ok(handle) = std::fs::File::open(temporary) {
        let _ = handle.sync_all();
    }
    std::fs::rename(temporary, destination).map_err(|error| {
        Refusal::io(
            "atomic_replace_failed",
            &format!("{} -> {}", temporary.display(), destination.display()),
            &error,
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> Installed {
        Installed {
            schema_version: STATE_SCHEMA_VERSION,
            channel: "stable".to_string(),
            channel_manifest_sha256: "a".repeat(64),
            current_generation: "g-20260920t000000z-00000001".to_string(),
            previous_generation: None,
            installed_at: Stamp::from_seconds(1_789_000_000),
        }
    }

    #[test]
    fn a_record_round_trips_through_its_canonical_text() {
        let record = sample();
        let text = record.to_text();
        let parsed = Installed::parse(&text).expect("the record it wrote must parse");
        assert_eq!(parsed.channel, record.channel);
        assert_eq!(parsed.current_generation, record.current_generation);
        assert_eq!(
            parsed.channel_manifest_sha256,
            record.channel_manifest_sha256
        );
        assert!(parsed.previous_generation.is_none());
        assert_eq!(parsed.installed_at.seconds(), record.installed_at.seconds());
    }

    #[test]
    fn a_short_digest_is_refused_rather_than_trusted() {
        let mut value: Json = sample().to_json();
        value
            .set("channel_manifest_sha256", Json::text("deadbeef"))
            .unwrap();
        let error = Installed::parse(&canonical_text(&value)).expect_err("must refuse");
        assert_eq!(
            error.reason,
            "invalid_installed_record:channel_manifest_sha256"
        );
    }

    #[test]
    fn an_unknown_channel_name_is_refused() {
        let mut value: Json = sample().to_json();
        value.set("channel", Json::text("latest")).unwrap();
        let error = Installed::parse(&canonical_text(&value)).expect_err("must refuse");
        assert_eq!(error.reason, "unsupported_installed_channel");
    }

    #[test]
    fn a_generation_id_may_not_carry_a_separator() {
        let mut value: Json = sample().to_json();
        value
            .set("current_generation", Json::text("gen/../../escape"))
            .unwrap();
        let error = Installed::parse(&canonical_text(&value)).expect_err("must refuse");
        assert_eq!(error.reason, "invalid_installed_record:current_generation");
    }

    #[test]
    fn the_override_env_var_wins_for_the_install_root() {
        let previous = std::env::var(INSTALL_ROOT_ENV).ok();
        std::env::set_var(INSTALL_ROOT_ENV, "D:/fixture/root");
        assert_eq!(default_root(), Some(PathBuf::from("D:/fixture/root")));
        match previous {
            Some(value) => std::env::set_var(INSTALL_ROOT_ENV, value),
            None => std::env::remove_var(INSTALL_ROOT_ENV),
        }
    }
}
