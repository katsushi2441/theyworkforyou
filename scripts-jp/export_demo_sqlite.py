#!/usr/bin/env python3
"""デモ用に、取り込んだ会議録と議員を SQLite 1ファイルへ書き出す。

なぜ SQLite にするか:
  本体は Docker（PHP + MariaDB + Xapian + memcached + redis）で、当社の公開先である
  heteml の共有レンタルサーバーでは動かない。デモは PHP 1枚で動く必要がある。
  幸い「会議録を日本語で引ける」という肝は SQLite の FTS5 で再現できるので、
  **デモは SQLite + FTS5**、本番の製品は Docker + Xapian、と分ける。

  FTS5 の trigram トークナイザは日本語をそのまま引ける（Xapian の CJK n-gram と同じ考え方）。

  /usr/bin/python3 scripts-jp/export_demo_sqlite.py --out twfy_demo.sqlite
"""
import argparse, html, os, re, sqlite3, subprocess, sys, json


def from_mariadb(sql):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "mariadb",
         "mariadb", "-utwfy", "-ppassword", "twfy", "--batch", "--raw", "-e", sql],
        capture_output=True, text=True, timeout=300,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    lines = [l for l in out.stdout.splitlines() if l and not l.startswith("mariadb:")]
    if not lines:
        sys.exit("MariaDB から取れませんでした: " + out.stderr[:200])
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:]]


def strip_tags(s):
    s = re.sub(r"<[^>]+>", "\n", s or "")
    return re.sub(r"\n{2,}", "\n", html.unescape(s)).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="twfy_demo.sqlite")
    ap.add_argument("--xml", default="data/pwdata/scrapedxml/debates")
    a = ap.parse_args()

    members = from_mariadb(
        "SELECT m.person_id, m.constituency, m.party, n.family_name "
        "FROM member m JOIN person_names n ON n.person_id = m.person_id "
        "WHERE m.constituency <> '' ORDER BY m.constituency;")

    # 発言は DB ではなく、生成した XML から読む。
    # DB 側は person_id が 0 のままで発言者が引けず、会議名も section_id を
    # 辿らないと取れない（2026-09-27 実測）。XML には speakername も
    # major-heading もそのまま入っているので、そちらが確実。
    import glob
    import xml.etree.ElementTree as ET
    rows = []
    root_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), a.xml)
    for path in sorted(glob.glob(os.path.join(root_dir, "*.xml"))):
        root = ET.parse(path).getroot()
        head = root.find("major-heading")
        meeting = (head.text or "").strip() if head is not None else ""
        date = (re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path)) or [None, ""])[1]
        for sp in root.findall("speech"):
            body = "\n".join((p.text or "").strip() for p in sp.findall("p") if (p.text or "").strip())
            if len(body) < 8:
                continue
            rows.append((sp.get("id"), date, sp.get("speakername") or "",
                         sp.get("speakeroffice") or "", meeting, body))

    if os.path.exists(a.out):
        os.remove(a.out)
    c = sqlite3.connect(a.out)
    c.executescript("""
    CREATE TABLE member(person_id INTEGER PRIMARY KEY, name TEXT, senkyoku TEXT, party TEXT);
    CREATE TABLE speech(id INTEGER PRIMARY KEY, gid TEXT, hdate TEXT, speaker TEXT,
                        party TEXT, meeting TEXT, body TEXT);
    -- 日本語の検索は LIKE。FTS5 の trigram は3文字単位で、「沖縄」「子供」のような
    -- 2文字の語が引けない（2026-09-27 実測。本文45件の「沖縄」が0件になった）。
    CREATE INDEX idx_speech_date ON speech(hdate);
    CREATE INDEX idx_speech_speaker ON speech(speaker);
    """)
    seen = set()
    for m in members:
        pid = int(m["person_id"])
        if pid in seen:
            continue
        seen.add(pid)
        c.execute("INSERT INTO member VALUES (?,?,?,?)",
                  (pid, m["family_name"], m["constituency"], m["party"]))
    for i, r in enumerate(rows, 1):
        c.execute("INSERT INTO speech VALUES (?,?,?,?,?,?,?)", (i,) + r)
    c.commit()
    print(f"議員 {len(seen)} / 発言 {len(rows)} → {a.out} "
          f"({os.path.getsize(a.out)/1e6:.1f}MB)")
    for q in ("沖縄", "気候変動", "子供"):
        k = c.execute("SELECT count(*) FROM speech WHERE body LIKE ?", (f"%{q}%",)).fetchone()[0]
        print(f"  {q}: {k}件")
    named = c.execute("SELECT count(*) FROM speech WHERE speaker <> ''").fetchone()[0]
    print(f"  発言者名あり: {named}/{len(rows)}")


if __name__ == "__main__":
    main()
