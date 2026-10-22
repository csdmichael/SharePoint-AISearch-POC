import { AgentPrompt } from '../../core/api/models/api.models';
import { groupByIssue, placeholdersIn, fillPlaceholders } from './agent.page';

describe('AgentPage functions', () => {
  describe('groupByIssue', () => {
    it('groups prompts by issueId and keeps first-appearance order', () => {
      const samplePrompts: AgentPrompt[] = [
        { id: '1', issueId: 'duplicate-files', issueLabel: 'Duplicate files', intent: 'find', text: 'Text 1' },
        { id: '2', issueId: 'expired-retention', issueLabel: 'Expired retention', intent: 'check', text: 'Text 2' },
        { id: '3', issueId: 'duplicate-files', issueLabel: 'Duplicate files', intent: 'find', text: 'Text 3' },
        { id: '4', issueId: 'excessive-sharing', issueLabel: 'Excessive sharing', intent: 'audit', text: 'Text 4' },
        { id: '5', issueId: 'expired-retention', issueLabel: 'Expired retention', intent: 'check', text: 'Text 5' },
      ];

      const groups = groupByIssue(samplePrompts);

      expect(groups.length).toBe(3);
      // Order of first appearance: duplicate-files, expired-retention, excessive-sharing
      expect(groups[0].issueId).toBe('duplicate-files');
      expect(groups[0].issueLabel).toBe('Duplicate files');
      expect(groups[0].prompts.map((p) => p.id)).toEqual(['1', '3']);

      expect(groups[1].issueId).toBe('expired-retention');
      expect(groups[1].issueLabel).toBe('Expired retention');
      expect(groups[1].prompts.map((p) => p.id)).toEqual(['2', '5']);

      expect(groups[2].issueId).toBe('excessive-sharing');
      expect(groups[2].issueLabel).toBe('Excessive sharing');
      expect(groups[2].prompts.map((p) => p.id)).toEqual(['4']);
    });

    it('returns empty array when given empty prompts', () => {
      expect(groupByIssue([])).toEqual([]);
    });

    it('renders whatever issueId and issueLabel the API returns without hardcoding', () => {
      const dynamicPrompts: AgentPrompt[] = [
        { id: 'custom-1', issueId: 'custom-anomaly-99', issueLabel: 'Custom Anomaly #99', text: 'Custom 1' },
        { id: 'custom-2', issueId: 'custom-anomaly-99', issueLabel: 'Custom Anomaly #99', text: 'Custom 2' },
      ];
      const groups = groupByIssue(dynamicPrompts);
      expect(groups.length).toBe(1);
      expect(groups[0].issueId).toBe('custom-anomaly-99');
      expect(groups[0].issueLabel).toBe('Custom Anomaly #99');
    });
  });

  describe('placeholders handling', () => {
    const pattern = '\\{([A-Za-z][A-Za-z0-9_]*)\\}';

    it('finds placeholders in prompt text', () => {
      const text = 'Check items for {userUpn} and {siteId} with {userUpn} again.';
      expect(placeholdersIn(text, pattern)).toEqual(['userUpn', 'siteId']);
    });

    it('fills placeholders with resolved values', () => {
      const text = 'User: {userUpn}, Site: {siteId}';
      const filled = fillPlaceholders(text, { userUpn: 'user@contoso.com', siteId: 'site-123' }, pattern);
      expect(filled).toBe('User: user@contoso.com, Site: site-123');
    });
  });
});
