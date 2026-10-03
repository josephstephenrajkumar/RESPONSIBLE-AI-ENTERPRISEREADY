import { createAction, Property } from '@activepieces/pieces-framework';
import { httpClient, HttpMethod } from '@activepieces/pieces-common';
import { litellmAuth, trimSlash } from '../common';

export const chatCompletionAction = createAction({
  auth: litellmAuth,
  name: 'chat_completion',
  displayName: 'Chat completion (LiteLLM)',
  description:
    'Call /chat/completions on the LiteLLM proxy with this app\'s virtual key. No Responsible AI processing is applied; use the Responsible AI Gateway piece when governance must apply.',
  props: {
    model: Property.ShortText({
      displayName: 'Model',
      description: 'A model group served by the proxy, for example chat-default.',
      required: true,
    }),
    systemPrompt: Property.LongText({
      displayName: 'System prompt',
      required: false,
    }),
    prompt: Property.LongText({
      displayName: 'Prompt',
      required: true,
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
    jsonOutput: Property.Checkbox({
      displayName: 'Ask for JSON output',
      description: 'Sets response_format to json_object when the model supports it.',
      required: false,
      defaultValue: false,
    }),
    appId: Property.ShortText({
      displayName: 'Workflow app id',
      description: 'Attribution tag written to the proxy spend log (client_id:workflow-app:<id>).',
      required: false,
    }),
    user: Property.ShortText({
      displayName: 'End user',
      description: 'Optional end-user identifier for the proxy spend log.',
      required: false,
    }),
  },
  async run(context) {
    const { proxyUrl, apiKey } = context.auth.props;
    const messages: Array<{ role: string; content: string }> = [];
    if (context.propsValue.systemPrompt) {
      messages.push({ role: 'system', content: context.propsValue.systemPrompt });
    }
    messages.push({ role: 'user', content: context.propsValue.prompt });

    const tags = ['purpose:workflow', 'mode:workflow'];
    if (context.propsValue.appId) {
      tags.push(`client_id:workflow-app:${context.propsValue.appId}`);
    }
    const body: Record<string, unknown> = {
      model: context.propsValue.model,
      messages,
      temperature: context.propsValue.temperature ?? 0.2,
      max_tokens: context.propsValue.maxTokens ?? 800,
      metadata: { tags, generation_name: 'workflow-app.chat_completion' },
    };
    if (context.propsValue.user) body['user'] = context.propsValue.user;
    if (context.propsValue.jsonOutput) body['response_format'] = { type: 'json_object' };

    const response = await httpClient.sendRequest<any>({
      method: HttpMethod.POST,
      url: `${trimSlash(proxyUrl)}/chat/completions`,
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body,
      timeout: 120000,
    });
    if (response.status >= 400) {
      throw new Error(`LiteLLM /chat/completions failed with HTTP ${response.status}: ${JSON.stringify(response.body).slice(0, 500)}`);
    }
    const headers = (response.headers ?? {}) as Record<string, string | string[] | undefined>;
    const header = (name: string) => {
      const value = headers[name] ?? headers[name.toLowerCase()];
      return Array.isArray(value) ? value[0] : value;
    };
    const payload = response.body ?? {};
    const choice = (payload.choices ?? [])[0] ?? {};
    const costHeader = header('x-litellm-response-cost');
    return {
      content: choice.message?.content ?? '',
      finish_reason: choice.finish_reason ?? '',
      model: payload.model ?? context.propsValue.model,
      usage: payload.usage ?? {},
      cost_usd: costHeader !== undefined && costHeader !== '' ? Number(costHeader) : null,
      call_id: header('x-litellm-call-id') ?? payload.id ?? '',
      raw: payload,
    };
  },
});
