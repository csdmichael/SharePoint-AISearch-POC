import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { of } from 'rxjs';
import { DocumentViewerComponent } from './document-viewer.component';
import { ApiService } from '../../../core/api/api.service';
import { ConfigService } from '../../../core/config/config.service';
import appConfig from '../../../../assets/config/app.config.json';
import layoutConfig from '../../../../assets/config/layout.json';
import navigationConfig from '../../../../assets/config/navigation.json';
import agentConfig from '../../../../assets/config/agent.json';
import stringsConfig from '../../../../assets/config/strings.json';
import themeConfig from '../../../../assets/config/theme.json';
import pagesConfig from '../../../../assets/config/pages.json';
import { registerIcons } from '../../../core/icons/icon-registry';

describe('DocumentViewerComponent', () => {
  let component: DocumentViewerComponent;
  let fixture: ComponentFixture<DocumentViewerComponent>;
  let apiService: jasmine.SpyObj<ApiService>;

  beforeEach(async () => {
    registerIcons();
    const apiSpy = jasmine.createSpyObj('ApiService', ['documentPreview', 'documentContent']);
    apiSpy.documentPreview.and.returnValue(
      of({ kind: 'docx', name: 'test.docx', blocks: [{ kind: 'paragraph', text: 'Hello' }], tables: [] }),
    );
    apiSpy.documentContent.and.returnValue(of(new Blob(['hello text'], { type: 'text/plain' })));

    await TestBed.configureTestingModule({
      imports: [DocumentViewerComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ApiService, useValue: apiSpy },
      ],
    }).compileComponents();

    const config = TestBed.inject(ConfigService);
    config.install(
      {
        app: appConfig,
        layout: layoutConfig,
        navigation: navigationConfig,
        agent: agentConfig,
        strings: stringsConfig,
        theme: themeConfig,
        pages: pagesConfig,
      },
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 23 23"><rect class="sq-red" x="0" y="0" width="10.5" height="10.5"/><rect class="sq-green" x="11.5" y="0" width="10.5" height="10.5"/><rect class="sq-blue" x="0" y="11.5" width="10.5" height="10.5"/><rect class="sq-yellow" x="11.5" y="11.5" width="10.5" height="10.5"/></svg>',
    );

    apiService = TestBed.inject(ApiService) as jasmine.SpyObj<ApiService>;
    fixture = TestBed.createComponent(DocumentViewerComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create and handle office document preview', () => {
    expect(component).toBeTruthy();
    fixture.componentRef.setInput('document', { id: 'test.1', name: 'test.docx' });
    fixture.detectChanges();
    expect(apiService.documentPreview).toHaveBeenCalledWith('test.1');
    expect(component.state().status).toBe('ready');
    expect(component.state().preview?.kind).toBe('docx');
  });

  it('should handle text and vtt files via content endpoint', async () => {
    fixture.componentRef.setInput('document', { id: 'test.2', name: 'meeting.txt' });
    fixture.detectChanges();
    expect(apiService.documentContent).toHaveBeenCalledWith('test.2');
  });

  it('should mark unsupported file extensions gracefully', () => {
    fixture.componentRef.setInput('document', { id: 'test.3', name: 'unknown.xyz' });
    fixture.detectChanges();
    expect(component.state().status).toBe('unsupported');
  });

  it('should support multi-page navigation across 12 pages', () => {
    const pages = Array.from({ length: 12 }, (_, idx) => ({
      number: idx + 1,
      title: `Section ${idx + 1}`,
      blocks: [{ kind: 'paragraph' as const, text: `Content for page ${idx + 1}` }],
    }));
    apiService.documentPreview.and.returnValue(
      of({ kind: 'docx', name: 'handbook.docx', pageCount: 12, pages, blocks: [], tables: [] }),
    );
    fixture.componentRef.setInput('document', { id: 'test.12', name: 'handbook.docx' });
    fixture.detectChanges();
    expect(component.totalPages()).toBe(12);
    expect(component.visiblePages().length).toBe(12);
    component.selectPage(5);
    expect(component.visiblePages().length).toBe(1);
    expect(component.visiblePages()[0].number).toBe(5);
    component.nextPage();
    expect(component.selectedPage()).toBe(6);
    component.prevPage();
    expect(component.selectedPage()).toBe(5);
    component.selectPage(null);
    expect(component.visiblePages().length).toBe(12);
  });
});
