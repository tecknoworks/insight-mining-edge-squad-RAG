// Configures the generated @hey-api/client-fetch client with the backend base
// URL. Imported once for its side effect (see main.tsx). This file is
// hand-written and lives OUTSIDE src/api/ (which is regenerated and must not be
// hand-edited).
import { client } from '../api/client.gen';

const baseUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

client.setConfig({ baseUrl });
