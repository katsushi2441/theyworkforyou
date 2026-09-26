#!/usr/bin/env python3
"""参議院の本会議投票に出てくる議員を people.json に足す（投票を本体の画面に出すため）。

TheyWorkForYou は賛否を「その日に参議院の議員だった人」に結びつけて表示する
（Divisions.php が member の entered_house〜left_house で絞る）。会議録の発言者から作った
所属（make_people_json.py）は発言した日の範囲しか持たないので、投票した日と重ならない。

- 氏名（空白を除いたもの）が発言者と同じなら、その人を使う。無ければ新しく作る
- その人の参議院の所属は、発言から作った短いものを捨てて **1本にまとめる**
  （重なった所属が2本あると、投票一覧に同じ人が2回出る）
- 会派は投票結果ページのもの（最新の日付）

    /usr/bin/python3 scripts-jp/add_sangiin_members.py --votes-db twfy_demo.sqlite \
        --people data/parlparse/members/people.json
"""
import argparse, json, re, sqlite3

HOUSE = "house-of-councillors"

ap = argparse.ArgumentParser()
ap.add_argument("--votes-db", required=True, help="sangiin_votes.py の出力（vote / vote_member）")
ap.add_argument("--people", default="data/parlparse/members/people.json")
a = ap.parse_args()

db = sqlite3.connect(a.votes_db)
rows = db.execute("""SELECT m.name_key, m.name, m.kaiha, MIN(v.date), MAX(v.date)
                     FROM vote_member m JOIN vote v ON v.id = m.vote_id
                     GROUP BY m.name_key""").fetchall()
latest = {k: g for k, g in db.execute("""SELECT m.name_key, m.kaiha FROM vote_member m JOIN vote v ON v.id = m.vote_id
                                          ORDER BY v.date, v.id""")}   # 後の行が勝つ＝最新の会派

d = json.load(open(a.people, encoding="utf-8"))
by_name = {}
for p in d["persons"]:
    for i in p.get("identifiers", []):
        if i.get("scheme") == "kokkai_speaker_name":
            by_name[re.sub(r"[\s　]+", "", i["identifier"])] = p["id"]
orgs = {o["id"] for o in d["organizations"]}
next_pid = max(int(p["id"]) for p in d["persons"]) + 1
next_mid = max(int(m["id"]) for m in d["memberships"]) + 1

added_p = reused = 0
sangiin = set()
for key, name, _, first, last in rows:
    pid = by_name.get(key)
    if pid:
        reused += 1
    else:
        pid = str(next_pid); next_pid += 1; added_p += 1
        family, _, given = name.partition(" ")
        d["persons"].append({"id": pid,
                             "identifiers": [{"identifier": key, "scheme": "kokkai_speaker_name"},
                                             {"identifier": name, "scheme": "sangiin_vote_name"}],
                             "other_names": [{"family_name": key, "given_name": "", "note": "Main"}]})
        by_name[key] = pid
    sangiin.add(pid)
    kaiha = latest.get(key, "")
    oid = "party/" + re.sub(r"[^\w぀-ヿ一-鿿]+", "-", kaiha).strip("-") if kaiha else None
    if oid and oid not in orgs:
        d["organizations"].append({"classification": "party", "id": oid, "name": kaiha}); orgs.add(oid)
    m = {"id": str(next_mid), "person_id": pid, "organization_id": HOUSE,
         # 開始は第221回国会の召集日。これより前の投票は取り込んでいない
         "start_date": "2026-02-18", "end_date": "9999-12-31"}
    next_mid += 1
    if oid:
        m["on_behalf_of_id"] = oid
    d["memberships"].append(("new", m))

before = len(d["memberships"])
dropped = [m for m in d["memberships"] if not isinstance(m, tuple)
           and m["person_id"] in sangiin and m["organization_id"] == HOUSE]
d["memberships"] = [m[1] if isinstance(m, tuple) else m for m in d["memberships"]
                    if isinstance(m, tuple) or not (m["person_id"] in sangiin and m["organization_id"] == HOUSE)]
json.dump(d, open(a.people, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"参議院議員 {len(rows)}人（既存の発言者と一致 {reused}・新規 {added_p}）"
      f" / 発言から作った短い参議院所属を {len(dropped)} 本まとめた → {a.people}")
