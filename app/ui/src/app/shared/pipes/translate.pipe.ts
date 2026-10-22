import { Pipe, PipeTransform, inject } from '@angular/core';
import { I18nService, TextParams } from '../../core/i18n/i18n.service';

/** Looks up user-visible text in strings.json: {{ 'nav.dashboard' | t }} */
@Pipe({ name: 't', pure: true })
export class TranslatePipe implements PipeTransform {
  private readonly i18n = inject(I18nService);

  transform(key: string, params?: TextParams): string {
    return this.i18n.text(key, params);
  }
}
