// NotebookAI Tauri 2 desktop shell
//
// Spawns the FastAPI backend as a sidecar (via `uv run notebookai-api`),
// waits for /healthz to return 200, then reveals the main window. Applies
// macOS vibrancy (Sidebar effect) when available; on Linux/Windows we
// fall back to a solid background.

use std::sync::Mutex;
use std::time::Duration;

use tauri::{Emitter, Manager, RunEvent, WindowEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

#[cfg(target_os = "macos")]
use tauri::utils::config::WindowEffectsConfig;
#[cfg(target_os = "macos")]
use tauri::utils::{WindowEffect, WindowEffectState};

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 8765;

struct BackendChild(Mutex<Option<CommandChild>>);

#[tauri::command]
fn backend_url() -> String {
    format!("http://{}:{}", BACKEND_HOST, BACKEND_PORT)
}

fn spawn_backend(app: &tauri::AppHandle) -> Result<CommandChild, String> {
    // Phase 12 trade-off: invoke the user's installed `uv` rather than bundling
    // a Python interpreter. Phase 13/14 will swap this for a PyInstaller binary.
    let shell = app.shell();
    let cmd = shell
        .command("uv")
        .args([
            "run",
            "--project",
            "../../backend",
            "notebookai-api",
            "--host",
            BACKEND_HOST,
            "--port",
            &BACKEND_PORT.to_string(),
        ]);

    let (mut rx, child) = cmd
        .spawn()
        .map_err(|e| format!("failed to spawn backend sidecar: {e}"))?;

    // Drain stdout/stderr so the child does not block on a full pipe.
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        use tauri_plugin_shell::process::CommandEvent;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let _ = app_handle.emit(
                        "backend-log",
                        serde_json::json!({"stream": "stdout", "line": String::from_utf8_lossy(&line)}),
                    );
                }
                CommandEvent::Stderr(line) => {
                    let _ = app_handle.emit(
                        "backend-log",
                        serde_json::json!({"stream": "stderr", "line": String::from_utf8_lossy(&line)}),
                    );
                }
                CommandEvent::Terminated(payload) => {
                    let _ = app_handle.emit("backend-terminated", payload.code);
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(child)
}

async fn wait_for_health(timeout: Duration) -> bool {
    let url = format!("http://{}:{}/healthz", BACKEND_HOST, BACKEND_PORT);
    let deadline = std::time::Instant::now() + timeout;

    while std::time::Instant::now() < deadline {
        // Minimal HTTP probe via std::net so we avoid pulling in reqwest just for this.
        if let Ok(mut stream) = std::net::TcpStream::connect((BACKEND_HOST, BACKEND_PORT)) {
            use std::io::{Read, Write};
            let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
            let req = format!("GET /healthz HTTP/1.0\r\nHost: {}\r\n\r\n", BACKEND_HOST);
            if stream.write_all(req.as_bytes()).is_ok() {
                let mut buf = [0u8; 64];
                if let Ok(n) = stream.read(&mut buf) {
                    if n > 12 && buf[9] == b'2' {
                        let _ = url; // keep variable used for clarity
                        return true;
                    }
                }
            }
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
    false
}

#[cfg(target_os = "macos")]
fn apply_vibrancy(window: &tauri::WebviewWindow) {
    let effects = WindowEffectsConfig {
        effects: vec![WindowEffect::Sidebar],
        state: Some(WindowEffectState::Active),
        radius: None,
        color: None,
    };
    if let Err(e) = window.set_effects(effects) {
        eprintln!("set_effects failed: {e}");
    }
}

#[cfg(not(target_os = "macos"))]
fn apply_vibrancy(_window: &tauri::WebviewWindow) {
    // Linux/Windows: rely on transparent + frontend backdrop. Wayland transparency is best-effort.
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .manage(BackendChild(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![backend_url])
        .setup(|app| {
            let handle = app.handle().clone();

            // Spawn the backend sidecar; surface failure via event but keep the UI alive.
            match spawn_backend(&handle) {
                Ok(child) => {
                    let state = handle.state::<BackendChild>();
                    *state.0.lock().unwrap() = Some(child);
                }
                Err(err) => {
                    eprintln!("backend sidecar failed to start: {err}");
                    let _ = handle.emit("backend-error", err);
                }
            }

            // Apply vibrancy and reveal the window once /healthz responds.
            tauri::async_runtime::spawn(async move {
                let healthy = wait_for_health(Duration::from_secs(30)).await;
                if let Some(window) = handle.get_webview_window("main") {
                    apply_vibrancy(&window);
                    let _ = window.show();
                    let _ = window.set_focus();
                }
                let _ = handle.emit("notebookai-ready", healthy);
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // macOS UX: hide instead of quit on close so the dock icon keeps the app alive.
            #[cfg(target_os = "macos")]
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    let _ = window.hide();
                    api.prevent_close();
                }
            }
            #[cfg(not(target_os = "macos"))]
            {
                let _ = window;
                let _ = event;
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<BackendChild>() {
                    if let Some(child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
