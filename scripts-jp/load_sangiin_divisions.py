#!/usr/bin/env python3
"""参議院の本会議投票（sangiin_votes.py の出力）を TheyWorkForYou の divisions /
persondivisionvotes に入れる SQL を出す。先に add_sangiin_members.py と load-people を済ませること。

    /usr/bin/python3 scripts-jp/load_sangiin_divisions.py --votes-db twfy_demo.sqlite \
        --people data/parlparse/members/people.json > /tmp/sangiin_divisions.sql
    docker compose exec -T mariadb mariadb -utwfy -ppassword twfy < /tmp/sangiin_divisions.sql

- 院は house='lords'（本キットは参議院を英国の上院 HOUSE_TYPE_LORDS=2 に当てている）
- 賛成→aye / 反対→no / 投票なし→absent
- division_id は本体と同じ「pw-<日付>-<番号>-lords」。本体の URL 書き換えは pw- / pbc- で始まる ID しか
  /divisions/<ID> に通さない（conf/httpd.conf）。独自の接頭辞にすると投票ページが 404 になった（2026-09-27）
- 何度流しても同じ結果になるよう、参議院（house='lords'）の分を消してから入れる。英国のデータと同じDBに混ぜない前提
"""
import argparse, json, re, sqlite3, sys

ap = argparse.ArgumentParser()
ap.add_argument("--votes-db", required=True)
ap.add_argument("--people", default="data/parlparse/members/people.json")
a = ap.parse_args()


def q(s):
    return "'" + str(s).replace("\\", "\\\\").replace("'", "''") + "'"


people = json.load(open(a.people, encoding="utf-8"))
pid = {}
for p in people["persons"]:
    for i in p.get("identifiers", []):
        if i.get("scheme") == "kokkai_speaker_name":
            pid[re.sub(r"[\s　]+", "", i["identifier"])] = int(p["id"])

db = sqlite3.connect(a.votes_db)
votes = db.execute("SELECT id, date, title, total, yes, no FROM vote ORDER BY date, id").fetchall()
out = ["SET NAMES utf8mb4;", "START TRANSACTION;",
       "DELETE FROM persondivisionvotes WHERE division_id IN (SELECT division_id FROM divisions WHERE house='lords');",
       "DELETE FROM divisions WHERE house='lords';"]
CH = {"賛成": "aye", "反対": "no", "欠": "absent"}
missing = set(); n_votes = 0
for vid, date, title, total, yes, no in votes:
    num = int(vid.rsplit("-v", 1)[1])
    did = f"pw-{date}-{num}-lords"
    members = db.execute("SELECT name_key, choice FROM vote_member WHERE vote_id=?", (vid,)).fetchall()
    absent = sum(1 for _, c in members if c == "欠")
    out.append("INSERT INTO divisions (division_id, house, gid, division_title, division_date, division_number,"
               " yes_total, no_total, absent_total, both_total, majority_vote) VALUES ("
               f"{q(did)}, 'lords', '', {q(title)}, {q(date)}, {num}, {yes}, {no}, {absent}, 0, "
               f"{q('aye' if yes > no else 'no')});")
    vals = []
    for key, choice in members:
        if key not in pid:
            missing.add(key); continue
        vals.append(f"({pid[key]}, {q(did)}, {q(CH[choice])})")
    n_votes += len(vals)
    out.append("INSERT INTO persondivisionvotes (person_id, division_id, vote) VALUES " + ",".join(vals) + ";")
out.append("COMMIT;")
print("\n".join(out))
print(f"採決 {len(votes)} 件 / 議員別の票 {n_votes} 行 / people.json に居ない議員 {len(missing)} 人",
      file=sys.stderr)
if missing:
    print("  先に add_sangiin_members.py を流すこと: " + "、".join(sorted(missing)[:10]), file=sys.stderr)
    sys.exit(1)
