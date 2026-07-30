import fs from 'node:fs';
import path from 'node:path';
import { defineConfig } from '@playwright/test';

const browserRoot = process.env.LOCALAPPDATA
  ? path.join(process.env.LOCALAPPDATA, 'ms-playwright')
  : '';
const installedHeadlessShell = browserRoot && fs.existsSync(browserRoot)
  ? fs.readdirSync(browserRoot)
    .filter((entry) => entry.startsWith('chromium_headless_shell-'))
    .sort()
    .reverse()
    .map((entry) => path.join(
      browserRoot,
      entry,
      'chrome-headless-shell-win64',
      'chrome-headless-shell.exe',
    ))
    .find((candidate) => fs.existsSync(candidate))
  : undefined;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    launchOptions: {
      executablePath: installedHeadlessShell,
    },
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: true,
  },
});
