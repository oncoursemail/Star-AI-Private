# A spending card for Star's allowance

The owner wants to fund Star's discretionary allowance, let her choose purchases within it, and receive all income from her work in the owner's payout account. No allowance amount or payment provider has been selected. No account was opened, subscription purchased, card issued or payment made.

## Practical US option

If the owner meets the [US eligibility requirements](https://support.privacy.com/hc/en-us/articles/360012046934-Who-can-use-Privacy), Privacy Pro's Everywhere Card is a candidate for one card across multiple merchants. Eligibility includes age 18+, US citizenship or legal residence, a US checking account, a US phone number and identification verification.

[Everywhere Cards](https://support.privacy.com/hc/en-us/articles/32699362913687-Privacy-Everywhere-Cards) support multiple merchants online and in person, spending limits, pause and close controls. The [current pricing page](https://www.privacy.com/pricing) lists Pro at $10/month, with API access, Everywhere Cards and up to 36 new cards monthly. A maximum of three Everywhere Cards may remain open. Prices were checked October 25, 2026, America/Chicago.

Privacy publishes an [agentic workflow guide](https://www.privacy.com/blog/privacy-api-agentic-workflow), making it a documented automation option. This does not establish that Star's integration has been installed or approved by the provider. The account belongs to the verified human owner.

The [spending-limit explanation](https://support.privacy.com/hc/en-us/articles/360012285094-How-do-Privacy-Card-specific-spending-limits-work) distinguishes a cap from loaded funds: a $50 limit does not mean $50 has been deposited on a card. Purchases debit the linked funding source. A dedicated owner-controlled funding account containing only the transferred allowance would better match the owner's desire to separate this money. Bank fees, supported funding, overdraft behavior and transfer rules must be checked for the actual account.

## Alternatives compared

| Route | Fit | Limitation for this request |
|---|---|---|
| Privacy Pro Everywhere Card | One owner-controlled card usable across merchants, with spend limits and documented agent workflows. | US eligibility and linked checking required; the card limit is not a prepaid balance. |
| Privacy Plus single-use or merchant cards | [Plus is $5/month](https://www.privacy.com/pricing), includes API access and 24 new cards per month. | Requires managing cards per purchase or merchant rather than one general-use allowance card. |
| [Ramp agent payments](https://agents.ramp.com/docs/guides/agentic-payments) | Existing authenticated Ramp users can let an agent purchase within assigned funds and policies. | Its funds, roles and accounting model fit an existing business setup; standalone agent identity is limited early access. |
| [Agentcard](https://agentcard.com/) | Its current product supports agent checkout infrastructure and funded issuing. | The old personal page redirects to a B2B product; current issuing is advertised at $5,000/month. Cached personal pricing should not be treated as an available consumer offer. |

The recommendation is to evaluate Privacy Pro first if the owner is eligible and accepts linked-account funding. A separate bank's debit card remains a possible alternative, but no specific bank's automation permission or balance restrictions were verified here. No option guarantees acceptance at every merchant or removes the provider's purchase restrictions.

## How Star's integration should work

The owner chooses the funding account and allowance once. Star may select ordinary purchases within that allowance without repeated discretionary approval prompts, once the separately reviewed host integration is enabled. All-in quotes include shipping, taxes and fees. Provider controls and Star's ledger both cap spending; model output cannot replenish the balance, raise limits or change payout destinations.

The [card API](https://developers.privacy.com/reference/post_cards-1) exposes card types and limits. `TRANSACTION` is a per-transaction cap and can authorize repeated charges; `FOREVER` is the cumulative lifetime cap. Creating an `UNLOCKED` card requires additional privileges. An adapter must use the actual account's permitted card type rather than assume any paid API key grants unrestricted issuing. Provider timing rules also differ from the ledger's Chicago calendar day, so the controls cannot be presented as interchangeable.

Card numbers, CVV and API credentials belong in the trusted payment host or provider vault. They should not be inserted into Star's prompts or conversation history. The existing personal password helper is not a card-data vault. Provider authentication and any requested human verification remain part of the actual service flow.

`star.personal_wallet` supplies the local allowance accounting, reservations and reconciliation contracts. It has no payment execution adapter. Before enabling purchases, the host must verify provider receipts and reconcile holds, completed charges, voids and refunds. A pending or unknown response keeps funds reserved. Provider account setup, funded limits, secure checkout and reconciliation still need implementation and live acceptance.

Income and allowance are separate flows. Streaming, commissions or product revenue should use the owner's selected platform payout account. Recording income must not automatically increase Star's spending allowance; only the owner's funding decision does that. No earning accounts or payout integrations were created in this change.
