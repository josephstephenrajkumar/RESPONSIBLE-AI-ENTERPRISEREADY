import { createAction } from '@activepieces/pieces-framework';
import { httpClient, HttpMethod } from '@activepieces/pieces-common';
import { gatewayAuth, trimSlash } from '../common';

export const listModelsAction = createAction({
  auth: gatewayAuth,
  name: 'list_models',
  displayName: 'List models',
  description: 'Models the gateway allows for chat, grouped by provider, as served by the LiteLLM proxy.',
  props: {},
  async run(context) {
    const { gatewayUrl, appToken } = context.auth.props;
    const response = await httpClient.sendRequest<Record<string, unknown>>({
      method: HttpMethod.GET,
      url: `${trimSlash(gatewayUrl)}/gateway/models`,
      headers: { Authorization: `Bearer ${appToken}` },
    });
    if (response.status >= 400) {
      throw new Error(`Gateway /gateway/models failed with HTTP ${response.status}`);
    }
    return response.body;
  },
});
