import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter, Router } from '@angular/router';
import { AgentFabComponent } from './agent-fab.component';
import { ConfigService } from '../../../core/config/config.service';
import appConfig from '../../../../assets/config/app.config.json';
import layoutConfig from '../../../../assets/config/layout.json';
import navigationConfig from '../../../../assets/config/navigation.json';
import agentConfig from '../../../../assets/config/agent.json';
import stringsConfig from '../../../../assets/config/strings.json';
import themeConfig from '../../../../assets/config/theme.json';
import pagesConfig from '../../../../assets/config/pages.json';
import { registerIcons } from '../../../core/icons/icon-registry';

describe('AgentFabComponent', () => {
  let fixture: ComponentFixture<AgentFabComponent>;
  let component: AgentFabComponent;
  let router: Router;

  beforeEach(async () => {
    registerIcons();
    await TestBed.configureTestingModule({
      imports: [AgentFabComponent],
      providers: [provideHttpClient(), provideRouter([])],
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
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 23 23"><rect class="sq-red" x="0" y="0" width="10.5" height="10.5"/><rect class="sq-green" x="11.5" y="0" width="10.5" height="10.5"/><rect class="sq-blue" x="0" y="11.5" width="10.5" height="10.5"/><rect class="sq-yellow" x="11.5" y="11.5" width="10.5" height="10.5"/></svg>',
    );

    router = TestBed.inject(Router);
    fixture = TestBed.createComponent(AgentFabComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('renders the agent FAB when on an allowed route', () => {
    expect(component).toBeTruthy();
    expect(component.visible()).toBeTrue();

    const element: HTMLElement = fixture.nativeElement;
    const fab = element.querySelector('[data-testid="agent-fab"]');
    expect(fab).toBeTruthy();
    expect(component.vertical).toBe('bottom');
    expect(component.horizontal).toBe('end');
    expect(fab?.querySelector('ion-fab-button')).toBeTruthy();
  });

  it('navigates to the agent route when activated', async () => {
    spyOn(router, 'navigateByUrl').and.returnValue(Promise.resolve(true));
    component.open();
    expect(router.navigateByUrl).toHaveBeenCalledWith(agentConfig.fab.route);
  });
});
