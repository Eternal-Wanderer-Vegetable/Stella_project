export default function memorySystemExtension(pi: any) {
  console.log("==========================================");
  console.log("🔥 [DEBUG] memory_system 扩展已成功被 PI Agent 加载！");
  console.log("==========================================");

  // 1. 注册工具清空逻辑到事件生命周期（不在加载阶段直接调用）
  const disableTools = () => {
    if (typeof pi.setActiveTools === 'function') {
      try {
        pi.setActiveTools([]);
        console.log("🔥 [DEBUG] 事件触发：已成功调用 pi.setActiveTools([]) 强行清空工具！");
      } catch (err) {
        console.error("❌ [DEBUG] 设置工具列表失败:", err);
      }
    }
  };

  if (pi.events && typeof pi.events.on === 'function') {
    // 监听 session/agent 启动事件
    pi.events.on('session:start', disableTools);
    pi.events.on('agent:start', disableTools);
    pi.events.on('before_request', disableTools);
  } else if (typeof pi.on === 'function') {
    pi.on('session:start', disableTools);
    pi.on('agent:start', disableTools);
    pi.on('before_request', disableTools);
  }

  return {
    name: 'memory_system',
    tools: []
  };
}