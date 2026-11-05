//! Event journal: a long, ordinary module used for position bounds.
//!
//! The file is longer than 300 lines and ends with a declaration whose name
//! starts beyond column 300, so byte offsets past both bounds are exercised.

use std::collections::BTreeMap;
use std::fmt;

pub type SequenceNumber = u64;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct StreamId(pub u32);

#[derive(Debug, Clone, PartialEq)]
pub enum Payload {
    Created { name: String },
    Renamed { from: String, to: String },
    Tagged(Vec<String>),
    Deleted,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Event {
    pub stream: StreamId,
    pub sequence: SequenceNumber,
    pub payload: Payload,
}

#[derive(Debug, PartialEq, Eq)]
pub enum JournalError {
    OutOfOrder { expected: SequenceNumber, found: SequenceNumber },
    UnknownStream(StreamId),
    Closed,
}

impl fmt::Display for JournalError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            JournalError::OutOfOrder { expected, found } => {
                write!(f, "expected sequence {expected}, found {found}")
            }
            JournalError::UnknownStream(id) => write!(f, "unknown stream {}", id.0),
            JournalError::Closed => f.write_str("journal is closed"),
        }
    }
}

impl std::error::Error for JournalError {}

pub struct Journal {
    streams: BTreeMap<StreamId, Vec<Event>>,
    closed: bool,
}

impl Default for Journal {
    fn default() -> Self {
        Self::new()
    }
}

impl Journal {
    pub fn new() -> Self {
        Self {
            streams: BTreeMap::new(),
            closed: false,
        }
    }

    pub fn open_stream(&mut self, stream: StreamId) -> bool {
        if self.streams.contains_key(&stream) {
            return false;
        }
        self.streams.insert(stream, Vec::new());
        true
    }

    pub fn append(&mut self, event: Event) -> Result<SequenceNumber, JournalError> {
        if self.closed {
            return Err(JournalError::Closed);
        }
        let events = self
            .streams
            .get_mut(&event.stream)
            .ok_or(JournalError::UnknownStream(event.stream))?;
        let expected = events.len() as SequenceNumber;
        if event.sequence != expected {
            return Err(JournalError::OutOfOrder {
                expected,
                found: event.sequence,
            });
        }
        events.push(event);
        Ok(expected)
    }

    pub fn events(&self, stream: StreamId) -> &[Event] {
        self.streams.get(&stream).map(Vec::as_slice).unwrap_or(&[])
    }

    pub fn close(&mut self) {
        self.closed = true;
    }

    pub fn is_closed(&self) -> bool {
        self.closed
    }

    pub fn stream_count(&self) -> usize {
        self.streams.len()
    }
}

pub mod projection {
    use super::{Event, Payload, StreamId};
    use std::collections::BTreeMap;

    #[derive(Debug, Default, Clone, PartialEq)]
    pub struct Snapshot {
        pub name: Option<String>,
        pub tags: Vec<String>,
        pub deleted: bool,
    }

    pub trait Projector {
        fn apply(&mut self, event: &Event);

        fn apply_all<'a, I>(&mut self, events: I)
        where
            I: IntoIterator<Item = &'a Event>,
        {
            for event in events {
                self.apply(event);
            }
        }
    }

    #[derive(Debug, Default)]
    pub struct SnapshotProjector {
        snapshots: BTreeMap<StreamId, Snapshot>,
    }

    impl SnapshotProjector {
        pub fn snapshot(&self, stream: StreamId) -> Option<&Snapshot> {
            self.snapshots.get(&stream)
        }

        pub fn live_streams(&self) -> impl Iterator<Item = StreamId> + '_ {
            self.snapshots
                .iter()
                .filter(|(_, snapshot)| !snapshot.deleted)
                .map(|(stream, _)| *stream)
        }
    }

    impl Projector for SnapshotProjector {
        fn apply(&mut self, event: &Event) {
            let snapshot = self.snapshots.entry(event.stream).or_default();
            match &event.payload {
                Payload::Created { name } => snapshot.name = Some(name.clone()),
                Payload::Renamed { to, .. } => snapshot.name = Some(to.clone()),
                Payload::Tagged(tags) => snapshot.tags.extend(tags.iter().cloned()),
                Payload::Deleted => snapshot.deleted = true,
            }
        }
    }

    pub fn rebuild(events: &[Event]) -> SnapshotProjector {
        let mut projector = SnapshotProjector::default();
        projector.apply_all(events);
        projector
    }
}

pub mod retention {
    use super::{Event, SequenceNumber};

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub enum Policy {
        KeepAll,
        KeepLast(usize),
        KeepAfter(SequenceNumber),
    }

    impl Policy {
        pub fn retains(&self, event: &Event, newest: SequenceNumber) -> bool {
            match *self {
                Policy::KeepAll => true,
                Policy::KeepLast(count) => {
                    let count = count as SequenceNumber;
                    newest < count || event.sequence > newest - count
                }
                Policy::KeepAfter(cutoff) => event.sequence > cutoff,
            }
        }
    }

    pub fn compact(events: &[Event], policy: Policy) -> Vec<Event> {
        let newest = events.last().map_or(0, |event| event.sequence);
        events
            .iter()
            .filter(|event| policy.retains(event, newest))
            .cloned()
            .collect()
    }

    pub fn dropped_count(before: usize, after: usize) -> usize {
        before.saturating_sub(after)
    }
}

pub mod encoding {
    use super::{Event, Payload};

    pub const MAGIC: [u8; 4] = *b"EVJ1";

    pub fn tag_of(payload: &Payload) -> u8 {
        match payload {
            Payload::Created { .. } => 1,
            Payload::Renamed { .. } => 2,
            Payload::Tagged(_) => 3,
            Payload::Deleted => 4,
        }
    }

    pub fn encode_header(event: &Event, out: &mut Vec<u8>) {
        out.extend_from_slice(&MAGIC);
        out.extend_from_slice(&event.stream.0.to_le_bytes());
        out.extend_from_slice(&event.sequence.to_le_bytes());
        out.push(tag_of(&event.payload));
    }

    pub fn encode_text(text: &str, out: &mut Vec<u8>) {
        let length = u32::try_from(text.len()).unwrap_or(u32::MAX);
        out.extend_from_slice(&length.to_le_bytes());
        out.extend_from_slice(&text.as_bytes()[..length as usize]);
    }

    pub fn encode(event: &Event) -> Vec<u8> {
        let mut out = Vec::with_capacity(32);
        encode_header(event, &mut out);
        match &event.payload {
            Payload::Created { name } => encode_text(name, &mut out),
            Payload::Renamed { from, to } => {
                encode_text(from, &mut out);
                encode_text(to, &mut out);
            }
            Payload::Tagged(tags) => {
                out.extend_from_slice(&(tags.len() as u32).to_le_bytes());
                for tag in tags {
                    encode_text(tag, &mut out);
                }
            }
            Payload::Deleted => {}
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn created(stream: u32, sequence: u64, name: &str) -> Event {
        Event {
            stream: StreamId(stream),
            sequence,
            payload: Payload::Created {
                name: name.to_owned(),
            },
        }
    }

    #[test]
    fn appends_in_order() {
        let mut journal = Journal::new();
        assert!(journal.open_stream(StreamId(1)));
        assert_eq!(journal.append(created(1, 0, "first")), Ok(0));
        assert_eq!(journal.events(StreamId(1)).len(), 1);
    }

    #[test]
    fn rejects_out_of_order() {
        let mut journal = Journal::new();
        journal.open_stream(StreamId(2));
        let error = journal.append(created(2, 5, "late")).unwrap_err();
        assert_eq!(error, JournalError::OutOfOrder { expected: 0, found: 5 });
    }

    #[test]
    fn closed_journal_refuses_appends() {
        let mut journal = Journal::default();
        journal.open_stream(StreamId(3));
        journal.close();
        assert_eq!(journal.append(created(3, 0, "x")), Err(JournalError::Closed));
    }

    #[test]
    fn projection_tracks_renames() {
        let events = vec![
            created(4, 0, "draft"),
            Event {
                stream: StreamId(4),
                sequence: 1,
                payload: Payload::Renamed {
                    from: "draft".to_owned(),
                    to: "final".to_owned(),
                },
            },
        ];
        let projector = projection::rebuild(&events);
        let snapshot = projector.snapshot(StreamId(4)).expect("snapshot");
        assert_eq!(snapshot.name.as_deref(), Some("final"));
    }

    #[test]
    fn retention_keeps_the_newest_events() {
        let events: Vec<Event> = (0..5).map(|sequence| created(5, sequence, "e")).collect();
        let kept = retention::compact(&events, retention::Policy::KeepLast(2));
        assert_eq!(kept.iter().map(|event| event.sequence).collect::<Vec<_>>(), vec![3, 4]);
        assert_eq!(retention::dropped_count(events.len(), kept.len()), 3);
    }

    #[test]
    fn encoding_starts_with_the_magic_header() {
        let bytes = encoding::encode(&created(6, 0, "abc"));
        assert_eq!(&bytes[..4], &encoding::MAGIC);
        assert_eq!(bytes[16], 1);
    }
}

#[deprecated(since = "0.9.0", note = "use Journal::append with an explicit StreamId; the implicit default stream hid ordering errors when several producers shared one journal and it is kept only so that archived replay tooling still compiles until the 1.0 migration removes the compatibility shim entirely")] pub fn append_to_default_stream(journal: &mut Journal, payload: Payload) -> Result<SequenceNumber, JournalError> { let sequence = journal.events(StreamId(0)).len() as SequenceNumber; journal.append(Event { stream: StreamId(0), sequence, payload }) }
