# AI エージェントへ（このファイルを最初に読ませてください）

TheyWorkForYou（mySociety・BSD 3条項）を、日本の国会会議録で動かします。
**本体は当社のものではありません。** ここにあるのは日本語で動かすための修正と、
会議録APIからの変換だけです。

## 手順（この順でやること）

```bash
# 1. 起動。ポートは docker-compose.override.yml で決める。
#    **必ず ss -ltn で空きを実測してから決めること。** ドキュメントの「未使用」は信用しない。
docker compose up -d

# 2. データが空だと HTTP 500 になる。最低限のファイルを置く
mkdir -p data/pwdata/scrapedjson && echo '{}' > data/pwdata/scrapedjson/policies.json

# 3. 会議録API → 取り込み用XML（上流のパーサーは書き換えない）
/usr/bin/python3 scripts-jp/kokkai2twfy.py --from 2026-06-01 --to 2026-06-30 \
    --max 25 --out data/pwdata/scrapedxml/debates

# 4. 発言者から議員名簿を作る（無いと 5 が止まる）
/usr/bin/python3 scripts-jp/make_people_json.py

# 5. 小選挙区289と現職議員を足す（giin のデータが要る。無ければこの手順は飛ばす）
GIIN_DB=/path/to/giin.sqlite /usr/bin/python3 scripts-jp/add_senkyoku.py

# 6. 名簿の取り込み
docker compose exec -T twfy sh -c "cd /twfy/scripts && ./load-people"

# 7. 会議録の取り込み。**TWFY_UTF8_OUTPUT=1 が要る**
for d in $(ls data/pwdata/scrapedxml/debates/*.xml | sed -E 's/.*debates(20[0-9-]+)[a-z]\.xml/\1/' | sort -u); do
  docker compose exec -T -e TWFY_UTF8_OUTPUT=1 twfy sh -c "cd /twfy/scripts && perl xml2db.pl --debates --date=$d"
done

# 8. 全文検索の索引。**TWFY_CJK_NGRAM=1 が要る**
docker compose exec -T -e TWFY_CJK_NGRAM=1 twfy sh -c \
  "cd /twfy/search && perl index.pl daterange 2026-06-01 2026-06-30"
```

## 確認（ここまでやって初めて「動いた」と言う）

```bash
curl -s "http://127.0.0.1:<PORT>/search/?q=%E6%B2%96%E7%B8%84" | grep -c 沖縄   # 1以上
curl -s "http://127.0.0.1:<PORT>/mps/" | grep -c "区"                          # 議員一覧
curl -s "http://127.0.0.1:<PORT>/jusho/?q=%E8%8C%82%E5%8E%9F%E5%B8%82"          # 千葉11区が出る
```

## 必ず踏む落とし穴（READMEの理由も読むこと）

1. **日本語が1件も検索できない** → `TWFY_CJK_NGRAM=1`。索引側と検索側の**両方**
2. **検索が黙って無効** → `php-xapian` は `/usr/share/php/xapian.php` を置かない
3. **本文が `&#12371;` になる** → `TWFY_UTF8_OUTPUT=1`
4. **議員一覧が空** → 院IDは衆議院1・参議院2（英国の下院IDに合わせる）
5. **289件が1件になる** → `member_id`・`person_id` は int 列。文字列IDは丸められる
6. **ポートが取れない** → `ss -ltn` で実測する

## やってはいけないこと

- 上流の `scripts/xml2db.pl`（1,904行）を書き換えない。形式を合わせれば通る
- 英国のデータと同じDBに混ぜない（院IDを共有しているため）
- 翻訳で `%s` や HTML タグを壊さない。`scripts-jp/translate_po.py` の検査を外さない
