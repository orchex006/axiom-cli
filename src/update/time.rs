//! Minimal RFC 3339 UTC timestamps with no third-party dependency.
//!
//! The distributed CLI builds offline from a pinned toolchain, so the update channel cannot
//! take a date library. Only the single format the version/update contract freezes is
//! accepted: `YYYY-MM-DDTHH:MM:SSZ` (see `contracts/schemas/update-plan.schema.json`,
//! `TIMESTAMP`). Anything else - an offset form, a fractional second, a local time, a date
//! without a zone - is rejected rather than guessed, because a guessed timestamp would let an
//! expired or not-yet-valid plan look usable.
//!
//! Calendar conversion uses the civil-from-days / days-from-civil algorithm, which is exact
//! for the whole proleptic Gregorian range and needs no lookup tables.

/// A UTC instant, held as whole seconds since the Unix epoch.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub struct Stamp {
    seconds: i64,
}

impl Stamp {
    /// Wrap an epoch-second count.
    pub fn from_seconds(seconds: i64) -> Stamp {
        Stamp { seconds }
    }

    /// Seconds since the Unix epoch.
    pub fn seconds(self) -> i64 {
        self.seconds
    }

    /// The current wall-clock instant.
    ///
    /// A clock that reports a time before the epoch is clamped to the epoch instead of
    /// producing a negative stamp; an untrusted or skewed clock must never make an expired
    /// plan look fresh, and the plan expiry check compares stamps rather than trusting this.
    pub fn now() -> Stamp {
        match std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
            Ok(elapsed) => Stamp::from_seconds(elapsed.as_secs() as i64),
            Err(_) => Stamp::from_seconds(0),
        }
    }

    /// `self` advanced by `seconds`.
    pub fn plus_seconds(self, seconds: i64) -> Stamp {
        Stamp::from_seconds(self.seconds.saturating_add(seconds))
    }

    /// Parse the frozen `YYYY-MM-DDTHH:MM:SSZ` form.
    pub fn parse(text: &str) -> Result<Stamp, String> {
        let bytes = text.as_bytes();
        if bytes.len() != 20 {
            return Err(format!(
                "timestamp `{text}` must be exactly 20 characters of the form YYYY-MM-DDTHH:MM:SSZ"
            ));
        }
        let digit = |index: usize, label: &str| -> Result<i64, String> {
            let byte = bytes[index];
            if !byte.is_ascii_digit() {
                return Err(format!(
                    "timestamp `{text}` has a non-digit in the {label} field"
                ));
            }
            Ok(i64::from(byte - b'0'))
        };
        let two = |index: usize, label: &str| -> Result<i64, String> {
            Ok(digit(index, label)? * 10 + digit(index + 1, label)?)
        };
        for (index, expected) in [
            (4usize, b'-'),
            (7, b'-'),
            (10, b'T'),
            (13, b':'),
            (16, b':'),
        ] {
            if bytes[index] != expected {
                return Err(format!(
                    "timestamp `{text}` must be YYYY-MM-DDTHH:MM:SSZ; position {} must be `{}`",
                    index + 1,
                    expected as char
                ));
            }
        }
        if bytes[19] != b'Z' {
            return Err(format!(
                "timestamp `{text}` must end in `Z`; a local time or an offset is not accepted"
            ));
        }
        let year = digit(0, "year")? * 1000
            + digit(1, "year")? * 100
            + digit(2, "year")? * 10
            + digit(3, "year")?;
        let month = two(5, "month")?;
        let day = two(8, "day")?;
        let hour = two(11, "hour")?;
        let minute = two(14, "minute")?;
        let second = two(17, "second")?;
        if !(1..=12).contains(&month) {
            return Err(format!(
                "timestamp `{text}` has month {month} outside 1..=12"
            ));
        }
        if !(1..=31).contains(&day) {
            return Err(format!("timestamp `{text}` has day {day} outside 1..=31"));
        }
        if !(0..=23).contains(&hour) {
            return Err(format!("timestamp `{text}` has hour {hour} outside 0..=23"));
        }
        if !(0..=59).contains(&minute) {
            return Err(format!(
                "timestamp `{text}` has minute {minute} outside 0..=59"
            ));
        }
        // 60 is refused: a leap second would not round-trip through this representation, and
        // silently folding it to the next minute would shift an expiry.
        if !(0..=59).contains(&second) {
            return Err(format!(
                "timestamp `{text}` has second {second} outside 0..=59"
            ));
        }
        let days = days_from_civil(year, month as u32, day as u32);
        if civil_from_days(days) != (year, month as u32, day as u32) {
            return Err(format!("timestamp `{text}` is not a real calendar date"));
        }
        Ok(Stamp::from_seconds(
            days * 86_400 + hour * 3_600 + minute * 60 + second,
        ))
    }

    /// Render the frozen `YYYY-MM-DDTHH:MM:SSZ` form.
    pub fn format(self) -> String {
        let days = self.seconds.div_euclid(86_400);
        let of_day = self.seconds.rem_euclid(86_400);
        let (year, month, day) = civil_from_days(days);
        let hour = of_day / 3_600;
        let minute = (of_day % 3_600) / 60;
        let second = of_day % 60;
        format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
    }
}

/// Days between 1970-01-01 and the supplied proleptic Gregorian date.
fn days_from_civil(year: i64, month: u32, day: u32) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = if year >= 0 { year } else { year - 399 }.div_euclid(400);
    let year_of_era = year - era * 400;
    let month_prime = if month > 2 { month - 3 } else { month + 9 } as i64;
    let day_of_year = (153 * month_prime + 2) / 5 + i64::from(day) - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

/// Inverse of [`days_from_civil`].
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let days = days + 719_468;
    let era = if days >= 0 { days } else { days - 146_096 }.div_euclid(146_097);
    let day_of_era = days - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_prime = (5 * day_of_year + 2) / 153;
    let day = (day_of_year - (153 * month_prime + 2) / 5 + 1) as u32;
    let month = if month_prime < 10 {
        month_prime + 3
    } else {
        month_prime - 9
    } as u32;
    (if month <= 2 { year + 1 } else { year }, month, day)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn epoch_and_known_instants_round_trip() {
        let cases = [
            ("1970-01-01T00:00:00Z", 0i64),
            ("2026-09-20T00:00:00Z", 1_789_862_400),
            ("2000-02-29T12:34:56Z", 951_827_696),
            ("1999-12-31T23:59:59Z", 946_684_799),
            ("2100-03-01T00:00:00Z", 4_107_542_400),
        ];
        for (text, seconds) in cases {
            let stamp = Stamp::parse(text).unwrap_or_else(|error| panic!("{text}: {error}"));
            assert_eq!(stamp.seconds(), seconds, "{text}");
            assert_eq!(stamp.format(), text);
        }
    }

    #[test]
    fn malformed_timestamps_are_rejected_not_guessed() {
        let cases = [
            "",
            "2026-09-20",
            "2026-09-20T00:00:00",
            "2026-09-20T00:00:00+07:00",
            "2026-09-20T00:00:00.500Z",
            "2026-09-20 00:00:00Z",
            "2026-13-01T00:00:00Z",
            "2026-02-30T00:00:00Z",
            "2026-09-20T24:00:00Z",
            "2026-09-20T00:60:00Z",
            "2026-09-20T00:00:60Z",
            "2026-09-2xT00:00:00Z",
            "main",
            "latest",
            "*",
        ];
        for text in cases {
            assert!(
                Stamp::parse(text).is_err(),
                "`{text}` must be rejected, never guessed"
            );
        }
    }

    #[test]
    fn expiry_comparison_is_an_instant_comparison() {
        let created = Stamp::parse("2026-09-20T00:00:00Z").unwrap();
        let same = Stamp::parse("2026-09-20T00:00:00Z").unwrap();
        let later = Stamp::parse("2026-09-21T00:00:00Z").unwrap();
        assert_eq!(created, same);
        assert!(later > created);
        assert_eq!(created.plus_seconds(86_400), later);
    }
}
