import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { IonContent, IonIcon, IonLabel, IonSegment, IonSegmentButton, IonSelect, IonSelectOption } from '@ionic/angular';
import { ApiError, asApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { DriveItem, Library, MemberView, PermissionEntry, PermissionWarning } from '../../core/api/models/api.models';
import { ConfigService } from '../../core/config/config.service';
import { I18nService } from '../../core/i18n/i18n.service';
import { LayoutService } from '../../core/layout/layout.service';
import { SessionService, ViewState, resolveViewState } from '../../core/session/session.service';
import { DocumentViewerComponent } from '../../shared/components/document-viewer/document-viewer.component';
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { DisplayService } from '../../shared/util/display.service';
import { safeHttpUrl } from '../../shared/util/url';

interface TreeBranch {
  items: DriveItem[];
  truncated: boolean;
  loading: boolean;
  error: ApiError | null;
}

interface TreeRow {
  item: DriveItem;
  depth: number;
}

/** A permission entry with the row key used for selection. The API does not number its entries. */
type PermissionRow = PermissionEntry & { id: string };
type PermissionTab = 'users' | 'groups';

const ROOT_KEY = '';

/** Library, folder tree, permissions, and item details. Three panes on desktop, two on tablet, stacked on mobile. */
@Component({
  selector: 'app-explorer-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, IonLabel, IonSegment, IonSegmentButton, IonSelect, IonSelectOption, DocumentViewerComponent, StateViewComponent, TranslatePipe],
  templateUrl: './explorer.page.html',
  styleUrl: './explorer.page.scss',
  host: { class: 'ion-page' },
})
export class ExplorerPage {
  private readonly api = inject(ApiService);
  private readonly config = inject(ConfigService);
  private readonly destroyRef = inject(DestroyRef);
  readonly display = inject(DisplayService);
  readonly i18n = inject(I18nService);
  readonly layout = inject(LayoutService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;

  readonly libraries = rxResource({
    params: () => (this.session.gate() === 'ready' ? this.api.siteContext() ?? '__default__' : undefined),
    stream: () => this.api.libraries(),
  });

  readonly libraryView = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.libraries.isLoading(),
      error: asApiError(this.libraries.error()),
      empty: this.libraryItems().length === 0,
    }),
  );
  readonly libraryItems = computed<Library[]>(() => this.libraries.hasValue() ? this.libraries.value().items : []);

  readonly selectedLibrary = signal<Library | null>(null);
  readonly branches = signal<Record<string, TreeBranch>>({});
  readonly expandedFolders = signal<ReadonlySet<string>>(new Set());
  readonly selectedItem = signal<DriveItem | null>(null);
  readonly detailTab = signal<'details' | 'preview'>('details');

  readonly visibleRows = computed<TreeRow[]>(() => {
    const rows: TreeRow[] = [];
    const branches = this.branches();
    const expanded = this.expandedFolders();
    const walk = (parentKey: string, depth: number): void => {
      const branch = branches[parentKey];
      if (!branch) {
        return;
      }
      for (const item of branch.items) {
        rows.push({ item, depth });
        if (item.kind === 'folder' && expanded.has(item.id)) {
          walk(item.id, depth + 1);
        }
      }
    };
    walk(ROOT_KEY, 0);
    return rows;
  });

  readonly rootBranch = computed<TreeBranch | undefined>(() => this.branches()[ROOT_KEY]);
  readonly rootView = computed<ViewState>(() => {
    const branch = this.rootBranch();
    return resolveViewState(this.session.gate(), {
      loading: branch?.loading ?? false,
      error: branch?.error ?? null,
      empty: branch !== undefined && branch.items.length === 0,
    });
  });

  readonly permissions = rxResource({
    params: () => {
      if (this.session.gate() !== 'ready') {
        return undefined;
      }
      const itemId = this.selectedItem()?.id;
      if (!itemId) {
        return undefined;
      }
      return `${this.api.siteContext() ?? '__default__'}:${itemId}`;
    },
    stream: ({ params }) => this.api.itemPermissions(params.slice(params.indexOf(':') + 1)),
  });
  private readonly permissionData = computed(() => this.permissions.hasValue() ? this.permissions.value() : undefined);

  readonly grantedViaFilter = signal('');
  readonly roleFilter = signal('');
  readonly permissionTab = signal<PermissionTab>('users');
  readonly selectedPermissionId = signal<string | null>(null);
  readonly expandedPrincipals = signal<ReadonlySet<string>>(new Set());

  readonly entries = computed<PermissionRow[]>(() =>
    (this.permissionData()?.entries ?? []).map((entry, index) => ({ ...entry, id: String(index) })),
  );
  readonly permissionWarnings = computed<PermissionWarning[]>(() => this.permissionData()?.warnings ?? []);
  readonly grantedViaOptions = computed(() => distinct(this.entries().map((entry) => entry.grantedVia)));
  readonly roleOptions = computed(() => distinct(this.entries().map((entry) => entry.role)));
  readonly filteredPermissions = computed<PermissionRow[]>(() => {
    const grantedVia = this.grantedViaFilter();
    const role = this.roleFilter();
    return this.entries().filter(
      (entry) => (grantedVia === '' || entry.grantedVia === grantedVia) && (role === '' || entry.role === role),
    );
  });
  readonly tabbedPermissions = computed<PermissionRow[]>(() => {
    const tab = this.permissionTab();
    return this.filteredPermissions().filter((entry) =>
      tab === 'users' ? this.isUserPrincipal(entry) : !this.isUserPrincipal(entry),
    );
  });
  readonly userPermissionCount = computed(() => this.filteredPermissions().filter((entry) => this.isUserPrincipal(entry)).length);
  readonly groupPermissionCount = computed(() => this.filteredPermissions().filter((entry) => !this.isUserPrincipal(entry)).length);
  readonly permissionView = computed<ViewState>(() => {
    const total = this.tabbedPermissions().length;
    return resolveViewState(this.session.gate(), {
      loading: this.permissions.isLoading(),
      error: asApiError(this.permissions.error()),
      empty: this.selectedItem() !== null && total === 0,
    });
  });
  readonly selectedPermission = computed<PermissionRow | null>(
    () => this.entries().find((entry) => entry.id === this.selectedPermissionId()) ?? null,
  );
  readonly treeTruncated = computed(() => Object.values(this.branches()).some((branch) => branch.truncated));

  constructor() {
    effect(() => {
      this.api.siteContext();
      this.selectedLibrary.set(null);
      this.branches.set({});
      this.expandedFolders.set(new Set());
      this.selectedItem.set(null);
      this.selectedPermissionId.set(null);
      this.expandedPrincipals.set(new Set());
      this.libraries.reload();
    });
    effect(() => {
      const libs = this.libraryItems();
      const current = this.selectedLibrary();
      if (libs.length > 0) {
        if (!current || !libs.some((l) => l.id === current.id)) {
          this.selectLibrary(libs[0]);
        }
      }
    });
    effect(() => {
      const selectedId = this.selectedPermissionId();
      if (!selectedId) {
        return;
      }
      if (!this.tabbedPermissions().some((entry) => entry.id === selectedId)) {
        this.selectedPermissionId.set(null);
      }
    });
  }

  selectLibrary(library: Library): void {
    this.selectedLibrary.set(library);
    this.branches.set({});
    this.expandedFolders.set(new Set());
    this.selectedItem.set(null);
    this.loadBranch(ROOT_KEY, null);
  }

  reloadLibraries(): void {
    this.session.refresh();
    this.libraries.reload();
  }

  retryRoot(): void {
    const library = this.selectedLibrary();
    if (library) {
      this.loadBranch(ROOT_KEY, null);
    }
  }

  retryBranch(key: string): void {
    if (key === ROOT_KEY) {
      this.retryRoot();
      return;
    }
    this.loadBranch(key, key);
  }

  selectValue(event: { detail: { value?: unknown } }): string {
    const value = event.detail.value;
    return typeof value === 'string' ? value : '';
  }

  selectPermissionTab(event: { detail: { value?: unknown } }): void {
    const value = event.detail.value;
    this.permissionTab.set(value === 'groups' ? 'groups' : 'users');
  }

  rowKey(row: TreeRow): string {
    return row.item.id;
  }

  toggleFolder(item: DriveItem): void {
    const next = new Set(this.expandedFolders());
    if (next.has(item.id)) {
      next.delete(item.id);
      this.expandedFolders.set(next);
      return;
    }
    next.add(item.id);
    this.expandedFolders.set(next);
    if (!this.branches()[item.id]) {
      this.loadBranch(item.id, item.id);
    }
  }

  selectItem(item: DriveItem): void {
    this.selectedItem.set(item);
    this.selectedPermissionId.set(null);
    this.expandedPrincipals.set(new Set());
    this.detailTab.set('details');
  }

  setDetailTab(tab: 'details' | 'preview'): void {
    this.detailTab.set(tab);
  }

  selectPermission(entry: PermissionRow): void {
    this.selectedPermissionId.set(entry.id);
  }

  togglePrincipal(entry: PermissionRow): void {
    const next = new Set(this.expandedPrincipals());
    if (next.has(entry.id)) {
      next.delete(entry.id);
    } else {
      next.add(entry.id);
    }
    this.expandedPrincipals.set(next);
  }

  isExpanded(id: string): boolean {
    return this.expandedFolders().has(id);
  }

  isSelectedItem(item: DriveItem): boolean {
    return this.selectedItem()?.id === item.id;
  }

  isPrincipalExpanded(entry: PermissionRow): boolean {
    return this.expandedPrincipals().has(entry.id);
  }

  branchFor(key: string): TreeBranch | undefined {
    return this.branches()[key];
  }

  itemLabel(item: DriveItem): string {
    return this.display.label('kind', item.kind);
  }

  toggleLabel(item: DriveItem): string {
    return this.i18n.text(this.isExpanded(item.id) ? 'a11y.collapseNode' : 'a11y.expandNode', { name: item.name });
  }

  permissionTypeLabel(entry: PermissionRow): string {
    return this.display.label('principalType', this.inferredPrincipalType(entry));
  }

  memberLine(member: MemberView): string {
    const parts = [
      member.displayName,
      member.userPrincipalName ?? '',
      member.accountEnabled === false ? this.i18n.text('explorer.accountDisabled') : '',
    ].filter((part) => part !== '');
    return parts.join(this.i18n.text('explorer.separator'));
  }

  grantedViaLabel(value: string): string {
    return this.display.label('grantedVia', value);
  }

  private isUserPrincipal(entry: PermissionRow): boolean {
    return this.inferredPrincipalType(entry) === 'user';
  }

  private inferredPrincipalType(entry: PermissionRow): string {
    if (entry.principal.type !== 'user') {
      return entry.principal.type;
    }
    if (entry.principal.email) {
      return 'user';
    }
    const login = (entry.principal.loginName ?? '').toLowerCase();
    if (
      login.includes('rolemanager') ||
      login.includes('federateddirectoryclaimprovider') ||
      login.includes('spo-grid-all-users')
    ) {
      return 'sharePointGroup';
    }
    const display = entry.principal.displayName.trim();
    if (/(owners|members|visitors)$/i.test(display)) {
      return 'sharePointGroup';
    }
    return 'user';
  }

  safeLink(value: string | null): string | null {
    return safeHttpUrl(value);
  }

  formatSize(bytes: number | null): string {
    return bytes === null ? this.i18n.text('states.notAvailable') : this.i18n.text('explorer.sizeBytes', { count: this.i18n.number(bytes) });
  }

  /** Whether the selected item has its own permissions or inherits them, and from which item. */
  scopeText(): string {
    const inheritance = this.permissionData()?.inheritance;
    if (inheritance?.hasUniquePermissions) {
      return this.i18n.text('explorer.uniquePermissions');
    }
    if (inheritance?.source) {
      return this.i18n.text('explorer.inheritsFrom', { path: inheritance.source.path });
    }
    return this.i18n.text('states.notAvailable');
  }

  /** Loads one level of a library (folderId null is the library root). The API does not page this list. */
  private loadBranch(key: string, folderId: string | null): void {
    const library = this.selectedLibrary();
    if (!library) {
      return;
    }
    this.updateBranch(key, () => ({ items: [], truncated: false, loading: true, error: null }));
    this.api
      .libraryChildren(library.id, folderId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (response) => {
          if (this.selectedLibrary()?.id !== library.id) {
            return;
          }
          this.updateBranch(key, () => ({
            items: response.items,
            truncated: response.truncated,
            loading: false,
            error: null,
          }));
        },
        error: (error: unknown) => {
          if (this.selectedLibrary()?.id !== library.id) {
            return;
          }
          this.updateBranch(key, (current) => ({
            items: current?.items ?? [],
            truncated: current?.truncated ?? false,
            loading: false,
            error: toApiError(error),
          }));
        },
      });
  }

  private updateBranch(key: string, change: (current: TreeBranch | undefined) => TreeBranch): void {
    this.branches.update((all) => ({ ...all, [key]: change(all[key]) }));
  }
}

function distinct(values: string[]): string[] {
  return [...new Set(values)].sort((a, b) => a.localeCompare(b));
}
