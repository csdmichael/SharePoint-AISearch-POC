import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { Inline, MarkdownBlock, parseMarkdown } from '../../util/markdown';
import { safeHttpUrl } from '../../util/url';

/** Renders agent Markdown (headings, tables, lists, bold, links, citations) as Angular nodes. No HTML is injected. */
@Component({
  selector: 'app-markdown',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet],
  templateUrl: './markdown.component.html',
  styleUrl: './markdown.component.scss',
})
export class MarkdownComponent {
  readonly source = input.required<string>();
  readonly blocks = computed<MarkdownBlock[]>(() => parseMarkdown(this.source()));

  href(inline: Inline): string | null {
    return inline.kind === 'link' ? safeHttpUrl(inline.href) : null;
  }
}
