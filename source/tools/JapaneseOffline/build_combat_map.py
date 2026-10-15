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
    "眠り": "sleep", "ねむり": "sleep", "睡眠": "sleep", "凍結": "frozen", "カチコチ": "frozen",
    "スタン": "stun", "気絶": "stun", "暗闇": "darkness", "挑発": "taunt",
    "王の威光": "high_dominance", "ハイ・ドミナンス": "high_dominance",
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
    target_chunk = None
    match = re.search(r"対象が(.{1,32}?)の時", text)
    if match:
        target_chunk = match.group(1)
    else:
        match = re.search(r"(.{1,12}?)状態の敵への", text)
        if match:
            target_chunk = match.group(1)
    if target_chunk:
        target_states = []
        for keyword, code in sorted(AILMENTS.items(), key=lambda item: -len(item[0])):
            if keyword in target_chunk and code not in target_states:
                target_states.append(code)
        for keyword, code in (("ブレイク", "broken"), ("弱点", "weak")):
            if keyword in target_chunk and code not in target_states:
                target_states.append(code)
        if len(target_states) > 1 and re.search(r"[・、]|または|もしくは", target_chunk):
            conds.append({"cond": "target_any_state", "states": target_states})
        else:
            conds.extend({"cond": "target_state", "state": state}
                         for state in target_states)
    quoted_state = re.search(r"対象に「(.+?)」が付与", text)
    if quoted_state:
        state_name = quoted_state.group(1)
        state = next((code for keyword, code in sorted(
            AILMENTS.items(), key=lambda item: -len(item[0])
        ) if keyword in state_name), None)
        if state:
            conds.append({"cond": "target_state", "state": state})
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
    # Membership gates (「TAG」の時 / 「TAG」の味方...): the tagged member
    # (or tagged allies for party scopes) must carry the character tag.
    # Only real tag names qualify so skill/state quotes never match.
    for match in re.finditer(r"「([^」]+?)」の(時|味方|対象|敵)", text):
        tag_id = TAG_INDEX.get(match.group(1), 0)
        if tag_id and not any(
                cond.get("cond") == "tag" and cond.get("tag") == tag_id for cond in conds):
            conds.append({"cond": "tag", "tag": tag_id})
    match = re.search(r"HPが([0-9]+)%以下", text)
    if match:
        conds.append({"cond": "hp_below", "value": int(match.group(1))})
    match = re.search(r"対象のマイナス効果が([0-9]+)個以上", text)
    if match:
        conds.append({"cond": "target_debuff_count", "min": int(match.group(1))})
    if "被弾時" in text:
        conds.append({"cond": "on_damaged"})
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
    out = {
        "dur_actions": 0,
        "dur_action_phase": None,
        "dur_hits": 0,
        "perm": False,
    }
    if "永続" in text:
        out["perm"] = True
    match = re.search(r"([0-9]+)回行動(開始|終了)するまで", text)
    if match:
        out["dur_actions"] = int(match.group(1))
        out["dur_action_phase"] = "start" if match.group(2) == "開始" else "end"
    match = re.search(r"([0-9]+)回攻撃を受けるまで", text)
    if match:
        out["dur_hits"] = int(match.group(1))
    if not out["dur_hits"]:
        # Passive-voice variant (1回攻撃されるまで) and the compact
        # parenthesized form ({0}%/3回) both count received hits.
        match = re.search(r"([0-9]+)回攻撃されるまで", text)
        if match:
            out["dur_hits"] = int(match.group(1))
        else:
            match = re.search(r"/([0-9]+)回\)", text)
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
    fixed = ("固定" in text or "強化効果量変化の効果を受けない" in text)
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
    if ("マイナス効果無効" in raw
            or "マイナス効果の付与を受け付けなくなる" in raw):
        return {"code": "ailment_immune", **base}
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
    if "バーストスキルダメージ" in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw or "-" in raw) else 1
        return {"code": "burst_damage", "direction": direction, **base}
    if ("受ける物理攻撃スキルダメージ" in raw
            or "受ける魔法攻撃スキルダメージ" in raw):
        direction = 1 if ("アップ" in raw or "上昇" in raw or "+" in raw) else -1
        attack_type = "physical" if "受ける物理攻撃スキルダメージ" in raw else "magic"
        return {"code": "taken_damage", "direction": direction,
                "attack_type": attack_type, **base}
    if "スキルダメージ" in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw or "-" in raw) else 1
        return {"code": "skill_damage", "direction": direction, **base}
    if "属性攻撃から受けるダメージ" in raw:
        for name, attr in sorted(ATTRS.items(), key=lambda item: -len(item[0])):
            if len(name) > 1 and name in raw:
                return {"code": "resist_down", "attr": attr, **base}
        return {"code": "resist_down", "attr": "unknown", **base}
    if "属性ダメージ" in raw and "受ける" not in raw:
        attrs = []
        for name, attr in sorted(ATTRS.items(), key=lambda item: -len(item[0])):
            if len(name) > 1 and name in raw and attr not in attrs:
                attrs.append(attr)
        if attrs:
            direction = -1 if ("ダウン" in raw or "減少" in raw or "-" in raw) else 1
            return {"code": "dealt_damage", "direction": direction,
                    "attrs": attrs, **base}
    if ("物理攻撃ダメージ" in raw or "魔法攻撃ダメージ" in raw) and "受ける" not in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw or "-" in raw) else 1
        attack_type = "physical" if "物理攻撃ダメージ" in raw else "magic"
        return {"code": "dealt_damage", "direction": direction,
                "attack_type": attack_type, **base}
    if "受ける" in raw and "属性ダメージ" in raw:
        attrs = []
        for name, attr in sorted(ATTRS.items(), key=lambda item: -len(item[0])):
            if len(name) > 1 and name in raw and attr not in attrs:
                attrs.append(attr)
        direction = 1 if ("アップ" in raw or "上昇" in raw or "+" in raw) else -1
        entry = {"code": "taken_damage", "direction": direction, **base}
        if attrs:
            entry["attrs"] = attrs
        if "物理攻撃" in raw:
            entry["attack_type"] = "physical"
        elif "魔法攻撃" in raw:
            entry["attack_type"] = "magic"
        return entry
    if "受ける物理攻撃ダメージ" in raw or "受ける魔法攻撃ダメージ" in raw:
        direction = 1 if ("アップ" in raw or "上昇" in raw or "+" in raw) else -1
        attack_type = "physical" if "受ける物理攻撃ダメージ" in raw else "magic"
        return {"code": "taken_damage", "direction": direction,
                "attack_type": attack_type, **base}
    if "対象が被ダメージUP状態" in raw:
        return {"code": "dealt_damage", "direction": 1, **base}
    if (("ダメージ+" in raw or "ダメージUP" in raw or "ダメージアップ" in raw)
            and "受ける" not in raw and "被ダメージ" not in raw):
        direction = -1 if ("ダウン" in raw or "減少" in raw or "-" in raw) else 1
        return {"code": "dealt_damage", "direction": direction, **base}
    if "与ダメージ" in raw or "与えるダメージ" in raw:
        direction = -1 if ("ダウン" in raw or "減少" in raw or "-" in raw) else 1
        return {"code": "dealt_damage", "direction": direction, **base}
    if "受けるダメージ" in raw or "被ダメージ" in raw:
        direction = 1 if ("アップ" in raw or "上昇" in raw or "増加" in raw or "+" in raw) else -1
        return {"code": "taken_damage", "direction": direction, **base}
    if "与えるHP回復量" in raw or "与える回復量" in raw:
        return {"code": "heal_given", **base}
    if "受けるHP回復量" in raw or "被回復量" in raw or "受ける回復量" in raw:
        return {"code": "heal_received", **base}
    if "回復力" in raw and ("アップ" in raw or "上昇" in raw or "+" in raw):
        return {"code": "heal_given", **base}
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
                    return {"code": "target_debuff", "slot": slot,
                            "stat": stat, **base}
        if "ダメージ" in raw and ("ダウン" in raw or "減少" in raw or "DOWN" in raw) and "受ける" not in raw:
            return {"code": "target_debuff", "slot": "skill_damage", **base}
        if "受けるダメージ" in raw and ("アップ" in raw or "上昇" in raw or "UP" in raw):
            return {"code": "target_debuff", "slot": "taken", **base}
    for word, stat in STAT_EXTENDED:
        match = re.search(re.escape(word) + r"\s*([+-])\s*(?:\{(?:value|[0-9]+)\}|[0-9]+)", raw)
        if match:
            return {"code": "stat_up" if match.group(1) == "+" else "stat_down",
                    "stat": stat, **base}
    for word, stat in STAT_EXTENDED:
        if word in raw and ("アップ" in raw or "上昇" in raw or "増加" in raw or "UP" in raw):
            return {"code": "stat_up", "stat": stat, **base}
        if word in raw and ("ダウン" in raw or "減少" in raw or "低下" in raw or "DOWN" in raw):
            return {"code": "stat_down", "stat": stat, **base}
    if "スキル発動後" in raw and "HP" in raw and "回復" in raw:
        return {"code": "post_skill_heal", **base}
    if "攻撃を受けた時" in raw and "HP" in raw and "回復" in raw:
        return {"code": "reactive_heal", **base}
    if "HPを回復" in raw or "HP回復" in raw:
        return {"code": "heal", **base}
    if "先駆け" in raw:
        return {"code": "pioneer", **base}
    if re.search(r"与える強化効果(の効果)?量", raw):
        return {"code": "potency_given_plus", **base}
    if re.search(r"与えるマイナス効果(の効果)?量", raw):
        return {"code": "potency_given_minus", **base}
    if (re.search(r"受ける強化効果(の効果)?量", raw)
            or re.search(r"受けるマイナス効果(の効果)?量", raw)):
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
    turns = find_number(r"([0-9]+)(?:手番|ターン)", raw)
    has_turn_unit = "手番" in raw or "ターンを" in raw
    if has_turn_unit and re.search(r"遅らせ|遅め|遅延", raw):
        return {"code": "delay_turn", "turns": turns, **base}
    if has_turn_unit and re.search(r"早め|早ま", raw):
        return {"code": "hasten_turn", "turns": turns, **base}
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
    ("回復無効", "heal_block"),
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
    text = normalize(row.get("description") or name)
    parsed = mark_foe(parse_effect(text), text)
    parsed["placeholder"] = "{0}" in text or "{value}" in text
    out = {"kind": "special", "unremovable": bool(row.get("is_unremovable")),
           "effect": parsed}

    if name in AILMENT_STATES:
        out["kind"] = "ailment"
        out["ailment"] = AILMENTS[name]
        out["potency_kind"] = "ailment"
        return out

    # Effect-immunity markers (プラス効果無効 etc.) carry no buff slot but
    # the game grants them as states (enemy burst 22002371 deals 920002),
    # and their presence drives grant_blocked_by_immunity. Classify them as
    # inert-but-grantable immunity instead of leaving them special/inert.
    if name in ("プラス効果無効", "相手からの効果無効"):
        out.update({"kind": "immunity", "direction": 1,
                    "potency_kind": "none"})
        return out

    if "耐性UP" in name or "耐性+" in name:
        for keyword, code in sorted(AILMENTS.items(), key=lambda item: -len(item[0])):
            if keyword in name:
                out["kind"] = "resist_up"
                out["ailment"] = code
                out["potency_kind"] = "out"
                return out
        for keyword, attr in sorted(ATTRS.items(), key=lambda item: -len(item[0])):
            if keyword in name:
                out.update({"kind": "resist_elem", "attr": attr,
                            "potency_kind": "out"})
                return out
        out["kind"] = "resist_up"
        out["potency_kind"] = "out"
        return out

    for keyword, kind in STATE_KEYWORDS:
        if keyword in name:
            out["kind"] = "special" if kind == "revive" else kind
            out["potency_kind"] = "out"
            if kind == "reflect":
                out["reflect"] = "magic" if "魔法" in name else "phys" if "物理" in name else "any"
            return out

    code = parsed.get("code")
    direction = int(parsed.get("direction", -1 if code == "stat_down" else 1) or 1)
    if code in ("potency_received", "potency_given_plus", "potency_given_minus"):
        direction = -1 if ("DOWN" in text or "ダウン" in text
                           or "減少" in text or "低下" in text
                           or re.search(r"-\s*(?:\{value\}|\{[0-9]+\})", text)) else 1
    if code == "delay_turn" and text.startswith("攻撃後、対象のターンを"):
        out.update({"kind": "delay_turn_attack", "direction": 1,
                    "potency_kind": "none"})
        return out
    slot_kinds = {
        "skill_damage": "skill_damage", "dealt_damage": "skill_damage",
        "skill_power": "skill_power", "crit_rate": "crit_rate",
        "crit_damage": "crit_damage", "break_damage": "break_up",
        "taken_break": "taken_break", "taken_crit_damage": "taken_crit_damage",
        "penetration": "penetration", "burst_damage": "burst_damage",
        "taken_damage": "taken", "heal_given": "recovery_given",
        "heal_received": "recovery_received", "resist_up": "resist_up",
        "resist_down": "resist_down", "ailment_resist": "resist_up",
        "ailment_resist_one": "resist_up", "ailment_immune": "ailment_immune",
        "pioneer": "pioneer", "item_damage": "item_damage",
        "item_crit": "item_crit", "item_heal": "item_heal",
        "cannon_damage": "cannon_damage", "cannon_crit": "cannon_crit",
        "ailment": "ailment", "ailment_dot": "ailment",
        "reactive_heal": "reactive_heal", "post_skill_heal": "post_skill_heal",
        "cleanse": "cleanse_turn_start",
        "regen": "regen", "barrier": "barrier", "evade": "evade",
        "reflect": "reflect", "reflect_magic": "reflect", "reflect_phys": "reflect",
        "cover": "cover", "null_damage": "null_damage", "counter": "counter",
        "break_power": "break_power", "panel_null": "panel_null",
        "potency_given_plus": "potency_given_plus",
        "potency_given_minus": "potency_given_minus",
        "potency_received": "potency_received",
    }

    if code in ("stat_up", "stat_down"):
        stat = {
            "patk": "attack", "matk": "magic", "pdef": "defense",
            "mdef": "mental", "spd": "speed",
        }.get(parsed.get("stat"), parsed.get("stat"))
        if stat in ("attack", "magic", "defense", "mental"):
            out.update({"kind": "stat", "stat": stat, "direction": direction,
                        "potency_kind": "out" if direction > 0 else "taken"})
            return out
        if stat == "hp":
            # Max-HP grants ride a present-but-inert buff: no battle stat
            # slot consumes hp, and mid-battle max-HP raising stays unmodeled.
            out.update({"kind": "stat", "stat": stat, "direction": direction,
                        "potency_kind": "out" if direction > 0 else "taken"})
            return out
        if stat == "speed":
            out.update({"kind": "speed", "direction": direction,
                        "potency_kind": "out" if direction > 0 else "taken"})
            return out

    if code == "target_debuff":
        slot = parsed.get("slot")
        stat = {"patk": "attack", "matk": "magic", "pdef": "defense",
                "mdef": "mental", "spd": "speed"}.get(
                    parsed.get("stat"), parsed.get("stat")
                )
        if stat in ("attack", "magic", "defense", "mental"):
            out.update({"kind": "stat", "stat": stat, "direction": -1,
                        "potency_kind": "taken"})
            return out
        if stat == "speed":
            out.update({"kind": "speed", "direction": -1,
                        "potency_kind": "taken"})
            return out
        if slot == "skill_damage":
            kind, direction = "skill_damage", -1
        elif slot == "taken":
            kind, direction = "taken", 1
        elif slot == "defense":
            kind, direction = "defense", -1
        elif slot == "speed":
            kind, direction = "speed", -1
        elif slot == "out":
            kind, direction = "out", -1
        else:
            kind = "special"
        if kind != "special":
            out.update({"kind": kind, "direction": direction,
                        "potency_kind": "taken"})
            return out

    if code in slot_kinds:
        kind = slot_kinds[code]
        potency_kind = "out"
        if code in ("resist_down", "ailment_resist_one"):
            potency_kind = "taken"
        elif code in ("ailment", "ailment_dot"):
            potency_kind = "ailment"
        elif code == "taken_damage":
            potency_kind = "taken" if direction > 0 else "out"
        elif code == "potency_received":
            potency_kind = "taken" if direction < 0 else "out"
        elif code == "potency_given_minus":
            potency_kind = "taken"
        elif direction < 0:
            potency_kind = "taken"
        out.update({"kind": kind, "direction": direction,
                    "potency_kind": potency_kind})
        for key in ("stat", "attr", "ailment", "reflect"):
            if parsed.get(key) is not None:
                out[key] = parsed[key]
        for key in ("attrs", "attack_type", "scope"):
            if parsed.get(key) is not None:
                out[key] = parsed[key]
        if code == "ailment_resist_one":
            out["ailment"] = parsed.get("ailment")
        if code in ("reflect_magic", "reflect_phys"):
            out["reflect"] = "magic" if code == "reflect_magic" else "phys"
        return out

    # state_change_type only says positive/negative/ailment. Unknown states
    # are left inert instead of being treated as generic damage buffs.
    out["state_change_type"] = state_type
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
RANGE_BONUS_RE = re.compile(
    r"([^;；「」]*?)([+\-])([0-9]+)(%)?[～〜~]([0-9]+)(%)?"
)
UNQUOTED_HEAL_RE = re.compile(r"HPを{(\d+)}%回復")
UNQUOTED_GAUGE_RE = re.compile(r"(アイテム|バースト|アトリエ砲)ゲージを{(\d+)}%?(回復|上昇|増加)")
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
                  "text_value": 0, "conds": [], "dur_actions": 0,
                  "dur_action_phase": None, "dur_hits": 0, "perm": False}
    match = re.search(r"for ([0-9]+) turns?", raw)
    if match:
        base["dur_actions"] = int(match.group(1))
        base["dur_action_phase"] = "end"
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
    if re.search(r"[Dd]elay.{0,30}turn|turn.{0,30}[Dd]elay", raw):
        return {"code": "delay_turn", **base}
    if re.search(r"[Hh]asten.{0,30}turn|turn.{0,30}[Hh]asten", raw):
        return {"code": "hasten_turn", **base}
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
                                  lamp_ids=lamp_ids, value_at=value_at,
                                  scale_source=chunk)
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


def dynamic_range_scale(branch: str, conds: list) -> dict | None:
    """Describe common passive ranges driven by party tags or owner speed."""
    tag_condition = next(
        (condition for condition in conds if condition.get("cond") == "tag_count"),
        None,
    )
    people = re.search(r"([0-9]+)[～〜~]([0-9]+)人で多いほど増加", branch)
    if tag_condition:
        return {
            "kind": "tag_count",
            "tag": int(tag_condition.get("tag", 0) or 0),
            "min_count": int(people.group(1)) if people else 1,
            "max_count": int(people.group(2)) if people else 5,
        }
    speed = re.search(r"素早さ([0-9]+)[～〜~]([0-9]+)で多いほど増加", branch)
    if speed:
        return {
            "kind": "speed",
            "min_count": int(speed.group(1)),
            "max_count": int(speed.group(2)),
        }
    return None


def expand_dual_stat_entry(entry: dict, text: str) -> list[dict]:
    """Split combined physical/magic stat bonuses into both stat slots."""
    if entry.get("code") not in ("stat_up", "stat_down", "stat_flat"):
        return [entry]
    for first, second, first_stat, second_stat in (
        ("物攻", "魔攻", "attack", "magic"),
        ("物防", "魔防", "defense", "mental"),
    ):
        if first in text and second in text:
            return [
                {**entry, "stat": first_stat},
                {**entry, "stat": second_stat},
            ]
    return [entry]


def expand_multi_slot_entry(entry: dict, segment: str, hint: str) -> list[dict]:
    """Split ・-joined multi-slot segments into one entry per slot.

    Covers stat pairs (物攻・魔攻), mixed damage slots (スキルダメージ・
    ブレイクダメージ), stat/speed mixes (物攻・素早さ), and longer runs
    (物攻・魔攻・物防・魔防). Each part re-parses for its own code; parts
    that do not parse are dropped. 基礎-prefixed parts map to flat stats.
    """
    if "・" not in segment:
        return [entry]
    parts = [part for part in re.split("・", segment) if part]
    if len(parts) < 2:
        return [entry]
    stat_map = {
        "patk": "attack", "matk": "magic", "pdef": "defense",
        "mdef": "mental", "spd": "speed",
    }
    expanded = []
    for part in parts:
        parsed = parse_effect(part + hint)
        if parsed.get("code") in (None, "unmapped"):
            continue
        variant = dict(entry)
        variant["code"] = parsed["code"]
        for key in ("stat", "slot", "attr", "ailment"):
            if parsed.get(key) is not None:
                variant[key] = stat_map.get(parsed[key], parsed[key])
        if "基礎" in part and variant.get("code") in ("stat_up", "stat_down"):
            variant["code"] = "stat_flat"
        expanded.append(variant)
    return expanded or [entry]


def _parse_ability_branch(branch: str, conds_base: list, mods: list, triggers: list,
                          name_index: dict, hyperlinks: dict, lamp_ids, value_at,
                          scale_source: str | None = None) -> None:
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
                              "dur_action_phase": parsed.get("dur_action_phase"),
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
            mods.extend(expand_dual_stat_entry(entry, branch))
        else:
            for variant in expand_dual_stat_entry(entry, branch):
                triggers.append({
                    "event": event,
                    "conds": conds,
                    "op": "buff",
                    "buff": variant,
                })
    if "先駆け" in branch:
        mods.append({"code": "pioneer", "value": 0, "conds": conds, "scope": scope})
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
        cap_percent = find_number(r"上限([0-9]+)%", branch)
        stack_max = find_number(r"上限([0-9]+)個", branch)
        duration = parse_duration(branch)
        if cap_percent:
            parsed["cap"] = cap_percent * 100
        elif parsed.get("cap"):
            parsed["cap"] = int(parsed["cap"]) * 100
        if stack_max:
            parsed["stack_max"] = stack_max
        for duration_field in (
            "dur_actions", "dur_action_phase", "dur_hits", "perm"
        ):
            if duration.get(duration_field):
                parsed[duration_field] = duration[duration_field]
        if (cap_percent or stack_max) and not parsed.get("dur_actions") and not parsed.get("dur_hits"):
            parsed["perm"] = True
        direction = -1 if sign == "-" else parsed.get("direction", 1)
        entry = {"code": parsed["code"], "value": value_at(int(num)),
                  "conds": conds + (parsed.get("conds") or []),
                  "direction": direction,
                  "scope": scope,
                  "stat": {
                      "patk": "attack",
                      "matk": "magic",
                      "pdef": "defense",
                      "mdef": "mental",
                      "spd": "speed",
                  }.get(parsed.get("stat"), parsed.get("stat")),
                  "foe": parsed.get("foe", False),
                  "slot": parsed.get("slot"), "attr": parsed.get("attr"),
                  "rate": parsed.get("rate", 100), "cap": parsed.get("cap", 0),
                  "stack_max": parsed.get("stack_max", 0),
                  "fixed": bool(parsed.get("fixed")),
                  "dur_actions": parsed.get("dur_actions", 0),
                  "dur_action_phase": parsed.get("dur_action_phase"),
                  "dur_hits": parsed.get("dur_hits", 0),
                  "perm": bool(parsed.get("perm"))}
        for variant in expand_multi_slot_entry(entry, seg, hint):
            if event is None:
                mods.append(variant)
            else:
                triggers.append({"event": event, "conds": conds, "op": "buff", "buff": variant})
    for match in RANGE_BONUS_RE.finditer(branch):
        source_text = scale_source or branch
        source_conds = parse_conditions(source_text)
        scale = dynamic_range_scale(source_text, conds + source_conds)
        if scale is None:
            continue
        segment, sign, minimum, low_percent, maximum, high_percent = match.groups()
        minimum_value = int(minimum)
        maximum_value = int(maximum)
        hint = "アップ" if sign == "+" else "ダウン"
        parsed = mark_foe(parse_effect(segment + hint), branch)
        if parsed.get("code") in (None, "unmapped"):
            continue
        if "基礎" in segment and parsed.get("code") in ("stat_up", "stat_down"):
            parsed["code"] = "stat_flat"
            parsed["stat"] = {
                "patk": "attack",
                "matk": "magic",
                "pdef": "defense",
                "mdef": "mental",
            }.get(parsed.get("stat"), parsed.get("stat"))
        multiplier = (
            100
            if (low_percent or high_percent) and parsed.get("code") != "stat_flat"
            else 1
        )
        scale["min_value"] = minimum_value * multiplier
        scale["max_value"] = maximum_value * multiplier
        duration = parse_duration(branch)
        if not (
            duration.get("dur_actions")
            or duration.get("dur_hits")
            or duration.get("perm")
        ):
            duration = parse_duration(source_text)
        cap_percent = find_number(r"上限([0-9]+)%", branch + source_text)
        stack_max = find_number(r"上限([0-9]+)個", branch)
        range_conds = list(conds)
        for condition in source_conds:
            if condition.get("cond") == "tag_count" and condition not in range_conds:
                range_conds.append(condition)
        entry = {
            "code": parsed["code"],
            "value": scale["min_value"],
            "scale": scale,
            "conds": range_conds + (parsed.get("conds") or []),
            "direction": -1 if sign == "-" else parsed.get("direction", 1),
            "scope": scope,
            "stat": {
                "patk": "attack",
                "matk": "magic",
                "pdef": "defense",
                "mdef": "mental",
                "spd": "speed",
            }.get(parsed.get("stat"), parsed.get("stat")),
            "foe": parsed.get("foe", False),
            "slot": parsed.get("slot"),
            "attr": parsed.get("attr"),
            "rate": parsed.get("rate", 100),
            "cap": cap_percent * 100 if cap_percent else 0,
            "stack_max": stack_max,
            "fixed": bool(parsed.get("fixed")),
            "dur_actions": duration.get("dur_actions", 0),
            "dur_action_phase": duration.get("dur_action_phase"),
            "dur_hits": duration.get("dur_hits", 0),
            "perm": bool(duration.get("perm")),
        }
        if (cap_percent or stack_max) and not entry["dur_actions"] and not entry["dur_hits"]:
            entry["perm"] = True
        range_event = event or detect_event(source_text)[0]
        entries = expand_dual_stat_entry(entry, segment)
        if range_event is None:
            mods.extend(entries)
        else:
            for variant in entries:
                triggers.append({
                    "event": range_event,
                    "conds": range_conds,
                    "op": "buff",
                    "buff": variant,
                })
    for num in UNQUOTED_HEAL_RE.findall(branch):
        entry = {"code": "heal", "value": value_at(int(num)), "conds": list(conds),
                 "direction": 1, "scope": scope}
        if event is None:
            mods.append(entry)
        else:
            triggers.append({"event": event, "conds": list(conds), "op": "buff", "buff": entry})
    for kind, num, _ in UNQUOTED_GAUGE_RE.findall(branch):
        code = ("item_gauge" if kind == "アイテム" else "burst_gauge"
                if kind == "バースト" else "cannon_gauge")
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
    for target_text, payload_text, num in re.findall(
            r"(?:(.+?)へ)?与える(.+?)の効果量\{([0-9]+)\}[%％]?アップ", branch):
        entry = parse_grant_potency(target_text or "", payload_text,
                                    value_at(int(num)))
        if entry is not None:
            entry["conds"] = list(conds)
            entry["scope"] = scope
            mods.append(entry)
    return {"mods": mods, "triggers": triggers}


# Combat buff kinds amplified by generic buff-enhancement traits. Granted
# values scale uniformly across stat and damage slots (verified: one
# skill's 物攻/魔攻/スキルダメージ grants share one factor), so combat
# traits match broadly here; barrier/evade/heal/ailment/cleanse/immunity
# and potency bookkeeping stay excluded (barriers match base values).
GRANT_POTENCY_COMBAT_KINDS = [
    "stat", "speed", "skill_damage", "dealt_damage", "skill_power",
    "crit_rate", "crit_damage", "break_up", "break_power", "taken",
    "taken_break", "taken_crit_damage", "penetration", "burst_damage",
    "resist_down", "resist_up", "resist_elem", "recovery_given",
    "recovery_received", "regen", "reflect", "reflect_magic",
    "reflect_phys", "cover", "null_damage",
]
GRANT_POTENCY_DAMAGE_KINDS = [
    "skill_damage", "dealt_damage", "skill_power", "crit_damage",
    "crit_rate", "break_up", "break_power",
]


def parse_grant_potency(target_text: str, payload_text: str, value: int) -> dict | None:
    """Parse equipment buff-enhancement traits (Xへ与えるY強化の効果量アップ).

    The holder amplifies buffs it grants to X-gated targets. Combat
    traits (damage/stat/resist wording) match broadly across grant kinds;
    item/cannon traits stay narrow. Returns a grant_potency mod.
    """
    if not value:
        return None
    gate: dict = {}
    for role, code in (("アタッカー", "attacker"), ("ブレイカー", "breaker"),
                       ("ディフェンダー", "defender"), ("サポーター", "supporter")):
        if role in (target_text or ""):
            gate["role"] = code
            break
    attrs = []
    for name, code in sorted(ATTRS.items(), key=lambda item: -len(item[0])):
        if len(name) > 1 and ("得意属性が%s" % name) in (target_text or ""):
            if code not in attrs:
                attrs.append(code)
    if attrs:
        gate["attrs"] = attrs
    tags = []
    for quoted in re.findall(r"「([^」]+)」", target_text or ""):
        tag_id = TAG_INDEX.get(quoted, 0)
        if tag_id and tag_id not in tags:
            tags.append(tag_id)
    if tags:
        gate["tags"] = tags
    kinds: list = []
    if "戦闘アイテム" in payload_text:
        kinds.append("item_damage")
    elif "アトリエ砲" in payload_text:
        kinds.append("cannon_damage")
    else:
        kinds.extend(GRANT_POTENCY_COMBAT_KINDS)
    if not kinds:
        return None
    return {"code": "grant_potency", "value": int(value), "kinds": kinds,
            "stats": [], "gate": gate, "direction": 1, "scope": "self"}


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


SKILL_GRANT_QUOTED_RE = re.compile(r"「([^」]+)」")
SKILL_GRANT_VALUE_RE = re.compile(r"([+\-−])?(?:\{([0-9]+)\}|([0-9]+))[%％]?")

# Synonym cores for state matching (effect text and state rows use
# different words for the same slot; 与ダメージ behaves as skill damage).
GRANT_CORE_SYNONYMS = {
    "スキルダメージ": ["与ダメージ"],
    "与ダメージ": ["スキルダメージ"],
    "物攻": ["物理攻撃"],
    "魔攻": ["魔法攻撃"],
    "物防": ["物理防御"],
    "魔防": ["魔法防御"],
    "受ける物理攻撃ダメージ": ["受ける物理攻撃スキルダメージ"],
    "受ける魔法攻撃ダメージ": ["受ける魔法攻撃スキルダメージ"],
    "与える強化効果DOWN": ["与える強化効果量DOWN"],
    "受ける強化効果DOWN": ["受ける強化効果量DOWN"],
    "強化効果DOWN": ["強化効果量DOWN"],
}

# Capture-verified pins for mechanically identical duplicate states.
# Keyed (skill_id, core, cap_percent); consulted before generic matching
# so wire ids stay faithful.
GRANT_STATE_OVERRIDES = {
    (14003647, "物防", 0): 610467,
    (14003647, "魔防", 0): 610468,
    (12003229, "クリティカルダメージ", 60): 610361,
    (12001748, "火属性耐性", 0): 920030,
    # Identical 被ダメージDOWN duplicates: the wire shows the older row.
    (22001725, "被ダメージDOWN", 0): 910045,
    (24001562, "被ダメージDOWN", 0): 910045,
    (20010058, "被ダメージDOWN", 0): 910045,
    # Crit/vulnerability grants whose text order differs from effect order.
    (11003560, "カチコチ", 0): 610052,
    (11003560, "クリティカルダメージ", 15): 610431,
    (11003637, "物防", 30): 610462,
    (11003637, "魔防", 30): 610463,
    # Stack/cap era duplicates where the wire keeps the older row.
    (12003017, "魔防", 0): 610301,
    (11003124, "魔防", 30): 610327,
    (12003072, "魔攻", 100): 610303,
    (14003130, "魔防", 0): 610322,
}

STAT_PART_WORDS = [
    ("物攻", "attack"), ("物理攻撃", "attack"), ("魔攻", "magic"),
    ("魔法攻撃", "magic"), ("物防", "defense"), ("物理防御", "defense"),
    ("魔防", "mental"), ("魔法防御", "mental"), ("素早さ", "speed"),
]


def build_grant_state_index(state_rows: list) -> dict:
    """Index state_change rows by name for skill-grant resolution."""
    index: dict[str, list] = {}
    for row in state_rows:
        name = row.get("name") or ""
        if not name:
            continue
        index.setdefault(name, []).append(row)
    return index


# Grant-state ids observed most often across captured setup states
# (808 setups, 2026-10-14): the game reuses a small set of generic rows
# for skill grants while same-named duplicates serve specific sources.
# 910049:3600, 910048:3014, 910039:2621, 910040:2346, 910007:1777,
# 910132:1772, 610467/610468:2262, 910171:3138, 940006:1624.
GRANT_STATE_PRIOR = frozenset({
    910049, 910048, 910039, 910040, 910007, 910132, 610467, 610468,
    910171, 940006, 910045,
})


def match_grant_state(core: str, direction: int, clause: str,
                      state_index: dict, states_map: dict | None = None,
                      skill_id_hint: int = 0, alt_cores: tuple = (),
                      cap_override=None) -> dict | None:
    """Resolve a grant core (e.g. 物防, 回避, 暗闇) to a state_change row.

    Scores exact/prefix/substring name matches with direction, stack, and
    cap agreement plus a frequency prior for the game's workhorse grant
    rows; ties fall back to the newest id. Returns None when nothing
    scores. cap_override carries a segment-local cap percent when one
    clause grants several capped stats (e.g. 上限30% defenses with an
    上限10% HP grant).
    """
    if cap_override is not None:
        cap_match = re.search(
            r"上限([0-9]+)[%％]", "上限%d%%" % int(cap_override // 100))
    else:
        cap_match = re.search(r"上限([0-9]+)[%％]", clause)
    stack_match = re.search(r"上限([0-9]+)個", clause)
    # Kindle kinds carry buff slots; special/dummy/counter states are never
    # granted as combat buffs (they are markers, judgments, or panels).
    # Potency states resolve through the classified potency kinds below.
    GRANTABLE_KINDS = {
        "stat", "speed", "skill_damage", "crit_rate", "crit_damage",
        "break_up", "taken_break", "taken_crit_damage", "taken",
        "penetration", "burst_damage", "resist_down", "resist_up",
        "resist_elem", "recovery_given", "recovery_received",
        "item_damage", "item_crit", "item_heal", "cannon_damage",
        "cannon_crit", "ailment", "regen", "barrier", "evade", "reflect",
        "reflect_magic", "reflect_phys", "cover", "null_damage",
        "counter", "break_power", "reactive_heal", "post_skill_heal",
        "cleanse_turn_start", "ailment_immune", "heal_block", "panel_null",
        "potency_given", "potency_given_plus", "potency_given_minus",
        "potency_received", "immunity",
    }
    best = None
    best_key = None
    # State rows omit 属性 (火属性耐性) while skill text keeps it
    # (火属性耐性); try both spellings. Slot synonyms (与ダメージ /
    # スキルダメージ etc.) name the same slot with different state rows,
    # so all spellings compete and the best-scoring row wins.
    cores = [core]
    for spelling in (core,) + tuple(alt_cores or ()):
        squashed = spelling.replace("属性", "")
        if squashed not in cores:
            cores.append(squashed)
        if spelling not in cores:
            cores.append(spelling)
    direct_spellings = {core, core.replace("属性", "")}
    for name, rows in state_index.items():
        for row in rows:
            desc = row.get("description") or ""
            # Resistance grants name an ailment/element only to select the
            # resisted axis; non-resistance rows must not win on the bare
            # keyword (e.g. 火傷耐性- must pick 910086, never burn 940006).
            if "耐性" in core and "耐性" not in name and "耐性" not in desc:
                continue
            # Counter grants name the mechanic; damage rows whose text
            # merely mentions countering must not win (810001's カウンター状態,
            # not 710030's conditional damage buff).
            if core == "カウンター" and "カウンター" not in name:
                continue
            base = 0
            name_prefix = False
            for variant in cores:
                # Cross-word synonym matches (与ダメージ for a スキルダメージ
                # core) score below same-wording matches: eras reuse words
                # per slot, but the skill's own word is stronger evidence.
                synonym = variant not in direct_spellings
                for text in (name, desc):
                    hit = 0
                    if text == variant:
                        hit = 3
                    elif variant and text.startswith(variant):
                        hit = 2
                        if text is name:
                            name_prefix = True
                    elif variant and variant in text:
                        hit = 1
                    elif text and variant and text in variant:
                        # Reversed containment for prefixed cores
                        # (受ける強化効果量DOWN).
                        hit = 2
                    if hit and synonym:
                        hit = max(hit - 1, 0)
                    base = max(base, hit)
            if not base:
                continue
            score = base
            # A state NAME beginning with the core is near-exact evidence
            # (カウンター状態 for カウンター); this carries directionless
            # mechanic states over the grant threshold.
            if name_prefix:
                score += 1
            classified = (states_map or {}).get(str(row.get("id", 0) or 0)) or {}
            if classified.get("kind") not in GRANTABLE_KINDS:
                continue
            try:
                row_direction = classified.get("direction", None)
                row_direction = int(row_direction) if row_direction is not None else None
            except (TypeError, ValueError):
                row_direction = None
            if row_direction is None:
                pass
            elif row_direction == direction:
                score += 2
            elif (direction < 0 and classified.get("potency_kind") == "taken"
                    and any(word in clause for word in ("対象", "敵", "相手"))):
                # Foe-targeted debuffs (resist_down etc.) classify with a
                # positive direction; the clause target marks agreement.
                score += 2
            elif (direction < 0 and classified.get("kind") == "recovery_received"
                    and any(word in clause for word in ("対象", "敵", "相手"))):
                # Healing-received reductions are foe debuffs with the same
                # conventional direction split (720011, not 920005).
                score += 2
            else:
                score -= 2
            if bool(row.get("is_unremovable")) != ("解除不可" in clause):
                score -= 2
            # No-duplicate rows (重複不可) lose plain grants (800232 over
            # 800236 for an unmarked skill2-taken grant).
            if "(重複不可)" in desc and "重複不可" not in clause:
                score -= 2
            elif "(重複不可)" in desc and "重複不可" in clause:
                score += 1
            # Conditional states ((突), (火), ...) only match clauses naming
            # the same condition.
            conditional = re.search(r"[(（]([^)）]*属性[^)）]*)[)）]", name + desc)
            if conditional:
                if conditional.group(1) in clause:
                    score += 2
                else:
                    score -= 3
            # の時 conditional prefixes (攻撃対象がブレイク状態の時、) are
            # decisive when the clause names them, and disqualifying when
            # it does not (e.g. 910064 vs generic skill-damage rows).
            desc_prefix = desc.split("、", 1)[0] if "の時" in desc.split("、", 1)[0] else ""
            if not desc_prefix:
                for text in (name, desc):
                    found = re.search(r"(.+の時)(?:、|$)", text)
                    if found:
                        desc_prefix = found.group(1)
                        break
            if desc_prefix:
                if desc_prefix in clause:
                    score += 6
                else:
                    score -= 4
            # Role-qualified rows (アタッカー与ダメージUP) win clauses naming
            # the role; generic rows lose some specificity there (610021).
            role_words = ("アタッカー", "ディフェンダー", "サポーター", "ブレイカー")
            row_roles = {word for word in role_words if word in name or word in desc}
            clause_roles = {word for word in role_words if word in clause}
            if row_roles & clause_roles:
                score += 4
            elif row_roles:
                score -= 3
            elif clause_roles:
                score -= 2
            # Mechanic-qualified rows lose clauses that never name each
            # mechanic (カウンターかばう needs かばう in text, not just
            # カウンター, so plain counter grants pick 810001).
            for mechanic in ("かばう", "身代わり", "カウンター"):
                if ((mechanic in name or mechanic in desc)
                        and mechanic not in clause and mechanic not in core):
                    score -= 2
            # Probabilistic rows need textual probability: a plain grant
            # picks the deterministic row (810001 over chance-based 810110).
            if (("確率" in name or "確率" in desc) and "確率" not in clause
                    and "付与率" not in clause):
                score -= 2
            desc_flat = desc.replace("％", "%")
            if cap_match:
                if ("上限%s%%" % cap_match.group(1)) in desc_flat:
                    score += 2
            elif re.search(r"上限[0-9]+%", desc_flat):
                score -= 2
            if stack_match:
                row_stack = None
                try:
                    row_stack = (classified.get("effect") or {}).get("stack_max")
                    row_stack = int(row_stack) if row_stack is not None else None
                except (TypeError, ValueError):
                    row_stack = None
                if ("上限%s個" % stack_match.group(1)) in desc:
                    score += 2
                elif row_stack is not None and row_stack != int(stack_match.group(1)):
                    # Same slot reissued with different stack caps resolves
                    # by stack agreement (上限2個 MDEF 610301/610322).
                    score -= 2
            elif re.search(r"上限[0-9]+個", desc):
                score -= 2
            try:
                prior_id = int(row.get("id", 0) or 0)
            except (TypeError, ValueError):
                prior_id = 0
            if prior_id in GRANT_STATE_PRIOR:
                score += 2
            if "固定" in clause:
                effect = classified.get("effect") or {}
                if effect.get("fixed"):
                    score += 1
                else:
                    score -= 1
            # Era-duplicate fixed rows (910193) lose to the observed
            # workhorse twin (910045) through the frequency prior above;
            # inherently fixed slots with no ordinary twin (最大HPUP)
            # keep full name agreement.
            # Duplicate states are re-issued per era; prefer the newest
            # candidate when scores tie (verified across the Score 33-1 set).
            key = (score, int(row.get("id", 0) or 0))
            if best_key is None or key > best_key:
                best_key = key
                best = row
    if best is None or (best_key or (0, 0))[0] < 3:
        return None
    return best


def match_grant_ailment(core: str, clause: str, states_map: dict,
                        state_index: dict | None = None) -> int | None:
    """Resolve an ailment core to a grantable state id.

    Grantor rows (their description hands the ailment out, e.g. 毒攻撃's
    攻撃後、対象に「毒」を付与) are excluded: granting the ailment itself
    needs the dot state (e.g. 940007).
    """
    ailment = next((code for keyword, code in sorted(
        AILMENTS.items(), key=lambda item: -len(item[0])
    ) if keyword in core), None)
    if ailment is None:
        return None
    duration = parse_duration(clause)
    candidates = []
    for key, entry in (states_map or {}).items():
        effect = entry.get("effect") or {}
        if (effect.get("ailment") or entry.get("ailment")) != ailment:
            continue
        if entry.get("kind") != "ailment":
            continue
        raw_desc = None
        if state_index:
            for _rows in (state_index or {}).values():
                for _row in _rows:
                    try:
                        if int(_row.get("id", 0) or 0) == int(key):
                            raw_desc = str(_row.get("description") or "")
                            break
                    except (TypeError, ValueError):
                        continue
                if raw_desc is not None:
                    break
        if raw_desc and ("を付与" in raw_desc or "で付与" in raw_desc):
            continue
        # Conditional-on-ailment rows (対象にXが付与されている時、...) are
        # payoffs for the ailment, not the ailment itself (e.g. 510258's
        # frozen-conditional crit buff is never a frozen grant).
        if raw_desc and "が付与されている時" in raw_desc:
            continue
        score = 1
        if duration.get("dur_actions") and effect.get("dur_actions") == duration["dur_actions"]:
            score += 2
        if duration.get("dur_hits") and effect.get("dur_hits") == duration["dur_hits"]:
            score += 2
        candidates.append((score, -int(key), int(key)))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


def skill_grant_scope(clause: str) -> tuple:
    """Return (scope, target_tags, target_attrs, target_roles, extreme).

    Scopes mirror the runtime resolver vocabulary. Enemy-perspective
    相手全員 maps to all_enemies (owner-relative, like 敵全体).
    """
    tags: list = []
    attrs: list = []
    roles: list = []
    if "物攻が最も高い味方" in clause:
        return "extreme_ally_patk_max", tags, attrs, roles, True
    if "魔攻が最も高い味方" in clause or "魔法攻撃が最も高い味方" in clause:
        return "extreme_ally_matk_max", tags, attrs, roles, True
    for tag_name, tag_id in sorted(TAG_INDEX.items(), key=lambda item: -len(item[0])):
        if tag_name and ("「%s」の" % tag_name) in clause:
            if tag_id not in tags:
                tags.append(tag_id)
    for name, code in sorted(ATTRS.items(), key=lambda item: -len(item[0])):
        if len(name) > 1 and ("得意属性が%s" % name) in clause:
            if code not in attrs:
                attrs.append(code)
    if "ディフェンダー" in clause and "味方" in clause:
        roles.append(3)
    if "対象に" in clause or "対象の" in clause:
        return "selected", tags, attrs, roles, False
    if "敵単体" in clause or "味方単体" in clause:
        return "selected", tags, attrs, roles, False
    if "敵全体" in clause or "相手全員" in clause or "敵対象" in clause:
        return "all_enemies", tags, attrs, roles, False
    if "味方全員" in clause or "味方全体" in clause or ("味方" in clause and "付与" in clause):
        return "all_allies", tags, attrs, roles, False
    if "自身に" in clause or "自身の" in clause:
        return "self", tags, attrs, roles, False
    return "self", tags, attrs, roles, False


def parse_skill_state_grants(row: dict, state_index: dict,
                             states_map: dict,
                             existing_codes: set | None = None,
                             skill_names: set | None = None) -> list:
    """Parse a skill description into state-grant behaviors.

    Skill effect descriptions are often empty while the skill description
    carries the full grant text with positional {N} values into the skill
    effect list. Each behavior records its source effect index so the
    simulator can link effect records to granted states. Clauses about the
    current attack only (この攻撃の) stay with the family behaviors.
    Returns behavior dicts with ASCII-only keys for combat_map.json.
    """
    existing_codes = existing_codes or set()
    description = row.get("description") or ""
    if not description:
        return []
    try:
        sid_hint = int(row.get("id", 0) or 0)
    except (TypeError, ValueError):
        sid_hint = 0
    effects = list(row.get("effects") or [])
    behaviors: list = []
    used_effects: set = set()

    def effect_value(number: int) -> int:
        if 0 <= number < len(effects):
            used_effects.add(number)
            return int((effects[number] or {}).get("value") or 0)
        return 0

    def next_effect_index() -> int | None:
        for index in range(len(effects)):
            if index not in used_effects:
                used_effects.add(index)
                return index
        return None

    def base_entry(clause: str, phase: str, scope_tags: list = (),
                     scope_attrs: list = (), scope_roles: list = ()) -> dict:
        duration = parse_duration(clause)
        cap_match = re.search(r"上限([0-9]+)%", clause)
        stack_match = re.search(r"上限([0-9]+)個", clause)
        rate = 100
        match = re.search(r"付与率([0-9]+)%", clause)
        if match:
            rate = int(match.group(1))
        elif "超高確率" in clause:
            rate = 95
        elif "高確率" in clause:
            rate = 85
        return {
            "dur_actions": duration.get("dur_actions", 0),
            "dur_action_phase": duration.get("dur_action_phase"),
            "dur_hits": duration.get("dur_hits", 0),
            "perm": bool(duration.get("perm")),
            "cap": int(cap_match.group(1)) * 100 if cap_match else 0,
            "stack_max": int(stack_match.group(1)) if stack_match else 0,
            "merge": bool("重複不可" in clause),
            "rate": rate,
            "fixed": bool("固定" in clause or "強化効果量変化の効果を受けない" in clause),
            "pre": phase == "pre",
            "target_tags": list(scope_tags),
            "target_attrs": list(scope_attrs),
            "target_roles": list(scope_roles),
        }

    clauses = [c.strip() for c in normalize(description).split(";") if c.strip()]
    # Scope/filter context inherits across clauses and fragments: later
    # text often omits the target (e.g. def-up following a barrier clause
    # that named the allies). Phase stays per-fragment (post default).
    inherit_scope, inherit_tags, inherit_attrs, inherit_roles = "self", [], [], []
    inherit_extra = []
    # Mechanic words that are also skill names (カウンター) must still grant:
    # skip the skill-name guard when the core appears in a state name.
    state_name_blob = "\n".join(state_index or {})
    # Placeholder-less grants attach to the last skill effect, except in
    # placeholder-free skills (usually tools) where successive clauses map
    # positionally onto the effect list (e.g. 20010058's three clauses).
    has_placeholders = bool(re.search(r"\{[0-9]+\}", description))
    for clause in clauses:
        if "この攻撃の" in clause and "付与" not in clause:
            continue
        fragments = [f.strip() for f in split_grant_fragments(clause) if f.strip()] or [clause]
        # Pre-attack timing inherits across fragments: 攻撃前 leads the
        # clause while the grant fragment omits it (攻撃後 wins when present).
        clause_pre = (("攻撃前" in clause or "スキル使用前" in clause)
                      and "攻撃後" not in clause)
        for frag in fragments:
            phase = "pre" if ("攻撃前" in frag or "スキル使用前" in frag
                              or (clause_pre and "攻撃後" not in frag)) else "post"
            scope, tags, attrs, roles, extreme = skill_grant_scope(frag)
            if (scope != "self" or "自身に" in frag or "対象" in frag or "味方" in frag
                    or "敵" in frag or "相手" in frag):
                inherit_scope, inherit_tags, inherit_attrs, inherit_roles = scope, tags, attrs, roles
                if extreme:
                    inherit_scope = scope
                # Self + role-filtered allies (自身とディフェンダーの味方全員).
                inherit_extra = ["self"] if (inherit_scope == "all_allies"
                                             and "自身と" in frag and inherit_roles) else []
            scope, tags, attrs, roles = inherit_scope, inherit_tags, inherit_attrs, inherit_roles
            extra_scopes = list(inherit_extra)

            def emit(entry: dict, grant_scope: str) -> None:
                entry = dict(entry)
                entry["target"] = grant_scope
                behaviors.append(entry)

            def emit_all(entry: dict) -> None:
                emit(entry, scope)
                for extra in extra_scopes:
                    emit(entry, extra)

            process_skill_grant_fragment(
                frag, clause, phase, scope, tags, attrs, roles, extra_scopes,
                effects, effect_value, next_effect_index, emit_all,
                existing_codes, state_index,
                states_map, sid_hint, skill_names, behaviors,
                state_name_blob, has_placeholders)
    return behaviors


def _skill_grant_base_entry(clause: str, phase: str, scope_tags: list = (),
                              scope_attrs: list = (), scope_roles: list = (),
                              cap_override=None, stack_override=None) -> dict:
    duration = parse_duration(clause)
    cap_match = re.search(r"上限([0-9]+)%", clause)
    stack_match = re.search(r"上限([0-9]+)個", clause)
    rate = 100
    match = re.search(r"付与率([0-9]+)%", clause)
    if match:
        rate = int(match.group(1))
    elif "超高確率" in clause:
        rate = 95
    elif "高確率" in clause:
        rate = 85
    return {
        "dur_actions": duration.get("dur_actions", 0),
        "dur_action_phase": duration.get("dur_action_phase"),
        "dur_hits": duration.get("dur_hits", 0),
        "perm": bool(duration.get("perm")),
        "cap": cap_override if cap_override is not None
        else (int(cap_match.group(1)) * 100 if cap_match else 0),
        "stack_max": stack_override if stack_override is not None
        else (int(stack_match.group(1)) if stack_match else 0),
        "merge": bool("重複不可" in clause),
        "rate": rate,
        "fixed": bool("固定" in clause or "強化効果量変化の効果を受けない" in clause),
        "pre": phase == "pre",
        "target_tags": list(scope_tags),
        "target_attrs": list(scope_attrs),
        "target_roles": list(scope_roles),
    }


def split_grant_fragments(clause: str) -> list:
    """Split a clause on commas outside 「」 quotes.

    Grant text routinely nests 、 inside quoted state names (e.g.
    「攻撃対象がブレイク状態の時、スキルダメージ+{0}%」); a naive split
    tears the grant across fragments so neither half matches.
    """
    parts: list = []
    depth = 0
    current: list = []
    chars = list(clause)
    for pos, char in enumerate(chars):
        if char == "「":
            depth += 1
            current.append(char)
        elif char == "」":
            depth = max(depth - 1, 0)
            current.append(char)
        elif depth == 0 and char in ("、", "，", ","):
            # A 、 before a bare count continues the value (被ダメージ
            # UP25%、2回); splitting there orphans the count and the grant.
            rest = "".join(chars[pos + 1:pos + 6])
            if re.match(r"[0-9]+回", rest):
                current.append(char)
            else:
                parts.append("".join(current))
                current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def trailing_segment_cap(frag: str, segment: str) -> int | None:
    """Cap percent attached to one grant segment (上限30% / 上限10%).

    Clauses often carry different caps per grant
    (物防・魔防+{0}%(上限30%)と最大HP+{1}%(上限10%)); the clause-wide
    first cap would misattribute them, so read the cap trailing the
    segment itself (e.g. 510207 over cap-30 800156 for the HP grant).
    """
    try:
        index = frag.find(segment)
    except (AttributeError, TypeError):
        return None
    if index < 0:
        return None
    tail = frag[index + len(segment):]
    match = re.match(r"[\s」」]*[（(]?上限([0-9]+)[%％][）)]?", tail)
    if match:
        return int(match.group(1)) * 100
    return None


def _split_grant_pairs(segment: str) -> list:
    """Split a grant segment into per-value cores on ・ and と."""
    parts = []
    for chunk in re.split(r"・", segment):
        subparts = re.split(r"(?<=\)|\%|％|個)と(?=[^と]*?(?:\{[0-9]+\}|[0-9]+[%％]?))", chunk)
        if len(subparts) <= 1:
            subparts = re.split(r"と(?=[^と]*?\{[0-9]+\})", chunk)
        parts.extend(subparts)
    return parts


def process_skill_grant_fragment(frag: str, clause: str, phase: str, scope: str,
                                 tags: list, attrs: list, roles: list,
                                 extra_scopes: list, effects: list,
                                 effect_value, next_effect_index, emit_all,
                                 existing_codes,
                                 state_index: dict, states_map: dict,
                                 sid_hint: int, skill_names: set | None,
                                 behaviors: list,
                                 state_name_blob: str = "",
                                 has_placeholders: bool = True) -> None:
    """Parse one comma-fragment of a skill description for granted states."""
    def base_entry(cap_override=None, stack_override=None):
        return _skill_grant_base_entry(clause, phase, tags, attrs, roles,
                                       cap_override, stack_override)

    # Cleanse clauses.
    if "解除" in frag and ("マイナス効果" in frag or "状態異常" in frag):
        code = "cleanse_allies_pre" if scope == "all_allies" else "cleanse_self_pre"
        if code not in existing_codes:
            existing_codes.add(code)
            emit_all({"code": code, "value": 0, "pre": phase == "pre"})
        return
    if "解除" in frag and "プラス効果" in frag:
        # Foe/ally plus-effect dispel (e.g. enemy burst 22002371) is covered
        # at runtime by captured removals; this records-only entry reserves
        # its positional effect slot so following grants stay aligned.
        if "dispel_plus" not in existing_codes:
            existing_codes.add("dispel_plus")
            emit_all({"code": "dispel_plus", "value": 0,
                      "effect_index": next_effect_index(),
                      "target": scope, "foe": scope == "all_enemies",
                      "pre": phase == "pre"})
        return
    # Forced break of one gauge.
    if "ブレイクゲージを0にする" in frag:
        emit_all({"code": "force_break", "value": 0, "pre": False,
                  "target": "selected", "foe": True, **base_entry()})
        return
    # Break-gauge restoration (falls through: further grants may follow).
    match = re.search(r"ブレイクゲージを\{([0-9]+)\}[%％]?回復", frag)
    if match:
        emit_all({"code": "break_gauge_heal_pct",
                  "value": effect_value(int(match.group(1))),
                  "effect_index": int(match.group(1)),
                  "target": scope, "foe": False, **base_entry()})
    # Overdrive: gauge threshold with extra consume and skill power.
    match = re.search(
        r"バーストゲージが([0-9]+)[%％]?以上.+さらに\{([0-9]+)\}[%％]?消費.+スキル威力\+{([0-9]+)}[%％]?",
        frag)
    if match:
        emit_all({"code": "overdrive_consume", "threshold": int(match.group(1)),
                  "value": effect_value(int(match.group(2))),
                  "effect_index": int(match.group(2)), **base_entry()})
        emit_all({"code": "overdrive_power",
                  "value": effect_value(int(match.group(3))),
                  "effect_index": int(match.group(3)), **base_entry()})
        return
    # Timeline delay of the target (falls through for paired grants).
    match = re.search(r"対象のターンを(?:\{([0-9]+)\}|([0-9]+))つ遅らせ", frag)
    if match:
        number = match.group(1) or match.group(2)
        value = effect_value(int(number)) if match.group(1) else int(number or 1)
        emit_all({"code": "delay_turn", "turns": value,
                  "effect_index": int(number) if match.group(1) else None,
                  "target": "selected", "foe": True, **base_entry()})
    # Bare barrier grants (durability as % of max HP) carry no quoted
    # segment, so the pair loop below never sees them. Quoted barriers
    # stay with the segment path to avoid double emission.
    if ("バリア" in frag and "付与" in frag and not any(
            "バリア" in quoted for quoted in SKILL_GRANT_QUOTED_RE.findall(frag))):
        match = re.search(r"(?:最大HPの\{([0-9]+)\}[%％]?の耐久値を持つ)?バリア", frag)
        if match:
            number = int(match.group(1)) if match.group(1) else None
            state_row = match_grant_state("バリア", 1, clause, state_index,
                                          states_map, sid_hint)
            if state_row is not None:
                emit_all({"code": "state_grant",
                          "state_id": int(state_row.get("id", 0) or 0),
                          "value": effect_value(number) if number is not None else 0,
                          "effect_index": number,
                          "direction": 1, "foe": False, **base_entry()})
                return
    if "蘇生" in frag or "復活" in frag:
        # Revival stays a records-only gap.
        return
    if "カウンター" in frag and "付与" not in frag and "付与" not in clause:
        # Counter retaliation stays a records-only gap.
        return
    if "パネル" in frag and ("変換" in frag or "生成" in frag):
        return
    # Excess-crit conversion names its vessel state with a cap and a
    # conversion target (e.g. crit-damage vs skill-power vessels share the
    # same cap, so the target word disambiguates them).
    if "変換" in frag:
        cap_match = re.search(r"変換上限([0-9]+)%", frag)
        target_words = [word for word in
                        ("クリティカルダメージ", "スキル威力", "与ダメージ",
                         "スキルダメージ", "ブレイクダメージ")
                        if word in frag]
        vessel = None
        for name, rows in state_index.items():
            if "変換" not in name:
                continue
            for candidate in rows:
                desc = candidate.get("description") or ""
                if cap_match and ("変換上限%s%%" % cap_match.group(1)) not in desc:
                    continue
                if target_words and not any(word in desc for word in target_words):
                    continue
                if vessel is None or int(candidate.get("id", 0) or 0) > int(vessel.get("id", 0) or 0):
                    vessel = candidate
        if vessel is not None:
            # Conversion vessels consume the next effect after the
            # fragment's placeholders (e.g. {3} then the conversion).
            used_here = {int(extra) for extra in re.findall(r"\{([0-9]+)\}", frag)}
            index = (max(used_here) + 1) if used_here else 0
            if index >= len(effects):
                index = None
            emit_all({"code": "state_grant", "state_id": int(vessel.get("id", 0) or 0),
                      "value": int((effects[index] or {}).get("value") or 0) if index is not None else 0,
                      "effect_index": index, "foe": False, **base_entry()})
        return
    # Quoted and bare grant segments. Explanatory notes (e.g. ※ clauses
    # describing what a state does) name states without granting them, so
    # quoted names only count when the fragment or clause grants something.
    segments: list = []
    for quoted in SKILL_GRANT_QUOTED_RE.findall(frag):
        if "付与" in frag or "付与" in clause:
            segments.append(quoted)
    for bare in re.findall(r"(?:対象|自身|相手全員|敵全体|味方全員|敵単体|味方単体)に(.+?)を付与", frag):
        if "「" not in bare:
            segments.append(bare)
    if not segments and "付与" in clause:
        targeted_fragment = re.search(
            r"(?:自身|対象|相手全員|敵全体|味方全員|味方全体|敵単体|味方単体)に(.+)$", frag
        )
        if targeted_fragment:
            segments.append(targeted_fragment.group(1))
    # Prefix-less parenthesized grants inherit their target from earlier
    # fragments (自身にカウンター(3回)、被ダメージDOWN(30%/3回)); without a
    # segment they vanish, so the fragment itself becomes the segment.
    if (not segments and "付与" in clause
            and re.search(r"\([0-9]+[%％]?/[0-9]+回\)", frag)):
        segments.append(frag)
    # State-change になる grants (かばう状態(3回)になる) name no 付与;
    # without this the cover grant vanishes (32005798).
    if not segments:
        become = re.search(r"(.+?)になる$", frag.strip())
        if become:
            candidate = become.group(1).strip()
            if candidate and "付与" not in candidate:
                segments.append(candidate)
    # Timed/bare fallbacks overlap the targeted forms above (both match
    # 「...」-free grants ending in 付与), so they only run when no target
    # prefix is present; otherwise one grant emits twice (e.g. 毒8つ5回).
    has_target_prefix = bool(re.search(
        r"(?:対象|自身|相手全員|敵全体|味方全員|味方全体|敵単体|味方単体)に", frag))
    if "「" not in frag and not has_target_prefix:
        timed_bare = re.search(
            r"(.+?)を(?:[0-9]+回(?:行動開始|行動終了)するまで|"
            r"[0-9]+回攻撃を受けるまで)?付与$",
            frag.strip(),
        )
        if timed_bare:
            segments.append(timed_bare.group(1))
        match = re.search(r"(.+?)を付与$", frag.strip())
        if match:
            candidate = match.group(1).strip()
            if candidate and "付与" not in candidate:
                segments.append(candidate)
    segments = [
        re.sub(r"^(?:対象|自身|相手全員|敵全体|味方全員|味方全体|敵単体|味方単体)に", "", segment)
        for segment in segments
    ]
    # Parallel extraction paths (targeted/bare/timed forms) yield the same
    # grant with and without its trailing を付与 suffix; normalize before
    # dedup so one behavior is emitted (e.g. 毒8つ5回を付与 vs 毒8つ5回).
    segments = [
        re.sub(
            r"を(?:[0-9]+回(?:行動開始|行動終了)するまで|"
            r"[0-9]+回攻撃を受けるまで)?付与$",
            "",
            segment,
        )
        for segment in segments
    ]
    segments = list(dict.fromkeys(seg for seg in segments if seg))
    seen_parts: set = set()
    for segment in segments:
        # For unquoted grants the generic "...を付与" form includes the
        # duration between the state name and 付与. Remove it before looking
        # for the state's literal/value so e.g. 回復無効状態を2回行動終了
        # するまで付与 resolves to state 920001 with value 0, not value 200.
        segment = re.sub(
            r"[0-9]+回(?:行動開始|行動終了)するまで|[0-9]+回攻撃を受けるまで",
            "", segment,
        )
        if "変換" in segment:
            continue  # handled at fragment level above
        # The middle dot is both a Japanese compound separator (物攻・魔攻)
        # and part of named effects such as ハイ・ドミナンス. Keep an ailment
        # name intact before applying the compound-stat split.
        if any(name in segment for name in AILMENTS):
            pairs = [segment]
        else:
            pairs = _split_grant_pairs(segment)
        seg_numbers = [int(n) for n in re.findall(r"\{([0-9]+)\}", segment)]
        seg_shared = seg_numbers[0] if len(set(seg_numbers)) == 1 else None
        # Segment-local caps (物防・魔防+{0}%(上限30%)と最大HP+{1}%(上限10%)):
        # the clause-wide first cap would misattribute them.
        seg_cap = trailing_segment_cap(frag, segment)
        for pair in pairs:
            part = re.sub(r"^(?:と|、|，|,|・|を|に)+", "", pair.strip())
            if not part or part in seen_parts:
                continue
            seen_parts.add(part)
            # Tag-count scaled ranges (魔攻+10～50%, 基礎魔攻+100～300):
            # keep the range floor as the literal value; the master effect
            # (via reconcile) carries the battle value since text scales.
            part = re.sub(r"([+\-−][0-9]+)[～〜~][0-9]+[%％]?",
                          lambda m: m.group(1), part)
            # Parenthesized and trailing-count value forms carry literal
            # values with hit/action counts instead of placeholders
            # (与える強化効果DOWN(50%/3回), 被ダメージUP25%、2回,
            # カウンター(3回)). Claim the next positional effect slot so
            # multi-grant tools stay aligned with their effect list.
            positional_value = None
            paren = re.search(r"\(([0-9]+)[%％]/([0-9]+)回\)", part)
            if paren:
                positional_value = int(paren.group(1)) * 100
                part = re.sub(r"\([0-9]+[%％]/[0-9]+回\)", "", part)
            else:
                tail = re.search(r"([0-9]+)[%％]?、([0-9]+)回$", part)
                if tail:
                    positional_value = int(tail.group(1)) * 100
                    part = re.sub(r"[0-9]+[%％]?、[0-9]+回$", "", part)
                else:
                    count_only = re.search(r"\([0-9]+回\)", part)
                    if count_only:
                        part = re.sub(r"\([0-9]+回\)", "", part)
            positional_index = None
            if positional_value is not None:
                positional_index = next_effect_index()
            # Skill-rank references (スキル2から受けるダメージ) are not
            # values: shield their digits before numeric matching, then
            # restore the rank word for state matching (800232).
            rank_num = None
            rank_hit = re.search(r"スキル([0-9]+)", part)
            if rank_hit:
                rank_num = rank_hit.group(1)
            shielded = re.sub(r"スキル[0-9]+", "スキルRANK", part) if rank_num else part
            value_match = re.search(r"([+\-−])?(?:\{([0-9]+)\}|([0-9]+))[%％]?", shielded)
            sign = value_match.group(1) if value_match else None
            placeholder = value_match.group(2) if value_match else None
            literal = value_match.group(3) if value_match else None
            core = re.sub(r"([+\-−])?(?:\{[0-9]+\}|[0-9]+)[%％]?", "", shielded)
            if rank_num:
                core = core.replace("スキルRANK", "スキル" + rank_num)
            # Tag-count scaled ranges (魔攻+10～50%, 基礎魔攻+100～300):
            # the slot core precedes the range; values resolve from the
            # master effect (reconcile) since the text scales by roster.
            core = re.sub(r"[+＋]?[0-9]*[～〜~][0-9]+[%％]?$", "", core)
            core = re.sub(r"\([^)]*\)", "", core).strip()
            core = re.sub(r"(?:[0-9]+回)?行動(?:開始|終了)するまで$", "", core)
            core = re.sub(r"(?:[0-9]+回)?攻撃を受けるまで$", "", core)
            core = re.sub(r"を$", "", core)
            core = re.sub(r"状態$", "", core)
            # Conditional prefixes (自身がアタッカーの時、 / 攻撃対象が
            # ブレイク状態の時、) select when the grant applies; the slot
            # core follows the 、 (e.g. 910064, 610021).
            core = re.sub(r"^.*の時、", "", core)
            core = re.sub(r"^(?:と|、|，|,|・|を|に)+", "", core)
            # Orphaned counters (2回を付与 split from its value) carry no
            # slot; without this they match any state mentioning 回.
            if (not core or core in ("回", "つ", "個")
                    or "スキルランプ" in core or "上限" in core or "Lv" in core
                    or core in TAG_INDEX
                    or (skill_names is not None and core in skill_names
                        and core not in state_name_blob)):
                continue
            number = int(placeholder) if placeholder is not None else seg_shared
            if placeholder is not None or seg_shared is not None:
                # Reserve positional effect slots even when skipped, so
                # later fallbacks stay aligned.
                effect_value(int(number))
            elif positional_index is not None:
                number = positional_index
            elif "カウンター" in core or not has_placeholders:
                # Self-granted counter states are positional (tools list
                # them first); placeholder-less grants otherwise attach to
                # the last effect. Placeholder-free skills map successive
                # grants onto successive effects instead.
                number = next_effect_index()
            direction = -1 if (sign in ("-", "−") or "ダウン" in part
                               or "減少" in part or "低下" in part or "DOWN" in part) else 1
            if "回避" in core:
                prob = re.search(r"確率([0-9]+)%", segment)
                value = int(prob.group(1)) * 100 if prob else 10000
                # Qualified evasion (魔法攻撃回避) must keep its qualifier;
                # matching bare 回避 loses it (22001966 needs 710035).
                state_row = match_grant_state(core, direction, clause, state_index,
                                              states_map, sid_hint)
                if state_row is None:
                    continue
                emit_all({"code": "state_grant",
                          "state_id": int(state_row.get("id", 0) or 0),
                          "value": value, "effect_index": None,
                          "direction": direction, "foe": False, **base_entry()})
                continue
            if "バリア" in core:
                state_row = match_grant_state("バリア", direction, clause, state_index,
                                              states_map, sid_hint)
                if state_row is None:
                    continue
                emit_all({"code": "state_grant",
                          "state_id": int(state_row.get("id", 0) or 0),
                          "value": effect_value(number) if number is not None else 0,
                          "effect_index": number,
                          "direction": direction, "foe": False, **base_entry()})
                continue
            state_row = None
            cap_key = re.search(r"上限([0-9]+)%", clause)
            cap_value = int(cap_key.group(1)) if cap_key else 0
            if seg_cap is not None:
                cap_value = seg_cap // 100
            override_id = GRANT_STATE_OVERRIDES.get((sid_hint, core, cap_value))
            if override_id is None:
                ailment_id = match_grant_ailment(core, clause, states_map, state_index)
                # Resistance grants (火傷耐性-, 全属性耐性-) name an ailment
                # only to select the resisted element; they resolve through
                # state matching below, never through the ailment path.
                if "耐性" not in core and (ailment_id is not None or any(
                        keyword in core for keyword in AILMENTS)):
                    if ailment_id is None:
                        continue
                    emit_all({"code": "state_grant", "state_id": ailment_id,
                              "value": 0, "effect_index": None,
                              "direction": 1, "foe": "対象" in clause or "敵" in clause,
                              **base_entry()})
                    continue
                state_row = match_grant_state(
                    core, direction, clause, state_index,
                    states_map, sid_hint,
                    alt_cores=tuple(GRANT_CORE_SYNONYMS.get(core, ())),
                    cap_override=seg_cap)
            else:
                state_row = {"id": override_id}
            if state_row is None:
                continue
            if number is not None:
                value = effect_value(number)
            elif literal is not None:
                value = int(literal) * 100
            else:
                value = 0
            if positional_index is not None:
                # Positional literal-value grants read the master effect
                # value at their claimed slot (it agrees with the text).
                number = positional_index
                try:
                    value = int((effects[number] or {}).get("value", 0) or 0)
                except (IndexError, TypeError, ValueError):
                    value = positional_value or 0
            hostile = direction < 0 or any(
                word in core for word in ("耐性", "ダメージ", "防御", "素早さ"))
            emit_all({"code": "state_grant",
                      "state_id": int(state_row.get("id", 0) or 0),
                      "value": value, "effect_index": number,
                      "direction": direction,
                      "foe": bool(hostile and ("対象" in clause or "敵" in clause
                                              or "相手" in clause)),
                      **base_entry(cap_override=seg_cap)})



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
    effect_names = {
        str(row.get("id")): row.get("name") or ""
        for row in load(master, "research_effect")
    }
    research_roles = (
        ("アタッカー", "attacker"), ("ブレイカー", "breaker"),
        ("ディフェンダー", "defender"), ("サポーター", "supporter"),
    )
    grouped: dict[str, list] = {}
    for row in load(master, "research"):
        grouped.setdefault(str(row.get("group_id")), []).append(row)
    for group_rows in grouped.values():
        seen: dict[str, int] = {}
        # The profile level completes every row up to it, so each stored
        # level merges all effects unlocked so far at their latest tier
        # (verified: attacker HP 2500, dealt 2020, defender resist 1500).
        merged: dict[str, dict] = {}
        for row in sorted(group_rows, key=lambda r: int(r.get("level", 0) or 0)):
            group = str(row.get("group_id"))
            level = int(row.get("level", 0) or 0)
            for effect_id in row.get("research_effect_ids") or []:
                key = str(effect_id)
                seen[key] = seen.get(key, 0) + 1
                tier = levels.get(key, {}).get(str(seen[key]), {})
                name = effect_names.get(key, "")
                slot = None
                if name.endswith("与ダメージアップ"):
                    slot = ("item_damage" if name.startswith("戦闘アイテム")
                            else "dealt_damage")
                elif name.endswith("ダメージ耐性アップ"):
                    slot = "taken"
                elif name.endswith("HP回復量アップ"):
                    slot = "item_heal"
                role = next(
                    (code for word, code in research_roles if word in name),
                    None,
                )
                merged[key] = {
                    "effect": effect_id,
                    "value": tier.get("value") or 0,
                    "slot": slot,
                    "role": role,
                    "status_buffs": tier.get("status_buffs") or [],
                    "equipment_buffs": tier.get("equipment_buffs") or [],
                }
            research.setdefault(group, {})[str(level)] = {
                "effects": list(merged.values()),
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
        "91000925": ("post_heal_allies", ["味方全員", "HPを回復"]),
        "91001007": ("cleanse_self_pre", ["攻撃前", "自身", "解除"]),
        "91001607": ("cleanse_self_pre", ["攻撃前", "自身", "解除"]),
        "91001587": ("post_magic_up_allies", ["味方全員", "魔攻"]),
        "91002004": ("item_gauge", ["アイテムゲージ"]),
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
    grant_state_rows = load(master, "state_change")
    grant_state_index = build_grant_state_index(grant_state_rows)
    grant_skill_names = {row.get("name") for row in skill_rows if row.get("name")}
    gauge_ids = gauge_effect_ids(skill_rows)
    skill_behavior: dict[str, list] = {}
    for row in load(master, "skill"):
        if not str(row.get("id"))[0] in "12":
            continue
        summary = row.get("summary") or ""
        description = row.get("description") or ""
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
                full_text = summary + description
                duration = parse_duration(full_text)
                entry: dict = {
                    "code": code,
                    "value": effect.get("value") or 0,
                    "effect_id": int(effect.get("id") or 0),
                }
                for duration_field in (
                    "dur_actions",
                    "dur_action_phase",
                    "dur_hits",
                    "perm",
                ):
                    if duration.get(duration_field):
                        entry[duration_field] = duration[duration_field]
                if code == "post_magic_up_allies":
                    cap_match = re.search(r"上限([0-9]+)%", full_text)
                    entry.update({
                        "stat": "magic",
                        "effect_id": int(effect.get("id") or 0),
                        "cap": int(cap_match.group(1)) * 100 if cap_match else 0,
                        "dur_actions": duration["dur_actions"],
                        "dur_action_phase": duration["dur_action_phase"],
                        "dur_hits": duration["dur_hits"],
                        "perm": duration["perm"] or bool(
                            cap_match and not duration["dur_actions"] and not duration["dur_hits"]
                        ),
                    })
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

    # Skill-description state grants cover empty-description skill effects
    # whose semantics live in the skill text (positional {N} values into the
    # skill effect list). Runs over every skill (allies, enemies, tools);
    # family behaviors above are kept and cleanse codes are deduped.
    grant_stats = {"skills": 0, "behaviors": 0}
    for row in load(master, "skill"):
        sid = str(row.get("id"))
        existing = skill_behavior.get(sid, [])
        existing_codes = {b.get("code") for b in existing}
        grants = parse_skill_state_grants(
            row, grant_state_index, states, existing_codes, grant_skill_names)
        if grants:
            grant_stats["skills"] += 1
            grant_stats["behaviors"] += len(grants)
            skill_behavior[sid] = existing + grants
    print("skill description grants: %d skills, %d behaviors" % (
        grant_stats["skills"], grant_stats["behaviors"]))


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
