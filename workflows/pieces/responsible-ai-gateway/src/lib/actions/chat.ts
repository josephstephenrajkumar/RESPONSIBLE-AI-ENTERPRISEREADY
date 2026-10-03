import { createAction, Property } from '@activepieces/pieces-framework';
import { httpClient, HttpMethod } from '@activepieces/pieces-common';
import { gatewayAuth, trimSlash } from '../common';

export const chatAction = createAction({
  auth: gatewayAuth,
  name: 'chat',
  displayName: 'Chat (Responsible AI)',
  description:
    'Send a message through the gateway /chat endpoint. Privacy redaction, safety guardrails, policy checks, evaluations and cost metering are applied by the gateway; the model call itself goes through the LiteLLM proxy.',
  props: {
    message: Property.LongText({
      displayName: 'Message',
      required: true,
    }),
    mode: Property.StaticDropdown({
      displayName: 'Responsible AI mode',
      description: 'framework = Presidio, Guardrails, Ragas and TruLens; code = lightweight heuristic evaluators.',
      required: true,
      defaultValue: 'framework',
      options: {
        options: [
          { label: 'framework', value: 'framework' },
          { label: 'code', value: 'code' },
        ],
      },
    }),
    model: Property.ShortText({
      displayName: 'Model',
      description: 'A model group exposed by the proxy (see Gateway → List models). Empty uses the gateway default.',
      required: false,
    }),
    temperature: Property.Number({
      displayName: 'Temperature',
      required: false,
      defaultValue: 0.2,
    }),
    maxTokens: Property.Number({
      displayName: 'Max tokens',
      required: false,
      defaultValue: 800,
    }),
    sessionId: Property.ShortText({
      displayName: 'Session id',
      description: 'Groups the turns of one conversation for attribution. Use the chat trigger sessionId.',
      required: false,
    }),
    agentId: Property.ShortText({
      displayName: 'Agent id',
      description: 'Optional attribution label for FinOps / AIOps.',
      required: false,
    }),
  },
  async run(context) {
    const { gatewayUrl, appToken } = context.auth.props;
    const body: Record<string, unknown> = {
      message: context.propsValue.message,
      mode: context.propsValue.mode ?? 'framework',
      model: context.propsValue.model ?? '',
      temperature: context.propsValue.temperature ?? 0.2,
      max_tokens: context.propsValue.maxTokens ?? 800,
      session_id: context.propsValue.sessionId ?? '',
      agent_id: context.propsValue.agentId ?? '',
    };
    const response = await httpClient.sendRequest<Record<string, unknown>>({
      method: HttpMethod.POST,
      url: `${trimSlash(gatewayUrl)}/chat`,
      headers: {
        Authorization: `Bearer ${appToken}`,
        'Content-Type': 'application/json',
      },
      body,
      timeout: 120000,
    });
    if (response.status >= 400) {
      throw new Error(`Gateway /chat failed with HTTP ${response.status}: ${JSON.stringify(response.body).slice(0, 500)}`);
    }
    return response.body;
  },
});
