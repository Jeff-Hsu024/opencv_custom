"""Separate portable family namespace with independent generation CAS."""
import json
import time

from vision_app.coordinator import canonical_json
from vision_app.qualification import reject

class PortableFamilies:
    def __init__(self,definitions):
        self.definitions=definitions
        self.ledger=definitions.ledger

    @staticmethod
    def tables(db):
        db.execute("""CREATE TABLE IF NOT EXISTS portable_family(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, family_id TEXT UNIQUE NOT NULL,
            generation INTEGER NOT NULL, active_revision INTEGER)""")
        db.execute("""CREATE TABLE IF NOT EXISTS portable_revision(
            family_id TEXT NOT NULL REFERENCES portable_family(family_id), revision INTEGER NOT NULL,
            portable_id TEXT NOT NULL, PRIMARY KEY(family_id,revision), UNIQUE(family_id,portable_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS portable_family_log(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, family_id TEXT NOT NULL, generation INTEGER NOT NULL,
            operation TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL,
            UNIQUE(family_id,generation))""")

    @staticmethod
    def _row(db,family):
        return db.execute("SELECT * FROM portable_family WHERE family_id=?",(family,)).fetchone()

    def _view(self,db,family):
        row=self._row(db,family)
        if row is None:
            reject("NOT_FOUND","Portable family not found")
        revisions=db.execute("SELECT revision,portable_id FROM portable_revision WHERE family_id=? ORDER BY revision",(family,)).fetchall()
        return {"family_id":family,"generation":row["generation"],"active_revision":row["active_revision"],
                "revisions":[dict(r) for r in revisions]}

    @staticmethod
    def _cas(row,expected):
        if expected!=(row["generation"] if row is not None else 0):
            reject("STALE_GENERATION","Family generation changed")

    @staticmethod
    def _log(db,family,generation,operation,payload):
        db.execute("INSERT INTO portable_family_log(family_id,generation,operation,payload,created_at) VALUES (?,?,?,?,?)",
                   (family,generation,operation,canonical_json(payload),time.time()))

    def publish(self,family_id,portable_id,expected_generation,reason):
        if not reason.strip():
            reject("INVALID_ARGUMENT","Publication reason required")
        with self.definitions.pinned(portable_id) as (_,_,source_recheck):
            with self.ledger.transaction() as db:
                self.tables(db)
                row=self._row(db,family_id)
                self._cas(row,expected_generation)
                if db.execute("SELECT 1 FROM portable_revision WHERE family_id=? AND portable_id=?",
                              (family_id,portable_id)).fetchone():
                    reject("INVALID_ARGUMENT","Portable definition already registered in family")
                source_recheck()
                if row is None:
                    db.execute("INSERT INTO portable_family(family_id,generation,active_revision) VALUES (?,0,NULL)",(family_id,))
                revision=db.execute("SELECT coalesce(max(revision),0)+1 FROM portable_revision WHERE family_id=?",(family_id,)).fetchone()[0]
                db.execute("INSERT INTO portable_revision VALUES (?,?,?)",(family_id,revision,portable_id))
                generation=expected_generation+1
                db.execute("UPDATE portable_family SET generation=? WHERE family_id=?",(generation,family_id))
                self._log(db,family_id,generation,"publish",{"portable_id":portable_id,"revision":revision,"reason":reason})
                return self._view(db,family_id)

    def activate(self,family_id,revision,expected_generation,reason):
        from contextlib import nullcontext
        if not reason.strip():
            reject("INVALID_ARGUMENT","Activation reason required")
        with self.ledger.transaction() as db:
            self.tables(db)
            view=self._view(db,family_id)
            self._cas(view,expected_generation)
            selected=next((r for r in view["revisions"] if r["revision"]==revision),None)
            if revision is not None and selected is None:
                reject("NOT_FOUND","Portable revision not found")
        source=self.definitions.pinned(selected["portable_id"]) if selected is not None else nullcontext((None,None,lambda:None))
        with source as (_,_,recheck):
            with self.ledger.transaction() as db:
                row=self._row(db,family_id)
                self._cas(row,expected_generation)
                recheck()
                generation=expected_generation+1
                db.execute("UPDATE portable_family SET generation=?,active_revision=? WHERE family_id=?",
                           (generation,revision,family_id))
                self._log(db,family_id,generation,"activate" if revision is not None else "disable",
                          {"revision":revision,"reason":reason})
                return self._view(db,family_id)

    def inspect(self,family_id):
        with self.ledger.transaction() as db:
            self.tables(db)
            return self._view(db,family_id)

    def list(self,limit=20,after=0):
        with self.ledger.transaction() as db:
            self.tables(db)
            rows=db.execute("SELECT * FROM portable_family WHERE seq>? ORDER BY seq LIMIT ?",(after,limit+1)).fetchall()
            return {"items":[{"family_id":r["family_id"],"generation":r["generation"],
                              "active_revision":r["active_revision"],"revision_count":db.execute(
                                  "SELECT count(*) FROM portable_revision WHERE family_id=?",(r["family_id"],)).fetchone()[0]}
                             for r in rows[:limit]],"next_cursor":rows[limit-1]["seq"] if len(rows)>limit else None}

    def active(self,family,expected_generation):
        with self.ledger.transaction() as db:
            self.tables(db)
            row=self._row(db,family)
            if row is None:
                reject("NOT_FOUND","Portable family not found")
            self._cas(row,expected_generation)
            revision=row["active_revision"]
            if revision is None:
                reject("FAMILY_INACTIVE","Portable family is inactive")
            pid=db.execute("SELECT portable_id FROM portable_revision WHERE family_id=? AND revision=?",(family,revision)).fetchone()[0]
            return {"family_id":family,"generation":row["generation"],"revision":revision,"portable_id":pid}

    def recheck(self,db,pin):
        row=self._row(db,pin["family_id"])
        if row is None or (row["generation"],row["active_revision"])!=(pin["generation"],pin["revision"]):
            reject("STALE_GENERATION","Family changed before admission")
        selected=db.execute("SELECT portable_id FROM portable_revision WHERE family_id=? AND revision=?",
                            (pin["family_id"],pin["revision"])).fetchone()
        if selected is None or selected["portable_id"]!=pin["portable_id"]:
            reject("STALE_GENERATION","Family revision changed before admission")
