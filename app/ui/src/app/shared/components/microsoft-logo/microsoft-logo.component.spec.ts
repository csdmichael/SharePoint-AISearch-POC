import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { MicrosoftLogoComponent } from './microsoft-logo.component';
import { ConfigService } from '../../../core/config/config.service';
import appConfig from '../../../../assets/config/app.config.json';
import layoutConfig from '../../../../assets/config/layout.json';
import navigationConfig from '../../../../assets/config/navigation.json';
import agentConfig from '../../../../assets/config/agent.json';
import stringsConfig from '../../../../assets/config/strings.json';
import themeConfig from '../../../../assets/config/theme.json';
import pagesConfig from '../../../../assets/config/pages.json';

describe('MicrosoftLogoComponent', () => {
  let fixture: ComponentFixture<MicrosoftLogoComponent>;
  let component: MicrosoftLogoComponent;
  const sampleSvg = '<svg data-testid="test-svg" viewBox="0 0 10 10"></svg>';

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MicrosoftLogoComponent],
      providers: [provideHttpClient()],
    }).compileComponents();

    const config = TestBed.inject(ConfigService);
    config.install(
      {
        app: appConfig,
        layout: layoutConfig,
        navigation: navigationConfig,
        agent: agentConfig,
        strings: stringsConfig,
        theme: themeConfig,
        pages: pagesConfig,
      },
      sampleSvg,
    );

    fixture = TestBed.createComponent(MicrosoftLogoComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('renders the Microsoft logo with mark and wordmark', () => {
    expect(component).toBeTruthy();
    const element: HTMLElement = fixture.nativeElement;
    const logo = element.querySelector('[data-testid="ms-logo"]');
    expect(logo).toBeTruthy();
    expect(logo?.getAttribute('role')).toBe('img');
    expect(logo?.getAttribute('aria-label')).toBe(stringsConfig['header.logoAltText']);

    const wordmark = element.querySelector('.ms-logo__wordmark');
    expect(wordmark?.textContent?.trim()).toBe(stringsConfig['header.microsoftWordmark']);

    const mark = element.querySelector('.ms-logo__mark');
    expect(mark?.innerHTML).toContain('test-svg');
  });
});
