import { HttpErrorResponse } from '@angular/common/http';
import { TimeoutError } from 'rxjs';

export type ApiErrorKind = 'unreachable' | 'unauthorized' | 'forbidden' | 'notFound' | 'server';

/** A failed API call, classified so pages can show the matching state from strings.json. */
export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number | null,
  ) {
    super(`API error: ${kind}${status === null ? '' : ` (HTTP ${status})`}`);
    this.name = 'ApiError';
  }
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (error instanceof TimeoutError) {
    return new ApiError('unreachable', null);
  }
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0) {
      return new ApiError('unreachable', 0);
    }
    if (error.status === 401) {
      return new ApiError('unauthorized', 401);
    }
    if (error.status === 403) {
      return new ApiError('forbidden', 403);
    }
    if (error.status === 404) {
      return new ApiError('notFound', 404);
    }
    return new ApiError('server', error.status);
  }
  return new ApiError('server', null);
}

/** The ApiError behind a resource error, or null when there is no error. */
export function asApiError(error: unknown): ApiError | null {
  return error === undefined || error === null ? null : toApiError(error);
}
