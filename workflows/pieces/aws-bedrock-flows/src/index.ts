import { createPiece, PieceCategory } from '@activepieces/pieces-framework';
import { svgLogo } from '../../aws-common/aws';
import { bedrockFlowsAuth } from './lib/common';
import { invokeFlowAction } from './lib/actions/invoke-flow';
import { listFlowsAction } from './lib/actions/list-flows';

export const awsBedrockFlows = createPiece({
  displayName: 'AWS Bedrock Flows',
  description: 'Run Amazon Bedrock Flows and use their outputs in later steps. Identity is the engine task role.',
  auth: bedrockFlowsAuth,
  minimumSupportedRelease: '0.36.1',
  logoUrl: svgLogo('#ff9900', '<path d="M14 22h12l6 10-6 10H14l6-10zm22 0h12l6 10-6 10H36l6-10z" fill="#fff"/>'),
  categories: [PieceCategory.ARTIFICIAL_INTELLIGENCE],
  authors: ['responsible-ai-enterpriseready'],
  actions: [invokeFlowAction, listFlowsAction],
  triggers: [],
});
