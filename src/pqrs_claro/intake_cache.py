"""Persistent request-level reuse, bound to original, sources and model policy."""

from copy import deepcopy

from .source_context import build_source_requests
from .source_library import digest

CACHE_VERSION = 1


def semantic(request):
    return {key: value for key, value in request.items() if key != 'label'}


def request_keys(identification):
    requests = {r['id']: r for r in identification['requests']}
    keys = {}
    for enriched in build_source_requests({'id': 'intake-cache', 'identification': identification}):
        key = enriched['id']
        request = requests[key]
        context = enriched['context']
        related = set(context['omitted_request_ids'])
        for group in ('ancestors', 'children', 'referenced_requests', 'preceding_section'):
            related.update(r['id'] for r in context[group])
        # Titles and references are semantic inputs too; labels only change presentation.
        keys[key] = digest({'request': semantic(request),
                            'unresolved': context['unresolved_references'],
                            'related': [semantic(requests[k]) for k in sorted(related)]})
    return keys


def reuse_plan(cache, context, identification, *, full=False):
    valid = bool(cache and cache.get('version') == CACHE_VERSION
                 and cache.get('context') == context and cache.get('report'))
    entries = deepcopy(cache.get('entries', {})) if valid and not full else {}
    keys = request_keys(identification)
    reused = {key: entries[key]['report'] for key, fingerprint in keys.items()
              if key in entries and entries[key]['key'] == fingerprint}
    return {'keys': keys, 'entries': entries, 'reused': reused,
            'pending': [key for key in keys if key not in reused],
            'reason': 'full' if full else 'changed_requests' if valid else 'context_changed'}
