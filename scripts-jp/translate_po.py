#!/usr/bin/env python3
"""TheyWorkForYou.pot から日本語の po を作る。下訳はローカルの gemma4。

なぜ機械で下訳するか:
  757文字列を手で訳すと数時間かかり、しかも大半は「Search」「Next」のような定型。
  機械で下訳して、**英国固有の語だけ人が決める**ほうが速くて間違いが少ない。

決めごと:
  - 英国の制度語は機械に訳させない。辞書（GLOSSARY）で固定する。
    MP を「国会議員」と訳すか「衆議院議員」と訳すかは制度の判断であって翻訳ではない。
  - %s や %d のような差し込みは数と順番を必ず保つ。壊れていたら採用しない。
  - HTMLタグを含む文字列はタグを壊さない。壊れていたら採用しない。
  - gemma4 は思考型なので think:false を必ず渡す（無いと response が空になる）。

  /usr/bin/python3 scripts-jp/translate_po.py [--limit N] [--out PATH]
"""
import argparse, json, os, re, sys, time, urllib.request

OLLAMA = os.environ.get("OLLAMA_URL", "http://192.168.0.3:11434") + "/api/generate"
MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:12b-it-qat")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POT = os.path.join(HERE, "locale", "TheyWorkForYou.pot")

# 英国の制度語。ここは翻訳ではなく「日本の制度のどれに当てるか」の判断なので固定する。
GLOSSARY = {
    "MP": "国会議員", "MPs": "国会議員", "Member of Parliament": "国会議員",
    "Lord": "参議院議員", "Lords": "参議院議員",
    "constituency": "選挙区", "Constituency": "選挙区",
    "postcode": "住所", "Postcode": "住所",
    "Hansard": "会議録", "debate": "会議録", "Debates": "会議録",
    "Written Answers": "答弁書", "Division": "採決", "Divisions": "採決",
    "Commons": "衆議院", "House of Commons": "衆議院",
    "House of Lords": "参議院", "Westminster": "国会",
}

PROMPT = """次の英語のUI文言を日本語に訳してください。訳文だけを1行で返してください。

【決まり】
- %s %d %1$s のような差し込み記号は、数も順番もそのまま残す。
- <a> <em> <strong> などのHTMLタグは、そのまま残す。
- 政治・議会のUIなので、丁寧だが短い言い方にする。
- 次の語は必ずこの訳を使う: {glossary}

【原文】
{text}"""


def gen(prompt, timeout=90):
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False, "think": False,
                       "options": {"temperature": 0.1, "num_predict": 300}}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read()).get("response", "")


def placeholders(s):
    return sorted(re.findall(r"%\d*\$?[sdxf%]", s))


def tags(s):
    return sorted(re.findall(r"</?([a-zA-Z][a-zA-Z0-9]*)", s))


def parse_pot(path):
    """msgid と msgid_plural を拾う。複数形は日本語では1つにまとめる。"""
    out, cur, key = [], {}, None
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        m = re.match(r'^(msgid|msgid_plural|msgstr|msgctxt)(\[\d+\])?\s+"(.*)"$', line)
        if m:
            key = m.group(1) + (m.group(2) or "")
            cur[key] = m.group(3)
            continue
        m = re.match(r'^"(.*)"$', line)
        if m and key:
            cur[key] = cur.get(key, "") + m.group(1)
            continue
        if line.startswith("#") or line == "":
            if cur.get("msgid"):
                out.append(cur)
            cur, key = {}, None
    if cur.get("msgid"):
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(HERE, "locale", "ja_JP.UTF-8",
                                                  "LC_MESSAGES", "TheyWorkForYou.po"))
    a = ap.parse_args()

    entries = [e for e in parse_pot(POT) if e["msgid"]]
    if a.limit:
        entries = entries[:a.limit]
    print(f"対象 {len(entries)} 文字列", flush=True)

    gl = "、".join(f"{k}→{v}" for k, v in list(GLOSSARY.items())[:14])
    done = {}
    skipped = []
    t0 = time.time()
    for i, e in enumerate(entries, 1):
        src = e["msgid"].replace("\\n", "\n").replace('\\"', '"')
        try:
            out = gen(PROMPT.format(glossary=gl, text=src)).strip().split("\n")[0].strip()
        except Exception as ex:
            skipped.append((src, f"{type(ex).__name__}")); continue
        out = out.strip('「」"\'')
        if not out:
            skipped.append((src, "空")); continue
        if placeholders(out) != placeholders(src):
            skipped.append((src, "差し込み記号が変わった")); continue
        if tags(out) != tags(src):
            skipped.append((src, "HTMLタグが変わった")); continue
        done[e["msgid"]] = out.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        if i % 50 == 0:
            el = time.time() - t0
            print(f"  {i}/{len(entries)}  採用{len(done)} 見送り{len(skipped)} "
                  f"経過{el/60:.1f}分 残り約{(el/i)*(len(entries)-i)/60:.0f}分", flush=True)

    # po を書き出す
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    src_text = open(POT, encoding="utf-8").read()
    src_text = re.sub(r'"Language:[^"]*\\n"', '"Language: ja\\\\n"', src_text)
    if '"Language:' not in src_text:
        src_text = src_text.replace('"MIME-Version: 1.0\\n"',
                                    '"Language: ja\\n"\n"MIME-Version: 1.0\\n"', 1)
    src_text = re.sub(r'"Plural-Forms:[^"]*"', '"Plural-Forms: nplurals=1; plural=0;\\\\n"', src_text)

    lines, out_lines, i = src_text.split("\n"), [], 0
    while i < len(lines):
        out_lines.append(lines[i])
        m = re.match(r'^msgid "(.*)"$', lines[i])
        if m and m.group(1) in done:
            j = i + 1
            while j < len(lines) and lines[j].startswith('"'):
                out_lines.append(lines[j]); j += 1
            if j < len(lines) and lines[j].startswith("msgstr"):
                out_lines.append('msgstr "%s"' % done[m.group(1)])
                j += 1
                while j < len(lines) and lines[j].startswith('"'):
                    j += 1
                i = j; continue
        i += 1
    open(a.out, "w", encoding="utf-8").write("\n".join(out_lines))
    print(f"\n採用 {len(done)} / 見送り {len(skipped)}  → {a.out}")
    for s, why in skipped[:8]:
        print(f"  見送り[{why}] {s[:60]}")


if __name__ == "__main__":
    main()
