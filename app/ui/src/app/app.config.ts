import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, inject, provideAppInitializer } from '@angular/core';
import { Router, RouteReuseStrategy, provideRouter, withComponentInputBinding } from '@angular/router';
import { IonicRouteStrategy, provideIonicAngular } from '@ionic/angular';
import { authInterceptor } from './core/auth/auth.interceptor';
import { AuthService } from './core/auth/auth.service';
import { ConfigService } from './core/config/config.service';
import { buildRoutes } from './core/navigation/navigation';
import { ThemeService } from './core/theme/theme.service';

/**
 * Startup order: load and validate configuration (fails fast), apply the theme, build routes from
 * navigation.json, then initialize MSAL. The router's first navigation runs after these steps.
 */
export const appConfig: ApplicationConfig = {
  providers: [
    { provide: RouteReuseStrategy, useClass: IonicRouteStrategy },
    provideIonicAngular(),
    provideHttpClient(withInterceptors([authInterceptor])),
    provideRouter([], withComponentInputBinding()),
    provideAppInitializer(async () => {
      const config = inject(ConfigService);
      const theme = inject(ThemeService);
      const router = inject(Router);
      const auth = inject(AuthService);

      await config.load();
      theme.apply();
      router.resetConfig(buildRoutes(config));
      await auth.initialize();
    }),
  ],
};
