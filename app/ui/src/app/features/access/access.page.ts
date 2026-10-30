import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { rxResource, toSignal } from '@angular/core/rxjs-interop';
import { IonContent, IonIcon, IonSearchbar } from '@ionic/angular';
import { Subject, debounceTime, distinctUntilChanged, map } from 'rxjs';
import { asApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { UserAccessRecord, UserSearchResult } from '../../core/api/models/api.models';
import { ConfigService } from '../../core/config/config.service';
import { I18nService } from '../../core/i18n/i18n.service';
import { LayoutService } from '../../core/layout/layout.service';
import { SessionService, ViewState, resolveViewState } from '../../core/session/session.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CursorList } from '../../shared/util/cursor-list';
import { toCsv, downloadText } from '../../shared/util/csv';
import { DisplayService } from '../../shared/util/display.service';

/** Search users, list the items each user can reach with their role and grant path, and export the rows as CSV. */
@Component({
  selector: 'app-access-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, IonSearchbar, BadgeComponent, StateViewComponent, TranslatePipe],
  templateUrl: './access.page.html',
  styleUrl: './access.page.scss',
  host: { class: 'ion-page' },
})
export class AccessPage {
  private readonly api = inject(ApiService);
  private readonly config = inject(ConfigService);
  private readonly document = inject(DOCUMENT);
  readonly display = inject(DisplayService);
  readonly i18n = inject(I18nService);
  readonly layout = inject(LayoutService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;
  readonly minQueryLength = this.config.pages.access.minQueryLength;

  private readonly queryInput = new Subject<string>();
  readonly searchTerm = toSignal(
    this.queryInput.pipe(
      debounceTime(this.config.pages.access.searchDebounceMs),
      map((value) => value.trim()),
      distinctUntilChanged(),
    ),
    { initialValue: '' },
  );
  readonly searchActive = computed(() => this.searchTerm().length >= this.minQueryLength);

  readonly users = rxResource({
    params: () =>
      this.session.gate() === 'ready' && this.searchActive()
        ? `${this.api.siteContext() ?? '__default__'}:${this.searchTerm()}`
        : undefined,
    stream: ({ params }) => this.api.searchUsers(params.slice(params.indexOf(':') + 1)),
  });
  readonly searchView = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.users.isLoading(),
      error: asApiError(this.users.error()),
      empty: this.userList().length === 0,
    }),
  );
  readonly userList = computed<UserSearchResult[]>(() =>
    this.users.hasValue() ? this.deduplicateUsers(this.users.value()) : [],
  );

  readonly selectedUser = signal<UserSearchResult | null>(null);
  readonly items = new CursorList<UserAccessRecord>({
    key: () =>
      this.session.gate() === 'ready' && this.selectedUser()?.userKey
        ? `${this.api.siteContext() ?? '__default__'}:${this.selectedUser()?.userKey ?? ''}`
        : undefined,
    fetch: (key, cursor) => this.api.userItems(key.slice(key.indexOf(':') + 1), cursor),
  });
  readonly itemsView = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.items.loading(),
      error: this.items.error(),
      empty: this.items.items().length === 0,
    }),
  );

  readonly itemFilter = signal('');
  readonly expandedKeys = signal<Set<string>>(new Set());
  readonly pageSize = signal(25);
  readonly currentPage = signal(1);

  readonly filteredItems = computed<UserAccessRecord[]>(() => {
    const query = this.itemFilter().trim().toLowerCase();
    const all = this.items.items();
    if (!query) return all;
    return all.filter(
      (r) =>
        (r.item.name || '').toLowerCase().includes(query) ||
        (r.item.path || '').toLowerCase().includes(query) ||
        (r.role || '').toLowerCase().includes(query) ||
        (r.grantedVia || '').toLowerCase().includes(query) ||
        r.via.some((v) => v.toLowerCase().includes(query)),
    );
  });

  readonly totalFilteredCount = computed(() => this.filteredItems().length);
  readonly totalPages = computed(() => Math.max(1, Math.ceil(this.totalFilteredCount() / this.pageSize())));
  readonly paginatedItems = computed<UserAccessRecord[]>(() => {
    const start = (this.currentPage() - 1) * this.pageSize();
    return this.filteredItems().slice(start, start + this.pageSize());
  });

  constructor() {
    effect(() => {
      this.api.siteContext();
      untracked(() => {
        this.selectedUser.set(null);
        this.expandedKeys.set(new Set());
        this.itemFilter.set('');
        this.currentPage.set(1);
        this.users.reload();
      });
    });
  }

  onSearch(value: string | null | undefined): void {
    this.queryInput.next(value ?? '');
  }

  selectUser(user: UserSearchResult): void {
    this.selectedUser.set(user);
    this.currentPage.set(1);
    this.expandedKeys.set(new Set());
  }

  isSelected(user: UserSearchResult): boolean {
    return this.selectedUser()?.userKey === user.userKey;
  }

  retrySearch(): void {
    this.session.refresh();
    this.users.reload();
  }

  isExpanded(record: UserAccessRecord): boolean {
    return this.expandedKeys().has(this.recordKey(record));
  }

  toggleExpand(record: UserAccessRecord): void {
    const key = this.recordKey(record);
    const next = new Set(this.expandedKeys());
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    this.expandedKeys.set(next);
  }

  expandAll(): void {
    const next = new Set<string>();
    for (const r of this.paginatedItems()) {
      next.add(this.recordKey(r));
    }
    this.expandedKeys.set(next);
  }

  collapseAll(): void {
    this.expandedKeys.set(new Set());
  }

  updateItemFilter(val: string | null | undefined): void {
    this.itemFilter.set(val ?? '');
    this.currentPage.set(1);
  }

  prevPage(): void {
    if (this.currentPage() > 1) {
      this.currentPage.update((p) => p - 1);
    }
  }

  nextPage(): void {
    if (this.currentPage() < this.totalPages()) {
      this.currentPage.update((p) => p + 1);
    }
  }

  setPageSize(size: number): void {
    this.pageSize.set(size);
    this.currentPage.set(1);
  }

  roleColor(role: string): string {
    const r = role.toLowerCase();
    if (r.includes('full control') || r.includes('manage')) return 'danger';
    if (r.includes('edit') || r.includes('contribute')) return 'primary';
    if (r.includes('read') || r.includes('view')) return 'success';
    if (r.includes('limited access')) return 'neutral';
    return 'neutral';
  }

  grantSummary(record: UserAccessRecord): string {
    if (record.grantedVia === 'direct') return 'Direct';
    if (record.grantedVia === 'sharePointGroup') {
      const g = this.joinVia(record.via);
      return `SP Group: ${g}`;
    }
    if (record.grantedVia === 'entraGroup') {
      const g = this.joinVia(record.via);
      return `Entra ID: ${g}`;
    }
    if (record.grantedVia === 'sharingLink') return 'Sharing Link';
    if (record.grantedVia === 'everyone') return 'Everyone';
    return record.grantedVia;
  }

  fileIcon(record: UserAccessRecord): string {
    if (record.item.kind === 'folder') return 'folder-outline';
    const name = record.item.name.toLowerCase();
    if (name.endsWith('.docx') || name.endsWith('.doc')) return 'document-text-outline';
    if (name.endsWith('.pptx') || name.endsWith('.ppt')) return 'easel-outline';
    if (name.endsWith('.xlsx') || name.endsWith('.xls')) return 'grid-outline';
    if (name.endsWith('.pdf')) return 'document-outline';
    if (name.endsWith('.vtt') || name.endsWith('.txt')) return 'reader-outline';
    if (name.endsWith('.mp4')) return 'videocam-outline';
    return 'document-outline';
  }

  kindLabel(kind: string): string {
    return this.display.label('kind', kind);
  }

  accessViaText(record: UserAccessRecord): string {
    const viaNames = this.joinVia(record.via);
    const base =
      record.grantedVia === 'direct'
        ? this.i18n.text('access.via.direct')
        : record.grantedVia === 'sharePointGroup'
          ? this.i18n.text('access.via.sharePointGroup', { groups: viaNames })
          : record.grantedVia === 'entraGroup'
            ? this.i18n.text('access.via.entraGroup', { groups: viaNames })
            : record.grantedVia === 'sharingLink'
              ? this.i18n.text('access.via.sharingLink')
              : record.grantedVia === 'everyone'
                ? this.i18n.text('access.via.everyone')
                : this.display.label('grantedVia', record.grantedVia);
    if (!record.inheritedFrom) {
      return base;
    }
    return `${base}${this.config.pages.access.grantPathSeparator}${this.i18n.text('access.inheritedFrom', { path: record.inheritedFrom.path })}`;
  }

  private joinVia(via: readonly string[]): string {
    const names = [...new Set(via.map((value) => value.trim()).filter((value) => value !== ''))];
    return names.length > 0 ? names.join(', ') : this.display.notAvailable();
  }

  private deduplicateUsers(users: readonly UserSearchResult[]): UserSearchResult[] {
    const byDisplay = new Map<string, UserSearchResult[]>();
    for (const user of users) {
      const key = user.displayName.trim().toLowerCase();
      const list = byDisplay.get(key);
      if (list) {
        list.push(user);
      } else {
        byDisplay.set(key, [user]);
      }
    }

    const deduplicated: UserSearchResult[] = [];
    for (const matches of byDisplay.values()) {
      if (matches.length === 1) {
        deduplicated.push(matches[0]);
        continue;
      }
      const internal = matches.find((candidate) => !candidate.external);
      deduplicated.push(internal ?? matches[0]);
    }
    return deduplicated.sort((a, b) => a.displayName.localeCompare(b.displayName));
  }

  recordKey(record: UserAccessRecord): string {
    return [record.item.id, record.role, record.grantedVia, record.via.join('>'), record.inheritedFrom?.path ?? ''].join('|');
  }

  exportCsv(): void {
    const exportConfig = this.config.app.export;
    const headers = [
      this.i18n.text('access.columns.name'),
      this.i18n.text('access.columns.path'),
      this.i18n.text('access.columns.kind'),
      this.i18n.text('access.columns.accessLevel'),
      this.i18n.text('access.columns.accessVia'),
    ];
    const rows = this.items.items().map((record) => [
      record.item.name,
      record.item.path ?? '',
      record.item.kind,
      record.role,
      this.accessViaText(record),
    ]);
    const content = toCsv(headers, rows, exportConfig.csvDelimiter, exportConfig.csvIncludeBom);
    downloadText(this.document, exportConfig.csvFileName, content, 'text/csv;charset=utf-8');
  }
}
