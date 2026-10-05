import { createAction } from '@activepieces/pieces-framework';
import { ListAgentsCommand, ListKnowledgeBasesCommand } from '@aws-sdk/client-bedrock-agent';
import { authValue, errorMessage } from '../../../../aws-common/aws';
import { bedrockAgentsAuth, control } from '../common';

export const listAgentsAction = createAction({
  auth: bedrockAgentsAuth,
  name: 'list_agents',
  displayName: 'List agents and knowledge bases',
  description: 'Agents and knowledge bases visible to the connection in its region.',
  props: {},
  async run(context) {
    const auth = authValue(context.auth);
    try {
      const client = control(auth);
      const [agents, kbs] = await Promise.all([client.send(new ListAgentsCommand({ maxResults: 100 })), client.send(new ListKnowledgeBasesCommand({ maxResults: 100 }))]);
      return {
        agents: (agents.agentSummaries || []).map((s) => ({ agentId: s.agentId, name: s.agentName, status: s.agentStatus, description: s.description, updatedAt: s.updatedAt })),
        knowledgeBases: (kbs.knowledgeBaseSummaries || []).map((s) => ({ knowledgeBaseId: s.knowledgeBaseId, name: s.name, status: s.status, description: s.description })),
      };
    } catch (error) {
      throw new Error(errorMessage(error));
    }
  },
});
