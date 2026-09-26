#!/usr/bin/env python3
"""参議院の本会議投票結果（押しボタン投票・記名投票）を議員別に取り込む。

出典: 参議院「本会議投票結果」 https://www.sangiin.go.jp/japanese/touhyoulist/touhyoulist.html
回次ごとの一覧 <回次>/vote_ind.htm → 案件ごとのページ <回次>-<月日>-v<番号>.htm。
案件ページは会派ごとに「賛成／反対／投票 なし」と議員名が並ぶ。

衆議院はほとんどが起立採決で、議員別の賛否が記録に残らない。記名投票（不信任案など）だけが
会議録の議長発表に出るが、ここでは扱っていない。**参議院だけ**である。

    python3 scripts-jp/sangiin_votes.py --session 221 --sqlite twfy_demo.sqlite
"""
import argparse, html, re, sqlite3, time, urllib.request

BASE = "https://www.sangiin.go.jp/japanese/touhyoulist/"
UA = {"User-Agent": "Mozilla/5.0 (theyworkforyou-jp)"}

ap = argparse.ArgumentParser()
ap.add_argument("--session", type=int, required=True)
ap.add_argument("--sqlite", required=True)
ap.add_argument("--wait", type=float, default=1.0, help="1件ごとの待ち秒（相手のサーバーに優しく）")
a = ap.parse_args()


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


idx = get(f"{BASE}{a.session}/vote_ind.htm")
items = []
for block_date, block in re.findall(r"<!--START\[(\d{4}/\d{2}/\d{2})\]-->(.*?)<!--END", idx, re.S):
    for href, title in re.findall(r'HREF="([^"]+-v\d+\.htm)">(.*?)</A>', block, re.S | re.I):
        items.append((block_date.replace("/", "-"), href, text(title)))
print(f"第{a.session}回国会: {len(items)} 件")

db = sqlite3.connect(a.sqlite)
db.executescript("""
CREATE TABLE IF NOT EXISTS vote (id TEXT PRIMARY KEY, session INTEGER, date TEXT, title TEXT,
                                 url TEXT, total INTEGER, yes INTEGER, no INTEGER);
CREATE TABLE IF NOT EXISTS vote_member (vote_id TEXT, name TEXT, name_key TEXT, kaiha TEXT, choice TEXT);
CREATE INDEX IF NOT EXISTS vote_member_key ON vote_member(name_key);
CREATE INDEX IF NOT EXISTS vote_member_vote ON vote_member(vote_id);
""")
for date, href, title in items:
    vid = href.rsplit("/", 1)[-1].removesuffix(".htm")
    if db.execute("SELECT 1 FROM vote WHERE id=?", (vid,)).fetchone():
        continue
    url = f"{BASE}{a.session}/{href}"
    body = text(re.sub(r"<script.*?</script>|<style.*?</style>", "", get(url), flags=re.S))
    m = re.search(r"投票総数 (\d+) 賛成票 (\d+) 反対票 (\d+)", body)
    if not m:
        print("  !! 集計が読めない", vid); continue
    rows = []
    # 会派の見出し「自由民主党・無所属の会(101名) 賛成票 99 反対票 0」で区切る
    parts = re.split(r"(\S+?\(\s*\d+名\)) 賛成票 \d+ 反対票 \d+", body[m.end():])
    for i in range(1, len(parts) - 1, 2):
        kaiha = re.sub(r"\(\s*\d+名\)", "", parts[i])
        for choice, name in re.findall(r"(賛成|反対|投票 なし) (.+?)(?= (?:賛成|反対|投票 なし) |$)",
                                       re.split(r" 〒| 本会議投票結果| トップ ", parts[i + 1])[0]):
            name = name.strip()
            rows.append((vid, name, name.replace(" ", "").replace("　", ""), kaiha,
                         "欠" if choice == "投票 なし" else choice))
    db.execute("INSERT INTO vote VALUES (?,?,?,?,?,?,?,?)",
               (vid, a.session, date, title, url, *map(int, m.groups())))
    db.executemany("INSERT INTO vote_member VALUES (?,?,?,?,?)", rows)
    db.commit()
    got = sum(1 for r in rows if r[4] != "欠")
    flag = "" if got == int(m.group(1)) else f"  !! 投票総数{m.group(1)}と議員別{got}が合わない"
    print(f"  {vid} {title[:36]} 賛{m.group(2)} 反{m.group(3)} 議員{len(rows)}{flag}")
    time.sleep(a.wait)
print("vote:", db.execute("SELECT COUNT(*) FROM vote").fetchone()[0],
      "/ vote_member:", db.execute("SELECT COUNT(*) FROM vote_member").fetchone()[0])
