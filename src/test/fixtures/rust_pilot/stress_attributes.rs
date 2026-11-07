//! Attribute bounds: more than sixteen outer attributes truncate explicitly.

#[doc = "Wire-level record shared by every transport."]
#[doc = ""]
#[doc = "Each attribute below changes how the record is derived or checked."]
#[derive(Debug)]
#[derive(Clone)]
#[derive(PartialEq)]
#[derive(Eq)]
#[derive(Hash)]
#[derive(PartialOrd)]
#[derive(Ord)]
#[repr(C)]
#[non_exhaustive]
#[must_use]
#[allow(clippy::struct_excessive_bools)]
#[cfg_attr(feature = "serde", derive(serde::Serialize))]
#[cfg_attr(feature = "serde", derive(serde::Deserialize))]
#[cfg(any(unix, windows))]
pub struct Record {
    pub compressed: bool,
    pub encrypted: bool,
    pub signed: bool,
}

#[inline]
#[must_use]
pub fn record_flags(record: &Record) -> u8 {
    u8::from(record.compressed) | (u8::from(record.encrypted) << 1) | (u8::from(record.signed) << 2)
}

#[deprecated(note = "a dangling attribute at the end of a scope is unsupported")]
