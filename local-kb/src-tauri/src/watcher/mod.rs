use crate::{
    database::Database,
    document::DocumentService,
    error::{AppError, AppResult},
};
use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use std::{
    path::Path,
    sync::mpsc::{self, Sender},
    thread,
    time::Duration,
};

enum WatchMessage {
    Changed,
    Stop,
}
pub struct WatchRegistration {
    watcher: RecommendedWatcher,
    tx: Sender<WatchMessage>,
}
impl Drop for WatchRegistration {
    fn drop(&mut self) {
        let _ = &self.watcher;
        let _ = self.tx.send(WatchMessage::Stop);
    }
}

pub fn start(kb_id: String, root: &Path, db: Database) -> AppResult<WatchRegistration> {
    let (tx, rx) = mpsc::channel::<WatchMessage>();
    let event_tx = tx.clone();
    let mut watcher = notify::recommended_watcher(move |result: notify::Result<notify::Event>| {
        if result.is_ok() {
            let _ = event_tx.send(WatchMessage::Changed);
        }
    })
    .map_err(|e| AppError::Internal(format!("watcher init: {e}")))?;
    watcher
        .watch(root, RecursiveMode::Recursive)
        .map_err(|e| AppError::Internal(format!("watch path: {e}")))?;
    thread::spawn(move || {
        while let Ok(message) = rx.recv() {
            match message {
                WatchMessage::Stop => break,
                WatchMessage::Changed => {
                    loop {
                        match rx.recv_timeout(Duration::from_millis(650)) {
                            Ok(WatchMessage::Stop) => return,
                            Ok(WatchMessage::Changed) => continue,
                            Err(mpsc::RecvTimeoutError::Timeout) => break,
                            Err(_) => return,
                        }
                    }
                    if let Err(error) = DocumentService::new(db.clone()).scan(&kb_id) {
                        tracing::warn!(%error,"incremental scan failed");
                    }
                }
            }
        }
    });
    Ok(WatchRegistration { watcher, tx })
}
