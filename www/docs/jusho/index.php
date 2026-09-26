<?php
/**
 * 住所（市区町村）から小選挙区と衆議院議員を引く。
 *
 * 英国版の入口は /postcode/ で、MapIt に郵便番号を投げて選挙区を得る作り。
 * 日本には「郵便番号→小選挙区」の公式な対応が無い（1つの郵便番号が複数区に
 * またがる）。一方、市区町村→小選挙区なら確定するので、そこを入口にする。
 * 対応表は data/jp/muni2senkyoku.json（giin の senkyoku から生成、1,708件）。
 *
 * 政令市などは1つの市が複数区にまたがる（105件）。その場合は候補を全部出して
 * 利用者に選ばせる。**勝手に1つに決めない。**
 */

include_once '../../includes/easyparliament/init.php';

$q = trim($_GET['q'] ?? '');

$MAP_FILE = BASEDIR . '/../../data/jp/muni2senkyoku.json';
$map = file_exists($MAP_FILE) ? json_decode(file_get_contents($MAP_FILE), true) : [];

/** 入力から市区町村名を拾う。都道府県名や丁目が付いていても拾えるようにする。 */
function jusho_match($q, $map) {
    if ($q === '') {
        return [];
    }
    if (isset($map[$q])) {
        return [$q => $map[$q]];
    }
    $hits = [];
    foreach ($map as $muni => $areas) {
        // 対応表には「市」「町」のような1〜2文字の項目が混じる（元データの揺れ）。
        // これを部分一致で拾うと、どんな住所でも当たってしまう
        // （「名古屋市瑞穂区」で「市」が当たった。2026-09-27 実測）。
        if (mb_strlen($muni) < 3) {
            continue;
        }
        if (mb_strpos($q, $muni) !== false) {
            $hits[$muni] = $areas;
        }
    }
    // 「北区」のように短い名前が長い名前に含まれるので、長い一致を先に出す
    uksort($hits, function ($a, $b) {
        return mb_strlen($b) - mb_strlen($a);
    });
    return array_slice($hits, 0, 3, true);
}

$hits = jusho_match($q, $map);

// 選挙区名 -> 議員
$members = [];
if ($hits) {
    $names = [];
    foreach ($hits as $areas) {
        foreach ($areas as $a) {
            $names[] = $a['name'];
        }
    }
    if ($names) {
        // この実装の ->query() は名前つきプレースホルダしか受けない
        // （Db/Query.php が bindValue にキーをそのまま渡す）。? は使えない。
        $names = array_values(array_unique($names));
        $ph = [];
        $params = [];
        foreach ($names as $i => $n) {
            $ph[] = ":c$i";
            $params[":c$i"] = $n;
        }
        $db = new ParlDB();
        $rows = $db->query(
            "SELECT m.constituency, m.party, n.family_name, m.person_id
             FROM member m JOIN person_names n ON n.person_id = m.person_id
             WHERE m.constituency IN (" . implode(',', $ph) . ")
               AND m.left_house >= NOW()",
            $params
        )->fetchAll();
        foreach ($rows as $r) {
            $members[$r['constituency']] = $r;
        }
    }
}

$PAGE->page_start();
$PAGE->stripe_start();
?>
<h1>住所から選挙区と議員を調べる</h1>
<p>市区町村名を入れてください。例: 名古屋市瑞穂区、千葉県茂原市</p>
<form method="get" action="">
  <input type="text" name="q" value="<?= _htmlspecialchars($q) ?>" size="30" placeholder="市区町村名">
  <input type="submit" value="調べる">
</form>
<?php if ($q !== '' && !$hits) { ?>
  <p>「<?= _htmlspecialchars($q) ?>」に当てはまる市区町村が見つかりませんでした。市区町村名だけで入れ直してみてください。</p>
<?php } ?>
<?php foreach ($hits as $muni => $areas) { ?>
  <h2><?= _htmlspecialchars($muni) ?></h2>
  <?php if (count($areas) > 1) { ?>
    <p>この市区町村は <strong><?= count($areas) ?>つの選挙区</strong>にまたがっています。
       どの区域かは町名で決まるので、下の選挙区のページで区域をご確認ください。</p>
  <?php } ?>
  <ul>
  <?php foreach ($areas as $a) {
      $m = $members[$a['name']] ?? null; ?>
    <li>
      <strong><?= _htmlspecialchars($a['name']) ?></strong>
      <?php if ($a['partial']) { ?><small>（市区町村の一部）</small><?php } ?>
      <?php if ($m) { ?>
        —
        <a href="/mp/<?= (int) $m['person_id'] ?>/"><?= _htmlspecialchars($m['family_name']) ?></a>
        <small><?= _htmlspecialchars($m['party']) ?></small>
      <?php } ?>
    </li>
  <?php } ?>
  </ul>
<?php } ?>
<p><small>選挙区の区域は衆議院小選挙区（第50回総選挙時点）。出典: 当社が公開データから作成。</small></p>
<?php
$PAGE->stripe_end();
$PAGE->page_end();
