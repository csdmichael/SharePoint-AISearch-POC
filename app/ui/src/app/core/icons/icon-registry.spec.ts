import { ICON_REGISTRY } from './icon-registry';
import agentConfig from '../../../assets/config/agent.json';
import layoutConfig from '../../../assets/config/layout.json';
import navigationConfig from '../../../assets/config/navigation.json';

describe('icon registry', () => {
  it('registers every icon named in the configuration', () => {
    const names = [...Object.values(layoutConfig.icons), ...navigationConfig.items.map((item) => item.icon), agentConfig.fab.icon];
    const missing = names.filter((name) => !(name in ICON_REGISTRY));
    expect(missing).toEqual([]);
  });
});
