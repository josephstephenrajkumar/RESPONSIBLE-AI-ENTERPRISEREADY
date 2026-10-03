import { PieceAuth, Property } from '@activepieces/pieces-framework';
import { httpClient, HttpMethod } from '@activepieces/pieces-common';

export const litellmAuth = PieceAuth.CustomAuth({
  description:
    'LiteLLM proxy base URL as seen from the Activepieces worker (http://litellm:4000 in the local compose stack) and the virtual key issued to this workflow app. The key carries the app budget and model scope.',
  props: {
    proxyUrl: Property.ShortText({
      displayName: 'LiteLLM proxy URL',
      required: true,
      defaultValue: 'http://litellm:4000',
    }),
    apiKey: PieceAuth.SecretText({
      displayName: 'Virtual key',
      description: 'A LiteLLM virtual key (sk-...). Never the master key.',
      required: true,
    }),
  },
  required: true,
  // `auth` here is the props object itself (not wrapped in .props as in action contexts).
  validate: async ({ auth }) => {
    try {
      const response = await httpClient.sendRequest({
        method: HttpMethod.GET,
        url: `${trimSlash(auth.proxyUrl)}/models`,
        headers: { Authorization: `Bearer ${auth.apiKey}` },
      });
      return response.status < 300 ? { valid: true } : { valid: false, error: `Proxy answered HTTP ${response.status}` };
    } catch (error) {
      return { valid: false, error: (error as Error).message };
    }
  },
});

export function trimSlash(url: string): string {
  return (url || '').replace(/\/+$/, '');
}
