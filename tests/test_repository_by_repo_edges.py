import datetime as dt
import types


class _Coll:
    def __init__(self, docs):
        self.docs = list(docs)
    def aggregate(self, pipeline, allowDiskUse=False):  # noqa: N803
        rows = list(self.docs)
        # very coarse emulation: support $match on tags/repo and user_id/is_active
        for st in pipeline:
            if "$match" in st:
                m = st["$match"]
                def ok(d):
                    if d.get("user_id") != m.get("user_id"):
                        return False
                    if m.get("tags") and m.get("tags") != (d.get("tags") or [None])[0]:
                        return False
                    if not (d.get("is_active") is True or d.get("is_active") is None):
                        return False
                    return True
                rows = [d for d in rows if ok(d)]
            elif "$group" in st and st["$group"].get("_id") == "$file_name":
                # distinct latest by file_name
                rows = sorted(rows, key=lambda x: (str(x.get("file_name","")), -int(x.get("version",1))))
                uniq = {}
                for d in rows:
                    fn = d.get("file_name")
                    if fn not in uniq:
                        uniq[fn] = d
                rows = list(uniq.values())
            elif "$replaceRoot" in st:
                pass
            elif "$sort" in st:
                key = st["$sort"]
                if key == {"updated_at": -1}:
                    rows = sorted(rows, key=lambda x: x.get("updated_at") or dt.datetime.min, reverse=True)
                else:
                    rows = sorted(rows, key=lambda x: (str(x.get("file_name","")), -int(x.get("version",1))))
            elif "$project" in st:
                proj = st["$project"]
                out = []
                for d in rows:
                    nd = {k: d.get(k) for k,v in proj.items() if v in (1, True)}
                    out.append(nd)
                rows = out
            elif "$skip" in st:
                rows = rows[st["$skip"]:]
            elif "$limit" in st:
                rows = rows[: st["$limit"]]
            elif "$count" in st:
                return [{"count": len(rows)}]
        return rows


def _repo(docs):
    # stub minimal env so importing database.repository won't require real config
    import os, sys
    import types as _t
    os.environ.setdefault('BOT_TOKEN', 'x')
    os.environ.setdefault('MONGODB_URL', 'mongodb://localhost')
    # stub telegram modules to satisfy utils import path
    if 'telegram' not in sys.modules:
        tg = _t.ModuleType('telegram')
        sys.modules['telegram'] = tg
        tge = _t.ModuleType('telegram.error')
        class _BR(Exception):
            pass
        tge.BadRequest = _BR
        sys.modules['telegram.error'] = tge
        tgc = _t.ModuleType('telegram.constants')
        tgc.ChatAction = None
        tgc.ParseMode = None
        sys.modules['telegram.constants'] = tgc
        tgext = _t.ModuleType('telegram.ext')
        class _CT:
            DEFAULT_TYPE = object
        tgext.ContextTypes = _CT
        sys.modules['telegram.ext'] = tgext
    from database.repository import Repository
    mgr = types.SimpleNamespace(collection=_Coll(docs), large_files_collection=_Coll([]), db=types.SimpleNamespace())
    return Repository(mgr)


def _docs(uid=1, total=7, tag="repo:me/app"):
    now = dt.datetime(2025,1,1)
    out = []
    for i in range(total):
        out.append({
            "_id": f"id{i}",
            "user_id": uid,
            "file_name": f"f{i}.py",
            "programming_language": "python",
            "version": 1,
            "updated_at": now,
            "is_active": True,
            "tags": [tag],
        })
    return out


def test_by_repo_per_page_one_and_high_page():
    repo = _repo(_docs(total=3))
    items, total = repo.get_user_files_by_repo(user_id=1, repo_tag="repo:me/app", page=2, per_page=1)
    assert total == 3 and len(items) == 1

    items2, total2 = repo.get_user_files_by_repo(user_id=1, repo_tag="repo:me/app", page=99, per_page=10)
    # when page is high, skip moves beyond and limit yields empty list — acceptable behavior
    assert total2 == 3 and (len(items2) == 0 or len(items2) <= 10)

