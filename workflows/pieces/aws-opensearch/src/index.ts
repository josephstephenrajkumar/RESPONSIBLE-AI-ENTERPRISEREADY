import { createPiece, PieceCategory } from '@activepieces/pieces-framework';
import { svgLogo } from '../../aws-common/aws';
import { openSearchAuth } from './lib/common';
import { bulkAction, deleteDocumentAction, getDocumentAction, indexDocumentAction, rawRequestAction } from './lib/actions/documents';
import { searchAction } from './lib/actions/search';

export const awsOpenSearch = createPiece({
  displayName: 'AWS OpenSearch',
  description: 'Search, index and manage documents in Amazon OpenSearch Service domains and Serverless collections with SigV4-signed requests from the engine task role.',
  auth: openSearchAuth,
  minimumSupportedRelease: '0.36.1',
  logoUrl: svgLogo('#005eb8', '<circle cx="28" cy="28" r="11" fill="none" stroke="#fff" stroke-width="5"/><path d="M36 36l12 12" stroke="#fff" stroke-width="6" stroke-linecap="round"/>'),
  categories: [PieceCategory.DEVELOPER_TOOLS],
  authors: ['responsible-ai-enterpriseready'],
  actions: [searchAction, indexDocumentAction, getDocumentAction, deleteDocumentAction, bulkAction, rawRequestAction],
  triggers: [],
});
