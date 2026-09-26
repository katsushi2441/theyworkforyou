# TheyWorkForYou 日本語導入キット

[TheyWorkForYou](https://github.com/mysociety/theyworkforyou)（mySociety・BSD 3条項）を
日本の国会会議録で動かすためのキットです。**本体は当社のものではありません。**
当社が足したのは、日本語で動かすための修正と、会議録APIからの変換だけです。

同じ mySociety の [Alaveteli 日本語導入キット](https://kappstore.exbridge.jp/)・
[FixMyStreet 日本語導入キット](https://kappstore.exbridge.jp/) と同じ型です。

## 動いている状態（2026-09-27 実測）

- 2026年6月の国会会議録 **25会議・1,397発言**を取り込み、**日本語で検索できる**
- 画面から「沖縄」5件、「子供」14件がヒット
- **衆議院議員289人**が選挙区・会派つきで一覧に並ぶ
- **住所から選挙区と議員を引ける**（`/jusho/`）。茂原市→千葉11区、横須賀市→神奈川11区
- UI は 636文字列が日本語

## 起動

```bash
docker compose up -d      # ポートは docker-compose.override.yml で 18383
```

ポートは `ss -ltn` で実測した空き番号。**ドキュメントの「未使用」表記は信用しない**
（2026-09-27 に 18384/18385/18386 を取ろうとして、先客がいて起動に失敗した）。

## データを入れる

```bash
# 1. 会議録API → Public Whip 形式のXML（上流のパーサーは書き換えない）
/usr/bin/python3 scripts-jp/kokkai2twfy.py --from 2026-06-01 --to 2026-06-30 \
    --max 25 --out data/pwdata/scrapedxml/debates

# 2. 発言者から parlparse 形式の名簿を作る（無いと xml2db.pl が止まる）
/usr/bin/python3 scripts-jp/make_people_json.py

# 3. 取り込み。**TWFY_UTF8_OUTPUT=1 が要る**（下記）
for d in $(ls data/pwdata/scrapedxml/debates/*.xml | sed -E 's/.*debates(20[0-9-]+)[a-z]\.xml/\1/' | sort -u); do
  docker compose exec -T -e TWFY_UTF8_OUTPUT=1 twfy sh -c "cd /twfy/scripts && perl xml2db.pl --debates --date=$d"
done

# 4. 全文検索の索引。**TWFY_CJK_NGRAM=1 が要る**（下記）
docker compose exec -T -e TWFY_CJK_NGRAM=1 twfy sh -c "cd /twfy/search && perl index.pl daterange 2026-06-01 2026-06-30"
```

## 上流に入れた5つの修正（すべて実測で原因を特定した）

いずれも**環境変数か設定で切り替える形**にしてあり、英語運用の既定は変えていない。

1. **`search/index.pl` — CJK の n-gram（`TWFY_CJK_NGRAM=1`）**
   Xapian の既定は空白と句読点でしか切らないので、日本語は「一文まるごとが一語」になり、
   「憲法」で引いても0件になる。実測では3文書で語が3つしか無かった。
   Perl バインディング 1.4.22 は `FLAG_CJK_NGRAM` を export しないので、値 2048 を直接渡す
   （PHP 側の `XapianTermGenerator::FLAG_CJK_NGRAM` で実測した値）。

2. **`www/includes/easyparliament/searchengine.php` — 検索側にも同じフラグ**
   **索引側と検索側の両方**で立てないと噛み合わない。対で直すこと。

3. **同ファイル — 拡張の判定**
   上流は `/usr/share/php/xapian.php` の有無だけを見るが、Debian の `php-xapian` は
   そのファイルを置かない。そのため**拡張が動いていても検索が黙って無効になる**。

4. **`scripts/xml2db.pl` — 出力フィルタ（`TWFY_UTF8_OUTPUT=1`）**
   Twig の `output_filter => 'safe'` は **ASCII 以外を全部 `&#12371;` にする**ので、
   日本語本文がその形で DB に入り、画面にも索引にもそのまま流れる。

5. **`search/index.pl` — UTF-8 のデコード**
   DB から来るのはバイト列。`HTML::Parser` にそのまま渡すと
   「Parsing of undecoded UTF-8 will give garbage」で日本語が壊れる。

あわせて `Dockerfile` に `ja_JP.UTF-8` のロケール生成と `extension=xapian.so` を恒久化した。
ロケールが無いと `setlocale` が失敗し、`.mo` があっても英語のまま出る。

## 日本語化の範囲

| | 状態 |
|---|---|
| UI の文字列 | 636/746 を翻訳（`scripts-jp/translate_po.py`・ローカルgemma4で下訳） |
| 会議録の取り込み | 動く |
| 全文検索 | 動く |
| 議員一覧・議員ページ | 動く（289人） |
| 住所→選挙区→議員 | 動く（`/jusho/`） |
| 郵便番号・政令市の区→選挙区 | 索引を作る（`scripts-jp/build_area_index.py`）。デモで動作確認済み |
| 投票記録 | 参議院のみ。採決一覧 `/divisions/?house=lords`・採決ごとの賛否 `/divisions/pw-<日付>-<番号>-lords`・議員ごとの `/mp/<id>/recent` に出る |

**英国固有の概念への対応。** `MP` が147ファイル、`constituency` 42、`postcode` 33 に
埋まっている。画面の入口は「郵便番号から自分の議員を引く」。日本には
郵便番号→小選挙区の公式な対応表は無いが、**郵便番号を日本郵便の郵便番号データで
市区町村と政令市の区に直せば引ける**（`scripts-jp/build_area_index.py`）。

- 全国1,741市区町村のうち、複数の小選挙区にまたがるのは **47**。
- **政令市は区まで持つ。** 名古屋市は市で引くと愛知1〜5区が全部出るが、瑞穂区なら愛知4区の1つ。
- 区そのものが2つの選挙区にまたがるのは全国で **7区**（札幌市西区・北区・白石区、浜松市中央区、
  福岡市東区・南区・城南区）。ここは町名で決まるので**候補を並べて選ばせる。勝手に1つに決めない。**
- **市区町村名だけで引かない。** 「池田町」「森町」など同名の町村が県をまたいで26組ある。
  名前だけで数えると「またがる市区町村」が105と出る（誤り。以前この数字を使っていた）。
- 区域データの側で「蒲郡市」「小郡市」が「市」に、「大和郡山市」が「山市」に切られていたので、
  区域の文から拾い直している。郵便番号データの「龍ケ崎市」「須惠町」などの表記ゆれも寄せる。

**投票記録は参議院だけ。** 参議院は本会議の採決を押しボタンで行い、議員別の賛否を公式サイトに
載せている（`scripts-jp/sangiin_votes.py`。第221回国会の120件で、全件の議員別票数が投票総数と一致）。
衆議院は起立採決がほとんどで、議員ごとの賛否が記録に残らない。
本体の画面に出すには、投票した参議院議員全員を people.json に足し（`add_sangiin_members.py`。発言から作った短い所属は1本にまとめる。
重なると一覧に同じ人が2回出る）、`load_sangiin_divisions.py` の SQL を流す。採決IDは本体と同じ `pw-` 始まりにする
（`conf/httpd.conf` の書き換えが `pw-`/`pbc-` しか通さず、独自の接頭辞だと採決ページが404になった）。
採決画面の見出しの一部（"Division number" "Members of the House of Lords"）はテンプレート直書きで英語のまま。

院の割り当ては、画面側が `HOUSE_TYPE_COMMONS`(=1) を147ファイルで直に使っているため、
**衆議院を 1、参議院を 2** に当てている。別番号だと議員一覧が空になる（実測）。
「下院＝選挙区から1人ずつ／上院＝それ以外」という構造が衆参と同じ形なので成り立つ。
**英国のデータと同じDBに混ぜないこと。**

## 翻訳の決めごと

`scripts-jp/translate_po.py` は機械翻訳をそのまま採用しない。

- **英国の制度語は辞書で固定**する。`MP`→国会議員、`constituency`→選挙区、
  `postcode`→住所、`Hansard`→会議録、`Commons`→衆議院、`Lords`→参議院。
  これは翻訳ではなく「日本の制度のどれに当てるか」の判断なので機械に任せない。
- `%s` `%d` の数と順番が変わったら採用しない。
- HTML タグが変わったら採用しない。
- 見送ったものは理由つきで出す（746件中7件が該当した）。

## 出典

国会会議録は国立国会図書館「国会会議録検索システム」のAPIから取得している。
郵便番号は日本郵便「郵便番号データ」（`data/jp/` に置く。repoには含めない）。
参議院の賛否は参議院「本会議投票結果」。
生成する XML の先頭に出典をコメントで入れてある。
