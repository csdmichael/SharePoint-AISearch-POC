import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IonContent, IonIcon, IonInput, IonLabel, IonSegment, IonSegmentButton } from '@ionic/angular';
import { ApiService } from '../../core/api/api.service';
import { DocumentPage, DocumentSummary } from '../../core/api/models/api.models';
import { ConfigService } from '../../core/config/config.service';
import { I18nService } from '../../core/i18n/i18n.service';
import { NavigationService } from '../../core/navigation/navigation';
import { SessionService, ViewState, resolveViewState } from '../../core/session/session.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { CursorList } from '../../shared/util/cursor-list';
import { DisplayService } from '../../shared/util/display.service';

/** Governance documents, filtered by knowledge category. Each title opens its governance detail. */
@Component({
  selector: 'app-document-list-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, IonInput, IonLabel, IonSegment, IonSegmentButton, RouterLink, BadgeComponent, StateViewComponent, TranslatePipe],
  templateUrl: './document-list.page.html',
  styleUrl: './document-list.page.scss',
  host: { class: 'ion-page' },
})
export class DocumentListPage {
  private readonly api = inject(ApiService);
  private readonly config = inject(ConfigService);
  readonly display = inject(DisplayService);
  readonly i18n = inject(I18nService);
  readonly navigation = inject(NavigationService);
  readonly session = inject(SessionService);

  readonly icons = this.config.layout.icons;

  /** The selected knowledge category. The empty string lists every category. */
  readonly category = signal('');
  /** The selected document iteration (e.g. Draft, Ready, etc.). */
  readonly iteration = signal('');
  readonly folderQuery = signal('');

  /** Segment value of the "All" choice. It is not a category name, so it cannot match one. */
  readonly allValue = '__all__';
  readonly documents = new CursorList<DocumentSummary, DocumentPage>({
    key: () => (this.session.gate() === 'ready' ? `${this.api.siteContext() ?? '__default__'}:${this.category()}:${this.iteration()}` : undefined),
    fetch: (key, cursor) => {
      const parts = key.split(':');
      const cat = parts[1] ?? '';
      const iter = parts[2] ? parts[2] : null;
      return this.api.documents(cat, cursor, iter);
    },
  });

  readonly view = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.documents.loading(),
      error: this.documents.error(),
      empty: this.documents.items().length === 0,
    }),
  );

  /** The categories in the whole library, so the choices stay the same when a category is selected. */
  readonly categories = computed<string[]>(() => this.documents.page()?.knowledgeCategories ?? []);
  readonly iterations = computed<string[]>(() => {
    const list = this.documents.page()?.documentIterations;
    if (list && list.length > 0) {
      return list;
    }
    return ['Draft', 'Ready', 'In Review', 'Approved', 'Archived'];
  });
  readonly filteredDocuments = computed<DocumentSummary[]>(() => {
    const query = this.folderQuery().trim().toLowerCase();
    const currentIter = this.iteration().trim().toLowerCase();
    let docs = this.documents.items();
    if (currentIter) {
      docs = docs.filter((doc) => (doc.documentIteration ?? '').toLowerCase() === currentIter);
    }
    if (query) {
      docs = docs.filter((doc) => (doc.path ?? '').toLowerCase().includes(query) || (doc.title ?? '').toLowerCase().includes(query));
    }
    return docs;
  });
  readonly countText = computed(() =>
    this.i18n.text('documents.countText', { count: this.i18n.number(this.filteredDocuments().length) }),
  );

  selectValue(event: { detail: { value?: unknown } }): string {
    const value = event.detail.value;
    return typeof value === 'string' ? value : '';
  }

  segmentValue(): string {
    return this.category() || this.allValue;
  }

  selectCategory(value: string): void {
    this.category.set(value === this.allValue ? '' : value);
  }

  iterationSegmentValue(): string {
    return this.iteration() || this.allValue;
  }

  selectIteration(value: string): void {
    this.iteration.set(value === this.allValue ? '' : value);
  }

  toggleDraftsOnly(): void {
    if (this.iteration().toLowerCase() === 'draft') {
      this.iteration.set('');
    } else {
      this.iteration.set('Draft');
    }
  }

  iterationLabel(value: string | null | undefined): string {
    return value ? value : this.i18n.text('states.notAvailable');
  }

  iterationColor(value: string | null | undefined): string {
    switch ((value ?? '').toLowerCase()) {
      case 'ready':
      case 'approved':
        return 'success';
      case 'draft':
        return 'warning';
      case 'in review':
        return 'primary';
      case 'archived':
        return 'danger';
      default:
        return 'neutral';
    }
  }

  updateFolderQuery(event: CustomEvent): void {
    const value = typeof event.detail?.value === 'string' ? event.detail.value : '';
    this.folderQuery.set(value);
  }

  documentPath(id: string): string {
    return this.navigation.documentPath(id);
  }

  lifecycleLabel(value: string | null): string {
    return value ? this.display.label('lifecycleStatus', value) : this.i18n.text('states.notAvailable');
  }

  ownerLabel(doc: DocumentSummary): string {
    return doc.ownerDisplayName ?? doc.knowledgeOwner ?? this.i18n.text('states.notAvailable');
  }

  trustLabel(score: number | null): string {
    return score === null ? this.i18n.text('states.notAvailable') : this.i18n.number(score);
  }

  trustColor(score: number | null): string {
    return score === null ? this.display.statusColor(null) : this.display.trustColor(score);
  }

  retry(): void {
    this.session.refresh();
    this.documents.reload();
  }
}
