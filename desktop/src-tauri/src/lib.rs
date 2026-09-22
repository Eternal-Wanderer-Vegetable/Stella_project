mod commands;
mod python;

use std::sync::atomic::{AtomicBool, Ordering};
use tauri::Emitter;

static CLOSE_IN_PROGRESS: AtomicBool = AtomicBool::new(false);

/// 桌面壳持有的会话秘钥：start_bot 时注入子进程环境变量，
/// WebUI 侧经 `POST /api/v1/auth/desktop-session`（回环 + 秘钥头）免登录。
pub fn desktop_session_secret() -> &'static str {
    use std::sync::OnceLock;
    static SECRET: OnceLock<String> = OnceLock::new();
    SECRET.get_or_init(|| {
        use rand::Rng;
        let secret: String = rand::thread_rng()
            .sample_iter(rand::distributions::Alphanumeric)
            .take(48)
            .map(char::from)
            .collect();
        std::env::set_var("STELLA_DESKTOP_SESSION_SECRET", &secret);
        secret
    })
}

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
                        CLOSE_IN_PROGRESS.swap(false, Ordering::AcqRel);
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
            commands::run_migrate,
            commands::desktop_session_secret,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
