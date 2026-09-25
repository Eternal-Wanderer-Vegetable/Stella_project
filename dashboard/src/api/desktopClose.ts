// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
/** 桌面壳关闭流程的全屏遮罩（仅壳内生效，浏览器里是 no-op）。

 关闭窗口时 Rust 侧会先优雅停止 Bot（等待在途任务收尾，可能数十秒），
 期间窗口看似无响应——盖遮罩告诉用户正在关，避免被当成卡死而强杀进程
 （强杀会打断在途记忆整合）。对齐 v1 安装器的 installCloseOverlay。
 */

export function installCloseOverlay(): void {
  const w = window as any;
  const listen = w.__TAURI__?.event?.listen;
  if (typeof listen !== "function") return;

  void listen("close-requested", () => {
    if (document.getElementById("stella-close-overlay")) return;
    const overlay = document.createElement("div");
    overlay.id = "stella-close-overlay";
    overlay.innerHTML = `
      <style>
        #stella-close-overlay{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.72);}
        #stella-close-overlay .stella-close-card{display:flex;flex-direction:column;align-items:center;gap:14px;color:#fff;font-family:inherit;padding:28px 36px;border-radius:12px;background:rgba(30,30,30,.92);}
        #stella-close-overlay .stella-close-spin{width:34px;height:34px;border-radius:50%;border:3px solid rgba(255,255,255,.25);border-top-color:#fff;animation:stella-close-spin .9s linear infinite;}
        @keyframes stella-close-spin{to{transform:rotate(360deg)}}
      </style>
      <div class="stella-close-card">
        <div class="stella-close-spin"></div>
        <strong>正在安全关闭 Stella</strong>
        <span>正在等待 Bot 完成退出……若有未完成的记忆整合，可能需要数十秒，请勿强制关闭窗口。</span>
      </div>`;
    document.body.appendChild(overlay);
  });

  // 停止失败时撤掉遮罩（壳随即会关闭窗口；失败原因由壳记入日志）
  void listen("close-failed", () => {
    document.getElementById("stella-close-overlay")?.remove();
  });
}
