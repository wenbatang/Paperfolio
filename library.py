"""Local catalogue with portable library paths and optional external attachment storage."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pymupdf as pdf


def timestamp():
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Edit:
    label: str
    table: str
    before: dict | None
    after: dict | None


@dataclass
class PaperEdit:
    label: str
    field: str
    previous: dict[int, int | None]
    value: int | None


class Library:
    def __init__(self, root):
        self.undo_stack = deque(maxlen=100)
        self.redo_stack = deque(maxlen=100)
        self.on_history_change = None
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "library.sqlite3", timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS collections(
                id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL);
            CREATE TABLE IF NOT EXISTS papers(
                id INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
                author TEXT DEFAULT '', year TEXT DEFAULT '', doi TEXT DEFAULT '',
                tags TEXT DEFAULT '', collection INTEGER REFERENCES collections,
                favorite INTEGER DEFAULT 0, trashed INTEGER DEFAULT 0, added TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS files(
                id INTEGER PRIMARY KEY, paper INTEGER NOT NULL REFERENCES papers,
                label TEXT NOT NULL, path TEXT UNIQUE NOT NULL, pages INTEGER NOT NULL,
                position INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS notes(
                id INTEGER PRIMARY KEY, file INTEGER NOT NULL REFERENCES files,
                page INTEGER NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS highlights(
                id INTEGER PRIMARY KEY, file INTEGER NOT NULL REFERENCES files,
                page INTEGER NOT NULL, quote TEXT NOT NULL, color TEXT NOT NULL, rects TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS highlights_file_page ON highlights(file,page);
            CREATE TABLE IF NOT EXISTS bookmarks(
                id INTEGER PRIMARY KEY, file INTEGER NOT NULL REFERENCES files,
                page INTEGER NOT NULL, UNIQUE(file,page));
            CREATE TABLE IF NOT EXISTS guides(
                paper INTEGER PRIMARY KEY REFERENCES papers, model TEXT NOT NULL,
                created TEXT NOT NULL, body TEXT NOT NULL);
        """)

    def preference(self, key, default=""):
        row = self.db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def save_preferences(self, values):
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO preferences VALUES(?,?)", values.items())

    @property
    def storage(self):
        return Path(self.preference("storage") or self.root)

    @property
    def export_dir(self):
        path = Path(self.preference("export") or Path.home() / "Downloads")
        return str(path if path.is_dir() else Path.home())

    def import_pdf(self, source, collection=None):
        source = Path(source)
        storage = self.storage
        storage.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=storage, suffix=".pdf", delete=False) as f:
            staged = Path(f.name)
        dest = None
        try:
            digest = hashlib.sha256()
            with source.open("rb") as src, staged.open("wb") as out:
                while chunk := src.read(1024 * 1024):
                    digest.update(chunk)
                    out.write(chunk)
            with pdf.open(staged) as doc:
                if not doc.is_pdf or doc.needs_pass or not len(doc):
                    raise ValueError("请导入可直接打开、至少有一页的 PDF")
                meta, count = doc.metadata or {}, len(doc)
                first_page = doc[0].get_text()
            title = (meta.get("title") or "").strip() or source.stem
            date = re.search(r"(?:19|20)\d{2}", meta.get("creationDate") or "")
            doi = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", first_page, re.I)
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                old = self.db.execute(
                    "SELECT id FROM papers WHERE digest=?", (digest.hexdigest(),)
                ).fetchone()
                if old:
                    original = self.original_record(old[0])
                    if original:
                        target = self.root / original["path"]
                        if not target.exists():
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                                repair = Path(output.name)
                            try:
                                shutil.copyfile(staged, repair)
                                os.replace(repair, target)
                            finally:
                                repair.unlink(missing_ok=True)
                    self.db.execute("UPDATE papers SET trashed=0 WHERE id=?", (old[0],))
                    return old[0], False
                pid = self.db.execute(
                    """INSERT INTO papers
                    (digest,title,author,year,doi,collection,added) VALUES(?,?,?,?,?,?,?)""",
                    (
                        digest.hexdigest(),
                        title,
                        meta.get("author") or "",
                        date[0] if date else "",
                        doi[0].rstrip(".)") if doi else "",
                        collection,
                        timestamp(),
                    ),
                ).lastrowid
                dest = storage / "attachments" / uuid.uuid4().hex / "original.pdf"
                dest.parent.mkdir(parents=True)
                os.replace(staged, dest)
                self.add_file(pid, "原文", dest, count)
            return pid, True
        except Exception:
            if dest and dest.exists():
                dest.unlink()
            raise
        finally:
            staged.unlink(missing_ok=True)

    def add_file(self, pid, label, path, pages):
        return self.db.execute(
            "INSERT INTO files(paper,label,path,pages) VALUES(?,?,?,?)",
            (pid, label, str(path.relative_to(self.root) if path.is_relative_to(self.root) else path), pages),
        ).lastrowid

    def papers(self, view="all", query=""):
        sql = "SELECT * FROM papers WHERE trashed=?"
        args = [int(view == "trash")]
        if view == "star":
            sql += " AND favorite=1"
        elif view == "unfiled":
            sql += " AND collection IS NULL"
        elif isinstance(view, int):
            sql += " AND collection=?"
            args.append(view)
        rows = self.db.execute(sql + " ORDER BY added DESC, id DESC", args)
        words = query.casefold().split()
        return [
            r
            for r in rows
            if all(
                w in " ".join(r[k] for k in ("title", "author", "year", "tags", "doi")).casefold()
                for w in words
            )
        ]

    def files(self, pid):
        rows = self.db.execute("SELECT * FROM files WHERE paper=? ORDER BY id", (pid,))
        return [row for row in rows if self.has_file(row)]

    def original_record(self, pid):
        return self.db.execute(
            "SELECT * FROM files WHERE paper=? AND label='原文' ORDER BY id LIMIT 1", (pid,)
        ).fetchone()

    def has_file(self, row):
        return row is not None and (self.root / row["path"]).is_file()

    def publish(self, pid, folder, description):
        outputs = []
        for kind, label in (("mono", "译文"), ("dual", "双语")):
            matches = [p for p in folder.rglob("*.pdf") if re.search(rf"[.\-_]{kind}\.pdf$", p.name, re.I)]
            if len(matches) != 1:
                raise ValueError(f"翻译引擎未生成唯一的{label} PDF")
            with pdf.open(matches[0]) as doc:
                if not len(doc):
                    raise ValueError(f"{label} PDF 没有页面")
                outputs.append((label, matches[0], len(doc)))
        dest = self.storage / "translations" / uuid.uuid4().hex
        dest.mkdir(parents=True)
        try:
            with self.db:
                for label, src, pages in outputs:
                    target = dest / src.name
                    shutil.copyfile(src, target)
                    fid = self.add_file(pid, f"{label} · {description}", target, pages)
            return fid  # The bilingual edition is published last.
        except Exception:
            shutil.rmtree(dest)
            raise

    def notes(self, pid):
        return self.db.execute(
            """SELECT n.*, f.label FROM notes n JOIN files f ON n.file=f.id
            WHERE f.paper=? ORDER BY n.id DESC""",
            (pid,),
        ).fetchall()

    def save_note(self, fid, page, body):
        if body.strip():
            self.record("添加笔记", "notes", None, dict(file=fid, page=page, body=body.strip(), created=timestamp()))

    def delete_note(self, nid):
        note = self.db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
        if note:
            self.record("删除笔记", "notes", note, None)

    def record(self, label, table, before, after):
        edit = Edit(label, table, dict(before) if before else None, dict(after) if after else None)
        self.apply_edit(table, edit.before, edit.after)
        self.remember(edit)

    def remember(self, edit):
        self.undo_stack.append(edit)
        self.redo_stack.clear()
        if self.on_history_change:
            self.on_history_change()

    def change_papers(self, ids, field, value, label, *, new_collection=None):
        if field not in ("collection", "favorite", "trashed"):
            raise ValueError("不支持的批量操作")
        ids = tuple(dict.fromkeys(ids))
        if not ids:
            return 0
        previous = {}
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if new_collection is not None:
                self.db.execute("INSERT INTO collections(name) VALUES(?) ON CONFLICT(name) DO NOTHING",
                                (new_collection,))
                value = self.db.execute("SELECT id FROM collections WHERE name=?", (new_collection,)).fetchone()[0]
            for pid in ids:
                row = self.db.execute(f"SELECT {field} FROM papers WHERE id=?", (pid,)).fetchone()
                if row is None:
                    raise ValueError("所选文献已发生变化，请重新选择。")
                if row[0] != value:
                    previous[pid] = row[0]
            self.db.executemany(f"UPDATE papers SET {field}=? WHERE id=?",
                                ((value, pid) for pid in previous))
        if previous:
            self.remember(PaperEdit(label, field, previous, value))
        return len(previous)

    def replay_papers(self, edit, redo):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for pid, previous in edit.previous.items():
                expected, target = (previous, edit.value) if redo else (edit.value, previous)
                changed = self.db.execute(
                    f"UPDATE papers SET {edit.field}=? WHERE id=? AND {edit.field} IS ?",
                    (target, pid, expected),
                )
                if not changed.rowcount:
                    raise ValueError("部分文献已在其他位置更改，本次操作已取消。")

    def apply_edit(self, table, old, new):
        if table not in ("notes", "highlights", "bookmarks"):
            raise ValueError("未知记录类型")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if old:
                row = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (old["id"],)).fetchone()
                if not row or dict(row) != old:
                    raise ValueError("这条记录已在其他窗口中更改，请刷新后重试。")
            if new is None:
                self.db.execute(f"DELETE FROM {table} WHERE id=?", (old["id"],))
            elif old is None:
                fields = ", ".join(new)
                slots = ", ".join("?" for _ in new)
                cur = self.db.execute(f"INSERT INTO {table} ({fields}) VALUES ({slots})", tuple(new.values()))
                new["id"] = cur.lastrowid
            else:
                fields = [k for k in new if k != "id"]
                assignments = ", ".join(f"{k}=?" for k in fields)
                self.db.execute(f"UPDATE {table} SET {assignments} WHERE id=?",
                                [new[k] for k in fields] + [old["id"]])

    def history_step(self, redo=False):
        source, dest = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not source:
            return None
        edit = source[-1]
        if isinstance(edit, PaperEdit):
            self.replay_papers(edit, redo)
        else:
            old, new = (edit.before, edit.after) if redo else (edit.after, edit.before)
            self.apply_edit(edit.table, old, new)
        dest.append(source.pop())
        if self.on_history_change:
            self.on_history_change()
        return edit

    def highlights(self, fid, page=None):
        if page is None:
            return self.db.execute(
                "SELECT * FROM highlights WHERE file=? ORDER BY page,id", (fid,)
            ).fetchall()
        return self.db.execute(
            "SELECT * FROM highlights WHERE file=? AND page=? ORDER BY id", (fid, page)
        ).fetchall()

    def export_highlights(self, file, target):
        target = Path(target).resolve()
        if any(target == (self.root / row[0]).resolve() for row in self.db.execute("SELECT path FROM files")):
            raise ValueError("请选择新的导出位置，文献库附件正在使用。")
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".pdf", delete=False) as temp:
            staged = Path(temp.name)
        try:
            with pdf.open(self.root / file["path"]) as doc:
                for mark in self.highlights(file["id"]):
                    page = doc[mark["page"] - 1]
                    quads = [pdf.Rect(box).quad for box in json.loads(mark["rects"])]
                    annot = page.add_highlight_annot(quads)
                    color = bytes.fromhex(mark["color"][1:])
                    annot.set_colors(stroke=tuple(c / 255 for c in color))
                    annot.set_info(content=mark["quote"])
                    annot.update()
                doc.save(staged)
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)

    def bibtex(self, paper):
        def escape(s):
            return re.sub(r"[{}\\]", lambda m: {"{": r"\{", "}": r"\}", "\\": r"\textbackslash{}"}[m[0]], s)

        fields = [
            "  " + k + " = {" + escape(paper[k]) + "}"
            for k in ("title", "author", "year", "doi")
            if paper[k]
        ]
        return "@misc{paper" + str(paper["id"]) + ",\n" + ",\n".join(fields) + "\n}\n"
