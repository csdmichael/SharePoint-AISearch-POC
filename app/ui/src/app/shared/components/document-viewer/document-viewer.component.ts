import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, signal } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { IonIcon } from '@ionic/angular';
import { ApiService } from '../../../core/api/api.service';
import { DocumentPreview, DocumentPreviewSheet, DocumentPreviewSlide } from '../../../core/api/models/api.models';

export interface ViewableDocument {
  id: string;
  name: string;
  webUrl?: string | null;
}

export type ViewerType = 'pdf' | 'office' | 'text' | 'media' | 'other';

interface ViewerState {
  status: 'idle' | 'loading' | 'ready' | 'error' | 'unsupported';
  objectUrl: string | null;
  textContent: string | null;
  preview: DocumentPreview | null;
  error?: string;
}

const IDLE_STATE: ViewerState = { status: 'idle', objectUrl: null, textContent: null, preview: null };

/**
 * Renders a document (PDF, video, text/VTT transcript, or docx/xlsx/pptx) directly in the page instead
 * of linking out to SharePoint or Office. Supports multi-page, multi-slide, and multi-sheet navigation,
 * tables, and embedded diagrams/images.
 */
@Component({
  selector: 'app-document-viewer',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IonIcon],
  templateUrl: './document-viewer.component.html',
  styleUrl: './document-viewer.component.scss',
})
export class DocumentViewerComponent {
  private readonly api = inject(ApiService);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly destroyRef = inject(DestroyRef);
  private activeObjectUrl: string | null = null;

  readonly document = input<ViewableDocument | null>(null);
  readonly state = signal<ViewerState>(IDLE_STATE);
  /** null means show all pages/slides/sheets; 1..N means show a single page/slide/sheet. */
  readonly selectedPage = signal<number | null>(null);
  readonly pdfNativeMode = signal(false);

  readonly pageItems = computed<DocumentPreviewSlide[]>(() => {
    const p = this.state().preview;
    if (!p) return [];
    if (p.kind === 'pptx' && p.slides?.length) return p.slides;
    if ((p.kind === 'docx' || p.kind === 'pdf') && p.pages?.length) return p.pages;
    if (p.kind === 'docx' && (p.blocks?.length || p.tables?.length)) {
      const blocks = [
        ...(p.blocks ?? []),
        ...(p.tables ?? []).map((table) => ({ kind: 'table' as const, table })),
      ];
      return [{ number: 1, title: 'Page 1', blocks }];
    }
    return [];
  });

  readonly sheetItems = computed<DocumentPreviewSheet[]>(() => {
    const p = this.state().preview;
    return p?.kind === 'xlsx' && p.sheets?.length ? p.sheets : [];
  });

  readonly totalPages = computed<number>(() => {
    const p = this.state().preview;
    if (!p) return 0;
    if (p.kind === 'xlsx') return this.sheetItems().length;
    return this.pageItems().length;
  });

  readonly visiblePages = computed<DocumentPreviewSlide[]>(() => {
    const all = this.pageItems();
    const sel = this.selectedPage();
    if (sel === null) return all;
    return all.filter((item) => item.number === sel);
  });

  readonly visibleSheets = computed<DocumentPreviewSheet[]>(() => {
    const all = this.sheetItems();
    const sel = this.selectedPage();
    if (sel === null) return all;
    const item = all[sel - 1];
    return item ? [item] : all;
  });

  readonly pageUnitLabel = computed<string>(() => {
    const kind = this.state().preview?.kind;
    if (kind === 'pptx') return 'Slides';
    if (kind === 'xlsx') return 'Sheets';
    return 'Pages';
  });

  constructor() {
    effect(() => {
      const doc = this.document();
      this.revokeObjectUrl();
      this.selectedPage.set(null);
      this.pdfNativeMode.set(false);
      if (!doc) {
        this.state.set(IDLE_STATE);
        return;
      }
      const type = this.viewerType(doc.name);
      if (type === 'other') {
        this.state.set({ ...IDLE_STATE, status: 'unsupported' });
        return;
      }
      this.state.set({ ...IDLE_STATE, status: 'loading' });
      let cancelled = false;
      this.destroyRef.onDestroy(() => {
        cancelled = true;
      });

      if (type === 'office' || type === 'pdf') {
        this.api.documentPreview(doc.id).subscribe({
          next: (preview) => {
            if (!cancelled) {
              this.state.set({ ...IDLE_STATE, status: 'ready', preview });
            }
          },
          error: () => {
            if (cancelled) return;
            if (type === 'pdf') {
              this.loadPdfBlob(doc.id, () => cancelled);
            } else {
              this.state.set({ ...IDLE_STATE, status: 'error', error: 'Document preview could not be loaded.' });
            }
          },
        });
        if (type === 'pdf') {
          this.api.documentContent(doc.id).subscribe({
            next: (blob) => {
              if (cancelled) return;
              this.activeObjectUrl = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
              this.state.update((cur) => ({ ...cur, objectUrl: this.activeObjectUrl }));
            },
            error: () => {},
          });
        }
        return;
      }

      this.api.documentContent(doc.id).subscribe({
        next: (blob) => {
          if (cancelled) return;
          if (type === 'text') {
            blob.text().then((textContent) => {
              if (!cancelled) {
                this.state.set({ ...IDLE_STATE, status: 'ready', textContent });
              }
            });
          } else {
            this.activeObjectUrl = URL.createObjectURL(blob);
            this.state.set({ ...IDLE_STATE, status: 'ready', objectUrl: this.activeObjectUrl });
          }
        },
        error: () => {
          if (!cancelled) {
            this.state.set({ ...IDLE_STATE, status: 'error', error: 'Document content could not be loaded.' });
          }
        },
      });
    });

    this.destroyRef.onDestroy(() => this.revokeObjectUrl());
  }

  private loadPdfBlob(id: string, isCancelled: () => boolean): void {
    this.api.documentContent(id).subscribe({
      next: (blob) => {
        if (isCancelled()) return;
        this.activeObjectUrl = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
        this.pdfNativeMode.set(true);
        this.state.set({ ...IDLE_STATE, status: 'ready', objectUrl: this.activeObjectUrl });
      },
      error: () => {
        if (!isCancelled()) {
          this.state.set({ ...IDLE_STATE, status: 'error', error: 'Document content could not be loaded.' });
        }
      },
    });
  }

  selectPage(pageNumber: number | null): void {
    this.selectedPage.set(pageNumber);
  }

  prevPage(): void {
    const total = this.totalPages();
    if (total <= 1) return;
    const current = this.selectedPage();
    if (current === null || current <= 1) {
      this.selectedPage.set(1);
    } else {
      this.selectedPage.set(current - 1);
    }
  }

  nextPage(): void {
    const total = this.totalPages();
    if (total <= 1) return;
    const current = this.selectedPage();
    if (current === null) {
      this.selectedPage.set(1);
    } else if (current < total) {
      this.selectedPage.set(current + 1);
    }
  }

  togglePdfNative(): void {
    this.pdfNativeMode.update((v) => !v);
  }

  private revokeObjectUrl(): void {
    if (this.activeObjectUrl) {
      URL.revokeObjectURL(this.activeObjectUrl);
      this.activeObjectUrl = null;
    }
  }

  fileExtension(name: string): string {
    const idx = name.lastIndexOf('.');
    return idx >= 0 ? name.substring(idx).toLowerCase() : '';
  }

  viewerType(name: string): ViewerType {
    switch (this.fileExtension(name)) {
      case '.docx':
      case '.doc':
      case '.pptx':
      case '.ppt':
      case '.xlsx':
      case '.xls':
        return 'office';
      case '.pdf':
        return 'pdf';
      case '.vtt':
      case '.txt':
        return 'text';
      case '.mp4':
        return 'media';
      default:
        return 'other';
    }
  }

  safeResourceUrl(url: string | null): SafeResourceUrl | null {
    return url ? this.sanitizer.bypassSecurityTrustResourceUrl(url) : null;
  }
}
