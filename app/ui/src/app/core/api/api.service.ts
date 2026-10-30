import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, catchError, map, of, throwError, timeout } from 'rxjs';
import { ConfigService } from '../config/config.service';
import { EndpointKey } from '../config/config.models';
import { SKIP_AUTH } from '../auth/auth.interceptor';
import { toApiError } from './api-error';
import {
  agentReply,
  anomalyRecords,
  cursorPage,
  duplicateRecords,
  exposureRecords,
  expiryRecords,
  unpaged,
} from './api.mappers';
import {
  AgentMessageRequest,
  AgentMessageResponse,
  AgentPrompt,
  AgentPromptsResponse,
  AgentReply,
  AnomaliesResponse,
  ChildrenResponse,
  CleanupRecord,
  DocumentDetail,
  DocumentListResponse,
  DocumentPreview,
  DocumentPage,
  DraftRequest,
  DraftResult,
  DuplicatesResponse,
  ExpiryResponse,
  ExposureResponse,
  HealthResponse,
  HygieneFindingDetail,
  HygieneSummary,
  KnowledgeConfig,
  KnowledgeDraft,
  KnowledgeExtractRequest,
  KnowledgeExtractResponse,
  KnowledgeIndexingStatus,
  KnowledgePublishRequest,
  KnowledgePublishResult,
  LibraryList,
  NotificationItem,
  NotificationListResponse,
  NotificationPage,
  Page,
  PermissionsResponse,
  PolicyResponse,
  SiteInfoResponse,
  UserAccessRecord,
  UserItemsResponse,
  UserSearchResponse,
  UserSearchResult,
} from './models/api.models';

interface SendOptions {
  params?: Record<string, string>;
  body?: unknown;
  skipAuth?: boolean;
  skipSiteContext?: boolean;
}

/** Typed client for the governance API. Every URL comes from app.config.json and apiBaseUrl. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly config = inject(ConfigService);
  readonly siteContext = signal<string | null>(typeof localStorage !== 'undefined' ? localStorage.getItem('selectedSiteId') : null);
  readonly isSwitchingSite = signal<boolean>(false);

  health(): Observable<HealthResponse> {
    return this.send<HealthResponse>('GET', this.endpoint('health'), { skipAuth: true });
  }

  siteInfo(): Observable<SiteInfoResponse> {
    return this.send<SiteInfoResponse>('GET', this.endpoint('siteInfo'));
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

  libraries(): Observable<LibraryList> {
    return this.send<LibraryList>('GET', this.endpoint('libraries'));
  }

  /** Children of a library, or of one folder when folderId is set (the API names it folderId). */
  libraryChildren(libraryId: string, folderId: string | null): Observable<ChildrenResponse> {
    const params = folderId ? { folderId } : undefined;
    return this.send<ChildrenResponse>('GET', this.endpoint('libraryChildren', { id: libraryId }), { params });
  }

  itemPermissions(itemId: string): Observable<PermissionsResponse> {
    return this.send<PermissionsResponse>('GET', this.endpoint('itemPermissions', { id: itemId }));
  }

  searchUsers(query: string): Observable<UserSearchResult[]> {
    return this.send<UserSearchResponse>('GET', this.endpoint('accessUsers'), { params: { query } }).pipe(
      map((response) => response.users),
    );
  }

  userItems(userKey: string, cursor: string | null = null): Observable<Page<UserAccessRecord>> {
    return this.send<UserItemsResponse>('GET', this.endpoint('accessUserItems', { key: userKey }), {
      params: this.pageParams(cursor),
    }).pipe(map((response) => cursorPage(response)));
  }

  /** Governance documents in one knowledge category ("" lists all), page by page. */
  documents(category: string, cursor: string | null = null, iteration: string | null = null): Observable<DocumentPage> {
    const params: Record<string, string> = { ...this.pageParams(cursor) };
    if (category) {
      params['knowledgeCategory'] = category;
    }
    if (iteration) {
      params['documentIteration'] = iteration;
    }
    return this.send<DocumentListResponse>('GET', this.endpoint('documents'), { params }).pipe(
      map((response) => ({
        ...cursorPage(response),
        total: response.total,
        knowledgeCategories: response.knowledgeCategories,
        documentIterations: response.documentIterations ?? [],
      })),
    );
  }

  document(id: string): Observable<DocumentDetail> {
    return this.send<DocumentDetail>('GET', this.endpoint('document', { id }));
  }

  /** Raw file bytes for the in-page viewer (PDF/video/text), as a Blob so it can become an object URL. */
  documentContent(id: string): Observable<Blob> {
    const url = this.endpoint('documentContent', { id });
    const site = this.siteContext();
    const paramsObject: Record<string, string> = {};
    if (site) {
      paramsObject['site'] = site;
    }
    const params = Object.keys(paramsObject).length > 0 ? new HttpParams({ fromObject: paramsObject }) : undefined;
    return this.http
      .get(url, { params, responseType: 'blob' })
      .pipe(
        timeout(this.config.app.requestTimeoutMs),
        catchError((error: unknown) => throwError(() => toApiError(error))),
      );
  }

  /** Structured preview (paragraphs/tables, sheets or slides) for docx, xlsx and pptx files. */
  documentPreview(id: string): Observable<DocumentPreview> {
    return this.send<DocumentPreview>('GET', this.endpoint('documentPreview', { id }));
  }

  /** One cleanup segment. Each analytics route has its own shape, so every segment becomes one record list. */
  cleanup(segment: string): Observable<Page<CleanupRecord>> {
    const url = this.endpoint('cleanup', { segment });
    switch (segment) {
      case 'duplicates':
        return this.send<DuplicatesResponse>('GET', url).pipe(map((response) => unpaged(duplicateRecords(response))));
      case 'expiry':
        return this.send<ExpiryResponse>('GET', url).pipe(map((response) => unpaged(expiryRecords(response))));
      case 'anomalies':
        return this.send<AnomaliesResponse>('GET', url).pipe(map((response) => unpaged(anomalyRecords(response))));
      case 'exposure':
        return this.send<ExposureResponse>('GET', url).pipe(map((response) => unpaged(exposureRecords(response))));
      default:
        return of(unpaged<CleanupRecord>([]));
    }
  }

  notifications(status: string | null): Observable<NotificationPage> {
    return this.send<NotificationListResponse>('GET', this.endpoint('notifications'), {
      params: status ? { status } : undefined,
    }).pipe(map((response) => ({ ...unpaged(response.items), total: response.total, mode: response.mode })));
  }

  createDrafts(templateId: string, documentIds: string[]): Observable<DraftResult> {
    const request: DraftRequest = { templateId, documentIds };
    return this.send<DraftResult>('POST', this.endpoint('notificationDrafts'), { body: request });
  }

  approveNotification(id: string): Observable<NotificationItem> {
    return this.send<NotificationItem>('POST', this.endpoint('notificationApprove', { id }));
  }

  sendNotification(id: string): Observable<NotificationItem> {
    return this.send<NotificationItem>('POST', this.endpoint('notificationSend', { id }));
  }

  agentPrompts(): Observable<AgentPromptsResponse> {
    return this.send<AgentPromptsResponse>('GET', this.config.app.apiBaseUrl.replace(/\/+$/, '') + this.config.agent.promptsPath);
  }

  agentMessage(prompt: string): Observable<AgentReply> {
    const request: AgentMessageRequest = { prompt };
    return this.send<AgentMessageResponse>('POST', this.config.app.apiBaseUrl.replace(/\/+$/, '') + this.config.agent.messagesPath, {
      body: request,
    }).pipe(map((response) => agentReply(response)));
  }

  knowledgeConfig(): Observable<KnowledgeConfig> {
    return this.send<KnowledgeConfig>('GET', this.endpoint('knowledgeConfig'), { skipSiteContext: true });
  }

  knowledgeExtract(request: KnowledgeExtractRequest): Observable<KnowledgeExtractResponse> {
    return this.send<KnowledgeExtractResponse>('POST', this.endpoint('knowledgeExtract'), { body: request, skipSiteContext: true });
  }

  knowledgeBlankDraft(): Observable<KnowledgeDraft> {
    return this.send<KnowledgeDraft>('GET', this.endpoint('knowledgeBlankDraft'), { skipSiteContext: true });
  }

  knowledgePublish(request: KnowledgePublishRequest): Observable<KnowledgePublishResult> {
    return this.send<KnowledgePublishResult>('POST', this.endpoint('knowledgePublish'), { body: request, skipSiteContext: true });
  }

  knowledgeIndexing(result: Pick<KnowledgePublishResult, 'artifactId' | 'publishedAt' | 'aiReady'>, refresh = false): Observable<KnowledgeIndexingStatus> {
    return this.send<KnowledgeIndexingStatus>(refresh ? 'POST' : 'GET', this.endpoint('knowledgeIndexing', { id: result.artifactId }), {
      params: { publishedAt: result.publishedAt, aiReady: String(result.aiReady) },
      skipSiteContext: true,
    });
  }

  knowledgeDocument(artifactId: string): Observable<Blob> {
    return this.http.get(this.endpoint('knowledgeDocument', { id: artifactId }), { responseType: 'blob' }).pipe(
      timeout(this.config.app.requestTimeoutMs),
      catchError((error: unknown) => throwError(() => toApiError(error))),
    );
  }

  setSiteContext(siteId: string | null): void {
    const next = siteId?.trim() ?? '';
    const val = next.length > 0 ? next : null;
    if (val !== this.siteContext()) {
      this.isSwitchingSite.set(true);
      this.siteContext.set(val);
      try {
        if (typeof localStorage !== 'undefined') {
          if (val) {
            localStorage.setItem('selectedSiteId', val);
          } else {
            localStorage.removeItem('selectedSiteId');
          }
        }
      } catch {
        // storage fallback
      }
      setTimeout(() => {
        this.isSwitchingSite.set(false);
      }, 1000);
    }
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

  /** Page parameters for routes that page by number. The first page is page 1. */
  private pageParams(cursor: string | null): Record<string, string> {
    return { pageSize: String(this.config.app.pageSize), page: cursor ?? '1' };
  }

  private send<T>(method: 'GET' | 'POST', url: string, options: SendOptions = {}): Observable<T> {
    const context = options.skipAuth ? new HttpContext().set(SKIP_AUTH, true) : undefined;
    const paramsObject = { ...(options.params ?? {}) };
    if (!options.skipSiteContext) {
      const site = this.siteContext();
      if (site && !paramsObject['site']) {
        paramsObject['site'] = site;
      }
    }
    const params = Object.keys(paramsObject).length > 0 ? new HttpParams({ fromObject: paramsObject }) : undefined;
    return this.http
      .request<T>(method, url, { params, body: options.body, context, responseType: 'json' })
      .pipe(
        timeout(this.config.app.requestTimeoutMs),
        catchError((error: unknown) => throwError(() => toApiError(error))),
      );
  }
}
