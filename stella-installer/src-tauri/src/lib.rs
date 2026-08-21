mod commands;
mod python;

use std::sync::atomic::{AtomicBool, Ordering};
use tauri::Emitter;

static CLOSE_IN_PROGRESS: AtomicBool = AtomicBool::new(false);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                if CLOSE_IN_PROGRESS.swap(true, Ordering::AcqRel) {
                    return;
                }
                let _ = window.emit("close-requested", ());
                let window = window.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = commands::stop_bot().await {
                        CLOSE_IN_PROGRESS.store(false, Ordering::Release);
                        let _ = window.emit("close-failed", e);
                        return;
                    }
                    let _ = window.destroy();
                });
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::run_doctor,
            commands::get_status,
            commands::start_bot,
            commands::stop_bot,
            commands::read_log_tail,
            commands::get_config,
            commands::save_config,
            commands::list_models,
            commands::get_version,
            commands::get_personas,
            commands::save_persona,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
