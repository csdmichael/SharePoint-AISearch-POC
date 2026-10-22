import { DestroyRef, ResourceRef, computed, inject, signal } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Observable } from 'rxjs';
import { ApiError, asApiError, toApiError } from '../../core/api/api-error';
import { Page } from '../../core/api/models/api.models';

export interface CursorListOptions<T, P extends Page<T>> {
  /** Undefined keeps the list idle, for example until the session gate is ready. */
  key: () => string | undefined;
  fetch: (key: string, cursor: string | null) => Observable<P>;
}

interface AppendedPages<T> {
  key: string | null;
  items: T[];
  nextCursor: string | null;
}

/**
 * A cursor-paged list bound to a key (segment, status, user). The first page loads through rxResource.
 * Later pages are appended with loadMore and discarded when the key changes.
 */
export class CursorList<T, P extends Page<T> = Page<T>> {
  private readonly destroyRef = inject(DestroyRef);
  private readonly options: CursorListOptions<T, P>;
  private readonly appended = signal<AppendedPages<T>>({ key: null, items: [], nextCursor: null });
  private readonly resource: ResourceRef<P | undefined>;

  readonly loadingMore = signal(false);
  readonly moreError = signal<ApiError | null>(null);

  /** The first page for the current key, including any extra response fields such as mode. */
  readonly page = computed<P | undefined>(() => this.resource.value());
  readonly loading = computed(() => this.resource.isLoading() || this.loadingMore());
  readonly error = computed(() => asApiError(this.resource.error()));
  readonly items = computed<T[]>(() => {
    const page = this.resource.value();
    if (!page) {
      return [];
    }
    const more = this.appended();
    const key = this.options.key();
    return more.key === key ? [...page.items, ...more.items] : [...page.items];
  });
  readonly nextCursor = computed<string | null>(() => {
    const more = this.appended();
    if (more.key !== null && more.key === this.options.key()) {
      return more.nextCursor;
    }
    return this.resource.value()?.nextCursor ?? null;
  });

  constructor(options: CursorListOptions<T, P>) {
    this.options = options;
    this.resource = rxResource({
      params: () => options.key(),
      stream: ({ params }) => options.fetch(params, null),
    });
  }

  reload(): void {
    this.resource.reload();
  }

  loadMore(): void {
    const key = this.options.key();
    const cursor = this.nextCursor();
    if (key === undefined || !cursor || this.loadingMore()) {
      return;
    }
    this.loadingMore.set(true);
    this.moreError.set(null);
    this.options
      .fetch(key, cursor)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (page) => {
          const previous = this.appended();
          const base = previous.key === key ? previous.items : [];
          this.appended.set({ key, items: [...base, ...page.items], nextCursor: page.nextCursor });
        },
        error: (error: unknown) => {
          this.moreError.set(toApiError(error));
          this.loadingMore.set(false);
        },
        complete: () => this.loadingMore.set(false),
      });
  }
}
