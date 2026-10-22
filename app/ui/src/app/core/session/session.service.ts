import { Injectable, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { AuthService } from '../auth/auth.service';
import { ApiService } from '../api/api.service';
import { ApiError, ApiErrorKind } from '../api/api-error';
import { ResponseMode } from '../api/models/api.models';

export type GateState = 'checking' | 'apiUnreachable' | 'authNotConfigured' | 'authError' | 'signInRequired' | 'ready';
export type ApiStatus = 'checking' | 'reachable' | 'unreachable';

/** API reachability, sign-in and the response mode shown in the header. */
@Injectable({ providedIn: 'root' })
export class SessionService {
  private readonly api = inject(ApiService);
  readonly auth = inject(AuthService);

  readonly apiStatus = signal<ApiStatus>('checking');
  readonly mode = signal<ResponseMode | null>(null);

  /** Pages load data only when the gate is ready. Otherwise they show the matching state from strings.json. */
  readonly gate = computed<GateState>(() => {
    const status = this.apiStatus();
    if (status === 'checking') {
      return 'checking';
    }
    if (status === 'unreachable') {
      return 'apiUnreachable';
    }
    if (this.auth.initFailed()) {
      return 'authError';
    }
    if (!this.auth.configured) {
      return 'authNotConfigured';
    }
    return this.auth.signedIn() ? 'ready' : 'signInRequired';
  });

  private healthCheck: Subscription | null = null;

  /** Runs the unauthenticated health check. A failure marks the API unreachable and shows the retry state. */
  refresh(): void {
    if (this.apiStatus() === 'unreachable') {
      this.apiStatus.set('checking');
    }
    this.healthCheck?.unsubscribe();
    this.healthCheck = this.api.health().subscribe({
      next: (health) => {
        this.mode.set(health.mode);
        this.apiStatus.set('reachable');
      },
      error: () => {
        this.mode.set(null);
        this.apiStatus.set('unreachable');
      },
    });
  }

  async signIn(): Promise<void> {
    await this.auth.signIn();
  }

  async signOut(): Promise<void> {
    await this.auth.signOut();
  }
}

export type ViewKind = 'loading' | 'gate' | 'error' | 'empty' | 'ready';

export interface ViewState {
  kind: ViewKind;
  gate: GateState | null;
  errorKind: ApiErrorKind | null;
}

export interface ViewInput {
  loading: boolean;
  error: ApiError | null;
  empty: boolean;
}

/** Decides which state a page shows. Gate states win, then errors, loading, empty, and finally ready content. */
export function resolveViewState(gate: GateState, input: ViewInput): ViewState {
  if (gate === 'checking') {
    return { kind: 'loading', gate: 'checking', errorKind: null };
  }
  if (gate !== 'ready') {
    return { kind: 'gate', gate, errorKind: null };
  }
  if (input.error) {
    switch (input.error.kind) {
      case 'unauthorized':
        return { kind: 'gate', gate: 'signInRequired', errorKind: 'unauthorized' };
      case 'unreachable':
        return { kind: 'gate', gate: 'apiUnreachable', errorKind: 'unreachable' };
      default:
        return { kind: 'error', gate: null, errorKind: input.error.kind };
    }
  }
  if (input.loading) {
    return { kind: 'loading', gate: null, errorKind: null };
  }
  if (input.empty) {
    return { kind: 'empty', gate: null, errorKind: null };
  }
  return { kind: 'ready', gate: null, errorKind: null };
}
