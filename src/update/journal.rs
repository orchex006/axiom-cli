//! The recovery journal of one update transaction.
//!
//! A transaction is interrupted whenever the process stops between the moment the previous
//! generation is still active and the moment the new one has passed its health check. The
//! journal is written before each such step, so the next invocation can tell which step was
//! reached and put the install root back into a consistent state instead of guessing.
//!
//! The rule this module exists for: a half-finished transaction must never be reported or left
//! as an applied update. Recovery either restores the previous generation or abandons work that
//! never changed the active generation, and it says which of the two it did.

use super::error::Refusal;
use super::json::{canonical_text, Json};
use super::state::State;
use super::time::Stamp;

/// Schema version of a journal document.
pub const JOURNAL_SCHEMA_VERSION: i64 = 1;

/// Journal states, in the order a transaction moves through them.
pub const STATE_STAGED: &str = "staged";
/// The new generation was swapped in; its health check has not been confirmed.
pub const STATE_SWAPPED: &str = "swapped";
/// The new generation passed its health check and is the active generation.
pub const STATE_FINALIZED: &str = "finalized";
/// The transaction rolled back to the previous generation.
pub const STATE_ROLLED_BACK: &str = "rolled_back";
/// Recovery abandoned work that never changed the active generation.
pub const STATE_ABANDONED: &str = "abandoned";

/// Whether a state means the transaction reached a settled outcome.
pub fn is_settled(state: &str) -> bool {
    matches!(state, STATE_FINALIZED | STATE_ROLLED_BACK | STATE_ABANDONED)
}

/// One transaction journal.
#[derive(Clone, Debug)]
pub struct Journal {
    /// Schema version.
    pub schema_version: i64,
    /// Transaction id.
    pub transaction_id: String,
    /// Plan id the transaction is applying.
    pub plan_id: String,
    /// Plan digest the transaction is applying.
    pub plan_digest: String,
    /// Channel.
    pub channel: String,
    /// Target host.
    pub host: String,
    /// Install root.
    pub install_root: String,
    /// Current state.
    pub state: String,
    /// When the transaction started.
    pub started_at: Stamp,
    /// When the journal was last written.
    pub updated_at: Stamp,
    /// The generation the transaction started from.
    pub from_generation: Option<String>,
    /// The generation the transaction was creating.
    pub to_generation: String,
    /// Components that must be restarted once the transaction settles.
    pub needs_restart: Vec<String>,
    /// One line per component, in plan order.
    pub actions: Vec<Json>,
}

impl Journal {
    /// Render as JSON.
    pub fn to_json(&self) -> Json {
        Json::from_pairs(vec![
            ("schema_version", Json::int(self.schema_version)),
            ("transaction_id", Json::text(&self.transaction_id)),
            ("plan_id", Json::text(&self.plan_id)),
            ("plan_digest", Json::text(&self.plan_digest)),
            ("channel", Json::text(&self.channel)),
            ("host", Json::text(&self.host)),
            ("install_root", Json::text(&self.install_root)),
            ("state", Json::text(&self.state)),
            ("started_at", Json::text(&self.started_at.format())),
            ("updated_at", Json::text(&self.updated_at.format())),
            (
                "from_generation",
                match &self.from_generation {
                    Some(id) => Json::text(id),
                    None => Json::null(),
                },
            ),
            ("to_generation", Json::text(&self.to_generation)),
            (
                "needs_restart",
                Json::text_array(
                    &self
                        .needs_restart
                        .iter()
                        .map(String::as_str)
                        .collect::<Vec<&str>>(),
                ),
            ),
            ("actions", Json::array(self.actions.clone())),
        ])
    }

    /// Canonical text form.
    pub fn to_text(&self) -> String {
        canonical_text(&self.to_json())
    }

    /// Move to a new state and stamp the update time.
    pub fn advance(&mut self, state: &str, now: Stamp) {
        self.state = state.to_string();
        self.updated_at = now;
    }

    /// Parse a journal document.
    pub fn parse(text: &str) -> Result<Journal, Refusal> {
        let value = super::json::parse(text).map_err(|error| {
            Refusal::validation(
                "journal_not_json",
                format!("the recovery journal is not valid JSON: {error}"),
            )
        })?;
        let object = value.as_object().ok_or_else(|| {
            Refusal::validation(
                "journal_not_object",
                "the recovery journal must be an object",
            )
        })?;
        let text_field = |key: &str| -> Option<String> {
            object.get(key).and_then(Json::as_text).map(str::to_string)
        };
        let schema_version = object.get("schema_version").and_then(Json::as_int);
        if schema_version != Some(JOURNAL_SCHEMA_VERSION) {
            return Err(Refusal::validation(
                "unsupported_journal_schema_version",
                format!(
                    "recovery journal schema_version {schema_version:?} is not supported; this \
                     CLI reads version {JOURNAL_SCHEMA_VERSION}"
                ),
            ));
        }
        let required = |key: &str| -> Result<String, Refusal> {
            text_field(key).ok_or_else(|| {
                Refusal::validation(
                    "invalid_journal_record",
                    format!("the recovery journal requires string `{key}`"),
                )
            })
        };
        let stamp = |key: &str, fallback: Stamp| -> Stamp {
            text_field(key)
                .and_then(|text| Stamp::parse(&text).ok())
                .unwrap_or(fallback)
        };
        let epoch = Stamp::from_seconds(0);
        Ok(Journal {
            schema_version: JOURNAL_SCHEMA_VERSION,
            transaction_id: required("transaction_id")?,
            plan_id: required("plan_id")?,
            plan_digest: required("plan_digest")?,
            channel: required("channel")?,
            host: required("host")?,
            install_root: required("install_root")?,
            state: required("state")?,
            started_at: stamp("started_at", epoch),
            updated_at: stamp("updated_at", epoch),
            from_generation: match object.get("from_generation") {
                None | Some(Json::Null) => None,
                Some(value) => Some(
                    value
                        .as_text()
                        .ok_or_else(|| {
                            Refusal::validation(
                                "invalid_journal_record",
                                "`from_generation` must be null or a generation id",
                            )
                        })?
                        .to_string(),
                ),
            },
            to_generation: required("to_generation")?,
            needs_restart: object
                .get("needs_restart")
                .and_then(Json::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(Json::as_text)
                        .map(str::to_string)
                        .collect()
                })
                .unwrap_or_default(),
            actions: object
                .get("actions")
                .and_then(Json::as_array)
                .map(|items| items.to_vec())
                .unwrap_or_default(),
        })
    }
}

/// Write a journal, replacing any previous revision atomically.
pub fn write(state: &State, journal: &Journal) -> Result<(), Refusal> {
    let path = state.journal_path(&journal.transaction_id);
    let temporary = path.with_extension("json.tmp");
    super::state::write_atomic(&temporary, &path, journal.to_text().as_bytes())
}

/// Read one journal.
pub fn read(state: &State, transaction_id: &str) -> Result<Journal, Refusal> {
    let path = state.journal_path(transaction_id);
    if !path.is_file() {
        return Err(Refusal::new(
            super::error::Class::NotFound,
            "transaction_unknown",
            format!(
                "no update transaction `{transaction_id}` is recorded at {}",
                path.display()
            ),
        ));
    }
    let text = std::fs::read_to_string(&path)
        .map_err(|error| Refusal::io("journal_unreadable", &path.display().to_string(), &error))?;
    Journal::parse(&text)
}

/// Every unsettled journal in the install root, oldest first.
pub fn unfinished(state: &State) -> Result<Vec<Journal>, Refusal> {
    let directory = state.journal_dir();
    if !directory.is_dir() {
        return Ok(Vec::new());
    }
    let entries = std::fs::read_dir(&directory).map_err(|error| {
        Refusal::io(
            "journal_unreadable",
            &directory.display().to_string(),
            &error,
        )
    })?;
    let mut journals: Vec<Journal> = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|error| {
            Refusal::io(
                "journal_unreadable",
                &directory.display().to_string(),
                &error,
            )
        })?;
        let path = entry.path();
        if path.extension().and_then(|value| value.to_str()) != Some("json") {
            continue;
        }
        let text = std::fs::read_to_string(&path).map_err(|error| {
            Refusal::io("journal_unreadable", &path.display().to_string(), &error)
        })?;
        let journal = Journal::parse(&text)?;
        if !is_settled(&journal.state) {
            journals.push(journal);
        }
    }
    journals.sort_by_key(|journal| journal.started_at.seconds());
    Ok(journals)
}

/// The result of a recovery pass.
#[derive(Clone, Debug, Default)]
pub struct Recovery {
    /// Transactions acted on, one line each.
    pub actions: Vec<String>,
}

impl Recovery {
    /// Whether anything was repaired.
    pub fn acted(&self) -> bool {
        !self.actions.is_empty()
    }
}

/// Put the install root back into a consistent state after an interrupted transaction.
///
/// The two cases are distinguished by what the active generation record says, not by trusting
/// the journal alone: a journal can be one step behind the disk when the process was stopped,
/// so the record is what decides whether the swap already happened.
pub fn recover(state: &State) -> Result<Recovery, Refusal> {
    let mut recovery = Recovery::default();
    let installed = if state.has_installed() {
        Some(state.read_installed()?)
    } else {
        None
    };
    for mut journal in unfinished(state)? {
        let now = Stamp::now();
        let swapped = installed
            .as_ref()
            .map(|record| record.current_generation == journal.to_generation)
            .unwrap_or(false);
        if swapped {
            let restored = journal.from_generation.clone().ok_or_else(|| {
                Refusal::new(
                    super::error::Class::Conflict,
                    "recovery_target_missing",
                    format!(
                        "transaction {} was interrupted after the swap but records no \
                             previous generation to restore",
                        journal.transaction_id
                    ),
                )
            })?;
            let mut record = installed
                .clone()
                .expect("swapped implies an installed record");
            record.current_generation = restored.clone();
            record.previous_generation = Some(journal.to_generation.clone());
            record.installed_at = now;
            state.write_installed(&record)?;
            journal.advance(STATE_ROLLED_BACK, now);
            write(state, &journal)?;
            recovery.actions.push(format!(
                "transaction {} was interrupted after the swap: restored generation {} and left \
                 generation {} retained as the previous generation",
                journal.transaction_id, restored, journal.to_generation
            ));
        } else {
            let tree = state.staging_tree(&journal.transaction_id);
            if tree.is_dir() {
                std::fs::remove_dir_all(&tree).map_err(|error| {
                    Refusal::io(
                        "staging_cleanup_failed",
                        &tree.display().to_string(),
                        &error,
                    )
                })?;
            }
            journal.advance(STATE_ABANDONED, now);
            write(state, &journal)?;
            recovery.actions.push(format!(
                "transaction {} never changed the active generation: discarded its staging tree \
                 and marked it abandoned",
                journal.transaction_id
            ));
        }
        let lock = state.lock_path();
        if lock.is_file() {
            let text = std::fs::read_to_string(&lock).unwrap_or_default();
            if text.contains(&journal.transaction_id) {
                std::fs::remove_file(&lock).map_err(|error| {
                    Refusal::io("lock_release_failed", &lock.display().to_string(), &error)
                })?;
                recovery.actions.push(format!(
                    "released the coordinator lock left behind by transaction {}",
                    journal.transaction_id
                ));
            }
        }
    }
    Ok(recovery)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn journal() -> Journal {
        Journal {
            schema_version: JOURNAL_SCHEMA_VERSION,
            transaction_id: "t-20260920t000000z-00000001".to_string(),
            plan_id: "update-stable-axiom-cli".to_string(),
            plan_digest: "b".repeat(64),
            channel: "stable".to_string(),
            host: "windows-x64".to_string(),
            install_root: "D:/fixture/root".to_string(),
            state: STATE_STAGED.to_string(),
            started_at: Stamp::from_seconds(1_789_000_000),
            updated_at: Stamp::from_seconds(1_789_000_000),
            from_generation: Some("g-20260920t000000z-00000001".to_string()),
            to_generation: "g-20260920t000100z-00000002".to_string(),
            needs_restart: vec!["axiom-cli".to_string()],
            actions: Vec::new(),
        }
    }

    #[test]
    fn a_journal_round_trips() {
        let value = journal();
        let parsed = Journal::parse(&value.to_text()).expect("must parse");
        assert_eq!(parsed.transaction_id, value.transaction_id);
        assert_eq!(parsed.state, STATE_STAGED);
        assert_eq!(parsed.from_generation, value.from_generation);
        assert_eq!(parsed.needs_restart, value.needs_restart);
    }

    #[test]
    fn only_settled_states_end_a_transaction() {
        assert!(is_settled(STATE_FINALIZED));
        assert!(is_settled(STATE_ROLLED_BACK));
        assert!(is_settled(STATE_ABANDONED));
        assert!(!is_settled(STATE_STAGED));
        assert!(!is_settled(STATE_SWAPPED));
        assert!(!is_settled("rolled_back_pending"));
    }

    #[test]
    fn advancing_journal_stamps_the_new_state() {
        let mut value = journal();
        value.advance(STATE_SWAPPED, Stamp::from_seconds(1_789_000_600));
        assert_eq!(value.state, STATE_SWAPPED);
        assert_eq!(value.updated_at.seconds(), 1_789_000_600);
        assert_eq!(value.started_at.seconds(), 1_789_000_000);
    }
}
