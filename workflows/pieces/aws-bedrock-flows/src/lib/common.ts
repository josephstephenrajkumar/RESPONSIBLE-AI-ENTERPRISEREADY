import { BedrockAgentClient, ListFlowAliasesCommand, ListFlowsCommand } from '@aws-sdk/client-bedrock-agent';
import { BedrockAgentRuntimeClient } from '@aws-sdk/client-bedrock-agent-runtime';
import { Property } from '@activepieces/pieces-framework';
import { authValue, clientConfig, makeAwsAuth, type AwsAuthValue } from '../../../aws-common/aws';

export const bedrockFlowsAuth = makeAwsAuth(
  {},
  'Amazon Bedrock Flows. The engine task role needs bedrock:InvokeFlow, bedrock:ListFlows, bedrock:GetFlow and bedrock:ListFlowAliases; locally supply keys or assume a role.',
);

export const control = (auth: AwsAuthValue) => new BedrockAgentClient(clientConfig(auth));
export const runtime = (auth: AwsAuthValue) => new BedrockAgentRuntimeClient(clientConfig(auth));

export const flowDropdown = Property.Dropdown({
  displayName: 'Flow',
  required: true,
  refreshers: [],
  options: async ({ auth }: Record<string, unknown>) => {
    const a = authValue(auth);
    if (!a?.region) return { disabled: true, placeholder: 'Connect first', options: [] };
    const out = await control(a).send(new ListFlowsCommand({ maxResults: 100 }));
    return { disabled: false, options: (out.flowSummaries || []).map((s) => ({ label: `${s.name} (${s.status})`, value: s.id as string })) };
  },
});

export const flowAliasDropdown = Property.Dropdown({
  displayName: 'Flow alias',
  description: 'Aliases point at a prepared version of the flow.',
  required: true,
  refreshers: ['flowIdentifier'],
  options: async ({ auth, flowIdentifier }: Record<string, unknown>) => {
    const a = authValue(auth);
    if (!a?.region || !flowIdentifier) return { disabled: true, placeholder: 'Pick a flow first', options: [] };
    const out = await control(a).send(new ListFlowAliasesCommand({ flowIdentifier: String(flowIdentifier), maxResults: 100 }));
    return { disabled: false, options: (out.flowAliasSummaries || []).map((s) => ({ label: `${s.name}`, value: s.id as string })) };
  },
});
