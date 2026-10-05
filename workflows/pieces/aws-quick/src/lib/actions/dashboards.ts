import { createAction, Property } from '@activepieces/pieces-framework';
import {
  CreateIngestionCommand, DescribeDashboardCommand, DescribeDashboardSnapshotJobCommand, DescribeDashboardSnapshotJobResultCommand, DescribeIngestionCommand,
  GenerateEmbedUrlForRegisteredUserCommand, ListDashboardsCommand, StartDashboardSnapshotJobCommand, UpdateDashboardPublishedVersionCommand,
  type SnapshotFileSheetSelection, type SnapshotFileSheetSelectionScope,
} from '@aws-sdk/client-quicksight';
import { authValue, errorMessage } from '../../../../aws-common/aws';
import { accountId, client, collectKeys, dashboardDropdown, dataSetDropdown, quickAuth, sleep, type QuickAuth } from '../common';

export const listDashboardsAction = createAction({
  auth: quickAuth,
  name: 'list_dashboards',
  displayName: 'List dashboards',
  description: 'Dashboards in the Quick account (name, id, published version).',
  props: {},
  async run(context) {
    const auth = authValue<QuickAuth>(context.auth);
    try {
      const out = await client(auth).send(new ListDashboardsCommand({ AwsAccountId: await accountId(auth), MaxResults: 100 }));
      return { dashboards: (out.DashboardSummaryList || []).map((d) => ({ dashboardId: d.DashboardId, name: d.Name, arn: d.Arn, publishedVersion: d.PublishedVersionNumber, lastPublished: d.LastPublishedTime, lastUpdated: d.LastUpdatedTime })) };
    } catch (error) { throw new Error(errorMessage(error)); }
  },
});

export const describeDashboardAction = createAction({
  auth: quickAuth,
  name: 'describe_dashboard',
  displayName: 'Describe dashboard',
  description: 'Version, status, sheets and errors of a dashboard.',
  props: { dashboardId: dashboardDropdown },
  async run(context) {
    const auth = authValue<QuickAuth>(context.auth);
    try {
      const out = await client(auth).send(new DescribeDashboardCommand({ AwsAccountId: await accountId(auth), DashboardId: String(context.propsValue.dashboardId) }));
      const d = out.Dashboard;
      return { dashboardId: d?.DashboardId, name: d?.Name, arn: d?.Arn, version: d?.Version?.VersionNumber, status: d?.Version?.Status, sheets: d?.Version?.Sheets, errors: d?.Version?.Errors, lastPublished: d?.LastPublishedTime, lastUpdated: d?.LastUpdatedTime };
    } catch (error) { throw new Error(errorMessage(error)); }
  },
});

export const publishDashboardAction = createAction({
  auth: quickAuth,
  name: 'publish_dashboard',
  displayName: 'Publish dashboard version',
  description: 'Makes a dashboard version the published one (the version readers see). Empty version = the latest version.',
  props: { dashboardId: dashboardDropdown, versionNumber: Property.Number({ displayName: 'Version number', required: false }) },
  async run(context) {
    const auth = authValue<QuickAuth>(context.auth);
    const account = await accountId(auth);
    const dashboardId = String(context.propsValue.dashboardId);
    try {
      let version = Number(context.propsValue.versionNumber);
      if (!version) {
        const desc = await client(auth).send(new DescribeDashboardCommand({ AwsAccountId: account, DashboardId: dashboardId }));
        version = Number(desc.Dashboard?.Version?.VersionNumber);
      }
      const out = await client(auth).send(new UpdateDashboardPublishedVersionCommand({ AwsAccountId: account, DashboardId: dashboardId, VersionNumber: version }));
      return { dashboardId: out.DashboardId, arn: out.DashboardArn, publishedVersion: version, status: out.Status };
    } catch (error) { throw new Error(errorMessage(error)); }
  },
});

export const refreshDatasetAction = createAction({
  auth: quickAuth,
  name: 'refresh_dataset',
  displayName: 'Refresh dataset (SPICE ingestion)',
  description: 'Starts a SPICE ingestion for a dataset and optionally waits for it to finish.',
  props: {
    dataSetId: dataSetDropdown,
    ingestionType: Property.StaticDropdown({ displayName: 'Type', required: true, defaultValue: 'FULL_REFRESH', options: { options: [{ label: 'Full refresh', value: 'FULL_REFRESH' }, { label: 'Incremental refresh', value: 'INCREMENTAL_REFRESH' }] } }),
    waitSeconds: Property.Number({ displayName: 'Wait up to (seconds)', description: '0 = return immediately.', required: false, defaultValue: 0 }),
  },
  async run(context) {
    const auth = authValue<QuickAuth>(context.auth);
    const account = await accountId(auth);
    const { dataSetId, ingestionType, waitSeconds } = context.propsValue;
    const ingestionId = `wf-${Date.now()}`;
    try {
      const started = await client(auth).send(new CreateIngestionCommand({ AwsAccountId: account, DataSetId: String(dataSetId), IngestionId: ingestionId, IngestionType: ingestionType as never }));
      let status = started.IngestionStatus as string | undefined;
      const deadline = Date.now() + Math.min(Number(waitSeconds) || 0, 600) * 1000;
      while (Date.now() < deadline && status && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(status)) {
        await sleep(5000);
        const d = await client(auth).send(new DescribeIngestionCommand({ AwsAccountId: account, DataSetId: String(dataSetId), IngestionId: ingestionId }));
        status = d.Ingestion?.IngestionStatus as string | undefined;
        if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(status || '')) return { ingestionId, status, rowInfo: d.Ingestion?.RowInfo, error: d.Ingestion?.ErrorInfo, timeInSeconds: d.Ingestion?.IngestionTimeInSeconds };
      }
      return { ingestionId, status, arn: started.Arn };
    } catch (error) { throw new Error(errorMessage(error)); }
  },
});

export const exportSnapshotAction = createAction({
  auth: quickAuth,
  name: 'export_snapshot',
  displayName: 'Export dashboard snapshot (PDF to S3)',
  description: 'Starts a dashboard snapshot job for all visible sheets as PDF, writes it to an S3 bucket and waits for the result.',
  props: {
    dashboardId: dashboardDropdown,
    bucketName: Property.ShortText({ displayName: 'S3 bucket', required: true }),
    bucketPrefix: Property.ShortText({ displayName: 'S3 prefix', required: false, defaultValue: 'quick-snapshots/' }),
    bucketRegion: Property.ShortText({ displayName: 'Bucket region', required: false }),
    waitSeconds: Property.Number({ displayName: 'Wait up to (seconds)', required: false, defaultValue: 180 }),
  },
  async run(context) {
    const auth = authValue<QuickAuth>(context.auth);
    const account = await accountId(auth);
    const { dashboardId, bucketName, bucketPrefix, bucketRegion, waitSeconds } = context.propsValue;
    try {
      const desc = await client(auth).send(new DescribeDashboardCommand({ AwsAccountId: account, DashboardId: String(dashboardId) }));
      const sheets: SnapshotFileSheetSelection[] = (desc.Dashboard?.Version?.Sheets || []).map((s) => ({ SheetId: s.SheetId as string, SelectionScope: 'ALL_VISIBLE_VISUALS' as SnapshotFileSheetSelectionScope }));
      if (!sheets.length) throw new Error('The dashboard has no sheets');
      const jobId = `wf-${Date.now()}`;
      await client(auth).send(new StartDashboardSnapshotJobCommand({
        AwsAccountId: account, DashboardId: String(dashboardId), SnapshotJobId: jobId,
        UserConfiguration: { AnonymousUsers: [{}] },
        SnapshotConfiguration: {
          FileGroups: [{ Files: [{ SheetSelections: sheets, FormatType: 'PDF' }] }],
          DestinationConfiguration: { S3Destinations: [{ BucketConfiguration: { BucketName: bucketName, BucketPrefix: bucketPrefix || 'quick-snapshots/', BucketRegion: bucketRegion || auth.region } }] },
        },
      }));
      const deadline = Date.now() + Math.min(Number(waitSeconds) || 180, 900) * 1000;
      let status = 'QUEUED';
      while (Date.now() < deadline) {
        await sleep(5000);
        const job = await client(auth).send(new DescribeDashboardSnapshotJobCommand({ AwsAccountId: account, DashboardId: String(dashboardId), SnapshotJobId: jobId }));
        status = String(job.JobStatus || status);
        if (status === 'COMPLETED' || status === 'FAILED') break;
      }
      if (status !== 'COMPLETED') return { jobId, status };
      const result = await client(auth).send(new DescribeDashboardSnapshotJobResultCommand({ AwsAccountId: account, DashboardId: String(dashboardId), SnapshotJobId: jobId }));
      return { jobId, status, s3Uris: collectKeys(result.Result, 'S3Uri'), errors: result.ErrorInfo, result: result.Result };
    } catch (error) { throw new Error(errorMessage(error)); }
  },
});

export const embedUrlAction = createAction({
  auth: quickAuth,
  name: 'embed_url',
  displayName: 'Generate embed URL',
  description: 'A one-time URL (valid 5 minutes, session up to 10 hours) to embed a dashboard, one visual, or the Quick chat agent for a registered Quick user. Allowed domains must include the portal origin.',
  props: {
    experience: Property.StaticDropdown({ displayName: 'Experience', required: true, defaultValue: 'DASHBOARD', options: { options: [{ label: 'Dashboard', value: 'DASHBOARD' }, { label: 'Single visual', value: 'VISUAL' }, { label: 'Quick chat agent', value: 'QUICK_CHAT' }] } }),
    dashboardId: Property.ShortText({ displayName: 'Dashboard id', description: 'For Dashboard and Single visual.', required: false }),
    sheetId: Property.ShortText({ displayName: 'Sheet id', description: 'Single visual only.', required: false }),
    visualId: Property.ShortText({ displayName: 'Visual id', description: 'Single visual only.', required: false }),
    userArn: Property.ShortText({ displayName: 'Quick user ARN', description: 'Empty = the connection\'s user ARN.', required: false }),
    allowedDomains: Property.Array({ displayName: 'Allowed domains', description: 'Origins that may load the embed, for example https://portal.example.com', required: true }),
    sessionLifetimeInMinutes: Property.Number({ displayName: 'Session lifetime (minutes)', required: false, defaultValue: 600 }),
  },
  async run(context) {
    const auth = authValue<QuickAuth>(context.auth);
    const account = await accountId(auth);
    const { experience, dashboardId, sheetId, visualId, userArn, allowedDomains, sessionLifetimeInMinutes } = context.propsValue;
    const user = userArn || auth.userArn;
    if (!user) throw new Error('A Quick user ARN is required (on the connection or the step)');
    let configuration: Record<string, unknown>;
    if (experience === 'QUICK_CHAT') configuration = { QuickChat: {} };
    else if (experience === 'VISUAL') {
      if (!dashboardId || !sheetId || !visualId) throw new Error('Dashboard id, sheet id and visual id are required for a single visual');
      configuration = { DashboardVisual: { InitialDashboardVisualId: { DashboardId: dashboardId, SheetId: sheetId, VisualId: visualId } } };
    } else {
      if (!dashboardId) throw new Error('Dashboard id is required');
      configuration = { Dashboard: { InitialDashboardId: dashboardId } };
    }
    try {
      const out = await client(auth).send(new GenerateEmbedUrlForRegisteredUserCommand({
        AwsAccountId: account, UserArn: String(user), ExperienceConfiguration: configuration as never,
        AllowedDomains: (allowedDomains as string[]).map(String), SessionLifetimeInMinutes: Number(sessionLifetimeInMinutes) || 600,
      }));
      return { embedUrl: out.EmbedUrl, experience, expiresInMinutes: 5 };
    } catch (error) { throw new Error(errorMessage(error)); }
  },
});
