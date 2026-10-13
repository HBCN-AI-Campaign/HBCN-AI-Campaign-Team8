import { createSDKAdapter } from './opencode.mjs';
import { createCodexCLIAdapter } from './codex-cli.mjs';

export async function createAdapterFromEnv(env = process.env, factories = {}) {
  if (env.OPENCODE_BASE_URL) {
    try {
      return await (factories.createSDKAdapter || createSDKAdapter)({
        baseUrl: env.OPENCODE_BASE_URL,
        username: env.OPENCODE_SERVER_USERNAME,
        password: env.OPENCODE_SERVER_PASSWORD,
      });
    } catch {
      return null;
    }
  }
  if (env.CODEX_CLI_PATH) {
    try {
      return await (factories.createCodexCLIAdapter || createCodexCLIAdapter)({
        cliPath: env.CODEX_CLI_PATH,
        model: env.CODEX_CLI_MODEL || 'gpt-6.1-sol',
        reasoningEffort: env.CODEX_CLI_REASONING_EFFORT || 'medium',
      });
    } catch {
      return null;
    }
  }
  return null;
}
