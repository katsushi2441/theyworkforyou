<?php
/**
 * 郵便番号か住所から、小選挙区と衆議院議員を引く。
 *
 * 英国版の入口は /postcode/ で、MapIt に郵便番号を投げて選挙区を得る作り。
 * 日本には「郵便番号→小選挙区」の公式な対応表は無いが、郵便番号を日本郵便の郵便番号データで
 * (都道府県, 市区町村, 政令市の区) に直せば、そこから引ける。
 * データは scripts-jp/build_area_index.py が作る:
 *   data/jp/area.json      … {"_n": {key: 表示名}, 県: {市区町村: {"d": [key], "w": {区: [key]}}}}
 *   data/jp/postal/NNN.json … 郵便番号の上3桁ごと {zip: [[県, 市区町村, 区], ...]}
 *
 * - 全国1,741市区町村のうち複数の選挙区にまたがるのは47。政令市は区まで見れば大半が1つに決まる。
 * - 区そのものがまたがるのは7区（札幌市西区など）。そこは候補を並べる。**勝手に1つに決めない。**
 * - **市区町村名だけで引かない。** 「池田町」は4県にある。県が無ければ該当する県を全部出す。
 */

include_once '../../includes/easyparliament/init.php';

$q = trim($_GET['q'] ?? '');
// $DATA は TWFY 本体のグローバル（Data オブジェクト）。上書きすると page.php が落ちる
$JDIR = BASEDIR . '/../../data/jp';
$area = is_file("$JDIR/area.json") ? json_decode(file_get_contents("$JDIR/area.json"), true) : [];
$keyname = $area['_n'] ?? [];

const JUSHO_PREFS = ['北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','茨城県','栃木県','群馬県',
  '埼玉県','千葉県','東京都','神奈川県','新潟県','富山県','石川県','福井県','山梨県','長野県','岐阜県',
  '静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県','和歌山県','鳥取県','島根県',
  '岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県','熊本県',
  '大分県','宮崎県','鹿児島県','沖縄県'];

/** 入力の揺れを寄せる。全角数字・空白、「龍ケ崎」と「龍ヶ崎」。 */
function jusho_norm($s) {
    $s = mb_convert_kana($s, 'as');
    $s = preg_replace('/[\s\x{3000}]+/u', '', $s);
    return preg_replace('/(?<=\p{Han})[ケヶ](?=\p{Han})/u', 'ヶ', $s);
}

/** 1つの区域の選挙区keyを決める。政令市は区まで分かれば区で絞る。 */
function jusho_keys($e, $ward) {
    if ($ward !== '' && isset($e['w'][$ward])) {
        return [$e['w'][$ward], ''];
    }
    if (!empty($e['w']) && count($e['d']) > 1) {
        return [$e['d'], '区まで入れると1つに絞れます'];
    }
    return [$e['d'], ''];
}

/** 郵便番号か住所 → [['label', 'keys', 'hint']] */
function jusho_match($area, $dir, $input) {
    $s = jusho_norm($input);
    if ($s === '') {
        return [];
    }
    if (preg_match('/^〒?(\d{3})-?(\d{4})$/u', $s, $m)) {
        $f = "$dir/postal/{$m[1]}.json";
        $shard = is_file($f) ? json_decode(file_get_contents($f), true) : [];
        $out = [];
        foreach ($shard[$m[1] . $m[2]] ?? [] as [$pref, $muni, $ward]) {
            $e = $area[$pref][$muni] ?? null;
            if (!$e) {
                continue;
            }
            [$keys, $hint] = jusho_keys($e, $ward);
            $out[] = ['label' => "〒{$m[1]}-{$m[2]}　$pref$muni$ward", 'keys' => $keys, 'hint' => $hint];
        }
        return $out;
    }
    $prefs = JUSHO_PREFS;
    foreach (JUSHO_PREFS as $p) {
        if (strpos($s, $p) === 0) {
            $prefs = [$p];
            $s = substr($s, strlen($p));
            break;
        }
    }
    $out = [];
    foreach ($prefs as $p) {
        if (empty($area[$p])) {
            continue;
        }
        foreach ([$s, preg_replace('/^.{1,5}?郡/u', '', $s)] as $rest) {
            $best = '';
            foreach ($area[$p] as $muni => $e) {
                if (strpos($rest, $muni) === 0 && strlen($muni) > strlen($best)) {
                    $best = $muni;
                }
            }
            if ($best === '') {
                continue;
            }
            $after = substr($rest, strlen($best));
            $ward = '';
            foreach (array_keys($area[$p][$best]['w']) as $w) {
                if (strpos($after, $w) === 0) {
                    $ward = $w;
                    break;
                }
            }
            [$keys, $hint] = jusho_keys($area[$p][$best], $ward);
            $out[] = ['label' => $p . $best . $ward, 'keys' => $keys, 'hint' => $hint];
            break;
        }
    }
    return array_slice($out, 0, 6);
}

$hits = jusho_match($area, $JDIR, $q);

// 選挙区名 -> 議員
$members = [];
if ($hits) {
    $names = [];
    foreach ($hits as $h) {
        foreach ($h['keys'] as $k) {
            $names[] = $keyname[$k] ?? $k;
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
<h1>郵便番号か住所から、選挙区と議員を調べる</h1>
<p>郵便番号（7桁）か住所を入れてください。例: 467-0853、名古屋市瑞穂区、千葉県茂原市</p>
<form method="get" action="">
  <input type="text" name="q" value="<?= _htmlspecialchars($q) ?>" size="30" placeholder="郵便番号か住所">
  <input type="submit" value="調べる">
</form>
<?php if ($q !== '' && !$hits) { ?>
  <p>「<?= _htmlspecialchars($q) ?>」に当てはまる場所が見つかりませんでした。郵便番号は7桁、住所は「県＋市区町村」から入れてみてください。</p>
<?php } ?>
<?php if (count($hits) > 1) { ?>
  <p>同じ名前の市区町村が <?= count($hits) ?> か所あります。都道府県から入れると1つに絞れます。</p>
<?php } ?>
<?php foreach ($hits as $h) { ?>
  <h2><?= _htmlspecialchars($h['label']) ?></h2>
  <?php if (count($h['keys']) > 1) { ?>
    <p><strong><?= count($h['keys']) ?>つの選挙区</strong>にまたがっています。
       <?= $h['hint'] ? _htmlspecialchars($h['hint']) . '。' : 'どちらになるかは町名で決まります。' ?></p>
  <?php } ?>
  <ul>
  <?php foreach ($h['keys'] as $k) {
      $nm = $keyname[$k] ?? $k;
      $m = $members[$nm] ?? null; ?>
    <li>
      <strong><?= _htmlspecialchars($nm) ?></strong>
      <?php if ($m) { ?>
        —
        <a href="/mp/<?= (int) $m['person_id'] ?>/"><?= _htmlspecialchars($m['family_name']) ?></a>
        <small><?= _htmlspecialchars($m['party']) ?></small>
      <?php } ?>
    </li>
  <?php } ?>
  </ul>
<?php } ?>
<p><small>選挙区の区域は衆議院小選挙区（第50回総選挙時点）。郵便番号は日本郵便「郵便番号データ」。</small></p>
<?php
$PAGE->stripe_end();
$PAGE->page_end();
