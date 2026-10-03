import { createPiece, PieceCategory } from '@activepieces/pieces-framework';
import { litellmAuth } from './lib/common';
import { chatCompletionAction } from './lib/actions/chat-completion';
import { listModelsAction } from './lib/actions/list-models';

const LOGO =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#0f766e"/><path d="M16 24h32v6H16zm0 10h22v6H16z" fill="#fff"/><circle cx="46" cy="37" r="4" fill="#99f6e4"/></svg>',
  );

export const litellmProxy = createPiece({
  displayName: 'LiteLLM Proxy',
  description:
    'Direct inference through the organisation\'s LiteLLM proxy with the workflow app\'s own virtual key. Budgeted and metered by the proxy; no Responsible AI processing.',
  auth: litellmAuth,
  minimumSupportedRelease: '0.36.1',
  logoUrl: LOGO,
  categories: [PieceCategory.ARTIFICIAL_INTELLIGENCE],
  authors: ['responsible-ai-enterpriseready'],
  actions: [chatCompletionAction, listModelsAction],
  triggers: [],
});
