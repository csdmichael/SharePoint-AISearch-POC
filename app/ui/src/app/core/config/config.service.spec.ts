import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { ConfigService } from './config.service';
import { ConfigValidationError } from './config.validation';
import appConfig from '../../../assets/config/app.config.json';
import layoutConfig from '../../../assets/config/layout.json';
import navigationConfig from '../../../assets/config/navigation.json';
import agentConfig from '../../../assets/config/agent.json';
import stringsConfig from '../../../assets/config/strings.json';
import themeConfig from '../../../assets/config/theme.json';
import pagesConfig from '../../../assets/config/pages.json';

describe('ConfigService', () => {
  let service: ConfigService;
  const validSvg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 23 23"></svg>';

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient()],
    });
    service = TestBed.inject(ConfigService);
  });

  it('accepts the JSON contract and makes configuration accessible', () => {
    service.install(
      {
        app: appConfig,
        layout: layoutConfig,
        navigation: navigationConfig,
        agent: agentConfig,
        strings: stringsConfig,
        theme: themeConfig,
        pages: pagesConfig,
      },
      validSvg,
    );

    expect(service.isLoaded).toBeTrue();
    expect(service.app.apiBaseUrl).toBe(appConfig.apiBaseUrl);
    expect(service.layout.breakpoints.desktopMinPx).toBe(layoutConfig.breakpoints.desktopMinPx);
    expect(service.navigation.items.length).toBeGreaterThan(0);
    expect(service.agent.maxInputChars).toBe(agentConfig.maxInputChars);
    expect(service.strings.appName).toBe(stringsConfig.appName);
    expect(service.theme.fontFamily).toBe(themeConfig.fontFamily);
    expect(service.pages.homeRoute).toBe(pagesConfig.homeRoute);
    expect(service.logoSvg).toBe(validSvg);
  });

  it('rejects an invalid configuration missing required sections', () => {
    expect(() => {
      service.install(
        {
          app: null as unknown as Record<string, unknown>,
          layout: layoutConfig,
          navigation: navigationConfig,
          agent: agentConfig,
          strings: stringsConfig,
          theme: themeConfig,
          pages: pagesConfig,
        },
        validSvg,
      );
    }).toThrowError(ConfigValidationError);
  });

  it('rejects an invalid configuration with malformed endpoints or strings', () => {
    const brokenApp = { ...appConfig, endpoints: {} };
    expect(() => {
      service.install(
        {
          app: brokenApp,
          layout: layoutConfig,
          navigation: navigationConfig,
          agent: agentConfig,
          strings: stringsConfig,
          theme: themeConfig,
          pages: pagesConfig,
        },
        validSvg,
      );
    }).toThrowError(ConfigValidationError);
  });
});
