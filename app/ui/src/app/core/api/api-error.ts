import { HttpErrorResponse } from '@angular/common/http';
import { TimeoutError } from 'rxjs';

export type ApiErrorKind = 'unreachable' | 'unauthorized' | 'forbidden' | 'notFound' | 'server';

/** A failed API call, classified so pages can show the matching state from strings.json. */
export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number | null,
    /** The API's error code and message ({"error": {"code", "message"}}), when it sent one. */
    readonly code: string | null = null,
    readonly detail: string | null = null,
  ) {
    super(`API error: ${kind}${status === null ? '' : ` (HTTP ${status})`}`);
    this.name = 'ApiError';
  }
}

function envelope(error: HttpErrorResponse): { code: string | null; detail: string | null } {
  const body: unknown = error.error;
  const inner = typeof body === 'object' && body !== null ? (body as { error?: unknown }).error : null;
  if (typeof inner !== 'object' || inner === null) {
    return { code: null, detail: null };
  }
  const { code, message } = inner as { code?: unknown; message?: unknown };
  return { code: typeof code === 'string' ? code : null, detail: typeof message === 'string' ? message : null };
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (error instanceof TimeoutError) {
    return new ApiError('unreachable', null);
  }
  if (error instanceof HttpErrorResponse) {
    const { code, detail } = envelope(error);
    if (error.status === 0) {
      return new ApiError('unreachable', 0);
    }
    if (error.status === 401) {
      return new ApiError('unauthorized', 401, code, detail);
    }
    if (error.status === 403) {
      return new ApiError('forbidden', 403, code, detail);
    }
    if (error.status === 404) {
      return new ApiError('notFound', 404, code, detail);
    }
    return new ApiError('server', error.status, code, detail);
  }
  return new ApiError('server', null);
}

/** The ApiError behind a resource error, or null when there is no error. */
export function asApiError(error: unknown): ApiError | null {
  return error === undefined || error === null ? null : toApiError(error);
}
