import { PieceAuth, Property } from '@activepieces/pieces-framework';
import { httpClient, HttpMethod } from '@activepieces/pieces-common';

export const gatewayAuth = PieceAuth.CustomAuth({
  description:
    'The gateway base URL as seen from the Activepieces worker (for example http://host.docker.internal:8000 locally) and the workflow app token issued from the Workflow Apps screen. The token is stored encrypted by Activepieces and never appears in the flow definition.',
  props: {
    gatewayUrl: Property.ShortText({
      displayName: 'Gateway URL',
      description: 'Base URL of the Responsible AI gateway, without a trailing slash.',
      required: true,
      defaultValue: 'http://host.docker.internal:8000',
    }),
    appToken: PieceAuth.SecretText({
      displayName: 'Workflow app token',
      description: 'Issued per workflow app by the gateway (prefix rai_app_).',
      required: true,
    }),
  },
  required: true,
  // `auth` here is the props object itself (not wrapped in .props as in action contexts).
  validate: async ({ auth }) => {
    try {
      const response = await httpClient.sendRequest({
        method: HttpMethod.GET,
        url: `${trimSlash(auth.gatewayUrl)}/auth/me`,
        headers: { Authorization: `Bearer ${auth.appToken}` },
      });
      if (response.status >= 200 && response.status < 300) {
        return { valid: true };
      }
      return { valid: false, error: `Gateway answered HTTP ${response.status}` };
    } catch (error) {
      return { valid: false, error: (error as Error).message };
    }
  },
});

export function trimSlash(url: string): string {
  return (url || '').replace(/\/+$/, '');
}
