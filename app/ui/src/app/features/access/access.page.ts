import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
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
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CursorList } from '../../shared/util/cursor-list';
import { toCsv, downloadText } from '../../shared/util/csv';
import { DisplayService } from '../../shared/util/display.service';

/** Search users, list the items each user can reach with their role and grant path, and export the rows as CSV. */
@Component({
  selector: 'app-access-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, IonSearchbar, StateViewComponent, TranslatePipe],
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

  onSearch(value: string | null | undefined): void {
    this.queryInput.next(value ?? '');
  }

  selectUser(user: UserSearchResult): void {
    this.selectedUser.set(user);
  }

  isSelected(user: UserSearchResult): boolean {
    return this.selectedUser()?.userKey === user.userKey;
  }

  retrySearch(): void {
    this.session.refresh();
    this.users.reload();
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
