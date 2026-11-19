#--------------------------------
# Minimal in-memory fake MongoDB for expression matrix unit tests
#--------------------------------
#
# The expression_matrix module only uses a small subset of pymongo:
#   * db[collection_name] -> collection handle
#   * collection.find_one(filter)
#   * collection.find(filter, projection) -> iterable of dicts
#
# This fake implements exactly that subset with enough query support for the
# tests: equality matches plus {"$in": [...]} operators. It avoids requiring a
# running MongoDB (or mongomock) for the focused matrix tests.

import copy


def _matches(doc, query):
    for key, cond in query.items():
        value = doc.get(key)
        if isinstance(cond, dict) and "$in" in cond:
            if value not in cond["$in"]:
                return False
        else:
            if value != cond:
                return False
    return True


class FakeCollection:
    def __init__(self, docs=None):
        self._docs = [copy.deepcopy(d) for d in (docs or [])]

    def insert_many(self, docs):
        self._docs.extend(copy.deepcopy(d) for d in docs)

    def insert_one(self, doc):
        self._docs.append(copy.deepcopy(doc))

    def find_one(self, query=None):
        query = query or {}
        for doc in self._docs:
            if _matches(doc, query):
                return copy.deepcopy(doc)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        results = []
        for doc in self._docs:
            if _matches(doc, query):
                if projection:
                    # projection here is always {"_id":0, col:1, ...}; return
                    # only the requested keys (excluding _id).
                    keep = [k for k, v in projection.items() if v == 1]
                    results.append({k: doc.get(k) for k in keep})
                else:
                    results.append(copy.deepcopy(doc))
        return results

    def distinct(self, field, query=None):
        query = query or {}
        seen = []
        for doc in self._docs:
            if _matches(doc, query):
                val = doc.get(field)
                if val not in seen:
                    seen.append(val)
        return seen


class FakeDB:
    def __init__(self, collections=None):
        self._collections = {}
        for name, docs in (collections or {}).items():
            self._collections[name] = FakeCollection(docs)

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = FakeCollection([])
        return self._collections[name]
