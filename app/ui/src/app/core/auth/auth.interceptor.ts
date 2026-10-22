import { HttpContextToken, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { from, switchMap } from 'rxjs';
import { ConfigService } from '../config/config.service';
import { AuthService } from './auth.service';

/** Set on requests that must not carry a bearer token (the health check). */
export const SKIP_AUTH = new HttpContextToken<boolean>(() => false);

/** Adds a bearer token for apiScopes to every request under apiBaseUrl. */
export const authInterceptor: HttpInterceptorFn = (request, next) => {
  if (request.context.get(SKIP_AUTH)) {
    return next(request);
  }
  const apiBaseUrl = inject(ConfigService).app.apiBaseUrl;
  if (!request.url.startsWith(apiBaseUrl)) {
    return next(request);
  }
  const auth = inject(AuthService);
  return from(auth.acquireToken()).pipe(
    switchMap((token) => next(token ? request.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : request)),
  );
};
