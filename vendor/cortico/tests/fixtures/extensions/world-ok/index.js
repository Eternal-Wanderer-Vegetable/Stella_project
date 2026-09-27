export default {
  id: 'fixture-world',
  label: '夹具 World',
  defaults: () => ({ enabled: false, port: 7 }),
  create: () => ({
    id: 'fixture-world',
    envPromptVars: () => ({}),
    tools: () => [],
    start: async () => {},
    stop: async () => {},
  }),
};
