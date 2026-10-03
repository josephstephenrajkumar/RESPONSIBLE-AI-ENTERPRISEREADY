import { createAction } from '@activepieces/pieces-framework';
import { httpClient, HttpMethod } from '@activepieces/pieces-common';
import { litellmAuth, trimSlash } from '../common';

export const listModelsAction = createAction({
  auth: litellmAuth,
  name: 'list_models',
  displayName: 'List models',
  description: 'Model groups this virtual key may call on the proxy.',
  props: {},
  async run(context) {
    const { proxyUrl, apiKey } = context.auth.props;
    const response = await httpClient.sendRequest<any>({
      method: HttpMethod.GET,
      url: `${trimSlash(proxyUrl)}/models`,
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    if (response.status >= 400) {
      throw new Error(`LiteLLM /models failed with HTTP ${response.status}`);
    }
    return { models: (response.body?.data ?? []).map((m: any) => m.id) };
  },
});
