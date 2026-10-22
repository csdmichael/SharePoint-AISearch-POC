/**
 * Models for the governance API under apiBaseUrl (app\api). They are written from the endpoint list
 * in the UI spec and the repo's governance vocabulary until the API publishes /openapi.json.
 * Assumptions are listed in app\ui\README.md ("API contract assumptions").
 */

export type ResponseMode = 'live' | 'dryRun';

/** Cursor-paged list. nextCursor is null on the last page. */
export interface Page<T> {
  items: T[];
  nextCursor: string | null;
}

export interface HealthResponse {
  status: string;
  mode: ResponseMode | null;
}

export interface PolicyMetricDefinition {
  key: string;
  label: string;
}

export interface PolicyResponse {
  hygiene: { metrics: PolicyMetricDefinition[] };
}

export interface HygieneFinding {
  id: string;
  title: string;
  severity: string;
  count: number | null;
}

export interface HygieneSummary {
  generatedAt: string | null;
  metrics: Record<string, number | null>;
  findings: HygieneFinding[];
}

export interface DocumentRef {
  id: string;
  name: string;
  path: string | null;
  webUrl: string | null;
}

export interface HygieneFindingDetail extends HygieneFinding {
  documents: DocumentRef[];
}

export interface Library {
  id: string;
  name: string;
  webUrl: string | null;
}

export type DriveItemKind = 'folder' | 'file';

export interface DriveItem {
  id: string;
  name: string;
  kind: DriveItemKind;
  path: string | null;
  webUrl: string | null;
  hasChildren: boolean;
  sizeBytes: number | null;
  modifiedAt: string | null;
}

export interface PermissionMember {
  displayName: string;
  principalType: string;
  upn: string | null;
}

export interface InheritedFrom {
  itemId: string;
  name: string;
  webUrl: string | null;
}

export interface PermissionEntry {
  id: string;
  principal: string;
  principalType: string;
  role: string;
  grantedVia: string;
  inheritedFrom: InheritedFrom | null;
  members: PermissionMember[] | null;
}

export interface UserSearchResult {
  key: string;
  displayName: string;
  upn: string;
}

export interface UserAccessItem {
  id: string;
  name: string;
  kind: string;
  path: string | null;
  webUrl: string | null;
  role: string;
  grantPath: string[];
}

export interface DuplicateClusterRecord {
  segment: 'duplicates';
  id: string;
  canonical: DocumentRef;
  members: DocumentRef[];
}

export interface ExpiryRecord {
  segment: 'expiry';
  id: string;
  document: DocumentRef;
  expirationDate: string;
  daysPastExpiry: number;
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
  sensitivity: string | null;
}

export type CleanupRecord = DuplicateClusterRecord | ExpiryRecord | AnomalyRecord | ExposureRecord;

export interface DraftRequest {
  segment: string;
  documentIds: string[];
}

export interface NotificationRecipient {
  displayName: string;
  upn: string;
}

export interface NotificationItem {
  id: string;
  status: string;
  subject: string;
  body: string;
  recipient: NotificationRecipient | null;
  documentIds: string[];
  createdAt: string | null;
  updatedAt: string | null;
}

export interface NotificationPage extends Page<NotificationItem> {
  mode: ResponseMode;
}

export interface NotificationResult {
  mode: ResponseMode;
  notification: NotificationItem;
}

export interface DraftResult {
  mode: ResponseMode;
  items: NotificationItem[];
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
  message: string;
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

export interface DocumentDetail {
  id: string;
  name: string;
  path: string | null;
  webUrl: string | null;
  documentType: string | null;
  productFamily: string | null;
  processArea: string | null;
  sensitivity: string | null;
  businessUnit: string | null;
  knowledgeOwner: string | null;
  ownerDisplayName: string | null;
  lifecycleStatus: string | null;
  dataQualityStatus: string | null;
  conflictStatus: string | null;
  authoritative: boolean | null;
  aiReady: boolean | null;
  effectiveDate: string | null;
  expirationDate: string | null;
  reviewDate: string | null;
  lastValidatedDate: string | null;
  duplicateOf: string | null;
  conflictWith: string[];
  supersedesDocument: string | null;
  trustScore: number | null;
  trustReasons: string[];
}
