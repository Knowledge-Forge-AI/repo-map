// Windows-authored file that starts with a byte order mark.

pub struct Settings {
    pub verbose: bool,
}

impl Settings {
    pub fn quiet() -> Self {
        Self { verbose: false }
    }
}

pub fn parse_flag(raw: &str) -> bool {
    matches!(raw, "1" | "true" | "yes")
}

pub mod nested {
    pub enum Level {
        Low,
        High,
    }
}
