import { ChangeDetectionStrategy, Component, ViewEncapsulation, inject } from '@angular/core';
import { ConfigService } from '../../../core/config/config.service';
import { I18nService } from '../../../core/i18n/i18n.service';

/**
 * Four-square Microsoft mark. The SVG geometry comes from theme.logoPath; square colours are
 * applied from brandColors through --brand-* custom properties. Wordmark and alt text come from strings.json.
 * Encapsulation is off because the SVG is injected as HTML and emulated styles would not reach it.
 */
@Component({
  selector: 'app-microsoft-logo',
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <span class="ms-logo" role="img" data-testid="ms-logo" [attr.aria-label]="altText">
      <span class="ms-logo__mark" aria-hidden="true" [innerHTML]="svg"></span>
      <span class="ms-logo__wordmark">{{ wordmark }}</span>
    </span>
  `,
  styleUrl: './microsoft-logo.component.scss',
})
export class MicrosoftLogoComponent {
  private readonly config = inject(ConfigService);
  private readonly i18n = inject(I18nService);

  readonly svg = this.config.logoSvg;
  readonly altText = this.i18n.text('header.logoAltText');
  readonly wordmark = this.i18n.text('header.microsoftWordmark');
}
