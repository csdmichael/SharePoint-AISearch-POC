import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError, timeout } from 'rxjs';
import { ConfigService } from '../config/config.service';
import { EndpointKey } from '../config/config.models';
import { SKIP_AUTH } from '../auth/auth.interceptor';
import { toApiError } from './api-error';
import {
  AgentMessageRequest,
  AgentPrompt,
  AgentPromptsResponse,
  AgentReply,
  CleanupRecord,
  DocumentDetail,
  DraftRequest,
  DraftResult,
  DriveItem,
  HealthResponse,
  HygieneFindingDetail,
  HygieneSummary,
  Library,
  NotificationPage,
  NotificationResult,
  Page,
  PermissionEntry,
  PolicyResponse,
  UserAccessItem,
  UserSearchResult,
} from './models/api.models';

interface SendOptions {
  params?: Record<string, string>;
  body?: unknown;
  skipAuth?: boolean;
}

/** Typed client for the governance API. Every URL comes from app.config.json and apiBaseUrl. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly config = inject(ConfigService);

  health(): Observable<HealthResponse> {
    return this.send<HealthResponse>('GET', this.endpoint('health'), { skipAuth: true });
  }

  policy(): Observable<PolicyResponse> {
    return this.send<PolicyResponse>('GET', this.endpoint('policy'));
  }

  hygiene(): Observable<HygieneSummary> {
    return this.send<HygieneSummary>('GET', this.endpoint('hygiene'));
  }

  hygieneFinding(id: string): Observable<HygieneFindingDetail> {
    return this.send<HygieneFindingDetail>('GET', this.endpoint('hygieneFinding', { id }));
  }

  libraries(cursor: string | null = null): Observable<Page<Library>> {
    return this.send<Page<Library>>('GET', this.endpoint('libraries'), { params: this.paging(cursor) });
  }

  libraryChildren(libraryId: string, parentId: string | null, cursor: string | null = null): Observable<Page<DriveItem>> {
    const params = { ...this.paging(cursor) };
    if (parentId) {
      params['parentId'] = parentId;
    }
    return this.send<Page<DriveItem>>('GET', this.endpoint('libraryChildren', { id: libraryId }), { params });
  }

  itemPermissions(itemId: string): Observable<PermissionEntry[]> {
    return this.send<PermissionEntry[]>('GET', this.endpoint('itemPermissions', { id: itemId }));
  }

  searchUsers(query: string): Observable<UserSearchResult[]> {
    return this.send<UserSearchResult[]>('GET', this.endpoint('accessUsers'), { params: { query } });
  }

  userItems(userKey: string, cursor: string | null = null): Observable<Page<UserAccessItem>> {
    return this.send<Page<UserAccessItem>>('GET', this.endpoint('accessUserItems', { key: userKey }), {
      params: this.paging(cursor),
    });
  }

  document(id: string): Observable<DocumentDetail> {
    return this.send<DocumentDetail>('GET', this.endpoint('document', { id }));
  }

  cleanup(segment: string, cursor: string | null = null): Observable<Page<CleanupRecord>> {
    return this.send<Page<CleanupRecord>>('GET', this.endpoint('cleanup', { segment }), { params: this.paging(cursor) });
  }

  notifications(status: string | null, cursor: string | null = null): Observable<NotificationPage> {
    const params = { ...this.paging(cursor) };
    if (status) {
      params['status'] = status;
    }
    return this.send<NotificationPage>('GET', this.endpoint('notifications'), { params });
  }

  createDrafts(request: DraftRequest): Observable<DraftResult> {
    return this.send<DraftResult>('POST', this.endpoint('notificationDrafts'), { body: request });
  }

  approveNotification(id: string): Observable<NotificationResult> {
    return this.send<NotificationResult>('POST', this.endpoint('notificationApprove', { id }));
  }

  sendNotification(id: string): Observable<NotificationResult> {
    return this.send<NotificationResult>('POST', this.endpoint('notificationSend', { id }));
  }

  agentPrompts(): Observable<AgentPromptsResponse> {
    return this.send<AgentPromptsResponse>('GET', this.config.app.apiBaseUrl.replace(/\/+$/, '') + this.config.agent.promptsPath);
  }

  agentMessage(message: string): Observable<AgentReply> {
    const request: AgentMessageRequest = { message };
    return this.send<AgentReply>('POST', this.config.app.apiBaseUrl.replace(/\/+$/, '') + this.config.agent.messagesPath, {
      body: request,
    });
  }

  private endpoint(key: EndpointKey, values: Record<string, string> = {}): string {
    const template = this.config.app.endpoints[key];
    const path = template.replace(/\{(\w+)\}/g, (_match: string, name: string) => {
      const value = values[name];
      if (value === undefined) {
        throw new Error(`Endpoint "${key}" needs a value for {${name}}.`);
      }
      return encodeURIComponent(value);
    });
    return this.config.app.apiBaseUrl.replace(/\/+$/, '') + path;
  }

  private paging(cursor: string | null): Record<string, string> {
    const params: Record<string, string> = { pageSize: String(this.config.app.pageSize) };
    if (cursor) {
      params['cursor'] = cursor;
    }
    return params;
  }

  private send<T>(method: 'GET' | 'POST', url: string, options: SendOptions = {}): Observable<T> {
    const context = options.skipAuth ? new HttpContext().set(SKIP_AUTH, true) : undefined;
    const params = options.params ? new HttpParams({ fromObject: options.params }) : undefined;
    return this.http
      .request<T>(method, url, { params, body: options.body, context, responseType: 'json' })
      .pipe(
        timeout(this.config.app.requestTimeoutMs),
        catchError((error: unknown) => throwError(() => toApiError(error))),
      );
  }
}
