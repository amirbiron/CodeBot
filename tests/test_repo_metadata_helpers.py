import types
import datetime as dt


class DummyCollection:
    def __init__(self, docs):
        self._docs = list(docs)

    def aggregate(self, pipeline, allowDiskUse=False):
        rows = list(self._docs)
        for st in pipeline:
            if "$match" in st:
                cond = st["$match"]
                out = []
                for d in rows:
                    ok = True
                    for k, v in cond.items():
                        if k == "tags":
                            if isinstance(v, dict) and "$regex" in v:
                                import re
                                rx = re.compile(v["$regex"])  # lowercase 'repo:' per convention
                                if not any(rx.search(str(t) or "") for t in (d.get("tags") or [])):
                                    ok = False
                                    break
                            else:
                                tags = d.get("tags") or []
                                if isinstance(tags, list):
                                    if v not in tags:
                                        ok = False
                                        break
                                else:
                                    if tags != v:
                                        ok = False
                                        break
                        else:
                            val = d.get(k)
                            if isinstance(val, list):
                                if v not in val:
                                    ok = False
                                    break
                            else:
                                if val != v:
                                    ok = False
                                    break
                    if ok:
                        out.append(d)
                rows = out
            elif "$unwind" in st:
                path = st["$unwind"]["path"].lstrip("$")
                new_rows = []
                for d in rows:
                    for t in d.get(path) or []:
                        nd = dict(d)
                        nd[path] = t
                        new_rows.append(nd)
                rows = new_rows
            elif "$group" in st and st["$group"].get("_id") == {"tag": "$tags", "file_name": "$file_name"}:
                seen = set()
                new_rows = []
                for d in rows:
                    key = (d.get("tags"), d.get("file_name"))
                    if key not in seen:
                        seen.add(key)
                        new_rows.append(d)
                rows = new_rows
            elif "$group" in st and st["$group"].get("_id") == "$file_name":
                # distinct by file_name and output docs with _id=file_name for subsequent project
                seen = set()
                out = []
                for d in rows:
                    fn = d.get("file_name")
                    if fn not in seen:
                        seen.add(fn)
                        out.append({"_id": fn, **{k: v for k, v in d.items() if k != "file_name"}})
                rows = out
            elif "$group" in st and st["$group"].get("_id") == "$_id.tag":
                counts = {}
                for d in rows:
                    _id = d.get("_id")
                    if isinstance(_id, dict) and "tag" in _id:
                        tag = _id.get("tag")
                    else:
                        tag = d.get("tags") if isinstance(d.get("tags"), str) else None
                    counts[tag] = counts.get(tag, 0) + 1
                rows = [{"_id": k, "count": v} for k, v in counts.items()]
            elif "$project" in st:
                proj = st["$project"]
                out = []
                for d in rows:
                    nd = {}
                    for k, v in proj.items():
                        if v in (1, True):
                            nd[k] = d.get(k)
                        elif isinstance(v, str) and v.startswith("$"):
                            path = v[1:]
                            cur = d
                            for part in path.split('.'):
                                if isinstance(cur, dict):
                                    cur = cur.get(part)
                                else:
                                    cur = None
                                    break
                            nd[k] = cur
                    out.append(nd)
                rows = out
            elif "$sort" in st:
                key = list(st["$sort"].keys())[0]
                rows = sorted(rows, key=lambda x: (x.get(key) is None, x.get(key)))
            elif "$limit" in st:
                rows = rows[: st["$limit"]]
        return rows


class DummyManager:
    def __init__(self, docs):
        self.collection = DummyCollection(docs)
        self.db = types.SimpleNamespace()


def _make_repo(docs):
    from database.repository import Repository
    return Repository(DummyManager(docs))


def test_get_repo_tags_with_counts_basic():
    now = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    docs = []
    for i in range(5):
        docs.append({
            "user_id": 1,
            "file_name": f"a{i}.py",
            "version": 1,
            "updated_at": now,
            "is_active": True,
            "tags": ["repo:me/x" if i % 2 == 0 else "repo:me/y"],
        })
    repo = _make_repo(docs)
    rows = repo.get_repo_tags_with_counts(1)
    tags = {r["tag"] for r in rows}
    assert "repo:me/x" in tags and "repo:me/y" in tags
    assert sum(r["count"] for r in rows) == 5


def test_get_user_file_names_by_repo_sorts_and_distinct():
    docs = [
        {"user_id": 2, "file_name": "a.py", "tags": ["repo:me/x"], "is_active": True, "version": 1},
        {"user_id": 2, "file_name": "b.py", "tags": ["repo:me/x"], "is_active": True, "version": 2},
        {"user_id": 2, "file_name": "a.py", "tags": ["repo:me/x"], "is_active": True, "version": 3},
    ]
    repo = _make_repo(docs)
    names = repo.get_user_file_names_by_repo(2, "repo:me/x")
    assert set(names) == {"a.py", "b.py"}
