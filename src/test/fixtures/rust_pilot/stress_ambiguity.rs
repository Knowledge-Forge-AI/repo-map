//! Same-named siblings stay separate, ordered alternatives.

pub mod codec {
    #[cfg(feature = "zstd")]
    pub fn compress(input: &[u8]) -> Vec<u8> {
        input.to_vec()
    }

    #[cfg(feature = "lz4")]
    pub fn compress(input: &[u8]) -> Vec<u8> {
        input.iter().rev().copied().collect()
    }

    #[cfg(not(any(feature = "zstd", feature = "lz4")))]
    pub fn compress(input: &[u8]) -> Vec<u8> {
        Vec::from(input)
    }

    pub struct Frame {
        pub len: u32,
    }

    #[cfg(feature = "legacy")]
    pub enum Frame {
        Short(u16),
        Long(u32),
    }

    pub mod compress {
        pub fn level() -> u8 {
            3
        }
    }
}

pub struct Header;

impl Header {
    pub fn size() -> usize {
        8
    }
}

impl Default for Header {
    fn default() -> Self {
        Header
    }
}

impl Clone for Header {
    fn clone(&self) -> Self {
        Header
    }
}

#[cfg(feature = "debug")]
impl Header {
    pub fn size() -> usize {
        16
    }
}

#[cfg(unix)]
macro_rules! path_sep {
    () => {
        "/"
    };
}

#[cfg(not(unix))]
macro_rules! path_sep {
    () => {
        "\\"
    };
}

pub trait Header {}
