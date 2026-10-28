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
    params: () => (this.session.gate() === 'ready' && this.searchActive() ? this.searchTerm() : undefined),
    stream: ({ params }) => this.api.searchUsers(params),
  });
  readonly searchView = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.users.isLoading(),
      error: asApiError(this.users.error()),
      empty: this.userList().length === 0,
    }),
  );
  readonly userList = computed<UserSearchResult[]>(() => this.users.hasValue() ? this.users.value() : []);

  readonly selectedUser = signal<UserSearchResult | null>(null);
  readonly items = new CursorList<UserAccessRecord>({
    key: () => (this.session.gate() === 'ready' ? this.selectedUser()?.userKey : undefined),
    fetch: (key, cursor) => this.api.userItems(key, cursor),
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

  /** Groups the access came through, then how the role was granted: the item it was inherited from, or the grant type. */
  grantPath(record: UserAccessRecord): string[] {
    const how = record.inheritedFrom
      ? this.i18n.text('access.inheritedFrom', { path: record.inheritedFrom.path })
      : this.display.label('grantedVia', record.grantedVia);
    return [...record.via, how];
  }

  grantPathText(record: UserAccessRecord): string {
    return this.grantPath(record).join(this.config.pages.access.grantPathSeparator);
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
      this.i18n.text('access.columns.role'),
      this.i18n.text('access.columns.grantPath'),
    ];
    const rows = this.items.items().map((record) => [
      record.item.name,
      record.item.path ?? '',
      record.item.kind,
      record.role,
      this.grantPathText(record),
    ]);
    const content = toCsv(headers, rows, exportConfig.csvDelimiter, exportConfig.csvIncludeBom);
    downloadText(this.document, exportConfig.csvFileName, content, 'text/csv;charset=utf-8');
  }
}
