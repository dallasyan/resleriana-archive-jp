"""Build the derived combat map for offline generated battles.

Reads the community master database (resleriana-db-main, no private data)
and emits an ASCII-coded combat_map.json next to the slim battle-master
tables. The map turns opaque effect/state/panel/research/emblem text into
machine-usable combat codes. Anything the parser cannot classify is kept as
``unmapped`` so the simulator stays crash-free and honest.

Usage:
    python build_combat_map.py <resleriana-db-jp-master-dir> <output-dir>
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def load(master: Path, name: str):
    return json.loads((master / f"{name}.json").read_text(encoding="utf-8-sig"))


TAG_INDEX: dict[str, int] = {}


FULLWIDTH_DIGITS = str.maketrans("0123456789", "0123456789")
FULLWIDTH_OFFSET = ord("\uff10") - ord("0")


def normalize(text: str) -> str:
    text = text or ""
    text = text.replace("<br>", ";").replace("<BR>", ";").replace("\n", ";")
    out = []
    for char in text:
        code = ord(char)
        if 0xFF10 <= code <= 0xFF19:
            out.append(chr(code - FULLWIDTH_OFFSET))
        elif char == "\uff05":
            out.append("%")
        elif char == "\uff0b":
            out.append("+")
        elif char == "\uff0d":
            out.append("-")
        elif char == "<":
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


def find_number(pattern: str, text: str) -> int:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else 0


ATTRS = {
    "斬": "slash", "斬属性": "slash", "打": "impact", "打属性": "impact",
    "突": "pierce", "突属性": "pierce", "火": "fire", "火属性": "fire",
    "氷": "ice", "氷属性": "ice", "雷": "lightning", "雷属性": "lightning",
    "風": "wind", "風属性": "wind",
}

AILMENTS = {
    "毒": "poison", "猛毒": "venom", "火傷": "burn", "麻痺": "paralysis",
    "眠り": "sleep", "睡眠": "sleep", "凍結": "frozen", "カチコチ": "frozen",
    "スタン": "stun", "気絶": "stun", "暗闇": "darkness", "挑発": "taunt",
}


def parse_conditions(text: str) -> list:
    conds = []
    for role, code in (("アタッカー", "attacker"), ("ブレイカー", "breaker"),
                       ("ディフェンダー", "defender"), ("サポーター", "supporter")):
        if ("自身が%sの時" % role) in text or ("かつ%sの時" % role) in text:
            conds.append({"cond": "role", "role": code})
    for name, code in ATTRS.items():
        if ("得意属性が%s" % name) in text or ("%s属性キャラ" % name) in text:
            conds.append({"cond": "attr", "attr": code})
    match = re.search(r"対象が(.{1,8}?)の時", text)
    if match:
        chunk = match.group(1)
        for keyword, code in list(AILMENTS.items()) + [("ブレイク", "broken"), ("弱点", "weak")]:
            if keyword in chunk:
                conds.append({"cond": "target_state", "state": code})
    match = re.search(r"HPが([0-9]+)%以上", text)
    if match:
        conds.append({"cond": "hp_above", "value": int(match.group(1))})
    if "HPが最大" in text:
        conds.append({"cond": "hp_above", "value": 100})
    match = re.search(r"バーストゲージが([0-9]+)%以上", text)
    if match:
        conds.append({"cond": "gauge_above", "value": int(match.group(1))})
    match = re.search(r"「(.+?)」タグを持つキャラ数に応じ", text)
    if match:
        conds.append({"cond": "tag_count", "tag": TAG_INDEX.get(match.group(1), 0), "min": 1})
    match = re.search(r"HPが([0-9]+)%以下", text)
    if match:
        conds.append({"cond": "hp_below", "value": int(match.group(1))})
    if "全体攻撃" in text:
        conds.append({"cond": "scope", "scope": "aoe"})
    if "単体攻撃" in text:
        conds.append({"cond": "scope", "scope": "single"})
    if "弱点" in text or "WEAK" in text:
        conds.append({"cond": "weak_hit"})
    if "ブレイク時" in text or "ブレイク状態" in text:
        conds.append({"cond": "target_broken"})
    if "クリティカル時" in text:
        conds.append({"cond": "crit"})
    if "撃破時" in text:
        conds.append({"cond": "ko"})
    if "ボス" in text and ("攻撃時" in text or "対象" in text):
        conds.append({"cond": "boss"})
    if "バーストパネル" in text:
        conds.append({"cond": "panel", "panel": "burst"})
    elif "プラスパネル" in text or "強化系パネル" in text:
        conds.append({"cond": "panel", "panel": "plus"})
    elif "弱体パネル" in text or "マイナスパネル" in text:
        conds.append({"cond": "panel", "panel": "minus"})
    return conds


def parse_duration(text: str) -> dict:
    out = {"dur_actions": 0, "dur_hits": 0, "perm": False}
    if "永続" in text:
        out["perm"] = True
    match = re.search(r"([0-9]+)回行動(開始|終了)するまで", text)
    if match:
        out["dur_actions"] = int(match.group(1))
    match = re.search(r"([0-9]+)回攻撃を受けるまで", text)
    if match:
        out["dur_hits"] = int(match.group(1))
    return out


def parse_common(text: str) -> dict:
    rate = 100
    match = re.search(r"付与率([0-9]+)%", text)
    if match:
        rate = int(match.group(1))
    elif "超高確率" in text:
        rate = 95
    elif "高確率" in text:
        rate = 85
    cap = find_number(r"上限([0-9]+)%", text)
    stack_max = find_number(r"上限([0-9]+)個", text)
    fixed = ("固定" in text)
    text_value = find_number(r"([0-9]+)%", text)
    return {
        "rate": rate, "cap": cap, "stack_max": stack_max, "fixed": fixed,
        "text_value": text_value,
        "conds": parse_conditions(text), **parse_duration(text),
    }


STAT_WORDS = [
    ("物攻", "patk"), ("物理攻撃", "patk"), ("魔攻", "matk"), ("魔法攻撃", "matk"),
    ("物防", "pdef"), ("物理防御", "pdef"), ("魔防", "mdef"), ("魔法防御", "mdef"),
    ("素早さ", "spd"), ("最大HP", "hp"), ("HP", "hp"),
]


BRACKET_SCOPES = [
    ("自身", "self"), ("味方全体", "all_allies"), ("味方全員", "all_allies"),
    ("敵全体", "all_enemies"), ("敵全員", "all_enemies"),
]

BRACKET_STATS = [
    ("物攻", "stat_up", "patk"), ("魔攻", "stat_up", "matk"),
    ("物防", "stat_up", "pdef"), ("魔防", "stat_up", "mdef"),
    ("素早さ", "stat_up", "spd"), ("最大HP", "stat_up", "hp"),
    ("スキルダメージ", "skill_damage", None), ("スキル威力", "skill_power", None),
    ("与ダメージ", "dealt_damage", None), ("被ダメージ", "taken_damage", None),
    ("受けるダメージ", "taken_damage", None),
    ("クリティカル確率", "crit_rate", None), ("クリティカルダメージ", "crit_damage", None),
    ("ブレイクダメージ", "break_damage", None),
    ("受ける回復量", "heal_received", None), ("与える回復量", "heal_given", None),
    ("バーストスキルダメージ", "burst_damage", None),
    ("毒耐性", "ailment_resist_one", "poison"), ("麻痺耐性", "ailment_resist_one", "paralysis"),
    ("暗闇耐性", "ailment_resist_one", "darkness"), ("眠り耐性", "ailment_resist_one", "sleep"),
    ("火傷耐性", "ailment_resist_one", "burn"), ("挑発耐性", "ailment_resist_one", "taunt"),
    ("状態異常耐性", "ailment_resist", None), ("状態異常無効", "ailment_immune", None),
    ("マイナス効果解除", "cleanse", None), ("マイナスパネル無効", "panel_null", None),
    ("HP回復", "heal", None), ("ダメージバフ", "dealt_damage", None),
]


def parse_bracket(text: str) -> dict | None:
    """Parse bracket-format effects like [scope/timing/stat]."""
    raw = normalize(text).strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        return None
    parts = raw[1:-1].split("/")
    scope = "self"
    conds: list = []
    for part in parts:
        for word, code in BRACKET_SCOPES:
            if word in part:
                scope = code
        for name, code in ATTRS.items():
            if len(name) > 1 and ("%s属性キャラ" % name) in part:
                scope = "attr_allies"
                conds.append({"cond": "attr", "attr": code})
        if "攻撃対象がブレイク中" in part or "ブレイク中" in part:
            conds.append({"cond": "target_broken"})
        if "ブレイク時" in part:
            conds.append({"cond": "target_broken"})
        if "クリティカル時" in part:
            conds.append({"cond": "crit"})
        if "撃破時" in part:
            conds.append({"cond": "ko"})
        if "被弾時" in part:
            conds.append({"cond": "on_damaged"})
        if "HPが100%未満" in part:
            conds.append({"cond": "hp_below", "value": 100})
    last = parts[-1]
    direction = -1 if ("ダウン" in last or "減少" in last) else 1
    for word, code, arg in BRACKET_STATS:
        if word in last:
            out: dict = {"code": code, "direction": direction,
                         "scope": scope, "conds": conds, **parse_common(raw)}
            if arg and code in ("stat_up",):
                out["stat"] = arg
            if arg and code == "ailment_resist_one":
                out["ailment"] = arg
            return out
    if "パネル" in last and "変換" in last:
        return {"code": "panel_convert", "scope": scope, "conds": conds, **parse_common(raw)}
    if "パネル" in last and ("生成" in last or "回復パネル" in last):
        return {"code": "panel_generate", "scope": scope, "conds": conds, **parse_common(raw)}
    return {"code": "unmapped", "scope": scope, "conds": conds, **parse_common(raw)}


def mark_foe(parsed: dict, raw: str) -> dict:
    """Flag debuff/grant effects explicitly aimed at foes.

    自身-targeted effects stay owner-side; bare 敵-wide text without 対象
    keeps the legacy owner-side behavior and is noted as a limitation.
    """
    if parsed.get("code") not in (None, "unmapped") and "自身" not in raw and \
            ("対象" in raw or "敵全体" in raw or "敵対象" in raw):
        parsed["foe"] = True
    return parsed


def parse_effect(text: str) -> dict:
    """Parse one effect/trait description into combat codes (ASCII only)."""
    bracket = parse_bracket(text)
    if bracket is not None:
        return bracket
    raw = normalize(text)
    base = parse_common(raw)
    if not raw or raw in ("state_change用",):
        return {"code": "unmapped", **base}
    for keyword, code in AILMENTS.items():
        if keyword in raw and "解除" not in raw and ("付与" in raw or "を" in raw):
            if keyword in ("毒", "猛毒", "火傷"):
                return {"code": "ailment_dot", "ailment": code, **base}
            return {"code": "ailment", "ailment": code, **base}
    if "マイナス効果" in raw and "解除" in raw or "状態異常" in raw and "解除" in raw:
        return {"code": "cleanse", **base}
    dispel_kinds = {"回避": "evade", "カウンター": "counter", "バリア": "barrier",
                    "再生": "regen", "挑発": "taunt", "物攻": "out", "魔攻": "out",
                    "物防": "defense", "魔防": "defense", "素早さ": "speed",
                    "強化効果": "out", "マイナス効果": "taken"}
    for word, kind in dispel_kinds.items():
        if word in raw and re.search(r"解除", raw):
            entry = {"code": "dispel", "dispel": kind, **base}
            if kind == "taunt":
                entry["ailment"] = "taunt"
            return entry
    if "再生" in raw:
        return {"code": "regen", **base}
    if "バリア" in raw:
        return {"code": "barrier", **base}
    if "回避" in raw:
        return {"code": "evade", **base}
    if "カウンター" in raw:
        return {"code": "counter", **base}
    if "反射" in raw:
        kind = "reflect_magic" if "魔法" in raw else "reflect_phys" if "物理" in raw else "reflect"
        return {"code": kind, **base}
    if "ダメージ無効" in raw or "無敵" in raw:
        return {"code": "null_damage", **base}
    if "蘇生" in raw or "復活" in raw:
        # No revive mechanic is modeled (KO has no recovery); leave unmapped.
        return {"code": "unmapped", **base}
    if "かばう" in raw or "身代わり" in raw:
        return {"code": "cover", **base}
    if "ターン入れ替え" in raw:
        return {"code": "turn_swap", **base}
    if "ターン" in raw and "消去" in raw:
        return {"code": "turn_erase", **base}
    if "追加攻撃" in raw:
        return {"code": "extra_attack", **base}
    if "変身" in raw:
        return {"code": "transform", **base}
    if "フィールド" in raw:
        return {"code": "field", **base}
    if "パネル生成" in raw or "パネルを生成" in raw:
        return {"code": "panel_generate", **base}
    if "パネル変換" in raw or "パネルを変換" in raw or "パネル変化" in raw:
        return {"code": "panel_convert", **base}
    if "パネル強化" in raw:
        return {"code": "panel_enhance", **base}
    if "アイテムゲージ" in raw and ("回復" in raw or "上昇" in raw):
        return {"code": "item_gauge", **base}
    if "バーストゲージ" in raw and ("回復" in raw or "上昇" in raw):
        return {"code": "burst_gauge", **base}
    if "アトリエ砲" in raw or "砲ダメージ" in raw:
        if "クリティカル" in raw:
            return {"code": "cannon_crit", **base}
        return {"code": "cannon_damage", **base}
    if "アイテム" in raw and "クリティカルダメージ" in raw:
        return {"code": "item_crit", **base}
    if "アイテム" in raw and ("ダメージ" in raw or "強化" in raw):
        return {"code": "item_damage", **base}
    if "アイテム" in raw and "回復" in raw:
        return {"code": "item_heal", **base}
    if "バーストゲージ" in raw and ("増加" in raw or "回復" in raw or "上昇" in raw) \
            and "減少" not in raw:
        return {"code": "burst_gauge", **base}
    if "貫通力" in raw:
        return {"code": "penetration", **base}
    if "ブレイクダメージ" in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw or "-" in raw) else 1
        scope = "taken_break" if ("被" in raw or "受ける" in raw) else "break_damage"
        return {"code": scope, "direction": direction, **base}
    if "ブレイクゲージ" in raw and "回復" in raw:
        return {"code": "break_gauge_heal", **base}
    if "クリティカルダメージ" in raw or "クリダメ" in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw) else 1
        scope = "taken_crit_damage" if ("受ける" in raw or "被" in raw) else "crit_damage"
        return {"code": scope, "direction": direction, **base}
    if "クリティカル率" in raw or "クリティカル確率" in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw) else 1
        return {"code": "crit_rate", "direction": direction, **base}
    if "スキル威力" in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw) else 1
        return {"code": "skill_power", "direction": direction, **base}
    if "ブレイク威力" in raw and ("アップ" in raw or "上昇" in raw):
        return {"code": "break_power", "direction": 1, **base}
    if "威力" in raw and ("アップ" in raw or "上昇" in raw):
        for name in sorted(ATTRS, key=len, reverse=True):
            if name in raw:
                entry = {"code": "skill_power", "direction": 1, **base}
                entry["conds"] = list(entry.get("conds") or []) + [{"cond": "skill_attr", "attr": ATTRS[name]}]
                return entry
    if "属性耐性" in raw and "アップ" in raw and "付与" in raw and "対象に" in raw:
        for name in sorted(ATTRS, key=len, reverse=True):
            if name in raw:
                return {"code": "on_hit_resist", "attr": ATTRS[name], **base}
    if "使用回数が1回" in raw:
        return {"code": "first_use_damage", **base}
    if "スキルダメージ" in raw or "バーストスキルダメージ" in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw or "-" in raw) else 1
        return {"code": "skill_damage", "direction": direction, **base}
    if "与ダメージ" in raw or "与えるダメージ" in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw) else 1
        return {"code": "dealt_damage", "direction": direction, **base}
    if "受けるダメージ" in raw or "被ダメージ" in raw:
        direction = 1 if ("アップ" in raw or "上昇" in raw or "増加" in raw or "+" in raw) else -1
        return {"code": "taken_damage", "direction": direction, **base}
    if "与えるHP回復量" in raw or "与える回復量" in raw:
        return {"code": "heal_given", **base}
    if "受けるHP回復量" in raw or "被回復量" in raw or "受ける回復量" in raw:
        return {"code": "heal_received", **base}
    if "耐性" in raw and ("ダウン" in raw or "減少" in raw or "-" in raw or "DOWN" in raw):
        for name, code in sorted(ATTRS.items(), key=lambda kv: -len(kv[0])):
            if name in raw:
                return {"code": "resist_down", "attr": code, **base}
        if "全属性" in raw:
            return {"code": "resist_down", "attr": "all", **base}
        return {"code": "resist_down", "attr": "unknown", **base}
    if "バーストゲージ" in raw and "減少" in raw:
        return {"code": "burst_gain_down", **base}
    STAT_EXTENDED = STAT_WORDS + [("攻撃力", "attack"), ("防御力", "defense")]
    # NOTE: bare 攻撃/防御 are deliberately excluded: they substring-match
    # timing words such as 攻撃前/攻撃後. Bare-form cases are covered by the
    # machine-EN fallback (e.g. "Reduces target's attack").
    if "対象" in raw or "敵全体" in raw or "敵対象" in raw:
        for word, stat in STAT_EXTENDED:
            if word in raw and ("ダウン" in raw or "減少" in raw or "低下" in raw or "DOWN" in raw):
                slot = {"patk": "out", "matk": "out", "pdef": "defense",
                        "mdef": "defense", "spd": "speed",
                        "attack": "out", "magic": "out", "defense": "defense",
                        "mental": "defense", "speed": "speed"}.get(stat)
                if slot:
                    return {"code": "target_debuff", "slot": slot, **base}
        if "ダメージ" in raw and ("ダウン" in raw or "減少" in raw or "DOWN" in raw) and "受ける" not in raw:
            return {"code": "target_debuff", "slot": "skill_damage", **base}
        if "受けるダメージ" in raw and ("アップ" in raw or "上昇" in raw or "UP" in raw):
            return {"code": "target_debuff", "slot": "taken", **base}
    for word, stat in STAT_EXTENDED:
        if word in raw and ("アップ" in raw or "上昇" in raw or "増加" in raw or "UP" in raw):
            return {"code": "stat_up", "stat": stat, **base}
        if word in raw and ("ダウン" in raw or "減少" in raw or "低下" in raw or "DOWN" in raw):
            return {"code": "stat_down", "stat": stat, **base}
    if "HPを回復" in raw or "HP回復" in raw:
        return {"code": "heal", **base}
    if "先駆け" in raw:
        return {"code": "pioneer", **base}
    if "与える強化効果量" in raw:
        return {"code": "potency_given_plus", **base}
    if "与えるマイナス効果量" in raw:
        return {"code": "potency_given_minus", **base}
    if "受ける強化効果量" in raw or "受けるマイナス効果量" in raw:
        return {"code": "potency_received", **base}
    if "与える効果量" in raw:
        return {"code": "potency_given_plus", **base}
    if "受ける効果量" in raw:
        return {"code": "potency_received", **base}
    if "状態異常耐性" in raw:
        return {"code": "ailment_resist", **base}
    for keyword, code in AILMENTS.items():
        if keyword + "耐性" in raw:
            return {"code": "ailment_resist_one", "ailment": code, **base}
    match = re.search(r"バーストゲージは([0-9]+)周分ストック可能", raw)
    if match:
        return {"code": "burst_stocks", "stocks": int(match.group(1)), **base}
    if "与える状態異常付与率" in raw:
        return {"code": "ailment_rate", **base}
    if "防御無視" in raw or "防御を無視" in raw:
        return {"code": "penetration", **base}
    if "吸収" in raw or "ドレイン" in raw:
        return {"code": "drain", **base}
    if "行動不能" in raw:
        return {"code": "ailment", "ailment": "stun", **base}
    if "100%を超えた" in raw and "変換" in raw:
        return {"code": "excess_crit", **base}
    if "カウンター攻撃から受けるダメージを無効" in raw:
        return {"code": "counter_immune", **base}
    if "命中率" in raw and ("ダウン" in raw or "減少" in raw or "-" in raw):
        return {"code": "accuracy_down", **base}
    if "手番を遅らせる" in raw or "手番遅延" in raw:
        return {"code": "delay_turn", **base}
    if "手番を早める" in raw:
        return {"code": "hasten_turn", **base}
    if "攻撃を受けた時" in raw and "HP" in raw and "回復" in raw:
        return {"code": "reactive_heal", **base}
    if "スキル発動後" in raw and "HP" in raw and "回復" in raw:
        return {"code": "post_skill_heal", **base}
    if "バーストスキルダメージ" in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw) else 1
        return {"code": "burst_damage", "direction": direction, **base}
    if ("物理ダメージ" in raw or "魔法ダメージ" in raw) and ("アップ" in raw or "上昇" in raw):
        return {"code": "skill_damage",
                "cat": "phys" if "物理" in raw else "magic",
                "direction": 1, **base}
    resist_attrs = []
    if "耐性+" in raw or "耐性アップ" in raw or re.search(r"耐性[+-]?[0-9]+%", raw):
        for name, code in ATTRS.items():
            if len(name) > 1 and name in raw:
                resist_attrs.append(code)
        if "全属性" in raw:
            resist_attrs = ["slash", "impact", "pierce", "fire", "ice", "lightning", "wind"]
        if "斬打突" in raw:
            resist_attrs.extend(["slash", "impact", "pierce"])
        if "火氷雷風" in raw:
            resist_attrs.extend(["fire", "ice", "lightning", "wind"])
        if resist_attrs:
            return {"code": "resist_up", "attrs": sorted(set(resist_attrs)), **base}
    return {"code": "unmapped", **base}


def detect_target(text: str) -> str:
    raw = normalize(text)
    if "自身" in raw and "味方" not in raw and "敵" not in raw:
        return "self"
    if "味方全員" in raw:
        return "all_allies"
    if "敵全員" in raw:
        return "all_enemies"
    if "スキル対象" in raw or "対象に" in raw or "対象の" in raw:
        return "skill_target"
    if "攻撃者" in raw:
        return "attacker"
    for scope in ("味方", "敵"):
        for stat_word in ("最大HP", "HP", "物攻", "魔攻", "素早さ"):
            for extreme in ("最も高い", "最も低い"):
                if stat_word in raw and extreme in raw and scope in raw:
                    return "extreme_%s_%s_%s" % (
                        "ally" if scope == "味方" else "enemy",
                        {"最大HP": "maxhp", "HP": "hp", "物攻": "patk",
                         "魔攻": "matk", "素早さ": "spd"}[stat_word],
                        "max" if extreme == "最も高い" else "min",
                    )
    if "ランダム" in raw:
        return "random"
    if "味方" in raw and ("1人" in raw or "単体" in raw):
        return "ally_one"
    if "敵" in raw and ("1体" in raw or "単体" in raw):
        return "enemy_one"
    return "context"


STATE_KEYWORDS = [
    ("再生", "regen"), ("バリア", "barrier"), ("回避", "evade"),
    ("カウンター", "counter"), ("反射", "reflect"), ("かばう", "cover"),
    ("身代わり", "cover"), ("ダメージ無効", "null_damage"), ("無敵", "null_damage"),
    ("蘇生", "revive"), ("復活", "revive"),
    ("パネル無効", "panel_null"), ("先駆け", "pioneer"),
    ("アウトレンジ", "range_out"), ("インレンジ", "range_in"),
    ("上限設定用ダミー", "dummy"), ("判定用ダミー", "dummy"),
    ("カウント", "counter_state"), ("入れ替えスキル禁止", "special"),
    ("戦艦バトル", "special"),
]

AILMENT_STATES = {
    "毒": "poison", "猛毒": "venom", "火傷": "burn", "麻痺": "paralysis",
    "眠り": "sleep", "カチコチ": "frozen", "スタン": "stun",
    "暗闇": "darkness", "挑発": "taunt", "ハイ・ドミナンス": "high_dominance",
}


def classify_state(row: dict) -> dict:
    state_type = row.get("state_change_type")
    name = row.get("name") or ""
    out = {"kind": "special", "unremovable": bool(row.get("is_unremovable"))}
    if name in AILMENT_STATES:
        out["kind"] = "ailment"
        out["ailment"] = AILMENT_STATES[name]
        return out
    if "耐性UP" in name or "耐性+" in name:
        for keyword, code in AILMENTS.items():
            if keyword in name:
                out["kind"] = "resist_up"
                out["ailment"] = code
                return out
        out["kind"] = "resist_up"
        return out
    for keyword, kind in STATE_KEYWORDS:
        if keyword in name:
            out["kind"] = kind
            if kind == "reflect":
                out["reflect"] = "magic" if "魔法" in name else "phys" if "物理" in name else "any"
            return out
    if state_type == 1:
        out["kind"] = "out"
    elif state_type == 2:
        out["kind"] = "taken"
    elif state_type == 4:
        out["kind"] = "special"
    else:
        out["kind"] = "special"
    return out


PANEL_BRANCH_RE = re.compile(r"(味方|敵)が獲得すると")


def parse_panel_branch(text: str, holder: str) -> list:
    ops = []
    chunks = re.split(r"[;；]", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or chunk in ("強化系パネルとして扱う", "効果なし", "書き換え用",
                                  "バーストスキル発動可能"):
            continue
        if "確定クリティカル" in chunk:
            ops.append({"op": "crit_force", "holder": holder})
            continue
        parsed = parse_effect(chunk)
        if parsed["code"] == "unmapped":
            ops.append({"op": "unmapped_panel", "holder": holder})
            continue
        parsed["holder"] = holder
        ops.append(parsed)
    return ops


def parse_panel(row: dict) -> dict:
    text = normalize(row.get("description") or "")
    branches = PANEL_BRANCH_RE.split(text)
    if len(branches) >= 5:
        ops = []
        ops.extend(parse_panel_branch(branches[2], "enemy" if branches[1] == "敵" else "ally"))
        ops.extend(parse_panel_branch(branches[4], "enemy" if branches[3] == "敵" else "ally"))
        return {"ops": ops}
    holder = "holder"
    return {"ops": parse_panel_branch(text, holder)}


QUOTED_BONUS_RE = re.compile(r"「([^」]*?)([+\-]){(\d+)}%?」?")
UNQUOTED_BONUS_RE = re.compile(r"([^\s、；「」]+?)([+\-]){(\d+)}%?")
UNQUOTED_HEAL_RE = re.compile(r"HPを{(\d+)}%回復")
UNQUOTED_GAUGE_RE = re.compile(r"(アイテム|バースト)ゲージを{(\d+)}%?(回復|上昇)")
HYPERLINK_RE = re.compile(r"\{hyperlink_id ([0-9]+)\}")
LAMP_LIGHT_RE = re.compile(r"「(.+?)」のスキルランプを(?:{(\d+)}|([0-9]+))個点灯")
SKILL_NAME_RE = re.compile(r"「([^」]+)」")

EVENT_WORDS = [
    ("バトル開始時", "battle_start"),
    ("WAVE開始時", "wave_start"),
    ("ターン開始時", "turn_start"),
    ("行動後", "post_attack"),
    ("スキル発動後", "skill_use"),
    ("スキル使用後", "skill_use"),
    ("いずれかのスキル使用後", "skill_use"),
    ("攻撃後", "post_attack"),
    ("攻撃前", "pre_attack"),
    ("攻撃を受けた時", "attacked"),
    ("HP回復を受けた時", "heal_received"),
    ("アイテム使用", "item_use"),
    ("WEAK攻撃後", "weak_hit"),
    ("WEAK攻撃時", "weak_hit"),
    ("撃破時", "ko"),
    ("クリティカル攻撃後", "crit"),
    ("クリティカル時", "crit"),
    ("ブレイク時", "break_hit"),
    ("ブレイク状態", "break_hit"),
    ("バーストスキル発動後", "party_burst"),
    ("状態異常が付与されている敵を攻撃後", "target_ailment_hit"),
]

PANEL_EVENT_WORDS = [
    ("バーストパネル", "burst"),
    ("プラスパネル", "plus"),
    ("強化系パネル", "plus"),
    ("弱体パネル", "minus"),
    ("マイナスパネル", "minus"),
]


def detect_event(chunk: str) -> tuple[str | None, list]:
    for word, event in EVENT_WORDS:
        if word in chunk:
            return event, []
    for word, panel in PANEL_EVENT_WORDS:
        if word in chunk and "獲得時" in chunk:
            return "panel_gain", [{"cond": "panel", "panel": panel}]
    return None, []


def detect_target_tag(chunk: str) -> str:
    if "自身" in chunk and "味方" not in chunk and "敵" not in chunk:
        return "self"
    if "味方全員" in chunk or "味方全体" in chunk:
        return "all_allies"
    if "敵全員" in chunk or "敵全体" in chunk:
        return "all_enemies"
    if "対象" in chunk:
        return "skill_target"
    if "攻撃者" in chunk:
        return "attacker"
    if "現在HPが最大の敵" in chunk or "現在HPが最も高い敵" in chunk:
        return "extreme_enemy_hp_max"
    if "現在HPが最小の敵" in chunk or "現在HPが最も低い敵" in chunk:
        return "extreme_enemy_hp_min"
    if "ブレイクゲージが最も高い敵" in chunk or "残りブレイクゲージが最も高い敵" in chunk:
        return "extreme_enemy_break_max"
    return "context"


EN_ATTRS = {"Slash": "slash", "Blunt": "impact", "Strike": "impact",
            "Pierce": "piercing", "Fire": "fire", "Ice": "ice",
            "Bolt": "lightning", "Lightning": "lightning", "Air": "wind", "Wind": "wind"}
EN_ROLES = {"Attacker": "attacker", "Breaker": "breaker",
            "Defender": "defender", "Supporter": "supporter"}
EN_AILMENTS = {"Poison": "poison", "Venom": "venom", "Burn": "burn",
               "Paralyz": "paralysis", "Paralysis": "paralysis", "Sleep": "sleep",
               "Blind": "darkness", "Darkness": "darkness", "Taunt": "taunt",
               "Frozen": "frozen", "Freeze": "frozen", "Freezing": "frozen",
               "Stun": "stun", "Stunned": "stun"}
EN_STATS = {"P.ATK": "attack", "M.ATK": "magic", "P.DEF": "defense",
            "M.DEF": "defense", "SPD": "speed", "HP": "hp",
            "attack": "attack", "defense": "defense", "magic": "magic",
            "speed": "speed"}


def parse_effect_en(text: str) -> dict:
    """Parse machine-translated English effect text into combat codes.

    Used only when the Japanese parse yields unmapped; disagreements
    where both parse are logged for review at build time.
    """
    raw = text or ""
    base: dict = {"rate": 100, "cap": 0, "stack_max": 0, "fixed": False,
                  "text_value": 0, "conds": [], "dur_actions": 0, "dur_hits": 0,
                  "perm": False}
    match = re.search(r"for ([0-9]+) turns?", raw)
    if match:
        base["dur_actions"] = int(match.group(1))
    for role, code in EN_ROLES.items():
        if re.search(r"\b%s\b" % role, raw):
            base["conds"].append({"cond": "role", "role": code})
    for name, code in sorted(EN_ATTRS.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"\b%s\b" % name, raw):
            base["conds"].append({"cond": "attr", "attr": code})
            break
    if "WEAK" in raw:
        base["conds"].append({"cond": "weak_hit"})
    attr = next((code for name, code in sorted(EN_ATTRS.items(), key=lambda kv: -len(kv[0]))
                 if re.search(r"\b%s\b" % name, raw)), "unknown")
    if "battle item" in raw.lower() and "critical damage" in raw.lower():
        return {"code": "item_crit", **base}
    if "battle item" in raw.lower() and "damage" in raw.lower():
        return {"code": "item_damage", "direction": 1, **base}
    if "Resistance Down" in raw and "target" in raw:
        return {"code": "resist_down", "attr": attr, **base}
    if "Resistance Up" in raw or "resistance +" in raw:
        return {"code": "resist_up", "attrs": [a for a in {attr} if a != "unknown"], **base}
    for stat_word, stat in EN_STATS.items():
        if re.search(r"(?:Reduces|Lowers|Decreases) (?:target'?s? )?%s\b" % re.escape(stat_word), raw):
            slot = {"attack": "out", "magic": "out", "defense": "defense",
                    "mental": "defense", "speed": "speed"}.get(stat)
            if slot:
                return {"code": "target_debuff", "slot": slot, **base}
    if re.search(r"[Rr]ecovery [Gg]iven", raw):
        return {"code": "heal_given", **base}
    if re.search(r"[Rr]ecovery [Rr]eceived", raw):
        return {"code": "heal_received", **base}
    if re.search(r"skill damage|damage buff", raw, re.I):
        return {"code": "skill_damage", "direction": -1 if re.search(r"[Rr]educ|[Dd]ecreas|[Dd]own", raw) else 1, **base}
    if re.search(r"Boosts damage to", raw):
        return {"code": "dealt_damage", "direction": 1, **base}
    if re.search(r"skill power", raw, re.I):
        return {"code": "skill_power", "direction": 1, **base}
    if re.search(r"critical damage (?:taken|received)|taken.+critical damage", raw, re.I):
        return {"code": "taken_crit_damage", "direction": 1, **base}
    if re.search(r"critical rate", raw, re.I):
        return {"code": "crit_rate", "direction": -1 if re.search(r"[Rr]educ|[Dd]ecreas|[Dd]own", raw) else 1, **base}
    if re.search(r"critical damage", raw, re.I):
        return {"code": "crit_damage", "direction": -1 if re.search(r"[Rr]educ|[Dd]ecreas|[Dd]own", raw) else 1, **base}
    for stat_word, stat in EN_STATS.items():
        if stat_word == "HP" and "ecover" in raw:
            continue
        match = re.search(r"(?:Boosts|Grants|Increases|Reduces|Lowers|Decreases) (?:.+? )?%s\b" % re.escape(stat_word), raw)
        if match:
            down = match.group(0).split()[0] in ("Reduces", "Lowers", "Decreases")
            if stat in ("attack", "magic", "defense", "mental", "speed"):
                return {"code": "stat_down" if down else "stat_up", "stat": stat, **base}
    if re.search(r"break damage", raw, re.I):
        return {"code": "break_damage", "direction": 1, **base}
    if re.search(r"penetrat", raw, re.I):
        return {"code": "penetration", **base}
    if re.search(r"\bheal\b|\bHeal\b|[Rr]estores (?:own |ally |allies )?HP", raw):
        return {"code": "heal", **base}
    for word, code in EN_AILMENTS.items():
        if word in raw and not re.search(r"%s Damage" % word, raw) and \
                re.search(r"[Ii]nflict|[Cc]aus|appl|[Gg]rant|[Ss]uffer", raw):
            return {"code": "ailment", "ailment": code, **base}
    if re.search(r"[Ee]vad|[Dd]odge", raw):
        return {"code": "evade", **base}
    if re.search(r"[Cc]ounter", raw):
        return {"code": "counter", **base}
    if re.search(r"[Rr]eflect", raw):
        return {"code": "reflect", **base}
    if re.search(r"[Bb]arrier", raw):
        return {"code": "barrier", **base}
    if re.search(r"[Rr]egen", raw):
        return {"code": "regen", **base}
    if re.search(r"[Rr]emov|[Cc]leanse|[Cc]ure|[Dd]ispel", raw):
        return {"code": "cleanse", **base}
    if re.search(r"[Ii]mmun|[Nn]ullif|[Ii]nvincible", raw):
        return {"code": "ailment_immune", **base}
    if re.search(r"[Ss]wap.{0,20}[Tt]urn|[Tt]urn.{0,20}[Ss]wap", raw):
        return {"code": "turn_swap", **base}
    if re.search(r"[Ee]xtra turn", raw):
        return {"code": "extra_turn_grant", "cond": "unconditional", **base}
    if re.search(r"[Ii]tem gauge", raw):
        return {"code": "item_gauge", **base}
    if re.search(r"[Bb]urst gauge", raw):
        if re.search(r"[Dd]ecreas|[Rr]educ|[Dd]own|[Ll]ess", raw):
            return {"code": "burst_gain_down", **base}
        return {"code": "burst_gauge", **base}
    return {"code": "unmapped", **base}


def parse_ability_row(ability: dict, name_index: dict, hyperlinks: dict,
                      lamp_ids: set | None = None) -> dict:
    """Parse one ability description into battle-long mods and triggers.

    Quoted 「X+{N}%」 segments resolve values positionally: {N} takes the
    Nth effect value of the ability row. Skill names resolve to ids via
    the skill name index; hyperlinks resolve via the hyperlink table.
    """
    desc = ability.get("description") or ""
    effects = ability.get("effects") or []

    def value_at(n: int) -> int:
        return int((effects[n] or {}).get("value") or 0) if 0 <= n < len(effects) else 0

    chunks = [c.strip() for c in normalize(desc).split(";") if c.strip()]
    mods: list = []
    triggers: list = []
    for chunk in chunks:
        # 「AまたはB」 conditions are alternatives: each condition-only
        # branch inherits the payload of branches that carry one.
        branches = expand_or_branches(chunk)
        for branch in branches:
            _parse_ability_branch(branch, conds_base=[], mods=mods, triggers=triggers,
                                  name_index=name_index, hyperlinks=hyperlinks,
                                  lamp_ids=lamp_ids, value_at=value_at)
    lamp_skills = [t.get("skill_variants") or [] for t in triggers if t.get("op") == "lamp_light"]
    for trigger in triggers:
        if trigger.get("op") == "lamp_bonus" and not trigger.get("skill_variants"):
            for variants in lamp_skills:
                if variants:
                    trigger["skill_variants"] = variants
                    break
    uses_max = find_number(r"発動上限([0-9]+)回", normalize(desc))
    if uses_max:
        for trigger in triggers:
            trigger["uses_max"] = uses_max
    return {"mods": mods, "triggers": triggers}


PAYLOAD_WORDS = ["追加攻撃", "パネルスキル", "点灯", "付与", "発動", "回復",
                 "変換", "生成", "入れ替える", "解除", "ゲージ", "バリア",
                 "再生", "カウンター", "回避", "蘇生", "復活", "変身"]


def split_payload(alt: str) -> tuple[str, str]:
    """Split an alternative into (condition part, payload part)."""
    best = -1
    for word in PAYLOAD_WORDS:
        index = alt.find(word)
        if index >= 0 and (best < 0 or index < best):
            best = index
    if best < 0:
        return alt, ""
    return alt[:best], alt[best:]


def gauge_effect_ids(skill_rows: list) -> dict[str, str]:
    """Effect ids that are the sole row of a gauge-granting skill.

    Shared ids like the burst-gauge grant then resolve unambiguously in
    multi-effect skills.
    """
    found: dict[str, str] = {}
    for row in skill_rows:
        summary = row.get("summary") or ""
        effects = row.get("effects") or []
        if len(effects) != 1:
            continue
        if "バーストゲージ" in summary and ("増加" in summary or "回復" in summary):
            found[str(effects[0].get("id"))] = "burst_gauge"
        elif "アイテムゲージ" in summary and ("増加" in summary or "回復" in summary):
            found[str(effects[0].get("id"))] = "item_gauge"
    return found


def gauge_behavior_value(summary: str, effects_list: list, gauge_ids: dict) -> tuple | None:
    """Gauge gain value: a known gauge effect id wins, else a lone row."""
    for code, keyword in (("burst_gauge", "バーストゲージ"), ("item_gauge", "アイテムゲージ")):
        if keyword not in summary or ("増加" not in summary and "回復" not in summary):
            continue
        for entry in effects_list:
            if gauge_ids.get(entry["id"]) == code:
                return code, entry["value"]
        if len(effects_list) == 1:
            return code, effects_list[0]["value"]
    return None


def expand_or_branches(chunk: str) -> list:
    if "または" not in chunk:
        return [chunk]
    alts = [a.strip() for a in re.split("または", chunk)]
    payloads = []
    cond_only = []
    for alt in alts:
        _, payload = split_payload(alt)
        if payload:
            payloads.append(payload)
        else:
            cond_only.append(alt)
    branches = list(alts)
    for cond in cond_only:
        for payload in payloads:
            combined = (cond + "、" + payload).strip()
            if combined not in branches:
                branches.append(combined)
    return branches


def _parse_ability_branch(branch: str, conds_base: list, mods: list, triggers: list,
                          name_index: dict, hyperlinks: dict, lamp_ids, value_at) -> None:
    event, event_conds = detect_event(branch)
    conds = list(conds_base) + parse_conditions(branch) + event_conds
    scope = "self"
    if "味方全員" in branch or "味方全体" in branch:
        scope = "all_allies"
    elif "敵全員" in branch or "敵全体" in branch:
        scope = "all_enemies"
    lamp_events = detect_all_events(branch)
    for skill_name, ph, num in LAMP_LIGHT_RE.findall(branch):
        variants = name_index.get(skill_name) or []
        if not variants:
            continue
        count = value_at(int(ph)) if ph else int(num)
        for lamp_event in lamp_events or ["battle_start"]:
            triggers.append({"event": lamp_event, "conds": conds,
                             "op": "lamp_light", "skill_variants": variants, "count": count})
    if "点灯数1個につき" in branch or "点灯数1個に付き" in branch:
        names = [n for n in SKILL_NAME_RE.findall(branch) if "スキルランプ" not in n and "点灯" not in n]
        lamp_variants = (name_index.get(names[0]) or []) if names else []
        segments = [(s, g, n) for s, g, n in QUOTED_BONUS_RE.findall(branch)]
        if not segments:
            fallback = re.search(r"(\S+?)\+{(\d+)}%?", branch)
            if fallback:
                segments = [(fallback.group(1), "+", fallback.group(2))]
        for seg, sign, num in segments:
            parsed = parse_effect(seg + ("アップ" if sign == "+" else "ダウン"))
            if parsed.get("code") in (None, "unmapped"):
                continue
            direction = -1 if sign == "-" else parsed.get("direction", 1)
            triggers.append({"event": None, "conds": conds, "op": "lamp_bonus",
                             "skill_variants": lamp_variants, "code": parsed["code"],
                             "direction": direction,
                             "per_lamp_value": value_at(int(num))})
    if "はじめのレンジを入れ替える" in branch:
        triggers.append({"event": "battle_start", "conds": conds, "op": "range_swap"})
    if "スキルランプの数に応じ" in branch:
        names = [n for n in SKILL_NAME_RE.findall(branch) if "スキルランプ" not in n]
        variants = []
        for name in names:
            variants.extend(name_index.get(name) or [])
        for seg, lo, hi in re.findall(r"「([^」]*?)\+([0-9]+)～([0-9]+).{0,2}」?", branch):
            parsed = parse_effect(seg + "アップ")
            if parsed.get("code") in (None, "unmapped"):
                continue
            triggers.append({"event": detect_event(branch)[0] or "pre_attack",
                             "conds": conds, "op": "lamp_scaled",
                             "skill_variants": variants, "code": parsed["code"],
                             "direction": parsed.get("direction", 1),
                             "lo_value": int(lo) * 100, "hi_value": int(hi) * 100,
                             "dur_actions": parsed.get("dur_actions", 0) or 1,
                             "dur_hits": parsed.get("dur_hits", 0)})
    for link_id in HYPERLINK_RE.findall(branch):
        skill_id = hyperlinks.get(str(link_id))
        if not skill_id:
            continue
        op = "panel_skill" if "パネルスキル" in branch else "extra_attack" if "追加攻撃" in branch else None
        if op is None:
            continue
        skill_names = [i for n in SKILL_NAME_RE.findall(branch) for i in (name_index.get(n) or [])]
        entry_conds = list(conds)
        if skill_names:
            entry_conds.append({"cond": "skill_ids", "skills": skill_names})
        trigger = {"event": event or "post_attack", "conds": entry_conds,
                   "op": op, "skill_id": skill_id,
                   "target": detect_target_tag(branch)}
        consume = find_number(r"バーストゲージをさらに([0-9]+)%?消費", branch)
        if consume:
            trigger["consume"] = consume
        triggers.append(trigger)
    if "パネル無効" in branch and "スキルランプ" not in branch:
        entry = {"code": "panel_null", "value": 0, "conds": conds, "scope": scope}
        if event is None:
            mods.append(entry)
        else:
            triggers.append({"event": event, "conds": conds, "op": "buff", "buff": entry})
    seen_segments = set()
    segments = [(s, g, n) for s, g, n in QUOTED_BONUS_RE.findall(branch)]
    for match in UNQUOTED_BONUS_RE.finditer(branch):
        seg, sign, num = match.group(1), match.group(2), match.group(3)
        if "スキルランプ" in seg or "上限" in seg or "Lv" in seg or "個" in seg:
            continue
        segments.append((seg, sign, num))
    for seg, sign, num in segments:
        if (seg, num) in seen_segments:
            continue
        seen_segments.add((seg, num))
        if "スキルランプ" in branch and "点灯数" in branch:
            continue
        hint = "アップ" if ("アップ" in seg or "上昇" in seg or sign == "+") else \
               "ダウン" if ("ダウン" in seg or "減少" in seg or "低下" in seg or sign == "-") else ""
        parsed = mark_foe(parse_effect(seg + hint), branch)
        if parsed.get("code") in (None, "unmapped"):
            continue
        direction = -1 if sign == "-" else parsed.get("direction", 1)
        entry = {"code": parsed["code"], "value": value_at(int(num)),
                 "conds": conds + (parsed.get("conds") or []),
                 "direction": direction,
                 "scope": scope,
                 "foe": parsed.get("foe", False),
                 "slot": parsed.get("slot"), "attr": parsed.get("attr"),
                 "rate": parsed.get("rate", 100), "cap": parsed.get("cap", 0),
                 "fixed": bool(parsed.get("fixed")),
                 "dur_actions": parsed.get("dur_actions", 0),
                 "dur_hits": parsed.get("dur_hits", 0),
                 "perm": bool(parsed.get("perm"))}
        if event is None:
            mods.append(entry)
        else:
            triggers.append({"event": event, "conds": conds, "op": "buff", "buff": entry})
    for num in UNQUOTED_HEAL_RE.findall(branch):
        entry = {"code": "heal", "value": value_at(int(num)), "conds": list(conds),
                 "direction": 1, "scope": scope}
        if event is None:
            mods.append(entry)
        else:
            triggers.append({"event": event, "conds": list(conds), "op": "buff", "buff": entry})
    for kind, num, _ in UNQUOTED_GAUGE_RE.findall(branch):
        code = "item_gauge" if kind == "アイテム" else "burst_gauge"
        entry = {"code": code, "value": value_at(int(num)), "conds": list(conds),
                 "direction": 1, "scope": scope}
        if event is None:
            mods.append(entry)
        else:
            triggers.append({"event": event, "conds": list(conds), "op": "buff", "buff": entry})
    if "状態異常無効" in branch:
        entry = {"code": "ailment_immune", "value": 0, "conds": list(conds), "scope": scope}
        if event is None:
            mods.append(entry)
        else:
            triggers.append({"event": event, "conds": list(conds), "op": "buff", "buff": entry})
    if "狙われやすく" in branch:
        entry = {"code": "aggro", "value": 20000, "conds": list(conds), "scope": scope}
        if event is None:
            mods.append(entry)
        else:
            triggers.append({"event": event, "conds": list(conds), "op": "buff", "buff": entry})
    return {"mods": mods, "triggers": triggers}


def detect_all_events(chunk: str) -> list:
    """Every trigger event named in a chunk (clauses often stack two)."""
    found = []
    for word, event in EVENT_WORDS:
        if word in chunk and event not in found:
            found.append(event)
    for word, panel in PANEL_EVENT_WORDS:
        if word in chunk and "獲得時" in chunk and "panel_gain" not in found:
            found.append("panel_gain")
    return found


def resolve_lamp_skill(name_index: dict, skill_name: str, lamp_ids: set | None = None) -> int | None:
    """Resolve a lamp skill name, preferring variants with lamp mechanics."""
    ids = name_index.get(skill_name) or []
    if lamp_ids:
        for skill_id in ids:
            if skill_id in lamp_ids:
                return skill_id
    return ids[0] if ids else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--machine", type=Path, default=None,
                        help="machine-translated master dir for EN fallback parsing")
    args = parser.parse_args()

    master: Path = args.master
    out: Path = args.output
    out.mkdir(parents=True, exist_ok=True)

    machine_effects: dict[str, str] = {}
    if getattr(args, "machine", None):
        try:
            for row in load(Path(args.machine), "effect"):
                if row.get("description"):
                    machine_effects[str(row.get("id"))] = row["description"]
        except (OSError, ValueError):
            pass
    disagreements = []
    effects = {}
    for row in load(master, "effect"):
        text = row.get("description") or ""
        parsed = mark_foe(parse_effect(text), text)
        if parsed.get("code") == "unmapped":
            en_text = machine_effects.get(str(row.get("id")), "")
            if en_text:
                en_parsed = parse_effect_en(en_text)
                if en_parsed.get("code") != "unmapped":
                    en_parsed["source"] = "en"
                    parsed = en_parsed
        else:
            en_text = machine_effects.get(str(row.get("id")), "")
            if en_text:
                en_parsed = parse_effect_en(en_text)
                if en_parsed.get("code") not in ("unmapped", parsed.get("code")):
                    disagreements.append((row.get("id"), parsed.get("code"),
                                          en_parsed.get("code")))
        if parsed.get("code") == "unmapped":
            popup = row.get("popup_text") or ""
            if "入れ替え" in popup:
                parsed["code"] = "turn_swap"
            elif "消失" in popup:
                parsed["code"] = "turn_erase"
            elif "短縮" in popup:
                parsed["code"] = "hasten_turn"
            elif "遅延" in popup:
                parsed["code"] = "delay_turn"
        parsed["target"] = detect_target(text)
        parsed["placeholder"] = "{0}" in text or "{value}" in text
        if row.get("field_effect_id"):
            parsed["field_effect_id"] = row.get("field_effect_id")
        effects[str(row["id"])] = parsed

    states = {}
    for row in load(master, "state_change"):
        states[str(row["id"])] = classify_state(row)

    panels = {}
    for row in load(master, "timeline_panel"):
        panels[str(row["id"])] = parse_panel(row)

    research = {}
    levels = {}
    for row in load(master, "research_effect_level"):
        levels.setdefault(str(row.get("research_effect_id")), {})[str(row.get("level"))] = {
            "value": row.get("value") or 0,
            "status_buffs": row.get("status_buffs") or [],
            "equipment_buffs": row.get("equipment_tool_buffs") or [],
        }
    for row in load(master, "research"):
        group = str(row.get("group_id"))
        research.setdefault(group, {})[str(row.get("level"))] = {
            "effects": [levels.get(str(effect_id), {}) for effect_id in row.get("research_effect_ids") or []],
        }

    emblems = {}
    for row in load(master, "emblem"):
        emblems[str(row["id"])] = {
            "group": row.get("emblem_group_id"),
            "parsed": parse_effect((row.get("effect_name") or "").replace("{}", "{0}")),
        }
    emblem_values: dict[str, list] = {}
    for row in load(master, "emblem_rarity"):
        emblem_values.setdefault(str(row.get("emblem_id")), []).append({
            "rarity": row.get("rarity"),
            "value": row.get("value") or 0,
            "status_buffs": row.get("status_buffs") or [],
            "equipment_buffs": row.get("equipment_tool_buffs") or [],
        })

    abilities = {}
    for row in load(master, "ability"):
        abilities[str(row["id"])] = {
            "effects": [
                {"id": e.get("id"), "value": e.get("value") or 0,
                 "limit": e.get("limit_count")}
                for e in row.get("effects") or []
            ],
        }

    leader_conditions = {}
    for row in load(master, "leader_skill_condition"):
        leader_conditions[str(row["id"])] = {
            "tags": row.get("character_tag_ids") or [],
            "roles": row.get("roles") or [],
            "attrs": row.get("attack_attributes") or [],
            "series": row.get("series_ids") or [],
            "genders": row.get("gender_ids") or [],
        }

    tools = {}
    for row in load(master, "battle_tool"):
        tools[str(row["id"])] = {
            "attrs": [int(a) for a in row.get("attack_attributes") or []],
        }

    mix = [
        {
            "attrs": sorted([int(row.get("first_item_attack_attribute") or 0),
                             int(row.get("second_item_attack_attribute") or 0)]),
            "rank": row.get("rank"),
            "skill_id": row.get("skill_id"),
        }
        for row in load(master, "battle_tool_mix")
    ]

    skill_rows = load(master, "skill")
    name_index: dict[str, list] = {}
    for row in skill_rows:
        name = row.get("name")
        if name:
            name_index.setdefault(name, []).append(row.get("id"))
    lamp_skill_ids = set()
    for row in skill_rows:
        desc = normalize(row.get("description") or "") + normalize(row.get("summary") or "")
        if "スキルランプ" in desc:
            lamp_skill_ids.add(row.get("id"))
    hyperlinks = {}
    for row in load(master, "hyperlink"):
        hyperlinks[str(row.get("id"))] = row.get("skill_id")
    skills = {}
    for row in skill_rows:
        desc = normalize(row.get("description") or "")
        summary = normalize(row.get("summary") or "")
        lamp_max = find_number(r"最大([0-9]+)個点灯", desc + summary)
        skills[str(row["id"])] = {
            "timeline": int(row.get("skill_target_type") or 0) == 6,
            "break_pct": (row.get("break_power") or 0) / 100,
            "power_pct": (row.get("power") or 0) / 100,
            "dest": row.get("skill_destination") or 0,
            "range_move": "out" if "アウトレンジに移動" in summary else
                          "in" if "インレンジに移動" in summary else "",
            "lamp_max": lamp_max,
            "transform": "変身する" in desc,
        }

    # Dominant-behavior families for empty-description skill-grant effects.
    # Each id was assigned by co-occurrence with skill summaries; the sim
    # applies a family behavior only when the skill summary contains the
    # confirming clause keywords below.
    families = {
        "91000925": ("post_heal_allies", ["攻撃後", "味方全員", "HPを回復"]),
        "91001007": ("cleanse_self_pre", ["攻撃前", "自身", "解除"]),
        "91001607": ("cleanse_self_pre", ["攻撃前", "自身", "解除"]),
        "91002004": ("item_gauge", ["攻撃後", "アイテムゲージ"]),
        "91000904": ("atk_crit_damage", ["この攻撃の", "クリティカルダメージ"]),
        "91001378": ("atk_crit_damage", ["この攻撃の", "クリティカルダメージ"]),
        "91000907": ("weak_break_up", ["WEAK", "ブレイクダメージ"]),
        "91001263": ("weak_break_up", ["WEAK", "ブレイクダメージ"]),
        "91000926": ("post_heal_self", ["攻撃後", "自身", "HPを回復"]),
        "91000908": ("post_break_up_self", ["攻撃後", "自身", "ブレイクダメージ"]),
        "91001135": ("post_break_up_self", ["自身", "ブレイクダメージ"]),
        "91000966": ("post_taken_up_target", ["攻撃後", "対象", "受けるダメージ"]),
        "91001337": ("atk_penetration", ["この攻撃の", "貫通力"]),
        "91000938": ("pre_resist_down_target", ["攻撃前", "対象", "耐性ダウン"]),
        "91000903": ("weak_dealt_up", ["WEAK", "ダメージ"]),
        "91000927": ("scaling_damage", ["ほどダメージアップ"]),
    }
    state_name_to_id = {}
    for row in load(master, "state_change"):
        name = row.get("name") or ""
        if name and name not in state_name_to_id:
            state_name_to_id[name] = row.get("id")
    TAG_INDEX.clear()
    for row in load(master, "character_tag"):
        if row.get("name"):
            TAG_INDEX[row["name"]] = row.get("id")
    gauge_ids = gauge_effect_ids(skill_rows)
    skill_behavior: dict[str, list] = {}
    for row in load(master, "skill"):
        if not str(row.get("id"))[0] in "12":
            continue
        summary = row.get("summary") or ""
        behaviors = []
        effects_list = [{"id": str(e.get("id")), "value": e.get("value") or 0}
                        for e in row.get("effects") or []]
        if "エクストラターンを生成" in summary:
            grant: dict = {"code": "extra_turn_grant", "value": 0}
            if "クリティカル攻撃後" in summary:
                grant["cond"] = "on_crit"
            else:
                match = re.search(r"「(.+?)」がLv[0-9]+の時", summary)
                if match:
                    grant["cond"] = "state_present"
                    grant["state_id"] = state_name_to_id.get(match.group(1), 0)
                else:
                    grant["cond"] = "unconditional"
            behaviors.append(grant)
        for effect in row.get("effects") or []:
            family = families.get(str(effect.get("id")))
            if not family:
                continue
            code, keywords = family
            if all(keyword in summary for keyword in keywords):
                entry: dict = {"code": code, "value": effect.get("value") or 0}
                if code == "pre_resist_down_target":
                    for name, attr in ATTRS.items():
                        if len(name) > 1 and name in summary:
                            entry["attr"] = attr
                            break
                    else:
                        entry["attr"] = "all" if "全属性" in summary else "unknown"
                if code == "scaling_damage":
                    if "HPが多い" in summary:
                        entry["cond"] = "hp_high"
                    elif "HPが少ない" in summary:
                        entry["cond"] = "hp_low"
                    elif "敵が多い" in summary:
                        entry["cond"] = "many_foes"
                    elif "敵が少ない" in summary:
                        entry["cond"] = "few_foes"
                behaviors.append(entry)
        gauge_found = gauge_behavior_value(summary, effects_list, gauge_ids)
        if gauge_found:
            code, value = gauge_found
            if not any(b.get("code") == code for b in behaviors):
                behaviors.append({"code": code, "value": value})
        if behaviors:
            skill_behavior[str(row["id"])] = behaviors


    ability_parsed = {}
    for row in load(master, "ability"):
        ability_parsed[str(row["id"])] = parse_ability_row(row, name_index, hyperlinks, lamp_skill_ids)

    data = {
        "states": states,
        "panels": panels,
        "effects": effects,
        "research": research,
        "emblems": emblems,
        "emblem_values": emblem_values,
        "mix": mix,
        "tools": tools,
        "skills": skills,
        "skill_behavior": skill_behavior,
        "abilities": abilities,
        "ability_parsed": ability_parsed,
        "hyperlinks": hyperlinks,
        "leader_conditions": leader_conditions,
    }
    (out / "combat_map.json").write_text(
        json.dumps(data, separators=(",", ":")), encoding="utf-8"
    )

    mapped = sum(1 for parsed in effects.values() if parsed["code"] != "unmapped")
    print("effects: %d total, %d mapped (%.1f%%)" % (
        len(effects), mapped, 100.0 * mapped / max(len(effects), 1)))
    en_mapped = sum(1 for parsed in effects.values() if parsed.get("source") == "en")
    print("effects mapped via machine EN: %d" % en_mapped)
    print("JP/EN disagreements: %d" % len(disagreements))
    for item in disagreements[:20]:
        print("  disagree:", item)
    state_kinds: dict[str, int] = {}
    for parsed in states.values():
        state_kinds[parsed["kind"]] = state_kinds.get(parsed["kind"], 0) + 1
    print("states: %d total %s" % (len(states), state_kinds))
    print("panels: %d research groups: %d emblems: %d mix rows: %d skills: %d" % (
        len(panels), len(research), len(emblems), len(mix), len(skills)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
