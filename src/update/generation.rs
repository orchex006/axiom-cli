//! The generation record: what one verified generation of the install root contains.
//!
//! A generation is the unit the atomic swap moves between. It owns the payload bytes that were
//! verified before use, the digests they were verified against, and the owner-declared health
//! probe of every component that changed. The previous generation is kept until the new one has
//! passed its health check, which is what makes a rollback a pointer move rather than a
//! re-download.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use super::error::{Class, Refusal};
use super::json::{canonical_text, Json};
use super::state::{self, State};
use super::time::Stamp;

/// Schema version of a generation record.
pub const GENERATION_SCHEMA_VERSION: i64 = 1;

/// An owner-declared post-swap probe, copied from the recorded channel manifest.
#[derive(Clone, Debug)]
pub struct Probe {
    /// Program to execute.
    pub program: String,
    /// Arguments, as argv.
    pub args: Vec<String>,
    /// Required exit code.
    pub expect_exit: i64,
}

impl Probe {
    /// Render as JSON.
    pub fn to_json(&self) -> Json {
        Json::from_pairs(vec![
            ("program", Json::text(&self.program)),
            (
                "args",
                Json::text_array(&self.args.iter().map(String::as_str).collect::<Vec<&str>>()),
            ),
            ("expect_exit", Json::int(self.expect_exit)),
        ])
    }

    /// Parse from a JSON object.
    pub fn from_json(value: &Json) -> Result<Probe, Refusal> {
        let object = value.as_object().ok_or_else(|| {
            Refusal::validation("generation_probe_not_object", "a probe must be an object")
        })?;
        let program = object
            .get("program")
            .and_then(Json::as_text)
            .filter(|text| !text.trim().is_empty())
            .ok_or_else(|| {
                Refusal::validation(
                    "generation_probe_invalid",
                    "a probe requires a non-empty string `program`",
                )
            })?;
        let args = object
            .get("args")
            .and_then(Json::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(Json::as_text)
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default();
        Ok(Probe {
            program: program.to_string(),
            args,
            expect_exit: object
                .get("expect_exit")
                .and_then(Json::as_int)
                .unwrap_or(0),
        })
    }
}

/// One component of one generation.
#[derive(Clone, Debug)]
pub struct Entry {
    /// Component id.
    pub component: String,
    /// Plan action that produced this entry.
    pub action: String,
    /// Target version.
    pub version: String,
    /// Target revision.
    pub revision: String,
    /// Digest the payload was verified against.
    pub artifact_sha256: String,
    /// Verified payload path, forward-slash and relative to the generation directory.
    ///
    /// Absent for a `noop` entry, whose bytes stay in the previous generation.
    pub payload: Option<String>,
    /// Whether the component must be restarted once the generation is active.
    pub needs_restart: bool,
    /// Owner-declared post-swap probe, when the recorded manifest declared one.
    pub probe: Option<Probe>,
}

impl Entry {
    fn to_json(&self) -> Json {
        Json::from_pairs(vec![
            ("component", Json::text(&self.component)),
            ("action", Json::text(&self.action)),
            ("version", Json::text(&self.version)),
            ("revision", Json::text(&self.revision)),
            ("artifact_sha256", Json::text(&self.artifact_sha256)),
            (
                "payload",
                match &self.payload {
                    Some(path) => Json::text(path),
                    None => Json::null(),
                },
            ),
            ("needs_restart", Json::bool(self.needs_restart)),
            (
                "probe",
                match &self.probe {
                    Some(probe) => probe.to_json(),
                    None => Json::null(),
                },
            ),
        ])
    }
}

/// One generation of the install root.
#[derive(Clone, Debug)]
pub struct Generation {
    /// Schema version.
    pub schema_version: i64,
    /// Generation id, a single safe path segment.
    pub generation_id: String,
    /// Transaction that produced it.
    pub transaction_id: String,
    /// Plan id it was built from.
    pub plan_id: String,
    /// Plan digest it was built from.
    pub plan_digest: String,
    /// Channel.
    pub channel: String,
    /// Target host.
    pub host: String,
    /// Install root.
    pub install_root: String,
    /// When the generation was recorded.
    pub created_at: Stamp,
    /// One entry per planned component, in plan order.
    pub entries: Vec<Entry>,
}

impl Generation {
    /// Render as JSON.
    pub fn to_json(&self) -> Json {
        Json::from_pairs(vec![
            ("schema_version", Json::int(self.schema_version)),
            ("generation_id", Json::text(&self.generation_id)),
            ("transaction_id", Json::text(&self.transaction_id)),
            ("plan_id", Json::text(&self.plan_id)),
            ("plan_digest", Json::text(&self.plan_digest)),
            ("channel", Json::text(&self.channel)),
            ("host", Json::text(&self.host)),
            ("install_root", Json::text(&self.install_root)),
            ("created_at", Json::text(&self.created_at.format())),
            (
                "components",
                Json::array(self.entries.iter().map(Entry::to_json).collect()),
            ),
        ])
    }

    /// Canonical text form.
    pub fn to_text(&self) -> String {
        canonical_text(&self.to_json())
    }

    /// Parse a generation document.
    pub fn parse(text: &str) -> Result<Generation, Refusal> {
        let value = super::json::parse(text).map_err(|error| {
            Refusal::validation(
                "generation_not_json",
                format!("the generation record is not valid JSON: {error}"),
            )
        })?;
        let object = value.as_object().ok_or_else(|| {
            Refusal::validation(
                "generation_not_object",
                "the generation record must be an object",
            )
        })?;
        let required = |key: &str| -> Result<String, Refusal> {
            object
                .get(key)
                .and_then(Json::as_text)
                .filter(|text| !text.trim().is_empty())
                .map(str::to_string)
                .ok_or_else(|| {
                    Refusal::validation(
                        "invalid_generation_record",
                        format!("the generation record requires string `{key}`"),
                    )
                })
        };
        let schema_version = object.get("schema_version").and_then(Json::as_int);
        if schema_version != Some(GENERATION_SCHEMA_VERSION) {
            return Err(Refusal::validation(
                "unsupported_generation_schema_version",
                format!(
                    "generation schema_version {schema_version:?} is not supported; this CLI \
                     reads version {GENERATION_SCHEMA_VERSION}"
                ),
            ));
        }
        let mut entries = Vec::new();
        for item in object
            .get("components")
            .and_then(Json::as_array)
            .ok_or_else(|| {
                Refusal::validation(
                    "invalid_generation_record",
                    "the generation record requires a `components` array",
                )
            })?
        {
            let entry = item.as_object().ok_or_else(|| {
                Refusal::validation(
                    "invalid_generation_record",
                    "every generation component entry must be an object",
                )
            })?;
            let field = |key: &str| -> Result<String, Refusal> {
                entry
                    .get(key)
                    .and_then(Json::as_text)
                    .map(str::to_string)
                    .ok_or_else(|| {
                        Refusal::validation(
                            "invalid_generation_record",
                            format!("a generation component entry requires string `{key}`"),
                        )
                    })
            };
            let payload = match entry.get("payload") {
                None | Some(Json::Null) => None,
                Some(value) => {
                    let text = value.as_text().unwrap_or("");
                    if !super::rules::is_relative_path(text) {
                        return Err(Refusal::validation(
                            "invalid_generation_record",
                            format!(
                                "generation payload `{text}` is not a forward-slash relative path"
                            ),
                        ));
                    }
                    Some(text.to_string())
                }
            };
            let probe = match entry.get("probe") {
                None | Some(Json::Null) => None,
                Some(value) => Some(Probe::from_json(value)?),
            };
            entries.push(Entry {
                component: field("component")?,
                action: field("action")?,
                version: field("version")?,
                revision: field("revision")?,
                artifact_sha256: field("artifact_sha256")?,
                payload,
                needs_restart: entry
                    .get("needs_restart")
                    .and_then(Json::as_bool)
                    .unwrap_or(false),
                probe,
            });
        }
        Ok(Generation {
            schema_version: GENERATION_SCHEMA_VERSION,
            generation_id: required("generation_id")?,
            transaction_id: required("transaction_id")?,
            plan_id: required("plan_id")?,
            plan_digest: required("plan_digest")?,
            channel: required("channel")?,
            host: required("host")?,
            install_root: required("install_root")?,
            created_at: object
                .get("created_at")
                .and_then(Json::as_text)
                .and_then(|text| Stamp::parse(text).ok())
                .ok_or_else(|| {
                    Refusal::validation(
                        "invalid_generation_record",
                        "the generation record requires a `created_at` UTC timestamp",
                    )
                })?,
            entries,
        })
    }

    /// Read one generation from the install root.
    pub fn read(state: &State, generation_id: &str) -> Result<Generation, Refusal> {
        if !state::generation_id_ok(generation_id) {
            return Err(Refusal::validation(
                "invalid_generation_id",
                format!("`{generation_id}` is not a valid generation id"),
            ));
        }
        let path = state.generation_record_path(generation_id);
        if !path.is_file() {
            return Err(Refusal::new(
                Class::NotFound,
                "generation_missing",
                format!(
                    "generation `{generation_id}` is not recorded at {}",
                    path.display()
                ),
            ));
        }
        let text = std::fs::read_to_string(&path).map_err(|error| {
            Refusal::io("generation_unreadable", &path.display().to_string(), &error)
        })?;
        Generation::parse(&text)
    }

    /// Write the record into its generation directory.
    pub fn write(&self, directory: &Path) -> Result<(), Refusal> {
        let path = directory.join(state::GENERATION_FILE);
        let temporary = path.with_extension("json.tmp");
        state::write_atomic(&temporary, &path, self.to_text().as_bytes())
    }

    /// Re-verify every payload digest this generation records.
    ///
    /// This runs both before the swap and after it, so the health check is not a separate
    /// convention: the bytes that were accepted are the bytes that are still on disk.
    pub fn verify(&self, directory: &Path) -> Result<(), Refusal> {
        for entry in &self.entries {
            let Some(relative) = entry.payload.as_deref() else {
                continue;
            };
            let path = directory.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR));
            if !path.is_file() {
                return Err(Refusal::validation(
                    format!("payload_missing:{}", entry.component),
                    format!(
                        "generation {} records payload {} for `{}` but the file is absent",
                        self.generation_id, relative, entry.component
                    ),
                ));
            }
            let observed = state::digest_file(&path, "payload_unreadable")?;
            if observed != entry.artifact_sha256 {
                return Err(Refusal::validation(
                    format!("payload_digest_mismatch:{}", entry.component),
                    format!(
                        "generation {} payload {} for `{}` digests to {} but was verified against \
                         {}: the bytes on disk are not the bytes that were verified",
                        self.generation_id,
                        relative,
                        entry.component,
                        observed,
                        entry.artifact_sha256
                    ),
                ));
            }
        }
        Ok(())
    }

    /// Installed version and revision per component, for the next plan.
    pub fn installed_versions(&self) -> BTreeMap<String, (Option<String>, Option<String>)> {
        let mut map = BTreeMap::new();
        for entry in &self.entries {
            map.insert(
                entry.component.clone(),
                (Some(entry.version.clone()), Some(entry.revision.clone())),
            );
        }
        map
    }

    /// Components that must be restarted once this generation is active.
    pub fn needs_restart(&self) -> Vec<String> {
        self.entries
            .iter()
            .filter(|entry| entry.needs_restart)
            .map(|entry| entry.component.clone())
            .collect()
    }

    /// Components that changed in this generation.
    pub fn changed(&self) -> Vec<String> {
        self.entries
            .iter()
            .filter(|entry| entry.action != "noop")
            .map(|entry| entry.component.clone())
            .collect()
    }

    /// The payload path of one component, if this generation carries bytes for it.
    pub fn payload_path(&self, directory: &Path, component: &str) -> Option<PathBuf> {
        let entry = self
            .entries
            .iter()
            .find(|item| item.component == component)?;
        let relative = entry.payload.as_deref()?;
        Some(directory.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR)))
    }
}

/// Keep only the named generations; everything else under `generations/` is removed.
///
/// This is what bounds the retained set to the active generation and its predecessor, so
/// "the previous generation is kept until the new one is verified" stays literally true
/// instead of growing without limit.
pub fn prune(state: &State, keep: &[String]) -> Result<Vec<String>, Refusal> {
    let directory = state.generations_dir();
    if !directory.is_dir() {
        return Ok(Vec::new());
    }
    let entries = std::fs::read_dir(&directory).map_err(|error| {
        Refusal::io(
            "generations_unreadable",
            &directory.display().to_string(),
            &error,
        )
    })?;
    let mut removed = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|error| {
            Refusal::io(
                "generations_unreadable",
                &directory.display().to_string(),
                &error,
            )
        })?;
        let name = entry.file_name().to_string_lossy().to_string();
        if keep.iter().any(|id| id == &name) {
            continue;
        }
        if !entry.path().is_dir() {
            continue;
        }
        std::fs::remove_dir_all(entry.path()).map_err(|error| {
            Refusal::io(
                "generation_prune_failed",
                &entry.path().display().to_string(),
                &error,
            )
        })?;
        removed.push(name);
    }
    removed.sort();
    Ok(removed)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn generation() -> Generation {
        Generation {
            schema_version: GENERATION_SCHEMA_VERSION,
            generation_id: "g-20260920t000000z-00000001".to_string(),
            transaction_id: "t-20260920t000000z-00000001".to_string(),
            plan_id: "update-stable-axiom-cli".to_string(),
            plan_digest: "c".repeat(64),
            channel: "stable".to_string(),
            host: "windows-x64".to_string(),
            install_root: "D:/fixture/root".to_string(),
            created_at: Stamp::from_seconds(1_789_000_000),
            entries: vec![
                Entry {
                    component: "axiom-cli".to_string(),
                    action: "install".to_string(),
                    version: "0.0.0-dev".to_string(),
                    revision: "7ac376b5e5e0f52f4fe3af7fb97971d220277d38".to_string(),
                    artifact_sha256: "d".repeat(64),
                    payload: Some("payload/axiom-cli/axiom-cli.exe".to_string()),
                    needs_restart: true,
                    probe: Some(Probe {
                        program: "D:/tools/probe.exe".to_string(),
                        args: vec!["--version".to_string()],
                        expect_exit: 0,
                    }),
                },
                Entry {
                    component: "axiom-mcp".to_string(),
                    action: "noop".to_string(),
                    version: "0.1.0".to_string(),
                    revision: "cebd159e12b283e3638feffc4cecfa033070cf66".to_string(),
                    artifact_sha256: "e".repeat(64),
                    payload: None,
                    needs_restart: false,
                    probe: None,
                },
            ],
        }
    }

    #[test]
    fn a_generation_round_trips_with_its_probe() {
        let value = generation();
        let parsed = Generation::parse(&value.to_text()).expect("must parse");
        assert_eq!(parsed.generation_id, value.generation_id);
        assert_eq!(parsed.entries.len(), 2);
        assert_eq!(
            parsed.entries[0].payload.as_deref(),
            Some("payload/axiom-cli/axiom-cli.exe")
        );
        let probe = parsed.entries[0].probe.as_ref().expect("probe survives");
        assert_eq!(probe.expect_exit, 0);
        assert_eq!(probe.args, vec!["--version".to_string()]);
        assert!(parsed.entries[1].probe.is_none());
    }

    #[test]
    fn a_backslash_payload_path_is_refused() {
        let value = generation().to_json();
        let mut object = value.as_object().unwrap().clone();
        let mut entries = object
            .get("components")
            .unwrap()
            .as_array()
            .unwrap()
            .to_vec();
        entries[0]
            .set("payload", Json::text("payload\\axiom-cli\\axiom-cli.exe"))
            .unwrap();
        object.insert("components".to_string(), Json::array(entries));
        let text = canonical_text(&Json::Object(object));
        let error = Generation::parse(&text).expect_err("must refuse");
        assert_eq!(error.reason, "invalid_generation_record");
    }

    #[test]
    fn a_generation_id_with_a_separator_cannot_be_read() {
        let state = State::new("D:/fixture/root");
        let error = Generation::read(&state, "../../escape").expect_err("must refuse");
        assert_eq!(error.reason, "invalid_generation_id");
    }

    #[test]
    fn the_installed_map_and_restart_set_follow_the_entries() {
        let value = generation();
        let map = value.installed_versions();
        assert_eq!(
            map.get("axiom-cli").cloned(),
            Some((
                Some("0.0.0-dev".to_string()),
                Some("7ac376b5e5e0f52f4fe3af7fb97971d220277d38".to_string())
            ))
        );
        assert_eq!(value.needs_restart(), vec!["axiom-cli".to_string()]);
        assert_eq!(value.changed(), vec!["axiom-cli".to_string()]);
    }
}
