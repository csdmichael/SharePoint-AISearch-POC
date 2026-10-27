/**
 * Response models for the governance API under apiBaseUrl (app\api). Field names are the JSON the routes return,
 * so the API services are the source of truth. ApiService reshapes only paged and cleanup responses (see
 * api.mappers.ts); pages read the rest as returned.
 */

/** Notification and agent response mode as the API reports it. "dryRun" records outcomes without delivering mail. */
export type ResponseMode = string;

/** Cursor-paged list for CursorList. nextCursor is null on the last page. */
export interface Page<T> {
  items: T[];
  nextCursor: string | null;
}

export interface HealthResponse {
  status: string;
  service?: string;
  version?: string;
  mode?: ResponseMode | null;
}

export interface PolicyMetricDefinition {
  key: string;
  label: string;
}

export interface PolicyResponse {
  hygiene: { metrics: PolicyMetricDefinition[] };
}

/** One hygiene metric with its current value. The value is null when it cannot be computed. */
export interface HygieneMetric {
  key: string;
  label: string;
  value: number | null;
}

export interface HygieneFinding {
  id: string;
  title: string;
  severity: string;
  count: number;
  byLibrary: Record<string, number>;
}

export interface HygieneSummary {
  asOfDate: string | null;
  metrics: HygieneMetric[];
  findings: HygieneFinding[];
}

export interface DocumentRef {
  id: string;
  name: string;
  path: string | null;
  webUrl: string | null;
}

export interface HygieneFindingDetail extends HygieneFinding {
  asOfDate: string | null;
  documents: DocumentRef[];
}

export interface Library {
  id: string;
  libraryId: string;
  title: string;
  rootPath: string | null;
  webUrl: string | null;
  hasUniquePermissions: boolean;
}

export interface LibraryList {
  items: Library[];
  total: number;
}

export type DriveItemKind = 'folder' | 'file';

/** A folder or file in a library listing (children route). */
export interface DriveItem {
  id: string;
  libraryId: string;
  name: string;
  kind: DriveItemKind;
  path: string | null;
  webUrl: string | null;
  hasUniquePermissions: boolean;
  childCount: number | null;
  size: number | null;
  modified: string | null;
  created: string | null;
}

export interface ChildrenResponse {
  library: { id: string; title: string; rootPath: string | null };
  folder: DriveItem | null;
  items: DriveItem[];
  total: number;
  truncated: boolean;
}

/** An item as the permission, access and analytics routes name it (item view in app\api). */
export interface ItemView {
  id: string;
  libraryId: string | null;
  libraryTitle: string | null;
  name: string;
  kind: string;
  path: string | null;
  webUrl: string | null;
  hasUniquePermissions: boolean;
  modified: string | null;
}

export interface PrincipalView {
  type: string;
  id: string | null;
  displayName: string;
  loginName: string | null;
  email: string | null;
}

export interface MemberView {
  id: string | null;
  displayName: string;
  userPrincipalName: string | null;
  accountEnabled: boolean | null;
  status: string | null;
}

/** The item whose role assignments apply: the item itself, an ancestor folder, the library or the site. */
export interface SourceRef {
  itemId: string;
  path: string;
  kind: string;
}

export interface PermissionEntry {
  principal: PrincipalView;
  role: string;
  roles: string[];
  grantedVia: string;
  inheritedFrom: SourceRef | null;
  linkScope: string | null;
  linkType: string | null;
  expandedMembers: MemberView[];
  accountEnabled: boolean | null;
  accountStatus: string | null;
}

export interface PermissionWarning {
  code: string;
  message: string;
}

export interface PermissionsResponse {
  item: ItemView;
  inheritance: { hasUniquePermissions: boolean; source: SourceRef | null };
  entries: PermissionEntry[];
  warnings: PermissionWarning[];
}

export interface UserSearchResult {
  userKey: string;
  displayName: string;
  userPrincipalName: string | null;
  email: string | null;
  loginName: string;
  external: boolean;
}

export interface UserSearchResponse {
  query: string;
  users: UserSearchResult[];
  scanned: number;
  scanLimited: boolean;
}

/** One item a user can reach, with the role and how the access was granted. */
export interface UserAccessRecord {
  item: ItemView;
  role: string;
  grantedVia: string;
  via: string[];
  inheritedFrom: SourceRef | null;
  linkScope: string | null;
}

export interface UserItemsResponse {
  user: { userKey: string; external: boolean };
  items: UserAccessRecord[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}

/** Coverage of one library in an analytics response. */
export interface LibraryCoverage {
  libraryId: string;
  libraryTitle: string;
  documentsScanned: number;
  truncated: boolean;
  warnings: string[];
}

export type DuplicateRole = 'canonical' | 'duplicate';

/** Date facts from the expiry rules (expiry analytics and document detail). */
export interface ExpiryView {
  expired: boolean;
  expiredBy: string[];
  expirationDate: string | null;
  daysPastExpiration: number | null;
  reviewDate: string | null;
  reviewOverdue: boolean;
  overdueBy: string[];
  daysOverdue: number | null;
  textDates: { kind: string; date: string; snippet: string }[];
}

/** A governance document as the list and analytics routes return it. */
export interface DocumentSummary extends ItemView {
  title: string;
  size: number | null;
  artifactId: string | null;
  knowledgeCategory: string | null;
  lifecycleStatus: string | null;
  authoritative: boolean | null;
  aiReady: boolean | null;
  reviewDate: string | null;
  expirationDate: string | null;
  effectiveDate: string | null;
  documentType: string | null;
  productFamily: string | null;
  processArea: string | null;
  sensitivity: string | null;
  dataQualityStatus: string | null;
  conflictStatus: string | null;
  trustScore: number | null;
  knowledgeOwner: string | null;
  ownerDisplayName: string | null;
  duplicateOf: string | null;
}

export interface DuplicateMember extends DocumentSummary {
  role: DuplicateRole;
}

export interface DuplicateCluster {
  clusterId: string;
  libraryId: string;
  kind: 'exact' | 'near';
  reason: string;
  canonical: string;
  size: number;
  members: DuplicateMember[];
}

export interface DuplicatesResponse {
  exact: DuplicateCluster[];
  near: DuplicateCluster[];
  asOfDate: string;
  libraries: LibraryCoverage[];
}

export interface ExpiryDocument extends DocumentSummary {
  expiry: ExpiryView;
}

export interface ExpiryResponse {
  asOfDate: string;
  reviewOverdueGraceDays: number;
  expired: ExpiryDocument[];
  reviewOverdue: ExpiryDocument[];
  libraries: LibraryCoverage[];
}

export interface AnomalyRow {
  item: ItemView;
  title: string;
  rank: number;
  score: number;
  isAnomaly: boolean;
  topContributions: { feature: string; share: number }[];
}

export interface AnomaliesResponse {
  asOfDate: string;
  items: AnomalyRow[];
  libraries: LibraryCoverage[];
}

export interface ExposureFinding {
  id: string;
  type: string;
  severity: string;
  subject: ItemView;
  principal: PrincipalView;
  role: string;
  grantedVia: string;
  member: MemberView | null;
  detail: string;
}

export interface ExposureResponse {
  asOfDate: string;
  total: number;
  bySeverity: Record<string, number>;
  findings: ExposureFinding[];
  libraries: LibraryCoverage[];
}

/** A member of a duplicate cluster. The canonical copy is kept, so only duplicates are notification candidates. */
export interface ClusterMember extends DocumentRef {
  role: DuplicateRole;
}

/** One duplicate cluster (exact or near) as the cleanup table shows it. */
export interface DuplicateClusterRecord {
  segment: 'duplicates';
  id: string;
  kind: 'exact' | 'near';
  canonical: DocumentRef;
  members: ClusterMember[];
}

export interface ExpiryRecord {
  segment: 'expiry';
  id: string;
  document: DocumentRef;
  reason: 'expired' | 'reviewOverdue';
  date: string | null;
  days: number | null;
}

export interface FeatureContribution {
  feature: string;
  contribution: number;
}

export interface AnomalyRecord {
  segment: 'anomalies';
  id: string;
  document: DocumentRef;
  score: number;
  contributions: FeatureContribution[];
}

export interface ExposureRecord {
  segment: 'exposure';
  id: string;
  document: DocumentRef;
  exposure: string;
  severity: string;
  detail: string;
}

export type CleanupRecord = DuplicateClusterRecord | ExpiryRecord | AnomalyRecord | ExposureRecord;

/** Notification templates used when cleanup records are drafted (pages.json cleanup.draftTemplates). */
export interface CleanupDraftTemplates {
  exact: string;
  near: string;
  expired: string;
  reviewOverdue: string;
}

/** An owner notification as the outbox stores it (app\api services\notifications.py). */
export interface NotificationItem {
  id: string;
  status: string;
  mode: ResponseMode;
  templateId: string;
  findingId: string | null;
  documentId: string;
  documentTitle: string;
  documentUrl: string | null;
  libraryTitle: string | null;
  ownerUpn: string | null;
  ownerName: string | null;
  to: string[];
  subject: string;
  body: string;
  reason: string | null;
  createdAt: string | null;
  approvedAt: string | null;
  sentAt: string | null;
  delivery: string | null;
  error: string | null;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  total: number;
  mode: ResponseMode;
}

export interface NotificationPage extends Page<NotificationItem> {
  total: number;
  mode: ResponseMode;
}

export interface DraftRequest {
  templateId: string;
  documentIds: string[];
}

export interface DraftResult {
  templateId: string;
  findingId: string | null;
  mode: ResponseMode;
  created: NotificationItem[];
  skipped: { documentId: string; reason: string }[];
}

export interface AgentPrompt {
  id: string;
  issueId: string;
  issueLabel: string;
  intent?: string | null;
  text: string;
}

export interface AgentPromptsResponse {
  schemaVersion?: string;
  note?: string;
  placeholders?: string[];
  prompts: AgentPrompt[];
}

export interface AgentMessageRequest {
  prompt: string;
}

/** Raw reply from POST /agent/messages. ApiService turns it into AgentReply. */
export interface AgentMessageResponse {
  conversationId: string;
  answer: string;
  mode: ResponseMode;
  intent: string | null;
  evidence: { items?: Record<string, unknown>[]; lines?: string[] } | null;
  citations: AgentCitation[];
  warnings: string[];
}

export type EvidenceValue = string | number | boolean | null;

export interface AgentEvidence {
  columns: string[];
  rows: EvidenceValue[][];
}

export interface AgentCitation {
  title: string;
  url: string;
}

export interface AgentReply {
  answer: string;
  mode: ResponseMode;
  intent: string | null;
  evidence: AgentEvidence | null;
  citations: AgentCitation[];
}

/** Governance detail for one document (GET /documents/{id}): the list fields plus the source and live analytics. */
export interface DocumentDetail extends DocumentSummary {
  businessUnit: string | null;
  sourceSystem: string | null;
  supersedesDocument: string | null;
  trustReasons: string[];
  conflictWith: string[];
  contentHash: string | null;
  lastValidatedDate: string | null;
  liveDuplicateRoles: unknown[];
  liveExpiry: ExpiryView | null;
}

export interface DocumentListResponse {
  items: DocumentSummary[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  sort: string;
  order: string;
  knowledgeCategories: string[];
}

/** One page of the document list as CursorList reads it, with the total and the category choices. */
export interface DocumentPage extends Page<DocumentSummary> {
  total: number;
  knowledgeCategories: string[];
}
