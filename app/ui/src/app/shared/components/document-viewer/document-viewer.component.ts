import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { IonIcon } from '@ionic/angular';
import { ApiService } from '../../../core/api/api.service';
import { DocumentPreview } from '../../../core/api/models/api.models';

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
}

const IDLE_STATE: ViewerState = { status: 'idle', objectUrl: null, textContent: null, preview: null };

/**
 * Renders a document (PDF, video, text/VTT transcript, or docx/xlsx/pptx) directly in the page instead
 * of linking out to SharePoint or Office. Fetches bytes through the API (so SharePoint auth is never
 * required in the browser) and, for office formats, a structured server-side preview.
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

  readonly document = input<ViewableDocument | null>(null);
  readonly state = signal<ViewerState>(IDLE_STATE);

  constructor() {
    effect((onCleanup) => {
      const doc = this.document();
      this.revoke();
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
      onCleanup(() => {
        cancelled = true;
      });
      if (type === 'office') {
        this.api.documentPreview(doc.id).subscribe({
          next: (preview) => {
            if (!cancelled) this.state.set({ ...IDLE_STATE, status: 'ready', preview });
          },
          error: () => {
            if (!cancelled) this.state.set({ ...IDLE_STATE, status: 'error' });
          },
        });
        return;
      }
      this.api.documentContent(doc.id).subscribe({
        next: (blob) => {
          if (cancelled) return;
          if (type === 'text') {
            blob.text().then((textContent) => {
              if (!cancelled) this.state.set({ ...IDLE_STATE, status: 'ready', textContent });
            });
          } else {
            const objectUrl = URL.createObjectURL(blob);
            this.state.set({ ...IDLE_STATE, status: 'ready', objectUrl });
          }
        },
        error: () => {
          if (!cancelled) this.state.set({ ...IDLE_STATE, status: 'error' });
        },
      });
    });
    this.destroyRef.onDestroy(() => this.revoke());
  }

  private revoke(): void {
    const current = this.state();
    if (current.objectUrl) {
      URL.revokeObjectURL(current.objectUrl);
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
