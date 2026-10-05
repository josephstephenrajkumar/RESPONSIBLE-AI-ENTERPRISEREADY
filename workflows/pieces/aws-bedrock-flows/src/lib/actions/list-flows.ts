import { createAction } from '@activepieces/pieces-framework';
import { ListFlowsCommand } from '@aws-sdk/client-bedrock-agent';
import { authValue, errorMessage } from '../../../../aws-common/aws';
import { bedrockFlowsAuth, control } from '../common';

export const listFlowsAction = createAction({
  auth: bedrockFlowsAuth,
  name: 'list_flows',
  displayName: 'List flows',
  description: 'Bedrock Flows visible to the connection in its region.',
  props: {},
  async run(context) {
    const auth = authValue(context.auth);
    try {
      const out = await control(auth).send(new ListFlowsCommand({ maxResults: 100 }));
      return { flows: (out.flowSummaries || []).map((s) => ({ id: s.id, name: s.name, status: s.status, version: s.version, description: s.description, updatedAt: s.updatedAt })) };
    } catch (error) {
      throw new Error(errorMessage(error));
    }
  },
});
