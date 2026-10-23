# NoneBot Platform Adapters

[中文](platforms.md) | English · [Usage guides](README.en.md) · [Documentation](../README.en.md)

Stella uses NoneBot adapters to connect to chat platforms. NoneBot separates installing an adapter package from registering it at runtime: an installed package is not enabled automatically. Stella registers only modules selected on the **Platforms** page, after a restart. NoneBot can register multiple adapters in one Bot; actual capabilities depend on each adapter and platform service.

## Catalog and installation

The catalog snapshot in the Platforms page follows the [official NoneBot adapter directory](https://raw.githubusercontent.com/nonebot/nonebot2/master/assets/adapters.json5) and contains 32 entries. OneBot V11 and V12 share `nonebot-adapter-onebot`. Stella bundles 28 distributions for the 29 selectable entries in its standard installers. Walle-Q, NTChat, and Mail are unavailable; see the table below.

These dependencies are declared in `requirements.txt` and `pyproject.toml`, so they are included in Docker, online/offline Windows installers, and source installations. Adapter credentials, platform permissions, and callback URLs remain adapter-specific. NoneBot's `DRIVER` is global; edit it from any selected adapter's **Runtime settings** dialog and it applies to all selected adapters. The installer does not create platform accounts or enable adapters automatically. Use **Runtime settings** on a custom adapter card to enter variables documented by its project.

The Heybox adapter requires Python 3.11 or newer. The project still supports Python 3.10, so that environment skips this distribution; the bundled Windows installer uses Python 3.12.

## Blocked adapters

| Catalog entry | Module | Reason |
| --- | --- | --- |
| Walle-Q | `nonebot_adapter_walleq` | Upstream 0.2.0 was released on 2023-04-10 and requires `nonebot-adapter-onebot~=2.2.2`; Stella core requires `nonebot-adapter-onebot>=2.4.6`, so the constraints cannot be resolved together. See [PyPI metadata](https://pypi.org/pypi/nonebot-adapter-walleq/0.2.0/json). |
| NTChat | `nonebot.adapters.ntchat` | Upstream 0.3.5 was released on 2023-02-03 and pins `httpx==0.23.0`; Stella core requires `httpx>=0.24.0`. See [PyPI metadata](https://pypi.org/pypi/nonebot-adapter-ntchat/0.3.5/json). |
| Mail | `nonebot.adapters.mail` | Its only release, 1.0.0a7, was uploaded on 2025-01-04 and requires `aiosmtplib~=3.0`; the affected range is fixed starting in 5.1.2. See [PyPI metadata](https://pypi.org/pypi/nonebot-adapter-mail/1.0.0a7/json) and the [security advisory](https://osv.dev/vulnerability/PYSEC-2026-3805). |

These packages are not installed by Stella's installers. The runtime registrar skips these modules and logs a warning. If an older `.env` still lists one, the Platforms page keeps it visible and asks you to remove the card; remove it and save to clean up the configuration. The same module paths are skipped when supplied through process environment variables.

## Connect a platform

1. Search for a platform in **Platforms → Add adapter** and select one or more available entries.
2. Choose **Runtime settings** on a selected card. The floating dialog contains fields prefilled from that adapter project's docs. Adapters that support multiple accounts let you add multiple bot entries; less common settings remain under **Advanced environment variables**. Legacy variables without an adapter stay in an unassigned section until you choose a card for them.
3. Follow the adapter project's instructions for accounts, credentials, and platform-side permissions. Supported catalog dependencies are already included in the installer; Heybox requires Python 3.11+.
4. Close the dialog to return to the page draft, use the page-level Save button to write settings to the local `.env`, and restart Stella. Startup logs list registered adapters. Missing packages, import failures, and Driver registration errors identify the relevant module path.

Catalog inclusion and bundled dependencies mean an adapter is selectable and can be assembled; they do not certify behavior compatibility, live platform delivery, or account acceptance. Adapter docs and platform version requirements can change, so review the project page linked from each catalog card.

Preset fields are based on each adapter's docs or configuration model. See the [adapter form research note](../reports/2026-10-23-nonebot-adapter-config-research.md). The Heybox upstream only provides an incomplete configuration example, so its fields are not marked required. The pinned Minecraft package is 1.8.2; RCON is not prefilled because older and newer upstream documentation conflict. Catalog entries do not mean that every field has been runtime-verified against the pinned package.

Some adapters use documented multi-account JSON forms. Matrix exposes static-token, password, and OAuth login fields plus sync, invitation, and end-to-end encryption settings. Villa stores the bot ID, secret, public key, and connection mode on each bot entry. WxClaw includes both account fields and the channel defaults documented by its project. Secret fields are redacted on read, and submitting them blank preserves their stored values.

## Official docs

- [NoneBot: install adapters from the store](https://nonebot.dev/docs/tutorial/store)
- [NoneBot: use and register adapters](https://nonebot.dev/docs/advanced/adapter)
- [Official NoneBot catalog source](https://raw.githubusercontent.com/nonebot/nonebot2/master/assets/adapters.json5)
- [WebUI administration](webui.en.md)
