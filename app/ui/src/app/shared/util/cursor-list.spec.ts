import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiError } from '../../core/api/api-error';
import { CursorList } from './cursor-list';

describe('CursorList failure recovery', () => {
  it('exposes an error without throwing from its data signals and reloads successfully', async () => {
    const failure = new ApiError('server', 502);
    const fetch = jasmine.createSpy('fetch').and.returnValue(throwError(() => failure));
    const list = TestBed.runInInjectionContext(() => new CursorList<string>({
      key: () => 'documents',
      fetch,
    }));
    TestBed.tick();
    await TestBed.inject(ApplicationRef).whenStable();
    expect(list.error()).toBe(failure);
    expect(list.loading()).toBeFalse();
    expect(list.items()).toEqual([]);
    expect(list.page()).toBeUndefined();
    expect(list.nextCursor()).toBeNull();

    fetch.and.returnValue(of({ items: ['recovered'], nextCursor: null }));
    list.reload();
    TestBed.tick();
    await TestBed.inject(ApplicationRef).whenStable();
    expect(list.error()).toBeNull();
    expect(list.items()).toEqual(['recovered']);
  });
});
import { ApplicationRef } from '@angular/core';
