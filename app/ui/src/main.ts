import { bootstrapApplication } from '@angular/platform-browser';
import { AppComponent } from './app/app.component';
import { appConfig } from './app/app.config';
import { registerIcons } from './app/core/icons/icon-registry';

registerIcons();

bootstrapApplication(AppComponent, appConfig).catch((error: unknown) => {
  console.error('The application could not start. Check the configuration files in assets/config.', error);
  document.documentElement.setAttribute('data-startup', 'failed');
});
