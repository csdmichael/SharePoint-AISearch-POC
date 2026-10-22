import { Injectable, Type, computed, inject } from '@angular/core';
import { Routes } from '@angular/router';
import { AgentFabConfig, LayoutName, NavigationConfig, NavigationItem } from '../config/config.models';
import { ConfigService } from '../config/config.service';
import { LayoutService } from '../layout/layout.service';

export interface NavigationSets {
  /** Persistent sidebar (desktop). */
  sidebar: NavigationItem[];
  /** Overlay menu (tablet and mobile). Desktop has no overlay. */
  overlay: NavigationItem[];
  /** Bottom tab bar (mobile), in the order of mobileTabIds. */
  tabBar: NavigationItem[];
}

/** Which navigation items each layout shows. Pure so it can be unit tested without a DOM. */
export function navigationForLayout(navigation: NavigationConfig, mobileTabIds: string[], layout: LayoutName): NavigationSets {
  const items = navigation.items;
  if (layout === 'desktop') {
    return { sidebar: items, overlay: [], tabBar: [] };
  }
  if (layout === 'tablet') {
    return { sidebar: [], overlay: items, tabBar: [] };
  }
  const tabBar = mobileTabIds
    .map((id) => items.find((item) => item.id === id))
    .filter((item): item is NavigationItem => item !== undefined);
  return { sidebar: [], overlay: items, tabBar };
}

/** Path without query string, hash, or a trailing slash (except the root). */
export function normalizePath(url: string): string {
  const path = url.split('?')[0].split('#')[0];
  return path.length > 1 && path.endsWith('/') ? path.slice(0, -1) : path;
}

/** The FAB is shown when enabled and the current path is not listed in hideOnRoutes. */
export function isFabVisible(url: string, fab: AgentFabConfig): boolean {
  return fab.enabled && !fab.hideOnRoutes.map(normalizePath).includes(normalizePath(url));
}

/** Angular route path for a configured absolute route: "/access/by-user" becomes "access/by-user". */
export function toRoutePath(route: string): string {
  return route.replace(/^\/+/, '');
}

/** Page components keyed by navigation id. Every navigation item must have one (checked when routes are built). */
const PAGE_LOADERS: Record<string, () => Promise<Type<unknown>>> = {
  dashboard: () => import('../../features/dashboard/dashboard.page').then((m) => m.DashboardPage),
  explorer: () => import('../../features/explorer/explorer.page').then((m) => m.ExplorerPage),
  access: () => import('../../features/access/access.page').then((m) => m.AccessPage),
  cleanup: () => import('../../features/cleanup/cleanup.page').then((m) => m.CleanupPage),
  notifications: () => import('../../features/notifications/notifications.page').then((m) => m.NotificationsPage),
  agent: () => import('../../features/agent/agent.page').then((m) => m.AgentPage),
  documentDetail: () => import('../../features/documents/document-detail.page').then((m) => m.DocumentDetailPage),
};

/** Builds the route table from navigation.json and pages.json. Throws when a configured page has no component. */
export function buildRoutes(config: ConfigService): Routes {
  const { navigation, pages } = config.current;
  const home = toRoutePath(pages.homeRoute);
  const routes: Routes = navigation.items.map((item) => {
    const loader = PAGE_LOADERS[item.id];
    if (!loader) {
      throw new Error(`navigation.json item "${item.id}" has no page component.`);
    }
    return { path: toRoutePath(item.route), loadComponent: loader };
  });
  routes.push({ path: toRoutePath(pages.documentRoute), loadComponent: PAGE_LOADERS['documentDetail'] });
  routes.push({ path: '', redirectTo: home, pathMatch: 'full' });
  routes.push({ path: '**', redirectTo: home });
  return routes;
}

@Injectable({ providedIn: 'root' })
export class NavigationService {
  private readonly config = inject(ConfigService);
  private readonly layoutService = inject(LayoutService);

  readonly groups = this.config.navigation.groups;
  readonly sets = computed(() => navigationForLayout(this.config.navigation, this.config.layout.mobileTabIds, this.layoutService.layout()));

  groupedItems(items: NavigationItem[]): { groupLabelKey: string; groupId: string; items: NavigationItem[] }[] {
    return this.groups
      .map((group) => ({
        groupId: group.id,
        groupLabelKey: group.labelKey,
        items: items.filter((item) => item.group === group.id),
      }))
      .filter((group) => group.items.length > 0);
  }

  /** Route for a navigation item, from navigation.json. */
  routeFor(id: string): string {
    const item = this.config.navigation.items.find((entry) => entry.id === id);
    if (!item) {
      throw new Error(`No navigation item "${id}" is configured.`);
    }
    return item.route;
  }

  /** Concrete document route from the configured pattern, for example "/documents/abc". */
  documentPath(id: string): string {
    return this.config.pages.documentRoute.replace(':id', encodeURIComponent(id));
  }
}
