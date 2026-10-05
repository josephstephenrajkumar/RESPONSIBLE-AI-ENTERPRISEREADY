import { createPiece, PieceCategory } from '@activepieces/pieces-framework';
import { svgLogo } from '../../aws-common/aws';
import { quickAuth } from './lib/common';
import { describeDashboardAction, embedUrlAction, exportSnapshotAction, listDashboardsAction, publishDashboardAction, refreshDatasetAction } from './lib/actions/dashboards';
import { describeAutomationJobAction, describeQuickFlowAction, listQuickFlowsAction, startAutomationJobAction } from './lib/actions/flows-automate';

export const awsQuick = createPiece({
  displayName: 'AWS Quick Suite',
  description: 'Amazon Quick Suite: dashboards and datasets (Quick Sight), PDF snapshot exports, embed URLs for dashboards and the Quick chat agent, Quick Flows metadata and Quick Automate jobs. Identity is the engine task role.',
  auth: quickAuth,
  minimumSupportedRelease: '0.36.1',
  logoUrl: svgLogo('#232f3e', '<rect x="14" y="34" width="8" height="16" fill="#ff9900"/><rect x="28" y="24" width="8" height="26" fill="#ff9900"/><rect x="42" y="14" width="8" height="36" fill="#ff9900"/>'),
  categories: [PieceCategory.BUSINESS_INTELLIGENCE],
  authors: ['responsible-ai-enterpriseready'],
  actions: [listDashboardsAction, describeDashboardAction, publishDashboardAction, refreshDatasetAction, exportSnapshotAction, embedUrlAction, listQuickFlowsAction, describeQuickFlowAction, startAutomationJobAction, describeAutomationJobAction],
  triggers: [],
});
