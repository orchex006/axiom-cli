//! Minimal, dependency-free JSON for the update channel (J-007).
//!
//! Two jobs, both of them contract work rather than plumbing:
//!
//! 1. Parse a plan document or a channel manifest.
//! 2. Re-emit it in the **canonical digest form** fixed by the canonical implementation
//!    `axiom-specs/tools/update_plan_contract.py` (`canonical_plan_bytes`): UTF-8,
//!    lexicographic key order, compact separators, exactly one trailing LF, and every
//!    non-ASCII character emitted raw (`ensure_ascii=False`).
//!
//! The digest produced here is compared byte-for-byte against that Python implementation
//! in the `J-007` evidence, so the encoding is not a local convention.
//!
//! Numbers are parsed as `i64` only. Every numeric field of
//! `contracts/schemas/update-plan.schema.json` is `"type": "integer"`, and Python re-emits
// an integer literal unchanged, so refusing a non-integer literal keeps the digest
// byte-identical instead of silently diverging on float formatting.

use std::collections::BTreeMap;

/// Deepest nesting accepted, so a hostile document cannot exhaust the stack.
const MAX_DEPTH: usize = 128;

/// One JSON value. Object keys are held in a `BTreeMap`, which yields the code-point key
/// order Python's `sort_keys=True` produces: byte order of UTF-8 equals code-point order.
#[derive(Clone, Debug, PartialEq)]
pub enum Json {
    /// `null`
    Null,
    /// `true` or `false`
    Bool(bool),
    /// An integer literal.
    Int(i64),
    /// A string.
    Text(String),
    /// An array.
    Array(Vec<Json>),
    /// An object.
    Object(BTreeMap<String, Json>),
}

impl Json {
    /// The `null` value.
    pub fn null() -> Json {
        Json::Null
    }

    /// A boolean value.
    pub fn bool(value: bool) -> Json {
        Json::Bool(value)
    }

    /// An integer value.
    pub fn int(value: i64) -> Json {
        Json::Int(value)
    }

    /// A string value.
    pub fn text(value: &str) -> Json {
        Json::Text(value.to_string())
    }

    /// An array value.
    pub fn array(items: Vec<Json>) -> Json {
        Json::Array(items)
    }

    /// An array of strings.
    pub fn text_array(items: &[&str]) -> Json {
        Json::Array(items.iter().map(|item| Json::text(item)).collect())
    }

    /// An object built from pairs; a repeated key keeps the last member.
    pub fn from_pairs(pairs: Vec<(&str, Json)>) -> Json {
        let mut entries = BTreeMap::new();
        for (key, value) in pairs {
            entries.insert(key.to_string(), value);
        }
        Json::Object(entries)
    }

    /// Insert one member. Fails when `self` is not an object.
    pub fn set(&mut self, key: &str, value: Json) -> Result<(), String> {
        match self {
            Json::Object(entries) => {
                entries.insert(key.to_string(), value);
                Ok(())
            }
            other => Err(format!(
                "cannot set `{key}`: expected a JSON object, found {}",
                other.kind()
            )),
        }
    }

    /// The member named `key`, when `self` is an object.
    pub fn get(&self, key: &str) -> Option<&Json> {
        match self {
            Json::Object(entries) => entries.get(key),
            _ => None,
        }
    }

    /// The string payload, when this is a string.
    pub fn as_text(&self) -> Option<&str> {
        match self {
            Json::Text(text) => Some(text.as_str()),
            _ => None,
        }
    }

    /// The integer payload, when this is an integer.
    pub fn as_int(&self) -> Option<i64> {
        match self {
            Json::Int(value) => Some(*value),
            _ => None,
        }
    }

    /// The boolean payload, when this is a boolean.
    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Json::Bool(value) => Some(*value),
            _ => None,
        }
    }

    /// The items, when this is an array.
    pub fn as_array(&self) -> Option<&[Json]> {
        match self {
            Json::Array(items) => Some(items.as_slice()),
            _ => None,
        }
    }

    /// The members, when this is an object.
    pub fn as_object(&self) -> Option<&BTreeMap<String, Json>> {
        match self {
            Json::Object(entries) => Some(entries),
            _ => None,
        }
    }

    /// True for `null`.
    pub fn is_null(&self) -> bool {
        matches!(self, Json::Null)
    }

    /// The JSON type name, for diagnostics.
    pub fn kind(&self) -> &'static str {
        match self {
            Json::Null => "null",
            Json::Bool(_) => "boolean",
            Json::Int(_) => "integer",
            Json::Text(_) => "string",
            Json::Array(_) => "array",
            Json::Object(_) => "object",
        }
    }

    /// Append the canonical encoding of this value; no trailing LF is added.
    pub fn write(&self, out: &mut String) {
        match self {
            Json::Null => out.push_str("null"),
            Json::Bool(true) => out.push_str("true"),
            Json::Bool(false) => out.push_str("false"),
            Json::Int(value) => out.push_str(&value.to_string()),
            Json::Text(text) => write_string(text, out),
            Json::Array(items) => {
                out.push('[');
                for (index, item) in items.iter().enumerate() {
                    if index > 0 {
                        out.push(',');
                    }
                    item.write(out);
                }
                out.push(']');
            }
            Json::Object(entries) => {
                out.push('{');
                for (index, (key, item)) in entries.iter().enumerate() {
                    if index > 0 {
                        out.push(',');
                    }
                    write_string(key, out);
                    out.push(':');
                    item.write(out);
                }
                out.push('}');
            }
        }
    }
}

/// The canonical digest input: canonical body plus exactly one trailing LF.
pub fn canonical_bytes(value: &Json) -> Vec<u8> {
    let mut out = String::new();
    value.write(&mut out);
    out.push('\n');
    out.into_bytes()
}

/// The canonical body as text, without the trailing LF.
pub fn canonical_text(value: &Json) -> String {
    let mut out = String::new();
    value.write(&mut out);
    out
}

fn write_string(text: &str, out: &mut String) {
    out.push('"');
    for character in text.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            control if (control as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", control as u32));
            }
            other => out.push(other),
        }
    }
    out.push('"');
}

/// Parse one complete JSON document. Trailing content is an error.
pub fn parse(text: &str) -> Result<Json, String> {
    let mut parser = Parser {
        bytes: text.as_bytes(),
        at: 0,
    };
    parser.skip_whitespace();
    let value = parser.value(0)?;
    parser.skip_whitespace();
    if parser.at != parser.bytes.len() {
        return Err(format!(
            "trailing content after the JSON document at byte {}",
            parser.at
        ));
    }
    Ok(value)
}

struct Parser<'a> {
    bytes: &'a [u8],
    at: usize,
}

impl Parser<'_> {
    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.at).copied()
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.at += 1;
        }
    }

    fn expect(&mut self, byte: u8) -> Result<(), String> {
        match self.peek() {
            Some(found) if found == byte => {
                self.at += 1;
                Ok(())
            }
            Some(found) => Err(format!(
                "expected `{}` at byte {}, found `{}`",
                byte as char, self.at, found as char
            )),
            None => Err(format!(
                "expected `{}` at byte {}, found end of input",
                byte as char, self.at
            )),
        }
    }

    fn literal(&mut self, text: &str, value: Json) -> Result<Json, String> {
        if self.bytes[self.at..].starts_with(text.as_bytes()) {
            self.at += text.len();
            Ok(value)
        } else {
            Err(format!("invalid literal at byte {}", self.at))
        }
    }

    fn value(&mut self, depth: usize) -> Result<Json, String> {
        if depth > MAX_DEPTH {
            return Err(format!("nesting deeper than {MAX_DEPTH} levels"));
        }
        match self.peek() {
            Some(b'{') => self.object(depth),
            Some(b'[') => self.array(depth),
            Some(b'"') => Ok(Json::Text(self.string()?)),
            Some(b't') => self.literal("true", Json::Bool(true)),
            Some(b'f') => self.literal("false", Json::Bool(false)),
            Some(b'n') => self.literal("null", Json::Null),
            Some(b'-' | b'0'..=b'9') => self.number(),
            Some(found) => Err(format!(
                "unexpected `{}` at byte {}",
                found as char, self.at
            )),
            None => Err("unexpected end of input; a JSON value was expected".to_string()),
        }
    }

    fn object(&mut self, depth: usize) -> Result<Json, String> {
        self.expect(b'{')?;
        let mut entries: BTreeMap<String, Json> = BTreeMap::new();
        self.skip_whitespace();
        if self.peek() == Some(b'}') {
            self.at += 1;
            return Ok(Json::Object(entries));
        }
        loop {
            self.skip_whitespace();
            let key = self.string()?;
            self.skip_whitespace();
            self.expect(b':')?;
            self.skip_whitespace();
            let value = self.value(depth + 1)?;
            entries.insert(key, value);
            self.skip_whitespace();
            match self.peek() {
                Some(b',') => self.at += 1,
                Some(b'}') => {
                    self.at += 1;
                    return Ok(Json::Object(entries));
                }
                Some(found) => {
                    return Err(format!(
                        "expected `,` or `}}` in an object at byte {}, found `{}`",
                        self.at, found as char
                    ))
                }
                None => return Err("unterminated object".to_string()),
            }
        }
    }

    fn array(&mut self, depth: usize) -> Result<Json, String> {
        self.expect(b'[')?;
        let mut items = Vec::new();
        self.skip_whitespace();
        if self.peek() == Some(b']') {
            self.at += 1;
            return Ok(Json::Array(items));
        }
        loop {
            self.skip_whitespace();
            items.push(self.value(depth + 1)?);
            self.skip_whitespace();
            match self.peek() {
                Some(b',') => self.at += 1,
                Some(b']') => {
                    self.at += 1;
                    return Ok(Json::Array(items));
                }
                Some(found) => {
                    return Err(format!(
                        "expected `,` or `]` in an array at byte {}, found `{}`",
                        self.at, found as char
                    ))
                }
                None => return Err("unterminated array".to_string()),
            }
        }
    }

    fn string(&mut self) -> Result<String, String> {
        self.expect(b'"')?;
        let mut out = String::new();
        loop {
            let Some(byte) = self.peek() else {
                return Err("unterminated string".to_string());
            };
            match byte {
                b'"' => {
                    self.at += 1;
                    return Ok(out);
                }
                b'\\' => {
                    self.at += 1;
                    let Some(escape) = self.peek() else {
                        return Err("unterminated escape sequence".to_string());
                    };
                    self.at += 1;
                    match escape {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{08}'),
                        b'f' => out.push('\u{0c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => out.push(self.unicode_escape()?),
                        other => {
                            return Err(format!(
                                "unsupported escape `\\{}` at byte {}",
                                other as char,
                                self.at - 1
                            ))
                        }
                    }
                }
                control if control < 0x20 => {
                    return Err(format!(
                        "raw control character 0x{control:02x} in a string at byte {}",
                        self.at
                    ))
                }
                _ => {
                    let start = self.at;
                    while let Some(byte) = self.peek() {
                        if byte == b'"' || byte == b'\\' || byte < 0x20 {
                            break;
                        }
                        self.at += 1;
                    }
                    match std::str::from_utf8(&self.bytes[start..self.at]) {
                        Ok(text) => out.push_str(text),
                        Err(_) => return Err(format!("invalid UTF-8 in a string at byte {start}")),
                    }
                }
            }
        }
    }

    fn unicode_escape(&mut self) -> Result<char, String> {
        let first = self.hex_quad()?;
        if (0xd800..0xdc00).contains(&first) {
            if self.peek() != Some(b'\\') || self.bytes.get(self.at + 1) != Some(&b'u') {
                return Err(format!(
                    "unpaired leading surrogate \\u{first:04x} at byte {}",
                    self.at
                ));
            }
            self.at += 2;
            let second = self.hex_quad()?;
            if !(0xdc00..0xe000).contains(&second) {
                return Err(format!(
                    "leading surrogate \\u{first:04x} is not followed by a trailing surrogate"
                ));
            }
            let combined = 0x10000 + ((first - 0xd800) << 10) + (second - 0xdc00);
            return char::from_u32(combined)
                .ok_or_else(|| format!("\\u{first:04x}\\u{second:04x} is not a character"));
        }
        if (0xdc00..0xe000).contains(&first) {
            return Err(format!(
                "unpaired trailing surrogate \\u{first:04x} at byte {}",
                self.at
            ));
        }
        char::from_u32(first).ok_or_else(|| format!("\\u{first:04x} is not a character"))
    }

    fn hex_quad(&mut self) -> Result<u32, String> {
        let mut value = 0u32;
        for _ in 0..4 {
            let Some(byte) = self.peek() else {
                return Err("truncated \\u escape".to_string());
            };
            let digit = match byte {
                b'0'..=b'9' => u32::from(byte - b'0'),
                b'a'..=b'f' => u32::from(byte - b'a') + 10,
                b'A'..=b'F' => u32::from(byte - b'A') + 10,
                _ => {
                    return Err(format!(
                        "invalid hex digit `{}` in a \\u escape at byte {}",
                        byte as char, self.at
                    ))
                }
            };
            value = value * 16 + digit;
            self.at += 1;
        }
        Ok(value)
    }

    fn number(&mut self) -> Result<Json, String> {
        let start = self.at;
        if self.peek() == Some(b'-') {
            self.at += 1;
        }
        match self.peek() {
            Some(b'0') => {
                self.at += 1;
                if matches!(self.peek(), Some(b'0'..=b'9')) {
                    return Err(format!("leading zero in the number at byte {start}"));
                }
            }
            Some(b'1'..=b'9') => {
                while matches!(self.peek(), Some(b'0'..=b'9')) {
                    self.at += 1;
                }
            }
            _ => return Err(format!("invalid number at byte {start}")),
        }
        if matches!(self.peek(), Some(b'.' | b'e' | b'E')) {
            let literal = String::from_utf8_lossy(&self.bytes[start..self.at]);
            return Err(format!(
                "unsupported_number_literal: `{literal}` is not an integer, and every numeric \
                 field of update-plan.schema.json is an integer"
            ));
        }
        let literal = String::from_utf8_lossy(&self.bytes[start..self.at]);
        literal
            .parse::<i64>()
            .map(Json::Int)
            .map_err(|_| format!("integer `{literal}` does not fit in a signed 64-bit value"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::update::sha256;

    fn canonical_of(input: &str) -> String {
        canonical_text(&parse(input).expect("the sample must parse"))
    }

    #[test]
    fn canonical_form_matches_the_python_reference() {
        // Each body was produced by the canonical implementation
        // (`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`),
        // and each digest is the sha256 of that body plus one trailing LF.
        let cases: [(&str, &str, &str); 3] = [
            (
                r#"{"b":1,"a":"x\ny","c":[true,null,2],"d":{"z":"é"}}"#,
                "{\"a\":\"x\\ny\",\"b\":1,\"c\":[true,null,2],\"d\":{\"z\":\"é\"}}",
                "3730b6094042d8796378626c22adb78564a1ac691bf0afef4104c0559fa26b6d",
            ),
            (
                r#"{"plan_id":"update-stable-to-0-1-0","n":0,"empty":[],"o":{},"t":false}"#,
                "{\"empty\":[],\"n\":0,\"o\":{},\"plan_id\":\"update-stable-to-0-1-0\",\"t\":false}",
                "f844aaeebdfe902b8cc8b84fd3a0fda5d3b39f6bf65517ae69adb7f645796c10",
            ),
            (
                r#"{"s":"tab\there quote\" back\\slash ctrl\u0001 del\u007f astral\ud83d\ude00"}"#,
                "{\"s\":\"tab\\there quote\\\" back\\\\slash ctrl\\u0001 del\u{7f} astral\u{1f600}\"}",
                "1833ce19da9fcf6465f1273447247aa44584fd401d17ec81a553feb96fa7789e",
            ),
        ];
        for (input, expected, digest) in cases {
            let value = parse(input).expect("the sample must parse");
            assert_eq!(canonical_text(&value), expected, "input={input}");
            assert_eq!(
                sha256::digest_hex(&canonical_bytes(&value)),
                digest,
                "digest differs from the Python reference for input={input}"
            );
        }
    }

    #[test]
    fn key_order_in_the_input_does_not_change_the_canonical_bytes() {
        let left = canonical_bytes(&parse(r#"{"a":1,"b":2}"#).unwrap());
        let right = canonical_bytes(&parse(r#"{"b":2,"a":1}"#).unwrap());
        assert_eq!(left, right);
        assert_eq!(left, b"{\"a\":1,\"b\":2}\n");
    }

    #[test]
    fn non_ascii_and_del_are_not_escaped() {
        // `\u007f` decodes to DEL, which is not a control character below 0x20, so the
        // canonical writer must emit it literally rather than re-escaping it.
        let value = parse("\"é\\u007f\"").unwrap();
        assert_eq!(canonical_text(&value), "\"é\u{7f}\"");
    }

    #[test]
    fn integers_are_normalised_without_a_leading_zero() {
        assert_eq!(canonical_of("[-0,0,10]"), "[0,0,10]");
    }

    #[test]
    fn a_float_literal_is_refused_by_name() {
        let error = parse("[1.0]").unwrap_err();
        assert!(
            error.starts_with("unsupported_number_literal"),
            "unexpected error: {error}"
        );
        assert!(parse("[1e3]").is_err());
    }

    #[test]
    fn structural_faults_are_refused() {
        assert!(parse("{\"a\":01}").is_err(), "leading zero");
        assert!(parse("{\"a\":1} trailing").is_err(), "trailing content");
        assert!(parse("{\"a\":1,}").is_err(), "trailing comma");
        assert!(parse("{\"a\" 1}").is_err(), "missing colon");
        assert!(parse("\"unterminated").is_err());
        assert!(parse("[1,2").is_err());
        assert!(parse("").is_err());
    }

    #[test]
    fn a_lone_surrogate_is_refused() {
        assert!(parse(r#""\ud83d""#).is_err());
        assert!(parse(r#""\ude00""#).is_err());
        assert_eq!(
            canonical_text(&parse(r#""\ud83d\ude00""#).unwrap()),
            "\"\u{1f600}\""
        );
    }

    #[test]
    fn a_repeated_key_keeps_the_last_member() {
        assert_eq!(canonical_of(r#"{"a":1,"a":2}"#), "{\"a\":2}");
    }

    #[test]
    fn deep_nesting_is_refused_instead_of_overflowing_the_stack() {
        let hostile = format!("{}{}", "[".repeat(400), "]".repeat(400));
        assert!(parse(&hostile).is_err());
    }
}
