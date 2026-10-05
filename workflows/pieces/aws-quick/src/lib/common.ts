import { Property } from '@activepieces/pieces-framework';
import { ListDashboardsCommand, ListDataSetsCommand, QuickSightClient } from '@aws-sdk/client-quicksight';
import { authValue, callerIdentity, clientConfig, makeAwsAuth, type AwsAuthValue } from '../../../aws-common/aws';

export type QuickAuth = AwsAuthValue & { awsAccountId?: string; userArn?: string };

export const quickAuth = makeAwsAuth(
  {
    awsAccountId: Property.ShortText({ displayName: 'AWS account id', description: 'Account that holds the Quick subscription. Empty = the account of the credentials.', required: false }),
    userArn: Property.ShortText({ displayName: 'Quick user ARN for embedding (optional)', description: 'A registered Quick user (arn:aws:quicksight:<region>:<account>:user/<namespace>/<name>) used by the Embed URL action.', required: false }),
  },
  'Amazon Quick Suite through the QuickSight API family. Quick Suite features are regional (N. Virginia, Oregon, Sydney, Ireland); set the region of your Quick account. The engine task role needs quicksight:List*, Describe*, CreateIngestion, StartDashboardSnapshotJob, GenerateEmbedUrlForRegisteredUser, StartAutomationJob and DescribeAutomationJob.',
);

export const client = (auth: QuickAuth) => new QuickSightClient(clientConfig(auth));

export async function accountId(auth: QuickAuth): Promise<string> {
  if (auth.awsAccountId) return String(auth.awsAccountId);
  const id = await callerIdentity(auth);
  if (!id.account) throw new Error('Could not determine the AWS account id; set it on the connection');
  return id.account;
}

export const dashboardDropdown = Property.Dropdown({
  displayName: 'Dashboard',
  required: true,
  refreshers: [],
  options: async ({ auth }: Record<string, unknown>) => {
    const a = authValue<QuickAuth>(auth);
    if (!a?.region) return { disabled: true, placeholder: 'Connect first', options: [] };
    const out = await client(a).send(new ListDashboardsCommand({ AwsAccountId: await accountId(a), MaxResults: 100 }));
    return { disabled: false, options: (out.DashboardSummaryList || []).map((d) => ({ label: `${d.Name} (v${d.PublishedVersionNumber ?? '-'})`, value: d.DashboardId as string })) };
  },
});

export const dataSetDropdown = Property.Dropdown({
  displayName: 'Dataset',
  required: true,
  refreshers: [],
  options: async ({ auth }: Record<string, unknown>) => {
    const a = authValue<QuickAuth>(auth);
    if (!a?.region) return { disabled: true, placeholder: 'Connect first', options: [] };
    const out = await client(a).send(new ListDataSetsCommand({ AwsAccountId: await accountId(a), MaxResults: 100 }));
    return { disabled: false, options: (out.DataSetSummaries || []).map((d) => ({ label: `${d.Name} (${d.ImportMode})`, value: d.DataSetId as string })) };
  },
});

export function collectKeys(value: unknown, key: string, out: string[] = []): string[] {
  if (Array.isArray(value)) value.forEach((v) => collectKeys(v, key, out));
  else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (k === key && typeof v === 'string') out.push(v);
      else collectKeys(v, key, out);
    }
  }
  return out;
}

export const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
