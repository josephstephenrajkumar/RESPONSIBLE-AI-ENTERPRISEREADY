import { createPiece, PieceCategory } from '@activepieces/pieces-framework';
import { gatewayAuth } from './lib/common';
import { chatAction } from './lib/actions/chat';
import { listModelsAction } from './lib/actions/list-models';

const LOGO =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#2563eb"/><path d="M18 40l14-22 14 22h-7l-7-11-7 11z" fill="#fff"/><circle cx="32" cy="46" r="4" fill="#bfdbfe"/></svg>',
  );

export const responsibleAiGateway = createPiece({
  displayName: 'Responsible AI Gateway',
  description:
    'Governed chat for workflow apps. Every call passes through the Responsible AI Enterprise Gateway, so privacy, safety, policy, evaluation and FinOps metering apply.',
  auth: gatewayAuth,
  minimumSupportedRelease: '0.36.1',
  logoUrl: LOGO,
  categories: [PieceCategory.ARTIFICIAL_INTELLIGENCE],
  authors: ['responsible-ai-enterpriseready'],
  actions: [chatAction, listModelsAction],
  triggers: [],
});
