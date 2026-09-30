#!/usr/bin/env python3
"""Generate the protobuf request/response cross-reference in ENDPOINTS.md."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import contract_codec


BEGIN = "<!-- BEGIN GENERATED PROTOBUF CONTRACT MAP -->"
END = "<!-- END GENERATED PROTOBUF CONTRACT MAP -->"
ROUTE_RE = re.compile(r"`(/[^`\s]+)`")

REQUEST_OVERRIDES = {
    "/status": "JSON",
    "/refund_info/get_country_code": "google.protobuf.Empty",
    "/user/log_in": "google.protobuf.Empty",
    "/web_session/token": "google.protobuf.Empty",
    "/login_bonus/receive": "google.protobuf.Empty",
    "/external_purchase/receive": "google.protobuf.Empty",
    "/mail/list": "google.protobuf.Empty",
    "/event/top": "google.protobuf.Empty",
    "/shop/gem_list": "google.protobuf.Empty",
    "/gacha/list": "google.protobuf.Empty",
    "/battle/finish": "google.protobuf.Empty",
    "/battle/retire": "google.protobuf.Empty",
    "/battle/resume": "google.protobuf.Empty",
    "/expedition/reward_receive": "google.protobuf.Empty",
    "/recipe/learn": "google.protobuf.Empty",
    "/master_data/*": "CDN/asset request",
    "/manifest.json": "JSON/asset request",
}

RESPONSE_OVERRIDES = {
    "/status": "JSON",
    "/refund_info/get_country_code": "blend.api.RefundInfoGetCountryCodeResponse",
    "/user/log_in": "blend.api.UserLogInResponse",
    "/web_session/token": "blend.api.WebSessionTokenResponse",
    "/login_bonus/receive": "blend.api.LoginBonusReceiveResponse",
    "/external_purchase/receive": "blend.api.ExternalPurchaseReceiveResponse",
    "/mail/list": "blend.api.MailListResponse",
    "/mail/open": "blend.api.MailOpenResponse",
    "/battle/finish": "blend.api.BattleFinishResponse",
    "/battle/retire": "blend.api.ChangedResourcesResponse",
    "/battle/resume": "blend.api.BattleResumeResponse",
    "/quest/battle/start": "blend.api.BattleStartResponse",
    "/quest/battle/total_battle_start": "blend.api.BattleStartResponse",
    "/quest/battle/solo_raid_battle_start": "blend.api.BattleStartResponse",
    "/quest/battle/rental_party_start": "blend.api.BattleStartResponse",
    "/quest/battle/skip": "blend.api.QuestBattleSkipResponse",
    "/exploration/start": "blend.api.ChangedResourcesResponse",
    "/exploration/update_party": "blend.api.ChangedResourcesResponse",
    "/exploration/battle_start": "blend.api.BattleStartResponse",
    "/exploration/finish": "blend.api.ExplorationFinishResponse",
    "/exploration/retire": "blend.api.ChangedResourcesResponse",
    "/exploration/skip": "blend.api.ExplorationSkipResponse",
    "/gacha/battle_start": "blend.api.BattleStartResponse",
    "/synthesis/bulk_execute": "blend.api.SynthesisExecuteResponse",
    "/synthesis/execute_rental": "blend.api.SynthesisExecuteResponse",
    "/quest/street/start": "blend.api.ChangedResourcesResponse",
    "/quest/street/talk": "blend.api.ChangedResourcesResponse",
    "/mail/delete": "blend.api.MailDeleteResponse",
    "/recipe/learn": "blend.api.RecipeLearnResponse",
    "/master_data/*": "CDN asset payload (not protobuf)",
    "/manifest.json": "JSON asset payload",
}

EMPTY_REQUEST_ROUTES = {
    "/status",
    "/refund_info/get_country_code",
    "/user/log_in",
    "/web_session/token",
    "/login_bonus/receive",
    "/external_purchase/receive",
    "/mail/list",
    "/gacha/list",
    "/battle/finish",
    "/battle/retire",
    "/battle/resume",
    "/expedition/reward_receive",
    "/recipe/learn",
}

def route_stem(path: str) -> str:
    return "".join(
        "".join(part[:1].upper() + part[1:] for part in segment.split("_") if part)
        for segment in path.strip("/").split("/")
    )


def endpoint_paths(markdown: str) -> list[str]:
    if BEGIN in markdown and END in markdown:
        start = markdown.index(BEGIN)
        finish = markdown.index(END) + len(END)
        markdown = markdown[:start] + markdown[finish:]
    paths: list[str] = []
    for match in ROUTE_RE.finditer(markdown):
        path = match.group(1)
        if path not in paths:
            paths.append(path)
    return paths


def request_type(path: str, db: contract_codec.ContractDB) -> str:
    override = REQUEST_OVERRIDES.get(path)
    if override is not None:
        return override
    candidate = f"blend.api.{route_stem(path)}Request"
    if candidate in db.messages:
        return candidate
    if path in EMPTY_REQUEST_ROUTES:
        return "google.protobuf.Empty"
    return "No matching request definition in fields.txt"


def response_type(path: str, db: contract_codec.ContractDB) -> str:
    override = RESPONSE_OVERRIDES.get(path)
    if override is not None:
        if override.startswith("blend.api.") and override not in db.messages:
            return "Missing from fields.txt: " + override
        return override
    candidate = f"blend.api.{route_stem(path)}Response"
    if candidate in db.messages:
        return candidate
    request_candidate = f"blend.api.{route_stem(path)}Request"
    if request_candidate in db.messages and "blend.api.ChangedResourcesResponse" in db.messages:
        return "blend.api.ChangedResourcesResponse"
    return "No matching response definition in fields.txt"


def mapping_markdown(markdown: str, db: contract_codec.ContractDB) -> str:
    paths = endpoint_paths(markdown)
    mappings = [(path, request_type(path, db), response_type(path, db)) for path in paths]
    used = {
        name
        for _, request, response in mappings
        for name in (request, response)
        if name.startswith("blend.api.") and name in db.messages
    }
    api_messages = sorted(
        name
        for name in db.messages
        if name.startswith("blend.api.") and name.rsplit(".", 1)[-1].endswith(("Request", "Response"))
    )
    unmatched = [name for name in api_messages if name not in used]

    lines = [
        "## Protobuf Contract Mapping",
        "",
        "Names below come from the installed client `contract-dump/fields.txt`. "
        "Shared response types (especially `ChangedResourcesResponse`) legitimately "
        "serve multiple routes. `Empty`, JSON, and asset entries are non-route-specific "
        "wire shapes rather than missing protobuf definitions.",
        "",
        "| Endpoint | Request definition | Response definition |",
        "|---|---|---|",
    ]
    for path, request, response in mappings:
        lines.append(f"| `{path}` | `{request}` | `{response}` |")

    lines.extend(
        [
            "",
            "### Request/response definitions not assigned to a listed endpoint",
            "",
            "These API messages are present in `fields.txt` but are not selected by "
            "the route mappings above. Some may be nested helpers, legacy/variant "
            "routes, or routes not yet observed; review them before adding endpoints.",
            "",
        ]
    )
    if unmatched:
        lines.extend(f"- `{name}`" for name in unmatched)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "### Candidate route names to verify against captures",
            "",
            "These are naming-based leads only, not confirmed endpoint registrations:",
            "",
            "- `/quest/street/move`, `/quest/street/receive_reward`, "
            "`/quest/street/list_talk`, and `/quest/street/replay_talk` "
            "from the corresponding `QuestStreet*Request` definitions.",
            "- `/synthesis/execute` from `blend.api.SynthesisExecuteRequest`.",
            "- `/user/update_birthdate` and `/user/update_language` from the "
            "corresponding `UserUpdate*Request` definitions.",
        ]
    )
    return "\n".join(lines)


def update_endpoints(path: Path, fields: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        raise ValueError(f"ENDPOINTS.md is missing generated mapping markers: {path}")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError("ENDPOINTS.md must contain exactly one start/end mapping marker")
    db = contract_codec.parse_fields_txt(fields)
    generated = mapping_markdown(text, db)
    start = text.index(BEGIN)
    finish = text.index(END) + len(END)
    replacement = f"{BEGIN}\n{generated}\n{END}"
    path.write_text(text[:start] + replacement + text[finish:], encoding="utf-8")
    print(f"WROTE protobuf mapping for {len(endpoint_paths(text))} endpoints: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fields", type=Path, help="installed contract-dump/fields.txt")
    parser.add_argument("endpoints", type=Path, help="share ENDPOINTS.md")
    args = parser.parse_args()
    update_endpoints(args.endpoints, args.fields)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
