import { createAction, Property } from '@activepieces/pieces-framework';
import { authValue, parseJsonInput } from '../../../../aws-common/aws';
import { indexProp, openSearchAuth, signedRequest, type OpenSearchAuth } from '../common';

export const indexDocumentAction = createAction({
  auth: openSearchAuth,
  name: 'index_document',
  displayName: 'Index document',
  description: 'Create or replace a JSON document. Serverless collections do not accept custom ids on PUT; leave the id empty there.',
  props: {
    index: indexProp,
    id: Property.ShortText({ displayName: 'Document id', required: false }),
    document: Property.Json({ displayName: 'Document (JSON)', required: true }),
    refresh: Property.Checkbox({ displayName: 'Refresh index after write (managed domains only)', required: false, defaultValue: false }),
  },
  async run(context) {
    const auth = authValue<OpenSearchAuth>(context.auth);
    const { index, id, document, refresh } = context.propsValue;
    const body = parseJsonInput(document, 'Document');
    const query = refresh && auth.service !== 'aoss' ? { refresh: 'true' } : undefined;
    const path = id ? `/${encodeURIComponent(index)}/_doc/${encodeURIComponent(id)}` : `/${encodeURIComponent(index)}/_doc`;
    const result = await signedRequest(auth, id ? 'PUT' : 'POST', path, body, query);
    return result.body;
  },
});

export const getDocumentAction = createAction({
  auth: openSearchAuth,
  name: 'get_document',
  displayName: 'Get document',
  description: 'Fetch one document by id.',
  props: { index: indexProp, id: Property.ShortText({ displayName: 'Document id', required: true }) },
  async run(context) {
    const auth = authValue<OpenSearchAuth>(context.auth);
    const { index, id } = context.propsValue;
    const result = await signedRequest(auth, 'GET', `/${encodeURIComponent(index)}/_doc/${encodeURIComponent(id)}`);
    const data = result.body as { _source?: unknown; found?: boolean };
    return { found: data.found, source: data._source, raw: data };
  },
});

export const deleteDocumentAction = createAction({
  auth: openSearchAuth,
  name: 'delete_document',
  displayName: 'Delete document',
  description: 'Delete one document by id.',
  props: { index: indexProp, id: Property.ShortText({ displayName: 'Document id', required: true }) },
  async run(context) {
    const auth = authValue<OpenSearchAuth>(context.auth);
    const { index, id } = context.propsValue;
    return (await signedRequest(auth, 'DELETE', `/${encodeURIComponent(index)}/_doc/${encodeURIComponent(id)}`)).body;
  },
});

export const bulkAction = createAction({
  auth: openSearchAuth,
  name: 'bulk',
  displayName: 'Bulk index documents',
  description: 'Index a list of JSON documents in one request (bulk API).',
  props: {
    index: indexProp,
    documents: Property.Json({ displayName: 'Documents (JSON array)', required: true }),
    idField: Property.ShortText({ displayName: 'Id field', description: 'Field of each document to use as the id (managed domains only).', required: false }),
  },
  async run(context) {
    const auth = authValue<OpenSearchAuth>(context.auth);
    const { index, documents, idField } = context.propsValue;
    const docs = parseJsonInput(documents, 'Documents');
    if (!Array.isArray(docs)) throw new Error('Documents must be a JSON array');
    const lines: string[] = [];
    for (const doc of docs) {
      const meta: Record<string, unknown> = { _index: index };
      if (idField && auth.service !== 'aoss' && doc && typeof doc === 'object' && idField in doc) meta._id = (doc as Record<string, unknown>)[idField];
      lines.push(JSON.stringify({ index: meta }), JSON.stringify(doc));
    }
    const result = await signedRequest(auth, 'POST', '/_bulk', lines.join('\n') + '\n');
    const data = result.body as { errors?: boolean; items?: unknown[]; took?: number };
    return { errors: data.errors, count: data.items?.length || 0, took: data.took, items: data.items };
  },
});

export const rawRequestAction = createAction({
  auth: openSearchAuth,
  name: 'raw_request',
  displayName: 'Raw request',
  description: 'Any OpenSearch REST call with a signed request: create an index with a k-NN mapping, run an aggregation, manage pipelines.',
  props: {
    method: Property.StaticDropdown({ displayName: 'Method', required: true, defaultValue: 'GET', options: { options: ['GET', 'POST', 'PUT', 'DELETE', 'HEAD'].map((m) => ({ label: m, value: m })) } }),
    path: Property.ShortText({ displayName: 'Path', description: 'For example /my-index/_mapping or /_cat/indices?format=json', required: true }),
    body: Property.Json({ displayName: 'Body (JSON)', required: false }),
  },
  async run(context) {
    const auth = authValue<OpenSearchAuth>(context.auth);
    const { method, path, body } = context.propsValue;
    const [p, qs] = path.split('?');
    const query = qs ? Object.fromEntries(new URLSearchParams(qs).entries()) : undefined;
    return (await signedRequest(auth, method, p, parseJsonInput(body, 'Body'), query)).body;
  },
});
