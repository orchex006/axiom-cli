//! The axiom-cli update channel (task J-007).
//!
//! The distribution contract puts one requirement above the rest of this module tree: versions
//! resolve **only** from the channel manifest recorded for the installed release, every artifact
//! is verified by sha256 before it is used, the new generation is swapped in atomically while the
//! previous one is retained, and a generation that fails verification or its health check is
//! rolled back. Nothing here resolves a branch tip, a tag alias, a network `latest`, `HEAD` or
//! `*`, pushes to any remote, or touches user data, the graph output root or portable workspace
//! state.
//!
//! `src/update/` and the install-root layout it owns are decisions of this task and are recorded
//! in `docs/50-UPDATE-CHANNEL.md`.
//!
//! Module map:
//!
//! - [`sha256`], [`json`], [`time`] - dependency-free primitives; the JSON canonical form is the
//!   one `axiom-specs/tools/update_plan_contract.py` uses for the plan digest.
//! - [`rules`] - the shared lexical rules (SemVer, digests, revisions, relative paths, forbidden
//!   pins, placeholders).
//! - [`channel`] - `channels/stable.json`: parse and validate the recorded manifest.
//! - [`state`] - the install root, its `installed.json` record and the recorded manifest bytes.
//! - [`plan`] - the canonical plan contract: build, digest, structural and approval evaluation.
//! - [`fetch`] - local acquisition with pre-use length and digest verification.
//! - [`generation`] - one verified generation and its payload digests.
//! - [`health`] - the post-swap health check.
//! - [`journal`] - the recovery journal for an interrupted transaction.
//! - [`report`], [`error`] - the result envelope and the refusal vocabulary.
//! - [`apply`] - the four `update` verbs and the transaction that backs them.

pub mod apply;
pub mod channel;
pub mod error;
pub mod fetch;
pub mod generation;
pub mod health;
pub mod journal;
pub mod json;
pub mod plan;
pub mod report;
pub mod rules;
pub mod sha256;
pub mod state;
pub mod time;

pub use apply::{run_update, Request, Subcommand};
