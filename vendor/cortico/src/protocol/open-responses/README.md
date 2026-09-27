<!-- Owner: src/protocol/open-responses/index.ts -->

# Open Responses

`openapi.json` is the published 2026-04-24 schema from
https://www.openresponses.org/openapi/2026-04-24/openapi.json.
The upstream revision recorded at import is
`92c12d96d7b61d6d15e2214daa5e9c6000ab6e1c`.
The upstream schema is licensed under Apache-2.0; see LICENSE.

Regenerate types with `pnpm exec tsx scripts/generate-open-responses.ts`.
Use `--check` to verify the generated file and embedded schema digest.
Type generation preserves the published unions, including fields whose upstream
type is intentionally open. Stream lifecycle validation is implemented separately.
