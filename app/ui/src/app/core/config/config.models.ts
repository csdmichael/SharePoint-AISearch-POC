/** Typed view of the JSON files in src/assets/config. Every value the UI shows or calls comes from these types. */

export const ENDPOINT_KEYS = [
  'health',
  'policy',
  'hygiene',
  'hygieneFinding',
  'libraries',
  'libraryChildren',
  'itemPermissions',
  'accessUsers',
  'accessUserItems',
  'document',
  'cleanup',
  'notifications',
  'notificationDrafts',
  'notificationApprove',
  'notificationSend',
] as const;

export type EndpointKey = (typeof ENDPOINT_KEYS)[number];
export type ApiEndpoints = Record<EndpointKey, string>;

export const LAYOUT_ICON_KEYS = [
  'menu',
  'close',
  'signIn',
  'signOut',
  'retry',
  'export',
  'send',
  'approve',
  'draft',
  'expand',
  'collapse',
  'folder',
  'file',
  'library',
  'members',
  'externalLink',
  'search',
  'user',
  'warning',
  'info',
  'empty',
  'notFound',
  'checking',
  'locked',
  'dryRun',
  'clear',
  'document',
  'trash',
  'select',
] as const;

export type LayoutIconKey = (typeof LAYOUT_ICON_KEYS)[number];
export type LayoutIcons = Record<LayoutIconKey, string>;

export const SPACING_KEYS = ['xxs', 'xs', 'sm', 'md', 'lg', 'xl'] as const;
export type SpacingKey = (typeof SPACING_KEYS)[number];

export type LayoutName = 'mobile' | 'tablet' | 'desktop';

export interface AppConfig {
  apiBaseUrl: string;
  requestTimeoutMs: number;
  pageSize: number;
  endpoints: ApiEndpoints;
  auth: AuthConfig;
  export: ExportConfig;
}

export interface AuthConfig {
  clientId: string;
  authority: string;
  redirectUri: string;
  postLogoutRedirectUri: string;
  cacheLocation: 'localStorage' | 'sessionStorage';
  apiScopes: string[];
}

export interface ExportConfig {
  csvFileName: string;
  csvDelimiter: string;
  csvIncludeBom: boolean;
}

export interface LayoutConfig {
  breakpoints: { tabletMinPx: number; desktopMinPx: number };
  sidebarWidthPx: number;
  headerHeightPx: number;
  tabBarHeightPx: number;
  maxContentWidthPx: number;
  paneWidths: { listPercent: number; detailPercent: number };
  cardColumns: Record<LayoutName, number>;
  mobileTabIds: string[];
  overlayMenuId: string;
  mainContentId: string;
  spacingPx: Record<SpacingKey, number>;
  radiusPx: number;
  fabOffsetPx: number;
  icons: LayoutIcons;
}

export interface NavigationGroup {
  id: string;
  labelKey: string;
}

export interface NavigationItem {
  id: string;
  route: string;
  labelKey: string;
  icon: string;
  group: string;
}

export interface NavigationConfig {
  groups: NavigationGroup[];
  items: NavigationItem[];
}

export interface AgentFabConfig {
  enabled: boolean;
  icon: string;
  labelKey: string;
  route: string;
  position: string;
  hideOnRoutes: string[];
}

export interface AgentConfig {
  fab: AgentFabConfig;
  promptsPath: string;
  messagesPath: string;
  maxInputChars: number;
  placeholderPattern: string;
}

/** Nested string table. Leaves are the visible text; lookups use dotted keys such as "states.apiUnreachable.title". */
export interface StringTable {
  [key: string]: string | StringTable;
}

export interface ThemeConfig {
  brandColors: Record<string, string>;
  logoPath: string;
  logoSquareOrder: string[];
  foundryIconPath: string;
  surfaces: Record<string, string>;
  contrast: { light: string; dark: string };
  ionicColors: Record<string, string>;
  trustScoreColors: { minScore: number; color: string }[];
  severityColors: Record<string, string>;
  statusColors: Record<string, string>;
}

export interface PagesConfig {
  homeRoute: string;
  documentRoute: string;
  access: { minQueryLength: number; searchDebounceMs: number; grantPathSeparator: string };
  cleanup: { defaultSegment: string; segments: string[] };
  notifications: { defaultStatus: string; statuses: string[] };
}

export interface ConfigBundle {
  app: AppConfig;
  layout: LayoutConfig;
  navigation: NavigationConfig;
  agent: AgentConfig;
  strings: StringTable & { lang: string; appName: string };
  theme: ThemeConfig;
  pages: PagesConfig;
  logoSvg: string;
}

/** Raw JSON before validation. Fields are unknown until validateConfigBundle runs. */
export interface RawConfigFiles {
  app: unknown;
  layout: unknown;
  navigation: unknown;
  agent: unknown;
  strings: unknown;
  theme: unknown;
  pages: unknown;
}
