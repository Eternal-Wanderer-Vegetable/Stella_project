import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildVLMRequestBody, mapVLMUsage, OpenRouterVLMClient, VLMError } from '../../../src/worlds/qq/vlm.ts';
import type { VLMMessage } from '../../../src/worlds/qq/vlm.ts';

const imageMessages: VLMMessage[] = [
  {
    role: 'user',
    content: [
      { type: 'image_url', image_url: { url: 'data:image/png;base64,AAAA' } },
      { type: 'text', text: '描述这张图' },
    ],
  },
];

describe('buildVLMRequestBody', () => {
  it('reasoning固定禁用 + max_tokens映射', () => {
    const body = buildVLMRequestBody('bytedance-seed/seed-2.0-mini', 1024, imageMessages);
    expect(body.model).toBe('bytedance-seed/seed-2.0-mini');
    expect(body.max_tokens).toBe(1024);
    expect(body.reasoning).toEqual({ enabled: false });
  });

  it('多模态content数组原样透传', () => {
    const body = buildVLMRequestBody('m', 512, imageMessages);
    expect(body.messages).toEqual(imageMessages);
  });

  it('纯文本多轮消息原样透传', () => {
    const msgs: VLMMessage[] = [
      ...imageMessages,
      { role: 'assistant', content: '一张红色方块图' },
      { role: 'user', content: '主要颜色?' },
    ];
    const body = buildVLMRequestBody('m', 512, msgs);
    expect(body.messages).toEqual(msgs);
  });
});

describe('mapVLMUsage', () => {
  it('OpenRouter无cache字段→填0', () => {
    expect(mapVLMUsage({ prompt_tokens: 100, completion_tokens: 20 })).toEqual({
      promptTokens: 100,
      completionTokens: 20,
      cacheHitTokens: 0,
      cacheMissTokens: 0,
    });
  });

  it('usage缺失→全0', () => {
    expect(mapVLMUsage(undefined)).toEqual({
      promptTokens: 0,
      completionTokens: 0,
      cacheHitTokens: 0,
      cacheMissTokens: 0,
    });
  });
});


function okResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), { status: 200 });
}

function makeClient(): OpenRouterVLMClient {
  return new OpenRouterVLMClient('sk-test', {
    baseUrl: 'https://openrouter.ai/api/v1',
    model: 'test-model',
    maxTokens: 256,
    timeoutMs: 5000,
  });
}

describe('OpenRouterVLMClient.chat(mock fetch)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('429后退避重试,再成功;usage正确映射', async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('rate limited', { status: 429 }))
      .mockResolvedValueOnce(
        okResponse({
          choices: [{ message: { content: '一张红色图片' } }],
          usage: { prompt_tokens: 88, completion_tokens: 7 },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const p = makeClient().chat(imageMessages);
    await vi.advanceTimersByTimeAsync(1000); // 第一次退避1s
    const r = await p;
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(r.text).toBe('一张红色图片');
    expect(r.usage).toEqual({ promptTokens: 88, completionTokens: 7, cacheHitTokens: 0, cacheMissTokens: 0 });
    // 请求体带reasoning禁用
    const sent = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(sent.reasoning).toEqual({ enabled: false });
    expect(sent.max_tokens).toBe(256);
  });

  it('400直抛VLMError,不重试', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('bad request', { status: 400 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(makeClient().chat(imageMessages)).rejects.toMatchObject({
      name: 'VLMError',
      status: 400,
      body: 'bad request',
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('响应缺choices抛VLMError(不重试:2xx解析失败属于4xx型直抛)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse({ usage: { prompt_tokens: 1 } }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(makeClient().chat(imageMessages)).rejects.toBeInstanceOf(VLMError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('usage缺失→全0;content为null→空串', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse({ choices: [{ message: { content: null } }] }));
    vi.stubGlobal('fetch', fetchMock);

    const r = await makeClient().chat(imageMessages);
    expect(r.text).toBe('');
    expect(r.usage).toEqual({ promptTokens: 0, completionTokens: 0, cacheHitTokens: 0, cacheMissTokens: 0 });
  });
});
