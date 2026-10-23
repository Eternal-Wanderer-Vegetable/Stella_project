mod commands;
mod python;

use std::sync::atomic::{AtomicBool, Ordering};
use tauri::Emitter;

static CLOSE_IN_PROGRESS: AtomicBool = AtomicBool::new(false);

/// Session capability for the desktop WebView; it is passed to Corona only.
pub fn desktop_session_secret() -> &'static str {
    use std::sync::OnceLock;
    static SECRET: OnceLock<String> = OnceLock::new();
    SECRET.get_or_init(|| {
        use rand::Rng;
        rand::thread_rng()
            .sample_iter(rand::distributions::Alphanumeric)
            .take(48)
            .map(char::from)
            .collect()
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
                    // 停止失败仍照常关窗；控制器身份/协议异常会通过 close-failed
                    // 事件报告，窗口关闭不会再尝试按端口或 PID 猜测并杀进程。
                    if let Err(e) = commands::stop_bot().await {
                        eprintln!("关闭时停止 Bot 失败（照常关窗）：{e}");
                        let _ = window.emit("close-failed", e);
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
            commands::read_start_progress,
            commands::wait_bot_ready,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
