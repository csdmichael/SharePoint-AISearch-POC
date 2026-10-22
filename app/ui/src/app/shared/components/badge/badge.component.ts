import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** Pill label. Text and colour come from the caller (strings.json and theme.json). */
@Component({
  selector: 'app-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="badge" [style.--badge-color]="color()">{{ text() }}</span>`,
  styleUrl: './badge.component.scss',
})
export class BadgeComponent {
  readonly text = input.required<string>();
  readonly color = input.required<string>();
}
