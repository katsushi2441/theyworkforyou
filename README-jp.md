# TheyWorkForYou 日本語導入キット

[TheyWorkForYou](https://github.com/mysociety/theyworkforyou)（mySociety・BSD 3条項）を
日本の国会会議録で動かすためのキットです。**本体は当社のものではありません。**
当社が足したのは、日本語で動かすための修正と、会議録APIからの変換だけです。

同じ mySociety の [Alaveteli 日本語導入キット](https://kappstore.exbridge.jp/)・
[FixMyStreet 日本語導入キット](https://kappstore.exbridge.jp/) と同じ型です。

## 動いている状態（2026-09-27 実測）

- 2026年6月の国会会議録 **25会議・1,397発言**を取り込み、**日本語で検索できる**
- 画面から「沖縄」5件、「子供」14件がヒット
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
| 議員ページ・選挙区 | **未対応**（下記） |

**英国固有の概念がコードに埋まっている。** `MP` が147ファイル、`constituency` 42、
`postcode` 33。画面の入口は「郵便番号から自分の議員を引く」で、日本の
「住所→小選挙区→議員」とは別物。ここは翻訳ではなく改修になる。
当社は giin で小選挙区289の対応表を持っているので、そこを当てる。

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
生成する XML の先頭に出典をコメントで入れてある。
