#!/usr/bin/env python3
"""国会会議録検索システムのAPIから、TheyWorkForYou が読む XML を書き出す。

なぜ変換で済むか（2026-09-27 に実物を突き合わせて確認）:
  TWFY の取り込みは scripts/xml2db.pl が読む「Public Whip 形式」のXMLで、中身は
    <publicwhip>
      <major-heading id=... >会議名</major-heading>
      <speech id=... speakername=... person_id=...><p>本文</p></speech>
    </publicwhip>
  という素直な入れ子。会議録APIは発言を1件ずつ、発言者・会派・役職・順番つきで返す。
  ほぼ1対1で写せるので、**上流のパーサーを書き換える必要がない**。

対応:
  speechRecord   -> <speech>
  speaker        -> speakername
  speechID       -> id と person_id の材料
  nameOfMeeting  -> <major-heading>
  date           -> ファイル名と id の日付

APIの決まり:
  https://kokkai.ndl.go.jp/api/meeting  (recordPacking=json, maximumRecords<=10)
  出典表示が要る。生成物の先頭にコメントで入れる。

  /usr/bin/python3 scripts-jp/kokkai2twfy.py --from 2026-06-01 --to 2026-06-30 --out data/pwdata/scrapedxml/debates
"""
import argparse, html, json, os, re, sys, time, urllib.parse, urllib.request

API = "https://kokkai.ndl.go.jp/api/meeting"
UA = {"User-Agent": "Mozilla/5.0 (compatible; theyworkforyou-jp-kit)"}


def fetch(params, tries=3):
    url = API + "?" + urllib.parse.urlencode(params)
    for n in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read())
        except Exception as ex:
            if n == tries - 1:
                raise
            print(f"  再試行 {n+1}: {type(ex).__name__}", file=sys.stderr)
            time.sleep(3 * (n + 1))


def esc(s):
    """属性用のエスケープ。&<>"' だけを実体参照にする。"""
    return html.escape(str(s or ""), quote=True)


def esc_text(s):
    """本文用のエスケープ。

    xml2db.pl は本文を Twig の output_filter 'safe' で出し直すので、日本語をここで
    実体参照にすると **DBに &#34886; のまま入る**（2026-09-27 に実測）。
    XMLとして壊さないために必要な & < > だけを直し、日本語はそのまま置く。
    """
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def clean(text):
    """会議録の本文から、TWFY 側で邪魔になる体裁を落とす。

    先頭の「○議長（関口昌一君）　」は発言者名の重複なので外す。
    全角空白の字下げも段落の区切りとして扱う。
    """
    t = str(text or "")
    t = re.sub(r"^○[^　\n]*　?", "", t)
    paras = [p.strip() for p in re.split(r"\n|　{1,}(?=\S)", t) if p.strip()]
    return paras or [t.strip()]


def to_xml(meeting, day_seq):
    """1会議 -> Public Whip 形式のXML文字列。"""
    date = meeting.get("date", "")
    house = meeting.get("nameOfHouse", "")
    name = meeting.get("nameOfMeeting", "")
    issue = meeting.get("issue", "")
    base = f"jp.go.ndl.kokkai/debate/{date}{day_seq}"
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           "<!-- 出典: 国立国会図書館 国会会議録検索システム "
           f"({esc(meeting.get('meetingURL',''))}) を加工して作成 -->",
           '<publicwhip scraperversion="jp" latest="yes">']
    out.append(f'  <major-heading id="{base}.0" nospeaker="true" colnum="0" time="" '
               f'url="{esc(meeting.get("meetingURL",""))}">{esc_text(house + " " + name + " " + issue)}</major-heading>')
    for sp in meeting.get("speechRecord", []) or []:
        order = sp.get("speechOrder", 0)
        speaker = (sp.get("speaker") or "").strip()
        group = (sp.get("speakerGroup") or "").strip()
        pos = (sp.get("speakerPosition") or "").strip()
        sid = sp.get("speechID") or f"{base}.{order}"
        paras = clean(sp.get("speech"))
        attrs = [f'id="{base}.{order}"']
        if speaker:
            attrs.append(f'speakername="{esc(speaker)}"')
            # person_id は会議録APIに無い。名前＋会派で当社の議員DBと名寄せする前提で、
            # いまは決定的なキーを入れておく（後段で giin の議員IDに差し替える）。
            attrs.append(f'person_id="jp.go.ndl.kokkai/person/{esc(speaker)}"')
        else:
            attrs.append('nospeaker="true"')
        if group:
            attrs.append(f'speakeroffice="{esc(group)}"')
        if pos:
            attrs.append(f'speakerposition="{esc(pos)}"')
        attrs += [f'colnum="{esc(sp.get("startPage",0))}"', 'time=""',
                  f'url="{esc(sp.get("speechURL",""))}"']
        out.append("  <speech " + " ".join(attrs) + ">")
        for i, p in enumerate(paras, 1):
            out.append(f'    <p pid="{base}.{order}/{i}">{esc_text(p)}</p>')
        out.append("  </speech>")
    out.append("</publicwhip>")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", required=True)
    ap.add_argument("--to", dest="to", required=True)
    ap.add_argument("--out", default="data/pwdata/scrapedxml/debates")
    ap.add_argument("--max", type=int, default=50, help="取り込む会議の上限")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    start, got, files = 1, 0, 0
    seen_dates = {}
    while got < a.max:
        d = fetch({"from": a.frm, "until": a.to, "recordPacking": "json",
                   "maximumRecords": 3, "startRecord": start})
        total = d.get("numberOfRecords", 0)
        recs = d.get("meetingRecord") or []
        if not recs:
            break
        for m in recs:
            date = m.get("date", "")
            seq = seen_dates.get(date, 0)
            seen_dates[date] = seq + 1
            suffix = chr(ord("a") + seq)
            path = os.path.join(a.out, f"debates{date}{suffix}.xml")
            open(path, "w", encoding="utf-8").write(to_xml(m, suffix))
            files += 1
            print(f"  {os.path.basename(path)}  {m.get('nameOfHouse')} {m.get('nameOfMeeting')} "
                  f"発言{len(m.get('speechRecord') or [])}件", flush=True)
            got += 1
            if got >= a.max:
                break
        nxt = d.get("nextRecordPosition")
        if not nxt:
            break
        start = nxt
        time.sleep(1)   # APIに負荷をかけない
    print(f"\n{files} ファイル書き出し（全体 {total} 会議中）→ {a.out}")


if __name__ == "__main__":
    main()
