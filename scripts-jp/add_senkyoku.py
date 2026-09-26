#!/usr/bin/env python3
"""小選挙区289と現職議員を people.json に足し、住所→選挙区の索引を作る。

なぜ要るか（2026-09-27）:
  TheyWorkForYou の入口は「郵便番号を入れて自分の議員を見る」。英国の postcode から
  constituency を引く仕組みが骨格に入っていて、`MP` は147ファイル、`constituency` は
  42ファイルに現れる。翻訳では埋まらないので、日本の制度を当てる必要がある。

  日本には「郵便番号→小選挙区」の公式な対応が無い（1つの郵便番号が複数区にまたがる）。
  一方、**市区町村→小選挙区**なら確定する。だから入口を「住所（市区町村）」にする。
  その対応表は当社が giin で持っている（senkyoku 289件・munis_json に市区町村）。

出力:
  - data/parlparse/members/people.json に posts（選挙区）と現職の所属を追記
  - data/jp/muni2senkyoku.json（市区町村名 → 選挙区キー）。住所検索の索引に使う

  /usr/bin/python3 scripts-jp/add_senkyoku.py
"""
import argparse, json, os, re, sqlite3, sys

GIIN_DB = os.environ.get("GIIN_DB", "data/giin.sqlite")  # 議員・選挙区のDB。場所は環境変数で渡す
HOUSE = "house-of-representatives"   # 小選挙区は衆議院


def norm_name(s):
    """会議録の表記に寄せる。氏名の間の全角空白は落として比べられるようにする。"""
    return re.sub(r"[\s　]+", "", str(s or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--people", default="data/parlparse/members/people.json")
    ap.add_argument("--muni-out", default="data/jp/muni2senkyoku.json")
    a = ap.parse_args()

    if not os.path.exists(GIIN_DB):
        sys.exit(f"giin のDBが見つかりません: {GIIN_DB}")
    con = sqlite3.connect(GIIN_DB)
    con.row_factory = sqlite3.Row
    sens = list(con.execute("SELECT key,pref,no,name,area,voters,munis_json FROM senkyoku ORDER BY key"))
    mems = {r["key"]: r for r in con.execute("SELECT key,display,kana,kaiha,wins,profile FROM senkyoku_member")}

    data = json.load(open(a.people, encoding="utf-8")) if os.path.exists(a.people) else \
        {"persons": [], "memberships": [], "posts": [], "organizations": []}
    by_name = {}
    for p in data["persons"]:
        for idf in p.get("identifiers", []):
            if idf.get("scheme") == "kokkai_speaker_name":
                by_name[norm_name(idf["identifier"])] = p["id"]

    orgs = {o["id"]: o for o in data["organizations"]}
    orgs.setdefault(HOUSE, {"classification": "legislature", "id": HOUSE, "name": "衆議院"})

    posts, muni = [], {}
    next_person = len(data["persons"]) + 1
    added_person = matched = 0

    for s in sens:
        key = s["key"]
        post_id = f"jp.go.ndl.kokkai/cons/{key}"
        posts.append({
            "id": post_id,
            "area": {"name": s["name"]},
            "label": f"{s['name']}選出 衆議院議員",
            "organization_id": HOUSE,
            "role": "Member",
            "start_date": "2024-10-28",   # 第50回総選挙の投票日
            "identifiers": [{"identifier": key, "scheme": "giin_senkyoku_key"}],
        })
        for m in json.loads(s["munis_json"] or "[]"):
            nm = m.get("name")
            if nm:
                muni.setdefault(nm, []).append({"key": key, "name": s["name"],
                                                "partial": bool(m.get("partial"))})

        mem = mems.get(key)
        if not mem:
            continue
        name = norm_name(mem["display"])
        pid = by_name.get(name)
        if pid:
            matched += 1
        else:
            pid = str(900000 + next_person)
            next_person += 1
            added_person += 1
            data["persons"].append({
                "id": pid,
                "identifiers": [{"identifier": mem["display"], "scheme": "kokkai_speaker_name"},
                                {"identifier": key, "scheme": "giin_senkyoku_key"}],
                "other_names": [{"family_name": mem["display"], "given_name": "", "note": "Main"}],
            })
            by_name[name] = pid

        oid = None
        if mem["kaiha"]:
            oid = "party/" + re.sub(r"[^\w぀-ヿ一-鿿]+", "-", mem["kaiha"]).strip("-")
            orgs.setdefault(oid, {"classification": "party", "id": oid, "name": mem["kaiha"]})
        ms = {"id": str(950000 + len(data["memberships"]) + 1),
              "person_id": pid, "organization_id": HOUSE, "post_id": post_id,
              "start_date": "2024-10-28", "end_date": "9999-12-31"}
        if oid:
            ms["on_behalf_of_id"] = oid
        data["memberships"].append(ms)

    data["posts"] = posts
    data["organizations"] = list(orgs.values())
    json.dump(data, open(a.people, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    os.makedirs(os.path.dirname(a.muni_out), exist_ok=True)
    json.dump(muni, open(a.muni_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    multi = sum(1 for v in muni.values() if len(v) > 1)
    print(f"選挙区 {len(posts)} / 議員 {len(mems)}（会議録と名前が一致 {matched} ／ 新規 {added_person}）")
    print(f"市区町村 {len(muni)} 件 → {a.muni_out}（複数区にまたがる市区町村 {multi} 件）")
    print(f"people.json: 人 {len(data['persons'])} / 所属 {len(data['memberships'])} / 組織 {len(data['organizations'])}")


if __name__ == "__main__":
    main()
