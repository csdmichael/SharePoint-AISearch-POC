import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { IonContent, IonIcon } from '@ionic/angular';
import { asApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { DocumentDetail } from '../../core/api/models/api.models';
import { ConfigService } from '../../core/config/config.service';
import { I18nService } from '../../core/i18n/i18n.service';
import { LayoutService } from '../../core/layout/layout.service';
import { SessionService, ViewState, resolveViewState } from '../../core/session/session.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { StateViewComponent } from '../../shared/components/state-view/state-view.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { DisplayService, ValueGroup } from '../../shared/util/display.service';
import { safeHttpUrl } from '../../shared/util/url';

type FieldKind = 'text' | 'date' | 'boolean' | 'list' | 'status' | 'trust';

interface FieldDefinition {
  key: keyof DocumentDetail;
  kind: FieldKind;
  group?: ValueGroup;
}

/** Governance fields in display order. Names match the repo's governance vocabulary. */
const FIELD_DEFINITIONS: FieldDefinition[] = [
  { key: 'path', kind: 'text' },
  { key: 'documentType', kind: 'text' },
  { key: 'productFamily', kind: 'text' },
  { key: 'processArea', kind: 'text' },
  { key: 'sensitivity', kind: 'text' },
  { key: 'businessUnit', kind: 'text' },
  { key: 'knowledgeCategory', kind: 'text' },
  { key: 'knowledgeOwner', kind: 'text' },
  { key: 'ownerDisplayName', kind: 'text' },
  { key: 'lifecycleStatus', kind: 'status', group: 'lifecycleStatus' },
  { key: 'dataQualityStatus', kind: 'status', group: 'dataQualityStatus' },
  { key: 'conflictStatus', kind: 'status', group: 'conflictStatus' },
  { key: 'authoritative', kind: 'boolean' },
  { key: 'aiReady', kind: 'boolean' },
  { key: 'effectiveDate', kind: 'date' },
  { key: 'expirationDate', kind: 'date' },
  { key: 'reviewDate', kind: 'date' },
  { key: 'lastValidatedDate', kind: 'date' },
  { key: 'duplicateOf', kind: 'text' },
  { key: 'conflictWith', kind: 'list' },
  { key: 'supersedesDocument', kind: 'text' },
  { key: 'trustScore', kind: 'trust' },
  { key: 'trustReasons', kind: 'list' },
];

interface FieldView {
  key: string;
  labelKey: string;
  text: string;
  list: string[] | null;
  badge: { text: string; color: string } | null;
}

/** Governance detail for one document (GET /documents/{id}). The id comes from the route. */
@Component({
  selector: 'app-document-detail-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonContent, IonIcon, BadgeComponent, StateViewComponent, TranslatePipe],
  templateUrl: './document-detail.page.html',
  styleUrl: './document-detail.page.scss',
  host: { class: 'ion-page' },
})
export class DocumentDetailPage {
  private readonly api = inject(ApiService);
  private readonly config = inject(ConfigService);
  private readonly display = inject(DisplayService);
  readonly i18n = inject(I18nService);
  readonly layout = inject(LayoutService);
  readonly session = inject(SessionService);

  readonly id = input.required<string>();
  readonly icons = this.config.layout.icons;

  readonly document = rxResource({
    params: () => (this.session.gate() === 'ready' ? this.id() : undefined),
    stream: ({ params }) => this.api.document(params),
  });

  readonly view = computed<ViewState>(() =>
    resolveViewState(this.session.gate(), {
      loading: this.document.isLoading(),
      error: asApiError(this.document.error()),
      empty: false,
    }),
  );

  readonly details = computed<DocumentDetail | null>(() => this.document.value() ?? null);
  readonly webLink = computed(() => safeHttpUrl(this.details()?.webUrl ?? null));
  readonly fields = computed<FieldView[]>(() => {
    const doc = this.details();
    return doc ? FIELD_DEFINITIONS.map((definition) => this.fieldView(doc, definition)) : [];
  });

  retry(): void {
    this.session.refresh();
    this.document.reload();
  }

  private fieldView(doc: DocumentDetail, definition: FieldDefinition): FieldView {
    const value = doc[definition.key];
    const base: FieldView = {
      key: definition.key,
      labelKey: `document.fields.${definition.key}`,
      text: this.i18n.text('states.notAvailable'),
      list: null,
      badge: null,
    };
    switch (definition.kind) {
      case 'date':
        return { ...base, text: this.i18n.date(typeof value === 'string' ? value : null) };
      case 'boolean':
        return { ...base, text: this.i18n.text(value === true ? 'document.yes' : value === false ? 'document.no' : 'states.notAvailable') };
      case 'list': {
        const listed: unknown = value;
        const items = Array.isArray(listed) ? listed.filter((item): item is string => typeof item === 'string') : [];
        return { ...base, text: items.length === 0 ? this.i18n.text('document.noneListed') : '', list: items };
      }
      case 'status': {
        const status = typeof value === 'string' ? value : null;
        if (status === null) {
          return base;
        }
        return { ...base, text: this.display.label(definition.group ?? 'lifecycleStatus', status), badge: { text: this.display.label(definition.group ?? 'lifecycleStatus', status), color: this.display.statusColor(status) } };
      }
      case 'trust': {
        if (typeof value !== 'number') {
          return base;
        }
        const text = this.i18n.text('document.trustScore', { score: this.i18n.number(value) });
        return { ...base, text, badge: { text, color: this.display.trustColor(value) } };
      }
      default:
        return { ...base, text: typeof value === 'string' && value.length > 0 ? value : this.i18n.text('states.notAvailable') };
    }
  }
}
