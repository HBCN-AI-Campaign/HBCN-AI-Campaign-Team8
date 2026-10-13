import { createServer } from 'node:http';
import { createApp } from './app.mjs';
import { createAdapterFromEnv } from './bootstrap.mjs';

const port = Number(process.env.PORT || 4178);
const host = '127.0.0.1';
const adapter = await createAdapterFromEnv(process.env);
const app = createApp({ adapter });
const server = createServer(app);
server.listen(port, host, () => process.stdout.write(`Team8 gateway listening on http://${host}:${port} mode=${adapter?.mode || (adapter ? 'opencode' : 'offline')}\n`));
const stop = () => server.close(() => process.exit(0));
process.once('SIGINT', stop);
process.once('SIGTERM', stop);
