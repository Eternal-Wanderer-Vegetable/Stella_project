/**
 * 手动联网检查:安装指定 llama.cpp release,以 router 模式启动 llama-server 并下载模型,
 * 经 LlamaCppProvider 验证流式工具调用与思维链;不启动 bot。
 *
 *   tsx scripts/check-llamacpp.ts [--home <部署根>] [--backend cuda-13.3] [--release b10930]
 *                                 [--model ggml-org/Qwen3-0.6B-GGUF:Q8_0] [--port 8097] [--keep]
 *
 * 默认部署根为 scratch/llamacpp-check/;`--home` 可覆盖。`--keep` 在检查结束后保留服务进程。
 */
import { createServer } from 'node:http';
import { join, resolve } from 'node:path';
import { LlamaCppProvider } from '../src/providers/llamacpp/native.ts';
import { RouterCatalog } from '../src/providers/llamacpp/catalog.ts';
import { LAUNCH_DEFAULTS, PINNED_RELEASE, defaultBackend, releasePlan } from '../src/providers/llamacpp/options.ts';
import { RuntimeStore } from '../src/providers/llamacpp/runtime-store.ts';
import { LlamaServerManager, smartAppControlState } from '../src/providers/llamacpp/server.ts';
import { repoRoot } from '../src/paths.ts';
import type { Logger } from '../src/core/types.ts';
import { nullLogger } from '../src/core/util.ts';

function arg(name: string, fallback: string): string {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}
const home = resolve(arg('home', join(repoRoot(), 'scratch', 'llamacpp-check')));
const backend = arg('backend', defaultBackend());
const release = arg('release', PINNED_RELEASE);
const model = arg('model', 'ggml-org/Qwen3-0.6B-GGUF:Q8_0');
const keep = process.argv.includes('--keep');

const log: Logger = {
  ...nullLogger(),
  info: (msg, data) => console.log(`[info] ${msg}`, data ?? ''),
  warn: (msg, data) => console.log(`[warn] ${msg}`, data ?? ''),
  error: (msg, data) => console.log(`[error] ${msg}`, data ?? ''),
};

async function freePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as { port: number };
  await new Promise<void>((resolve) => server.close(() => resolve()));
  return port;
}
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const mb = (n: number) => `${(n / 1024 / 1024).toFixed(0)}MB`;

async function main(): Promise<void> {
  console.log(`部署根 ${home};release ${release};backend ${backend};SAC=${await smartAppControlState()}`);
  const plan = releasePlan(release, backend);
  if (!plan) throw new Error(`本机平台没有后端 ${backend} 的官方构建`);
  const store = new RuntimeStore(join(home, 'runtimes'), log);
  const dir = store.dir(release, plan);
  if (!store.installed(dir)) {
    const ticker = setInterval(() => {
      const state = store.state(dir);
      if (state.phase === 'downloading' || state.phase === 'extracting') console.log(`  ${state.phase} ${state.file} ${mb(state.done)}${state.total ? ` / ${mb(state.total)}` : ''}`);
    }, 3000);
    try {
      await store.install(release, plan);
    } finally {
      clearInterval(ticker);
    }
  }
  console.log(`运行时 ${dir}`);

  const port = Number(arg('port', '')) || (await freePort());
  const baseUrl = `http://127.0.0.1:${port}/v1`;
  const manager = new LlamaServerManager({
    name: 'check', baseUrl, runtimeDir: dir, serverExe: plan.serverExe,
    cacheDir: join(home, 'models', 'llamacpp', 'cache'), localModelsDir: join(home, 'models', 'llamacpp', 'local'),
    launch: { ...LAUNCH_DEFAULTS, contextSize: 8192 }, log, healthTimeoutMs: 120_000,
  });
  await manager.start();
  for (;;) {
    const state = await manager.state();
    if (state.phase === 'running') break;
    if (state.phase === 'error') throw new Error(state.detail ?? 'server error');
    await sleep(500);
  }
  console.log(`llama-server 就绪 ${baseUrl}`);

  const catalog = new RouterCatalog(() => ({ baseUrl }));
  let models = await catalog.list();
  console.log('模型列表', models.map((row) => `${row.id} [${row.status}]`));
  if (!models.some((row) => row.id === model)) {
    console.log(`拉取 ${model}`);
    await catalog.download(model);
    for (;;) {
      await sleep(2000);
      models = await catalog.list();
      const row = models.find((item) => item.id === model);
      if (!row) continue;
      if (row.status === 'downloading') console.log(`  下载 ${row.progress ? `${mb(row.progress.done)} / ${mb(row.progress.total)}` : ''}`);
      else if (row.status === 'failed') throw new Error(`模型下载或加载失败: ${model}`);
      else break;
    }
  }
  console.log('加载', model);
  await catalog.load(model);
  for (;;) {
    const row = (await catalog.list()).find((item) => item.id === model);
    if (row?.status === 'loaded') break;
    if (row?.status === 'failed') throw new Error(`模型加载失败: ${model}`);
    await sleep(1000);
  }
  await sleep(500);
  catalog.contextWindow(model);
  await catalog.settled(model);
  console.log('上下文窗口(/props)', catalog.contextWindow(model), '模态', (await catalog.list()).find((row) => row.id === model)?.inputModalities);

  const provider = new LlamaCppProvider({ baseUrl, log });
  let text = '';
  const first = await provider.respond(
    {
      model,
      instructions: 'You are a terse assistant. When asked for the time, call the tool.',
      input: [{ type: 'message', role: 'user', content: 'What time is it in Tokyo? Use the tool.' }],
      tools: [{ type: 'function', name: 'get_time', description: 'Current time in a city', parameters: { type: 'object', properties: { city: { type: 'string' } }, required: ['city'] } }],
      max_output_tokens: 256,
      reasoning: { effort: 'none' },
    },
    { nativeSpec: { model, thinking: false, maxTokens: 256 }, onEvent: (event) => { if (event.type === 'response.output_text.delta') text += event.delta; } },
  );
  console.log('工具调用检查(思维链关闭):', first.response.output.map((item) => item.type === 'function_call' ? `function_call ${item.name}(${item.arguments})` : item.type), '流式正文:', JSON.stringify(text));
  console.log('计量', first.attempts.at(-1)?.meters);

  const second = await provider.respond(
    { model, input: [{ type: 'message', role: 'user', content: 'In one sentence: why is the sky blue?' }], max_output_tokens: 512 },
    { nativeSpec: { model, thinking: true, maxTokens: 512 } },
  );
  console.log('思维链检查:', second.response.output.map((item) => `${item.type}:${'content' in item && Array.isArray(item.content) ? JSON.stringify(item.content).slice(0, 160) : ''}`));
  console.log('计量', second.attempts.at(-1)?.meters);

  if (!keep) await manager.stop();
  else console.log(`--keep:保留服务进程,${baseUrl}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
