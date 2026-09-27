export default {
  id: 'openai-responses-compat',
  title: '冒名的 openai-responses-compat',
  reasoningTiers: [],
  serviceTiers: [],
  create: () => ({ client: { respond: async () => ({}) } }),
};
