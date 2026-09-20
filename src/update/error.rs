//! The refusal vocabulary shared by the update transaction.
//!
//! Every refusal carries a stable machine-readable reason and a canonical exit class, so the
//! same facts can be asserted in a test, quoted in evidence and read by a caller. The classes
//! are the exit vocabulary of axiom-specs/docs/16-CLI-AND-CONTROL-API.md section 6; this
//! module introduces no private exit-code space.
//!
//! The rule that shapes the whole slice lives here: a refusal is never a success. A component
//! that could not be obtained and verified, a plan whose recorded digest does not match its
//! body, and an artifact whose bytes do not match the recorded digest all produce a refusal
//! with a stated reason, and the caller learns that nothing was applied.

use crate::cli::exit;

/// The failure class of a refusal, mapped to the canonical exit vocabulary.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Class {
    /// Not ready or stale: the requested work needs state that does not exist yet.
    NotReady,
    /// Validation: the request or a document it names is structurally wrong.
    Validation,
    /// Conflict: the request is valid but conflicts with the current system state.
    Conflict,
    /// Lock unavailable: another transaction already holds the update coordinator lock.
    LockUnavailable,
    /// Incompatible: the plan targets something this host or CLI cannot accept.
    Incompatible,
    /// I/O or internal failure.
    IoInternal,
    /// Not found: a named path or record does not exist.
    NotFound,
}

impl Class {
    /// The canonical process exit code for this class.
    pub fn exit_code(self) -> i32 {
        match self {
            Class::NotReady => exit::NOT_READY,
            Class::Validation => exit::VALIDATION,
            Class::Conflict => exit::CONFLICT,
            Class::LockUnavailable => exit::LOCK_UNAVAILABLE,
            Class::Incompatible => exit::INCOMPATIBLE,
            Class::IoInternal => exit::IO_INTERNAL,
            Class::NotFound => exit::NOT_FOUND,
        }
    }

    /// The status token written into the JSON envelope for this class.
    pub fn status(self) -> &'static str {
        match self {
            Class::NotReady => "not_ready",
            Class::Validation => "validation_error",
            Class::Conflict => "conflict",
            Class::LockUnavailable => "lock_unavailable",
            Class::Incompatible => "incompatible",
            Class::IoInternal => "io_error",
            Class::NotFound => "not_found",
        }
    }

    /// Whether a caller could sensibly retry the same request unchanged.
    pub fn retryable(self) -> bool {
        matches!(
            self,
            Class::NotReady | Class::LockUnavailable | Class::IoInternal
        )
    }
}

/// A refusal: a stable reason token plus a human explanation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Refusal {
    /// Failure class, which fixes the exit code.
    pub class: Class,
    /// Stable machine reason token.
    pub reason: String,
    /// Human-readable explanation.
    pub message: String,
}

impl Refusal {
    /// Build a refusal.
    pub fn new(class: Class, reason: impl Into<String>, message: impl Into<String>) -> Refusal {
        Refusal {
            class,
            reason: reason.into(),
            message: message.into(),
        }
    }

    /// A not-ready refusal.
    pub fn not_ready(reason: impl Into<String>, message: impl Into<String>) -> Refusal {
        Refusal::new(Class::NotReady, reason, message)
    }

    /// A validation refusal.
    pub fn validation(reason: impl Into<String>, message: impl Into<String>) -> Refusal {
        Refusal::new(Class::Validation, reason, message)
    }

    /// A conflict refusal.
    pub fn conflict(reason: impl Into<String>, message: impl Into<String>) -> Refusal {
        Refusal::new(Class::Conflict, reason, message)
    }

    /// An I/O or internal refusal built from an io error.
    pub fn io(reason: impl Into<String>, context: &str, error: &std::io::Error) -> Refusal {
        Refusal::new(Class::IoInternal, reason, format!("{context}: {error}"))
    }
}

impl From<super::channel::ChannelError> for Refusal {
    /// Channel refusals stay validation failures, except an unreachable channel, which is a
    /// not-ready condition: nothing about the request is wrong, and retrying later can work.
    fn from(error: super::channel::ChannelError) -> Refusal {
        let class = if error.reason == "channel_unreachable" {
            Class::NotReady
        } else {
            Class::Validation
        };
        Refusal::new(class, error.reason, error.message)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classes_map_onto_the_canonical_exit_vocabulary() {
        assert_eq!(Class::NotReady.exit_code(), 4);
        assert_eq!(Class::Validation.exit_code(), 2);
        assert_eq!(Class::Conflict.exit_code(), 6);
        assert_eq!(Class::LockUnavailable.exit_code(), 10);
        assert_eq!(Class::Incompatible.exit_code(), 9);
        assert_eq!(Class::IoInternal.exit_code(), 8);
        assert_eq!(Class::NotFound.exit_code(), 3);
    }

    #[test]
    fn only_a_transient_class_is_retryable() {
        assert!(Class::NotReady.retryable());
        assert!(Class::LockUnavailable.retryable());
        assert!(!Class::Validation.retryable());
        assert!(!Class::Conflict.retryable());
    }

    #[test]
    fn an_unreachable_channel_is_not_ready_and_a_malformed_one_is_validation() {
        let unreachable: Refusal =
            super::super::channel::ChannelError::new("channel_unreachable", "x").into();
        assert_eq!(unreachable.class, Class::NotReady);
        let malformed: Refusal =
            super::super::channel::ChannelError::new("unsigned_channel", "x").into();
        assert_eq!(malformed.class, Class::Validation);
        assert_eq!(malformed.reason, "unsigned_channel");
    }
}
