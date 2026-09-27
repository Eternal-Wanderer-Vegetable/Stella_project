/**
 * mineflayer-pathfinder 只在包导出面上带类型;性能补丁与基准要摸 lib 子路径
 * (AStar/Move 未导出),这里补最小声明。形状在 pathfinder-perf.ts 使用处自行收窄。
 */
declare module 'mineflayer-pathfinder/lib/astar.js' {
  const AStar: unknown;
  export default AStar;
}

declare module 'mineflayer-pathfinder/lib/move.js' {
  const Move: unknown;
  export default Move;
}
