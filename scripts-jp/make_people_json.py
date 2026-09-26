#!/usr/bin/env python3
"""生成した会議録XMLの発言者から、parlparse 形式の people.json を作る。

なぜ要るか:
  xml2db.pl は取り込みの最初に data/parlparse/members/people.json を読み、
  発言者名を person_id に名寄せする。無いと「open: No such file or directory」で止まる。
  英国版の people.json は 27MB・14,824人で、当然ながら日本の議員は入っていない。

やり方:
  会議録APIの speaker（氏名）と speakerGroup（会派）をそのまま人と所属にする。
  **氏名は会議録に出たとおりを正とする。** 表記ゆれの名寄せ（「小寺裕雄」と「小寺 裕雄」）は
  ここではやらない。後段で giin の議員DBと突き合わせるときにまとめて解く。
  議員でない発言者（「会議録情報」「政府参考人」など）も、会議録に出る以上は人として作る。
  省くと xml2db.pl が person_id を引けずに落ちる。

  /usr/bin/python3 scripts-jp/make_people_json.py --xml data/pwdata/scrapedxml/debates \
      --out data/parlparse/members/people.json
"""
import argparse, glob, json, os, re
import xml.etree.ElementTree as ET

NOT_MEMBER = ("会議録情報", "政府参考人", "参考人", "公述人", "証人")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", default="data/pwdata/scrapedxml/debates")
    ap.add_argument("--out", default="data/parlparse/members/people.json")
    a = ap.parse_args()

    people = {}        # 氏名 -> {id, 会派の集合, 院の集合, 日付の範囲}
    for path in sorted(glob.glob(os.path.join(a.xml, "*.xml"))):
        root = ET.parse(path).getroot()
        head = root.find("major-heading")
        house = ""
        if head is not None and head.text:
            house = "house-of-councillors" if "参議院" in head.text else "house-of-representatives"
        date = (re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path)) or [None, ""])[1]
        for sp in root.findall("speech"):
            name = sp.get("speakername")
            if not name:
                continue
            p = people.setdefault(name, {"groups": set(), "houses": set(), "dates": set()})
            g = sp.get("speakeroffice")
            if g:
                p["groups"].add(g)
            if house:
                p["houses"].add(house)
            if date:
                p["dates"].add(date)

    persons, memberships, posts, orgs = [], [], [], {}
    orgs["house-of-representatives"] = {"classification": "legislature",
                                        "id": "house-of-representatives", "name": "衆議院"}
    orgs["house-of-councillors"] = {"classification": "legislature",
                                    "id": "house-of-councillors", "name": "参議院"}

    for i, (name, p) in enumerate(sorted(people.items()), start=1):
        pid = f"jp.go.ndl.kokkai/person/{i}"
        persons.append({
            "id": pid,
            "identifiers": [{"identifier": name, "scheme": "kokkai_speaker_name"}],
            "other_names": [{"family_name": name, "given_name": "", "note": "Main"}],
        })
        house = sorted(p["houses"])[0] if p["houses"] else "house-of-representatives"
        start = min(p["dates"]) if p["dates"] else "2000-01-01"
        end = max(p["dates"]) if p["dates"] else "9999-12-31"
        for g in (sorted(p["groups"]) or [""]):
            oid = None
            if g:
                oid = "party/" + re.sub(r"[^\w぀-ヿ一-鿿]+", "-", g).strip("-")
                orgs.setdefault(oid, {"classification": "party", "id": oid, "name": g})
            m = {"id": f"jp.go.ndl.kokkai/member/{len(memberships)+1}",
                 "person_id": pid, "organization_id": house,
                 "start_date": start, "end_date": end}
            if oid:
                m["on_behalf_of_id"] = oid
            memberships.append(m)

    data = {"persons": persons, "memberships": memberships,
            "posts": posts, "organizations": list(orgs.values())}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(data, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    kin = sum(1 for n in people if not any(k in n for k in NOT_MEMBER))
    print(f"人 {len(persons)}（うち議員らしき名前 {kin}）／ 所属 {len(memberships)} ／ "
          f"組織 {len(orgs)}  → {a.out}")


if __name__ == "__main__":
    main()
