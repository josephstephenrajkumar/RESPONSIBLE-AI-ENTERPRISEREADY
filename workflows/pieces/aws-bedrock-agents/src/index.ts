import { createPiece, PieceCategory } from '@activepieces/pieces-framework';
import { svgLogo } from '../../aws-common/aws';
import { bedrockAgentsAuth } from './lib/common';
import { invokeAgentAction } from './lib/actions/invoke-agent';
import { listAgentsAction } from './lib/actions/list-agents';
import { retrieveAction, retrieveAndGenerateAction } from './lib/actions/retrieve';

export const awsBedrockAgents = createPiece({
  displayName: 'AWS Bedrock Agents',
  description: 'Invoke Amazon Bedrock Agents and query Bedrock Knowledge Bases. Identity is the engine task role (no stored keys in AWS).',
  auth: bedrockAgentsAuth,
  minimumSupportedRelease: '0.36.1',
  logoUrl: svgLogo('#ff9900', '<path d="M20 44V20h8l8 14 8-14h0v24h-6V31l-6 10h-2l-6-10v13z" fill="#fff"/>'),
  categories: [PieceCategory.ARTIFICIAL_INTELLIGENCE],
  authors: ['responsible-ai-enterpriseready'],
  actions: [invokeAgentAction, retrieveAction, retrieveAndGenerateAction, listAgentsAction],
  triggers: [],
});
