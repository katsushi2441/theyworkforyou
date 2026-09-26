#!/usr/bin/env python3
"""住所・郵便番号 → 小選挙区 の索引を作る。

入力:
  - 小選挙区の区域（giin の senkyoku テーブル。munis_json に市区町村と政令市の区）
  - 日本郵便の郵便番号データ utf_ken_all.csv（https://www.post.japanpost.jp/zipcode/dl/utf-zip.html）
出力:
  - --area-json : {県: {市区町村: {"d": [選挙区key], "w": {区: [選挙区key]}}}}
  - --sqlite    : postal(zip, pref, muni, ward) を追加（デモの SQLite に足す）

**市区町村名だけで引かない。** 「池田町」「森町」「伊達市」など同名の市町村が県をまたいで26組あり、
名前だけで数えると「複数の選挙区にまたがる市区町村」が 105 と出る（実際は県込みで 47）。
2026-09-27 に一度この誤った数字を公開してしまった。必ず (県, 市区町村) で持つ。

**政令市は区まで持つ。** 名古屋市を市単位で引くと愛知1〜5区が全部出るが、区で引けば1つに決まる。
区そのものが2つの選挙区にまたがるのは全国で7区だけ（札幌市西区・北区・白石区、浜松市中央区、
福岡市東区・南区・城南区）。そこは候補を並べて選んでもらう。

    # 本体（/jusho/ が読む）
    GIIN_DB=/path/to/giin.sqlite python3 scripts-jp/build_area_index.py \
        --ken-all data/jp/utf_ken_all.csv --area-json data/jp/area.json --postal-dir data/jp/postal
    # PHP1枚のデモ（SQLite）
    GIIN_DB=/path/to/giin.sqlite python3 scripts-jp/build_area_index.py \
        --ken-all data/jp/utf_ken_all.csv --area-json twfy_area.json --sqlite twfy_demo.sqlite
"""
import argparse, collections, csv, json, os, re, sqlite3, sys

ap = argparse.ArgumentParser()
ap.add_argument("--giin-db", default=os.environ.get("GIIN_DB", "data/giin.sqlite"))
ap.add_argument("--ken-all", required=True)
ap.add_argument("--area-json", required=True)
ap.add_argument("--sqlite", help="デモ用: postal テーブルを足す SQLite")
ap.add_argument("--postal-dir", help="本体用: 郵便番号の上3桁ごとの JSON（data/jp/postal/NNN.json）を出す")
a = ap.parse_args()

def norm(s):
    """表記ゆれを寄せる。郵便番号データは「龍ケ崎市」「須惠町」、区域データは「龍ヶ崎市」「須恵町」。"""
    s = re.sub(r"(?<=[一-龥])[ケヶ](?=[一-龥])", "ヶ", s)
    return s.replace("惠", "恵")


def repair(area_text, munis):
    """区域データの「郡を含む市」の欠落を直す。

    giin の区域データは「郡」で町村を展開するとき、蒲郡市・小郡市を「市」、大和郡山市を「山市」に
    切ってしまっている（2026-09-27 に確認。giin 側は未修正）。区域の文から「◯郡◯市」を拾い直す。
    """
    for t in area_text.split("、"):
        name = re.sub(r"（.*?）", "", t).strip()
        if "郡" in name and name.endswith("市"):
            munis = [m for m in munis if not (m["name"] != name and name.endswith(m["name"]))]
            if not any(m["name"] == name for m in munis):
                munis.append({"name": name, "wards": None, "partial": "（" in t})
    return munis


area = collections.defaultdict(dict)
names = {}   # 選挙区key → 表示名（aichi-1 → 愛知1区）。画面と議員表はこの表示名で持っている
for key, pref, area_text, mj, sname in sqlite3.connect(a.giin_db).execute(
        "SELECT key, pref, area, munis_json, name FROM senkyoku"):
    names[key] = sname
    for m in repair(area_text, json.loads(mj)):
        m = dict(m, name=norm(m["name"]))
        e = area[pref].setdefault(m["name"], {"d": [], "w": {}})
        if key not in e["d"]:
            e["d"].append(key)
        for w in m.get("wards") or []:
            e["w"].setdefault(w, [])
            if key not in e["w"][w]:
                e["w"][w].append(key)


def split_muni(pref, name):
    """郵便番号データの市区町村名 → (市区町村, 区)。郡名は落とす（区域データは郡を持たない）。"""
    name = norm(name)
    name = re.sub(r"^.+?郡(?=.+[町村]$)", "", name)
    if pref == "東京都":   # 島しょ部「三宅島三宅村」。他県の「木島平村」「粟島浦村」は島で切らない
        name = re.sub(r"^.+?島(?=.+[町村]$)", "", name)
    m = re.match(r"^(.+?市)(.+区)$", name)
    if m and m.group(1) in area.get(pref, {}):
        return m.group(1), m.group(2)
    return name, ""


rows, miss = {}, collections.Counter()
with open(a.ken_all, encoding="utf-8") as f:
    for r in csv.reader(f):
        z, pref, raw = r[2], r[6], r[7]
        muni, ward = split_muni(pref, raw)
        if muni not in area.get(pref, {}):
            miss[(pref, raw)] += 1
            continue
        rows.setdefault(z, set()).add((pref, muni, ward))

json.dump({"_n": names, **area}, open(a.area_json, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
munis = sum(len(v) for v in area.values())
split = sum(1 for v in area.values() for e in v.values() if len(e["d"]) > 1)
wsplit = sum(1 for v in area.values() for e in v.values() for d in e["w"].values() if len(d) > 1)
print(f"区域: 市区町村 {munis} / 複数の選挙区にまたがる {split} / 区でまたがる {wsplit}")
print(f"郵便番号: 対応 {len(rows)} 件 / 区域データに無い市区町村名 {len(miss)} 種")
for (p, n), c in miss.most_common(15):
    print("   未対応", p, n, c)

if a.postal_dir:
    # 本体（/jusho/）は MariaDB に表を足さずに済むよう、上3桁で割ったJSONを1枚だけ読む。
    # 12万件を1枚にすると1リクエストごとに数MBを読むことになる。
    os.makedirs(a.postal_dir, exist_ok=True)
    shards = collections.defaultdict(dict)
    for z, st in rows.items():
        shards[z[:3]][z] = [list(x) for x in sorted(st)]
    for k, v in shards.items():
        json.dump(v, open(os.path.join(a.postal_dir, k + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
    print("postal-dir:", len(shards), "枚 →", a.postal_dir)

if a.sqlite:
    db = sqlite3.connect(a.sqlite)
    db.execute("DROP TABLE IF EXISTS postal")
    db.execute("CREATE TABLE postal (zip TEXT, pref TEXT, muni TEXT, ward TEXT)")
    db.executemany("INSERT INTO postal VALUES (?,?,?,?)",
                   [(z, p, m, w) for z, s in rows.items() for (p, m, w) in sorted(s)])
    db.execute("CREATE INDEX postal_zip ON postal(zip)")
    db.commit()
    print("postal:", db.execute("SELECT COUNT(*) FROM postal").fetchone()[0], "行 →", a.sqlite)
