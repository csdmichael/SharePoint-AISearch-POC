import {
  AgentConfig,
  AppConfig,
  ConfigBundle,
  ENDPOINT_KEYS,
  LAYOUT_ICON_KEYS,
  LayoutConfig,
  NavigationConfig,
  PagesConfig,
  RawConfigFiles,
  SPACING_KEYS,
  StringTable,
  ThemeConfig,
} from './config.models';

/** Strings the UI cannot render without. Validated at startup so a missing key fails fast. */
export const REQUIRED_STRING_KEYS = [
  'lang',
  'appName',
  'header.logoAltText',
  'header.microsoftWordmark',
  'header.menuButtonLabel',
  'header.sidebarLabel',
  'header.tabBarLabel',
  'header.overlayTitle',
  'header.signedInAs',
  'modeBadges.live',
  'modeBadges.dryRun',
  'modeBadges.offline',
  'modeBadges.checking',
  'buttons.retry',
  'buttons.signIn',
  'buttons.signOut',
  'states.loading',
  'states.checking',
  'states.empty',
  'states.notAvailable',
  'states.notFound.title',
  'states.notFound.body',
  'states.apiUnreachable.title',
  'states.apiUnreachable.body',
  'states.requestFailed.title',
  'states.requestFailed.body',
  'states.signInRequired.title',
  'states.signInRequired.body',
  'states.authNotConfigured.title',
  'states.authNotConfigured.body',
  'states.authError.title',
  'states.authError.body',
  'pages.notFound',
  'a11y.mainRegion',
];

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;
const FAB_POSITIONS = ['top-start', 'top-end', 'bottom-start', 'bottom-end'];
const SEVERITIES = ['low', 'medium', 'high', 'critical'];
const SQUARE_COUNT = 4;

type Obj = Record<string, unknown>;

export class ConfigValidationError extends Error {
  constructor(readonly issues: string[]) {
    super(`Configuration is incomplete or invalid. ${issues.join(' | ')}`);
    this.name = 'ConfigValidationError';
  }
}

/** Collects every problem so one startup failure lists all missing keys at once. */
class Collector {
  readonly issues: string[] = [];

  constructor(private readonly file: string) {}

  fail(path: string, reason: string): void {
    this.issues.push(`${this.file}: ${path} ${reason}`);
  }
}

function objectAt(c: Collector, value: unknown, path: string): Obj {
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    return value as Obj;
  }
  c.fail(path, '(missing or not an object)');
  return {};
}

function stringAt(c: Collector, source: Obj, key: string, path: string, allowEmpty = false): string {
  const value = source[key];
  if (typeof value === 'string' && (allowEmpty || value.trim().length > 0)) {
    return value;
  }
  c.fail(`${path}.${key}`, '(missing or empty string)');
  return '';
}

function numberAt(
  c: Collector,
  source: Obj,
  key: string,
  path: string,
  options: { min: number; integer?: boolean; max?: number },
): number {
  const value = source[key];
  const integerOk = options.integer === false || Number.isInteger(value);
  const max = options.max ?? Number.POSITIVE_INFINITY;
  if (typeof value === 'number' && Number.isFinite(value) && integerOk && value >= options.min && value <= max) {
    return value;
  }
  c.fail(`${path}.${key}`, `(missing or outside ${options.min}..${max === Number.POSITIVE_INFINITY ? 'infinity' : max})`);
  return options.min;
}

function booleanAt(c: Collector, source: Obj, key: string, path: string): boolean {
  const value = source[key];
  if (typeof value === 'boolean') {
    return value;
  }
  c.fail(`${path}.${key}`, '(missing or not a boolean)');
  return false;
}

function stringArrayAt(c: Collector, source: Obj, key: string, path: string, minLength = 0): string[] {
  const value = source[key];
  if (Array.isArray(value) && value.length >= minLength && value.every((item) => typeof item === 'string')) {
    return value as string[];
  }
  c.fail(`${path}.${key}`, `(missing or not an array of strings with at least ${minLength} item(s))`);
  return [];
}

function stringMapAt(c: Collector, source: Obj, key: string, path: string, requiredKeys: readonly string[]): Record<string, string> {
  const map = objectAt(c, source[key], `${path}.${key}`);
  const result: Record<string, string> = {};
  for (const name of requiredKeys) {
    const value = map[name];
    if (typeof value === 'string' && value.length > 0) {
      result[name] = value;
    } else {
      c.fail(`${path}.${key}.${name}`, '(missing or empty)');
    }
  }
  for (const [name, value] of Object.entries(map)) {
    if (typeof value === 'string') {
      result[name] = value;
    }
  }
  return result;
}

function hasStringKey(strings: StringTable, dottedKey: string): boolean {
  let node: string | StringTable | undefined = strings;
  for (const part of dottedKey.split('.')) {
    if (typeof node !== 'object' || node === null) {
      return false;
    }
    node = (node as StringTable)[part];
  }
  return typeof node === 'string';
}

function validateApp(c: Collector, raw: Obj): AppConfig {
  const apiBaseUrl = stringAt(c, raw, 'apiBaseUrl', 'app.config.json');
  try {
    const url = new URL(apiBaseUrl);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      c.fail('apiBaseUrl', '(must use http or https)');
    }
  } catch {
    c.fail('apiBaseUrl', '(not an absolute URL)');
  }
  const requestTimeoutMs = numberAt(c, raw, 'requestTimeoutMs', 'app.config.json', { min: 1000 });
  const pageSize = numberAt(c, raw, 'pageSize', 'app.config.json', { min: 1, max: 200 });

  const endpoints = objectAt(c, raw['endpoints'], 'app.config.json.endpoints');
  const endpointMap = {} as Record<string, string>;
  for (const key of ENDPOINT_KEYS) {
    const value = endpoints[key];
    if (typeof value === 'string' && value.startsWith('/')) {
      endpointMap[key] = value;
    } else {
      c.fail(`app.config.json.endpoints.${key}`, '(missing or not a path starting with /)');
    }
  }

  const auth = objectAt(c, raw['auth'], 'app.config.json.auth');
  const clientId = stringAt(c, auth, 'clientId', 'app.config.json.auth', true);
  const authority = stringAt(c, auth, 'authority', 'app.config.json.auth', true);
  const redirectUri = stringAt(c, auth, 'redirectUri', 'app.config.json.auth', true);
  const postLogoutRedirectUri = stringAt(c, auth, 'postLogoutRedirectUri', 'app.config.json.auth', true);
  const cacheLocation = stringAt(c, auth, 'cacheLocation', 'app.config.json.auth');
  if (cacheLocation !== 'localStorage' && cacheLocation !== 'sessionStorage') {
    c.fail('app.config.json.auth.cacheLocation', '(must be localStorage or sessionStorage)');
  }
  const apiScopes = stringArrayAt(c, auth, 'apiScopes', 'app.config.json.auth');
  if (clientId.length > 0) {
    if (apiScopes.length === 0) {
      c.fail('app.config.json.auth.apiScopes', '(required when auth.clientId is set)');
    }
    if (authority.length === 0 || redirectUri.length === 0 || postLogoutRedirectUri.length === 0) {
      c.fail('app.config.json.auth', '(authority, redirectUri and postLogoutRedirectUri are required when clientId is set)');
    }
  }

  const exportConfig = objectAt(c, raw['export'], 'app.config.json.export');
  const csvDelimiter = stringAt(c, exportConfig, 'csvDelimiter', 'app.config.json.export');
  if (csvDelimiter.length !== 1) {
    c.fail('app.config.json.export.csvDelimiter', '(must be a single character)');
  }

  return {
    apiBaseUrl,
    requestTimeoutMs,
    pageSize,
    endpoints: endpointMap as AppConfig['endpoints'],
    auth: {
      clientId,
      authority,
      redirectUri,
      postLogoutRedirectUri,
      cacheLocation: cacheLocation as AppConfig['auth']['cacheLocation'],
      apiScopes,
    },
    export: {
      csvFileName: stringAt(c, exportConfig, 'csvFileName', 'app.config.json.export'),
      csvDelimiter,
      csvIncludeBom: booleanAt(c, exportConfig, 'csvIncludeBom', 'app.config.json.export'),
    },
  };
}

function validateLayout(c: Collector, raw: Obj): LayoutConfig {
  const breakpoints = objectAt(c, raw['breakpoints'], 'layout.json.breakpoints');
  const tabletMinPx = numberAt(c, breakpoints, 'tabletMinPx', 'layout.json.breakpoints', { min: 1 });
  const desktopMinPx = numberAt(c, breakpoints, 'desktopMinPx', 'layout.json.breakpoints', { min: 1 });
  if (desktopMinPx <= tabletMinPx) {
    c.fail('layout.json.breakpoints', '(desktopMinPx must be greater than tabletMinPx)');
  }

  const paneWidths = objectAt(c, raw['paneWidths'], 'layout.json.paneWidths');
  const listPercent = numberAt(c, paneWidths, 'listPercent', 'layout.json.paneWidths', { min: 1, integer: false, max: 99 });
  const detailPercent = numberAt(c, paneWidths, 'detailPercent', 'layout.json.paneWidths', { min: 1, integer: false, max: 99 });
  if (listPercent + detailPercent >= 100) {
    c.fail('layout.json.paneWidths', '(listPercent plus detailPercent must be below 100)');
  }

  const cardColumns = objectAt(c, raw['cardColumns'], 'layout.json.cardColumns');
  const spacing = objectAt(c, raw['spacingPx'], 'layout.json.spacingPx');
  const spacingPx = {} as LayoutConfig['spacingPx'];
  for (const key of SPACING_KEYS) {
    spacingPx[key] = numberAt(c, spacing, key, 'layout.json.spacingPx', { min: 0 });
  }

  const icons = objectAt(c, raw['icons'], 'layout.json.icons');
  const iconMap = {} as LayoutConfig['icons'];
  for (const key of LAYOUT_ICON_KEYS) {
    iconMap[key] = stringAt(c, icons, key, 'layout.json.icons');
  }

  return {
    breakpoints: { tabletMinPx, desktopMinPx },
    sidebarWidthPx: numberAt(c, raw, 'sidebarWidthPx', 'layout.json', { min: 1 }),
    headerHeightPx: numberAt(c, raw, 'headerHeightPx', 'layout.json', { min: 1 }),
    tabBarHeightPx: numberAt(c, raw, 'tabBarHeightPx', 'layout.json', { min: 1 }),
    maxContentWidthPx: numberAt(c, raw, 'maxContentWidthPx', 'layout.json', { min: 1 }),
    paneWidths: { listPercent, detailPercent },
    cardColumns: {
      mobile: numberAt(c, cardColumns, 'mobile', 'layout.json.cardColumns', { min: 1, max: 12 }),
      tablet: numberAt(c, cardColumns, 'tablet', 'layout.json.cardColumns', { min: 1, max: 12 }),
      desktop: numberAt(c, cardColumns, 'desktop', 'layout.json.cardColumns', { min: 1, max: 12 }),
    },
    mobileTabIds: stringArrayAt(c, raw, 'mobileTabIds', 'layout.json', 1),
    overlayMenuId: stringAt(c, raw, 'overlayMenuId', 'layout.json'),
    mainContentId: stringAt(c, raw, 'mainContentId', 'layout.json'),
    spacingPx,
    radiusPx: numberAt(c, raw, 'radiusPx', 'layout.json', { min: 0 }),
    fabOffsetPx: numberAt(c, raw, 'fabOffsetPx', 'layout.json', { min: 0 }),
    icons: iconMap,
  };
}

function validateNavigation(c: Collector, raw: Obj, strings: StringTable): NavigationConfig {
  const groups = Array.isArray(raw['groups']) ? (raw['groups'] as unknown[]) : [];
  const items = Array.isArray(raw['items']) ? (raw['items'] as unknown[]) : [];
  if (groups.length === 0) {
    c.fail('navigation.json.groups', '(missing or empty)');
  }
  if (items.length === 0) {
    c.fail('navigation.json.items', '(missing or empty)');
  }

  const groupIds = new Set<string>();
  const groupList = groups.map((value, index) => {
    const group = objectAt(c, value, `navigation.json.groups[${index}]`);
    const id = stringAt(c, group, 'id', `navigation.json.groups[${index}]`);
    const labelKey = stringAt(c, group, 'labelKey', `navigation.json.groups[${index}]`);
    if (labelKey && !hasStringKey(strings, labelKey)) {
      c.fail(`navigation.json.groups[${index}].labelKey`, `(string key "${labelKey}" not found in strings.json)`);
    }
    groupIds.add(id);
    return { id, labelKey };
  });

  const itemIds = new Set<string>();
  const routes = new Set<string>();
  const itemList = items.map((value, index) => {
    const path = `navigation.json.items[${index}]`;
    const item = objectAt(c, value, path);
    const id = stringAt(c, item, 'id', path);
    const route = stringAt(c, item, 'route', path);
    const labelKey = stringAt(c, item, 'labelKey', path);
    const group = stringAt(c, item, 'group', path);
    const icon = stringAt(c, item, 'icon', path);
    if (id && itemIds.has(id)) {
      c.fail(`${path}.id`, `(duplicate id "${id}")`);
    }
    if (route && (!route.startsWith('/') || routes.has(route))) {
      c.fail(`${path}.route`, '(must start with / and be unique)');
    }
    if (group && !groupIds.has(group)) {
      c.fail(`${path}.group`, `(unknown group "${group}")`);
    }
    if (labelKey && !hasStringKey(strings, labelKey)) {
      c.fail(`${path}.labelKey`, `(string key "${labelKey}" not found in strings.json)`);
    }
    itemIds.add(id);
    routes.add(route);
    return { id, route, labelKey, icon, group };
  });

  return { groups: groupList, items: itemList };
}

function validateAgent(c: Collector, raw: Obj, strings: StringTable): AgentConfig {
  const fab = objectAt(c, raw['fab'], 'agent.json.fab');
  const position = stringAt(c, fab, 'position', 'agent.json.fab');
  if (position && !FAB_POSITIONS.includes(position)) {
    c.fail('agent.json.fab.position', `(must be one of ${FAB_POSITIONS.join(', ')})`);
  }
  const labelKey = stringAt(c, fab, 'labelKey', 'agent.json.fab');
  if (labelKey && !hasStringKey(strings, labelKey)) {
    c.fail('agent.json.fab.labelKey', `(string key "${labelKey}" not found in strings.json)`);
  }
  const placeholderPattern = stringAt(c, raw, 'placeholderPattern', 'agent.json');
  try {
    new RegExp(placeholderPattern, 'g');
  } catch {
    c.fail('agent.json.placeholderPattern', '(not a valid regular expression)');
  }
  const hideOnRoutes = stringArrayAt(c, fab, 'hideOnRoutes', 'agent.json.fab');
  return {
    fab: {
      enabled: booleanAt(c, fab, 'enabled', 'agent.json.fab'),
      icon: stringAt(c, fab, 'icon', 'agent.json.fab'),
      labelKey,
      route: stringAt(c, fab, 'route', 'agent.json.fab'),
      position,
      hideOnRoutes,
    },
    promptsPath: stringAt(c, raw, 'promptsPath', 'agent.json'),
    messagesPath: stringAt(c, raw, 'messagesPath', 'agent.json'),
    maxInputChars: numberAt(c, raw, 'maxInputChars', 'agent.json', { min: 1, max: 100000 }),
    placeholderPattern,
  };
}

function validateTheme(c: Collector, raw: Obj): ThemeConfig {
  const brandColors = stringMapAt(c, raw, 'brandColors', 'theme.json', ['red', 'green', 'blue', 'yellow']);
  const squareOrder = stringArrayAt(c, raw, 'logoSquareOrder', 'theme.json', SQUARE_COUNT);
  for (const name of squareOrder) {
    if (!(name in brandColors)) {
      c.fail('theme.json.logoSquareOrder', `(unknown brand color "${name}")`);
    }
  }
  const surfaces = stringMapAt(c, raw, 'surfaces', 'theme.json', ['page', 'card', 'text', 'mutedText', 'border', 'accent', 'accentText']);
  const contrast = objectAt(c, raw['contrast'], 'theme.json.contrast');
  const contrastLight = stringAt(c, contrast, 'light', 'theme.json.contrast');
  const contrastDark = stringAt(c, contrast, 'dark', 'theme.json.contrast');
  const ionicColors = stringMapAt(c, raw, 'ionicColors', 'theme.json', ['primary', 'danger', 'success', 'warning', 'medium', 'light', 'dark']);
  const severityColors = stringMapAt(c, raw, 'severityColors', 'theme.json', SEVERITIES);
  const statusColors = stringMapAt(c, raw, 'statusColors', 'theme.json', ['default']);
  const trustEntries = Array.isArray(raw['trustScoreColors']) ? (raw['trustScoreColors'] as unknown[]) : [];
  if (trustEntries.length === 0) {
    c.fail('theme.json.trustScoreColors', '(missing or empty)');
  }
  const trustScoreColors = trustEntries.map((entry, index) => {
    const band = objectAt(c, entry, `theme.json.trustScoreColors[${index}]`);
    return {
      minScore: numberAt(c, band, 'minScore', `theme.json.trustScoreColors[${index}]`, { min: 0, max: 100 }),
      color: stringAt(c, band, 'color', `theme.json.trustScoreColors[${index}]`),
    };
  });

  const colorGroups: Record<string, string>[] = [brandColors, surfaces, ionicColors, severityColors, statusColors];
  colorGroups.push({ light: contrastLight, dark: contrastDark });
  for (const group of colorGroups) {
    for (const [name, value] of Object.entries(group)) {
      if (!HEX_COLOR.test(value)) {
        c.fail(`theme.json color "${name}"`, `(not a #RRGGBB value: ${value})`);
      }
    }
  }
  for (const band of trustScoreColors) {
    if (!HEX_COLOR.test(band.color)) {
      c.fail('theme.json.trustScoreColors', `(not a #RRGGBB value: ${band.color})`);
    }
  }

  return {
    brandColors,
    logoPath: stringAt(c, raw, 'logoPath', 'theme.json'),
    logoSquareOrder: squareOrder,
    foundryIconPath: stringAt(c, raw, 'foundryIconPath', 'theme.json'),
    surfaces,
    contrast: { light: contrastLight, dark: contrastDark },
    ionicColors,
    trustScoreColors,
    severityColors,
    statusColors,
  };
}

function validatePages(c: Collector, raw: Obj, strings: StringTable): PagesConfig {
  const homeRoute = stringAt(c, raw, 'homeRoute', 'pages.json');
  const documentRoute = stringAt(c, raw, 'documentRoute', 'pages.json');
  if (documentRoute && !documentRoute.includes(':id')) {
    c.fail('pages.json.documentRoute', '(must contain the :id parameter)');
  }
  const access = objectAt(c, raw['access'], 'pages.json.access');
  const cleanup = objectAt(c, raw['cleanup'], 'pages.json.cleanup');
  const notifications = objectAt(c, raw['notifications'], 'pages.json.notifications');

  const segments = stringArrayAt(c, cleanup, 'segments', 'pages.json.cleanup', 1);
  const defaultSegment = stringAt(c, cleanup, 'defaultSegment', 'pages.json.cleanup');
  if (defaultSegment && !segments.includes(defaultSegment)) {
    c.fail('pages.json.cleanup.defaultSegment', '(must be one of the segments)');
  }
  for (const segment of segments) {
    if (!hasStringKey(strings, `cleanup.segments.${segment}`)) {
      c.fail('pages.json.cleanup.segments', `(string key cleanup.segments.${segment} not found in strings.json)`);
    }
  }

  const draftTemplates = objectAt(c, cleanup['draftTemplates'], 'pages.json.cleanup.draftTemplates');
  const draftTemplateIds = {
    exact: stringAt(c, draftTemplates, 'exact', 'pages.json.cleanup.draftTemplates'),
    near: stringAt(c, draftTemplates, 'near', 'pages.json.cleanup.draftTemplates'),
    expired: stringAt(c, draftTemplates, 'expired', 'pages.json.cleanup.draftTemplates'),
    reviewOverdue: stringAt(c, draftTemplates, 'reviewOverdue', 'pages.json.cleanup.draftTemplates'),
  };

  const statuses = stringArrayAt(c, notifications, 'statuses', 'pages.json.notifications', 1);
  const defaultStatus = stringAt(c, notifications, 'defaultStatus', 'pages.json.notifications');
  if (defaultStatus && !statuses.includes(defaultStatus)) {
    c.fail('pages.json.notifications.defaultStatus', '(must be one of the statuses)');
  }
  for (const status of statuses) {
    if (!hasStringKey(strings, `notifications.statuses.${status}`)) {
      c.fail('pages.json.notifications.statuses', `(string key notifications.statuses.${status} not found in strings.json)`);
    }
  }

  return {
    homeRoute,
    documentRoute,
    access: {
      minQueryLength: numberAt(c, access, 'minQueryLength', 'pages.json.access', { min: 1, max: 20 }),
      searchDebounceMs: numberAt(c, access, 'searchDebounceMs', 'pages.json.access', { min: 0 }),
      grantPathSeparator: stringAt(c, access, 'grantPathSeparator', 'pages.json.access', true),
    },
    cleanup: { defaultSegment, segments, draftTemplates: draftTemplateIds },
    notifications: { defaultStatus, statuses },
  };
}

function validateStrings(c: Collector, raw: Obj): ConfigBundle['strings'] {
  const table = raw as StringTable;
  for (const key of REQUIRED_STRING_KEYS) {
    if (!hasStringKey(table, key)) {
      c.fail(`strings.json.${key}`, '(missing)');
    }
  }
  return table as ConfigBundle['strings'];
}

function validateLogo(c: Collector, svg: string, path: string): void {
  const squares = svg.match(/<rect\b/g)?.length ?? 0;
  if (!svg.includes('<svg') || squares !== SQUARE_COUNT) {
    c.fail(path, `(expected an SVG with ${SQUARE_COUNT} rect squares, found ${squares})`);
  }
}

/**
 * Validates every startup configuration file together and returns a typed bundle.
 * Throws ConfigValidationError listing every missing or invalid key so misconfiguration fails fast.
 */
export function validateConfigBundle(raw: RawConfigFiles, logoSvg: string, logoPath: string): ConfigBundle {
  const issues: string[] = [];
  const collect = <T>(file: string, build: (c: Collector) => T): T | null => {
    const collector = new Collector(file);
    const result = build(collector);
    issues.push(...collector.issues);
    return collector.issues.length === 0 ? result : null;
  };

  const stringsCollector = new Collector('strings.json');
  const stringsObj = objectAt(stringsCollector, raw.strings, 'strings.json');
  issues.push(...stringsCollector.issues);
  const strings = collect('strings.json', (c) => validateStrings(c, stringsObj));

  const app = collect('app.config.json', (c) => validateApp(c, objectAt(c, raw.app, 'app.config.json')));
  const layout = collect('layout.json', (c) => validateLayout(c, objectAt(c, raw.layout, 'layout.json')));
  const theme = collect('theme.json', (c) => validateTheme(c, objectAt(c, raw.theme, 'theme.json')));
  const pages = collect('pages.json', (c) => validatePages(c, objectAt(c, raw.pages, 'pages.json'), stringsObj as StringTable));
  const navigation = collect('navigation.json', (c) =>
    validateNavigation(c, objectAt(c, raw.navigation, 'navigation.json'), stringsObj as StringTable),
  );
  const agent = collect('agent.json', (c) => validateAgent(c, objectAt(c, raw.agent, 'agent.json'), stringsObj as StringTable));
  collect('theme.json logo asset', (c) => validateLogo(c, logoSvg, logoPath));

  if (layout) {
    const tabIds = navigation?.items.map((item) => item.id) ?? [];
    for (const id of layout.mobileTabIds) {
      if (!tabIds.includes(id)) {
        issues.push(`layout.json: mobileTabIds contains "${id}", which is not a navigation item`);
      }
    }
  }
  if (navigation && pages) {
    const routes = navigation.items.map((item) => item.route);
    if (!routes.includes(pages.homeRoute)) {
      issues.push(`pages.json: homeRoute "${pages.homeRoute}" is not a navigation route`);
    }
  }

  if (issues.length > 0 || !app || !layout || !navigation || !agent || !theme || !pages || !strings) {
    throw new ConfigValidationError(issues.length > 0 ? issues : ['configuration could not be built']);
  }

  return {
    app,
    layout,
    navigation,
    agent,
    strings,
    theme,
    pages,
    logoSvg,
  };
}
