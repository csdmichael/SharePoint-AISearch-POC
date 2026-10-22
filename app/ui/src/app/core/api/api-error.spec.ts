import { HttpErrorResponse } from '@angular/common/http';
import { TimeoutError } from 'rxjs';
import { ApiError, asApiError, toApiError } from './api-error';

describe('ApiError classification', () => {
  describe('toApiError', () => {
    it('preserves an existing ApiError instance', () => {
      const original = new ApiError('notFound', 404);
      expect(toApiError(original)).toBe(original);
    });

    it('classifies TimeoutError as unreachable', () => {
      const err = new TimeoutError();
      const classified = toApiError(err);
      expect(classified.kind).toBe('unreachable');
      expect(classified.status).toBeNull();
    });

    it('classifies HTTP status 0 as unreachable', () => {
      const httpErr = new HttpErrorResponse({ status: 0, statusText: 'Unknown Error' });
      const classified = toApiError(httpErr);
      expect(classified.kind).toBe('unreachable');
      expect(classified.status).toBe(0);
    });

    it('classifies HTTP status 401 as unauthorized', () => {
      const httpErr = new HttpErrorResponse({ status: 401, statusText: 'Unauthorized' });
      const classified = toApiError(httpErr);
      expect(classified.kind).toBe('unauthorized');
      expect(classified.status).toBe(401);
    });

    it('classifies HTTP status 403 as forbidden', () => {
      const httpErr = new HttpErrorResponse({ status: 403, statusText: 'Forbidden' });
      const classified = toApiError(httpErr);
      expect(classified.kind).toBe('forbidden');
      expect(classified.status).toBe(403);
    });

    it('classifies HTTP status 404 as notFound', () => {
      const httpErr = new HttpErrorResponse({ status: 404, statusText: 'Not Found' });
      const classified = toApiError(httpErr);
      expect(classified.kind).toBe('notFound');
      expect(classified.status).toBe(404);
    });

    it('classifies HTTP status 500 (or other 5xx) as server', () => {
      const httpErr = new HttpErrorResponse({ status: 500, statusText: 'Internal Server Error' });
      const classified = toApiError(httpErr);
      expect(classified.kind).toBe('server');
      expect(classified.status).toBe(500);
    });

    it('classifies non-HTTP errors as server', () => {
      const err = new Error('Unexpected failure');
      const classified = toApiError(err);
      expect(classified.kind).toBe('server');
      expect(classified.status).toBeNull();
    });
  });

  describe('asApiError', () => {
    it('returns null for undefined and null', () => {
      expect(asApiError(undefined)).toBeNull();
      expect(asApiError(null)).toBeNull();
    });

    it('classifies unreachable, unauthorized, forbidden, notFound, and server correctly', () => {
      expect(asApiError(new TimeoutError())?.kind).toBe('unreachable');
      expect(asApiError(new HttpErrorResponse({ status: 0 }))?.kind).toBe('unreachable');
      expect(asApiError(new HttpErrorResponse({ status: 401 }))?.kind).toBe('unauthorized');
      expect(asApiError(new HttpErrorResponse({ status: 403 }))?.kind).toBe('forbidden');
      expect(asApiError(new HttpErrorResponse({ status: 404 }))?.kind).toBe('notFound');
      expect(asApiError(new HttpErrorResponse({ status: 503 }))?.kind).toBe('server');
    });
  });
});
