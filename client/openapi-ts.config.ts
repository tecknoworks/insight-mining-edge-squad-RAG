import { defineConfig } from '@hey-api/openapi-ts';

// Generates the typed API client into src/api/ from the backend's live OpenAPI
// schema. Run `pnpm --filter client generate:api` with the backend running on
// :8000. Treat src/api/ as generated output — never hand-edit it.
export default defineConfig({
  input: 'http://localhost:8000/openapi.json',
  output: {
    path: 'src/api',
    format: 'prettier',
  },
  plugins: ['@hey-api/client-fetch', '@hey-api/sdk', '@hey-api/typescript'],
});
