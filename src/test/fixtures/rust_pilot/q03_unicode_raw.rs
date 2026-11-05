//! Identifiers outside ASCII, and raw identifiers that shadow keywords.

pub mod größen {
    pub struct Maß {
        pub wert: f64,
    }

    pub fn umrechnen(maß: &Maß, faktor: f64) -> Maß {
        Maß { wert: maß.wert * faktor }
    }
}

pub mod 日本 {
    pub fn 挨拶() -> &'static str {
        "こんにちは"
    }
}

pub fn r#match(pattern: &str, candidate: &str) -> bool {
    candidate.contains(pattern)
}

pub struct r#Type {
    pub r#ref: u32,
}

pub enum Ελληνικά {
    Άλφα,
    Βήτα,
}

pub trait r#async {
    fn r#await(&self) -> bool;
}

impl r#async for r#Type {
    fn r#await(&self) -> bool {
        self.r#ref > 0
    }
}

pub fn café_au_lait(shots: u8) -> u8 {
    shots.saturating_add(1)
}

macro_rules! décaler {
    ($valeur:expr) => {
        $valeur << 1
    };
}
