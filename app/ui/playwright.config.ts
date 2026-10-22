import { defineConfig } from '@playwright/test';
import devicesConfig from './e2e/config/devices.json';
import serverConfig from './e2e/config/e2e-server.json';

const projects = devicesConfig.devices.map((device) => ({
  name: device.name,
  use: {
    browserName: (device.fallbackEngine || device.engine || 'chromium') as 'chromium' | 'firefox' | 'webkit',
    viewport: device.viewport,
    deviceScaleFactor: device.deviceScaleFactor,
    isMobile: device.isMobile,
    hasTouch: device.hasTouch,
    ...(device.userAgent ? { userAgent: device.userAgent } : {}),
  },
}));

export default defineConfig({
  testDir: './e2e/specs',
  outputDir: serverConfig.outputFolder,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: serverConfig.url,
  },
  projects,
  webServer: {
    command: `${serverConfig.buildCommand} && ${serverConfig.serverCommand}`,
    url: serverConfig.url,
    timeout: serverConfig.startTimeoutMs,
    reuseExistingServer: true,
    env: {
      PORT: String(serverConfig.port),
      HOST: serverConfig.host,
    },
  },
});
