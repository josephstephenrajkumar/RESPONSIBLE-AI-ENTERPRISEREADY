import { BedrockAgentClient, ListAgentAliasesCommand, ListAgentsCommand, ListKnowledgeBasesCommand } from '@aws-sdk/client-bedrock-agent';
import { BedrockAgentRuntimeClient } from '@aws-sdk/client-bedrock-agent-runtime';
import { Property } from '@activepieces/pieces-framework';
import { authValue, clientConfig, makeAwsAuth, type AwsAuthValue } from '../../../aws-common/aws';

export const bedrockAgentsAuth = makeAwsAuth(
  {},
  'Amazon Bedrock Agents and Knowledge Bases. In AWS the engine task role needs bedrock:InvokeAgent, bedrock:Retrieve, bedrock:RetrieveAndGenerate and the bedrock:List* and Get* actions; locally supply keys or assume a role.',
);

export const control = (auth: AwsAuthValue) => new BedrockAgentClient(clientConfig(auth));
export const runtime = (auth: AwsAuthValue) => new BedrockAgentRuntimeClient(clientConfig(auth));

export const agentDropdown = Property.Dropdown({
  displayName: 'Agent',
  required: true,
  refreshers: [],
  options: async ({ auth }: Record<string, unknown>) => {
    const a = authValue(auth);
    if (!a?.region) return { disabled: true, placeholder: 'Connect first', options: [] };
    const out = await control(a).send(new ListAgentsCommand({ maxResults: 100 }));
    return { disabled: false, options: (out.agentSummaries || []).map((s) => ({ label: `${s.agentName} (${s.agentStatus})`, value: s.agentId as string })) };
  },
});

export const aliasDropdown = Property.Dropdown({
  displayName: 'Agent alias',
  description: 'Use TSTALIASID to call the working draft.',
  required: true,
  refreshers: ['agentId'],
  options: async ({ auth, agentId }: Record<string, unknown>) => {
    const a = authValue(auth);
    if (!a?.region || !agentId) return { disabled: true, placeholder: 'Pick an agent first', options: [] };
    const out = await control(a).send(new ListAgentAliasesCommand({ agentId: String(agentId), maxResults: 100 }));
    const options = (out.agentAliasSummaries || []).map((s) => ({ label: `${s.agentAliasName} (${s.agentAliasStatus})`, value: s.agentAliasId as string }));
    return { disabled: false, options: [{ label: 'Working draft (TSTALIASID)', value: 'TSTALIASID' }, ...options] };
  },
});

export const knowledgeBaseDropdown = Property.Dropdown({
  displayName: 'Knowledge base',
  required: true,
  refreshers: [],
  options: async ({ auth }: Record<string, unknown>) => {
    const a = authValue(auth);
    if (!a?.region) return { disabled: true, placeholder: 'Connect first', options: [] };
    const out = await control(a).send(new ListKnowledgeBasesCommand({ maxResults: 100 }));
    return { disabled: false, options: (out.knowledgeBaseSummaries || []).map((s) => ({ label: `${s.name} (${s.status})`, value: s.knowledgeBaseId as string })) };
  },
});
