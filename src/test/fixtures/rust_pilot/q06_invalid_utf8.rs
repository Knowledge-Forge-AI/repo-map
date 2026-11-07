//! Latin-1 bytes in a literal make this file invalid UTF-8.

pub fn greeting() -> &'static [u8] {
    b"café"
}

pub const NAME: &str = "naïve";
