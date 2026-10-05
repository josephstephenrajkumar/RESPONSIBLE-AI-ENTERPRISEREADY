import { createAction, Property } from '@activepieces/pieces-framework';
import { authValue, parseJsonInput } from '../../../../aws-common/aws';
import { indexProp, openSearchAuth, signedRequest, type OpenSearchAuth } from '../common';

export const searchAction = createAction({
  auth: openSearchAuth,
  name: 'search',
  displayName: 'Search',
  description: 'Run a query against an index: a full query DSL body, or a simple query string.',
  props: {
    index: indexProp,
    query: Property.Json({ displayName: 'Query DSL (JSON body)', description: 'For example {"query":{"match":{"title":"invoice"}}}. Leave empty to use the query string.', required: false }),
    q: Property.ShortText({ displayName: 'Query string', description: 'Lucene syntax, used when no DSL body is given. Example: status:open AND customer:acme', required: false }),
    size: Property.Number({ displayName: 'Size', required: false, defaultValue: 10 }),
  },
  async run(context) {
    const auth = authValue<OpenSearchAuth>(context.auth);
    const { index, query, q, size } = context.propsValue;
    const body = parseJsonInput(query, 'Query DSL') as Record<string, unknown> | undefined;
    const params: Record<string, string> = { size: String(Number(size) || 10) };
    if (!body && q) params.q = q;
    const result = await signedRequest(auth, body ? 'POST' : 'GET', `/${encodeURIComponent(index)}/_search`, body, params);
    const data = result.body as { hits?: { total?: unknown; hits?: { _id: string; _score: number; _source: unknown }[] } };
    return { total: data.hits?.total, hits: (data.hits?.hits || []).map((h) => ({ id: h._id, score: h._score, source: h._source })), raw: data };
  },
});
