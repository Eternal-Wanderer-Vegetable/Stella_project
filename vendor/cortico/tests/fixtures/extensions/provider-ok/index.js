export default {
  id: 'fixture-provider',
  title: '夹具端点',
  reasoningTiers: [{ id: 'low', label: '低' }],
  serviceTiers: [],
  create: () => ({ client: { respond: async () => ({}) } }),
};
