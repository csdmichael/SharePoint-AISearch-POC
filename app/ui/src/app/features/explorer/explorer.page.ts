import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { IonContent, IonIcon, IonSelect, IonSelectOption } from '@ionic/angular';
import { ApiError, asApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { DriveItem, Library, PermissionEntry, PermissionMember } from '../../core/api/models/api.models';
import { ConfigService } from '../../core/config/config.service';
import { I18nService } from '../../core/i18n/i18n.service';
import { LayoutService } from '../../core/layout/layout.service';
import { SessionService, ViewState, resolveViewState } from '../../core/session/session.service';
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { DisplayService } from '../../shared/util/display.service';
import { safeHttpUrl } from '../../shared/util/url';

interface TreeBranch {
  items: DriveItem[];
  nextCursor: string | null;
  loading: boolean;
  error: ApiError | null;
}

type TreeRow =
  | { type: 'item'; item: DriveItem; depth: number }
  | { type: 'more'; parentKey: string; depth: number };

const ROOT_KEY = '';

/** Library, folder tree, permissions, and item details. Three panes on desktop, two on tablet, stacked on mobile. */
@Component({
  selector: 'app-explorer-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, IonSelect, IonSelectOption, StateViewComponent, TranslatePipe],
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
    params: () => (this.session.gate() === 'ready' ? true : undefined),
    stream: () => this.api.libraries(),
  });

  readonly libraryView = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.libraries.isLoading(),
      error: asApiError(this.libraries.error()),
      empty: (this.libraries.value()?.items.length ?? 0) === 0,
    }),
  );
  readonly libraryItems = computed<Library[]>(() => this.libraries.value()?.items ?? []);

  readonly selectedLibrary = signal<Library | null>(null);
  readonly branches = signal<Record<string, TreeBranch>>({});
  readonly expandedFolders = signal<ReadonlySet<string>>(new Set());
  readonly selectedItem = signal<DriveItem | null>(null);

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
        rows.push({ type: 'item', item, depth });
        if (item.kind === 'folder' && expanded.has(item.id)) {
          walk(item.id, depth + 1);
        }
      }
      if (branch.nextCursor) {
        rows.push({ type: 'more', parentKey, depth });
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
    params: () => (this.session.gate() === 'ready' ? this.selectedItem()?.id : undefined),
    stream: ({ params }) => this.api.itemPermissions(params),
  });

  readonly grantedViaFilter = signal('');
  readonly roleFilter = signal('');
  readonly selectedPermissionId = signal<string | null>(null);
  readonly expandedPrincipals = signal<ReadonlySet<string>>(new Set());

  readonly grantedViaOptions = computed(() => distinct((this.permissions.value() ?? []).map((entry) => entry.grantedVia)));
  readonly roleOptions = computed(() => distinct((this.permissions.value() ?? []).map((entry) => entry.role)));
  readonly filteredPermissions = computed<PermissionEntry[]>(() => {
    const grantedVia = this.grantedViaFilter();
    const role = this.roleFilter();
    return (this.permissions.value() ?? []).filter(
      (entry) => (grantedVia === '' || entry.grantedVia === grantedVia) && (role === '' || entry.role === role),
    );
  });
  readonly permissionView = computed<ViewState>(() => {
    const total = this.permissions.value()?.length ?? 0;
    return resolveViewState(this.session.gate(), {
      loading: this.permissions.isLoading(),
      error: asApiError(this.permissions.error()),
      empty: this.selectedItem() !== null && total === 0,
    });
  });
  readonly selectedPermission = computed<PermissionEntry | null>(
    () => this.permissions.value()?.find((entry) => entry.id === this.selectedPermissionId()) ?? null,
  );

  selectLibrary(library: Library): void {
    this.selectedLibrary.set(library);
    this.branches.set({});
    this.expandedFolders.set(new Set());
    this.selectedItem.set(null);
    this.loadBranch(ROOT_KEY, null, null);
  }

  reloadLibraries(): void {
    this.session.refresh();
    this.libraries.reload();
  }

  retryRoot(): void {
    const library = this.selectedLibrary();
    if (library) {
      this.loadBranch(ROOT_KEY, null, null);
    }
  }

  retryBranch(key: string): void {
    if (key === ROOT_KEY) {
      this.retryRoot();
      return;
    }
    this.loadBranch(key, key, null);
  }

  selectValue(event: { detail: { value?: unknown } }): string {
    const value = event.detail.value;
    return typeof value === 'string' ? value : '';
  }

  rowKey(row: TreeRow): string {
    return row.type === 'item' ? `item:${row.item.id}` : `more:${row.parentKey}`;
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
      this.loadBranch(item.id, item.id, null);
    }
  }

  loadMore(parentKey: string): void {
    const branch = this.branches()[parentKey];
    if (!branch?.nextCursor) {
      return;
    }
    this.loadBranch(parentKey, parentKey === ROOT_KEY ? null : parentKey, branch.nextCursor);
  }

  selectItem(item: DriveItem): void {
    this.selectedItem.set(item);
    this.selectedPermissionId.set(null);
    this.expandedPrincipals.set(new Set());
  }

  selectPermission(entry: PermissionEntry): void {
    this.selectedPermissionId.set(entry.id);
  }

  togglePrincipal(entry: PermissionEntry): void {
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

  isPrincipalExpanded(entry: PermissionEntry): boolean {
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

  permissionTypeLabel(value: string): string {
    return this.display.label('principalType', value);
  }

  memberLine(member: PermissionMember): string {
    const parts = [member.displayName, this.permissionTypeLabel(member.principalType), member.upn ?? ''].filter((part) => part !== '');
    return parts.join(this.i18n.text('explorer.separator'));
  }

  grantedViaLabel(value: string): string {
    return this.display.label('grantedVia', value);
  }

  safeLink(value: string | null): string | null {
    return safeHttpUrl(value);
  }

  formatSize(bytes: number | null): string {
    return bytes === null ? this.i18n.text('states.notAvailable') : this.i18n.text('explorer.sizeBytes', { count: this.i18n.number(bytes) });
  }

  private loadBranch(key: string, parentId: string | null, cursor: string | null): void {
    const library = this.selectedLibrary();
    if (!library) {
      return;
    }
    this.updateBranch(key, (current) => ({
      items: cursor ? current?.items ?? [] : [],
      nextCursor: cursor ? current?.nextCursor ?? null : null,
      loading: true,
      error: null,
    }));
    this.api
      .libraryChildren(library.id, parentId, cursor)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (page) => {
          if (this.selectedLibrary()?.id !== library.id) {
            return;
          }
          this.updateBranch(key, (current) => ({
            items: [...(current?.items ?? []), ...page.items],
            nextCursor: page.nextCursor,
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
            nextCursor: current?.nextCursor ?? null,
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
